"""Wespeaker ResNet34 声纹引擎

模型: iic/speech_resnet34_sv_zh-cn_3dspeaker_16k
EER: 1.05% (VoxCeleb), 6.92% (CNCeleb)
"""
import numpy as np
import torch
import chromadb
import time
import os
from collections import defaultdict

current_dir = os.path.dirname(os.path.abspath(__file__))


class WespeakerEngine:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WespeakerEngine, cls).__new__(cls)
            cls._instance._init_model()
            
            cls._instance.chroma_client = chromadb.PersistentClient(
                path=os.path.join(current_dir, "speaker_db", "wespeaker")
            )
            cls._instance.collection = cls._instance.chroma_client.get_or_create_collection(
                name="speaker_fingerprints_wespeaker",
                metadata={"hnsw:space": "cosine"}
            )
            
            cls._instance.emb_buffer = defaultdict(list)
            cls._instance.EMB_BUFFER_SIZE = 5
            
            cls._instance.match_history = defaultdict(list)
            cls._instance.HISTORY_SIZE = 3
            
            print("[Wespeaker] 初始化完成")
        return cls._instance

    def _init_model(self):
        """初始化模型"""
        print("[Wespeaker] 加载模型...")
        from modelscope.models import Model
        model_id = 'iic/speech_resnet34_sv_zh-cn_3dspeaker_16k'
        self.model = Model.from_pretrained(model_id, device='cpu')
        self.model.eval()
        print("[Wespeaker] ResNet34 模型加载成功")

    def extract_feat(self, audio_data: np.ndarray) -> np.ndarray:
        """提取声纹特征"""
        try:
            tensor = torch.FloatTensor(audio_data).unsqueeze(0)
            with torch.no_grad():
                outputs = self.model(tensor)
                emb = outputs['spk_embedding'] if isinstance(outputs, dict) else outputs
                final_emb = emb.cpu().numpy().flatten()
                final_emb = final_emb / (np.linalg.norm(final_emb) + 1e-6)
                return final_emb
        except Exception as e:
            print(f"[Wespeaker] 提取异常: {e}")
            return None

    def get_smoothed_embedding(self, emb: np.ndarray, client_id: str) -> np.ndarray:
        """滑动窗口加权平均"""
        self.emb_buffer[client_id].append(emb)
        if len(self.emb_buffer[client_id]) > self.EMB_BUFFER_SIZE:
            self.emb_buffer[client_id].pop(0)
        
        buffer = self.emb_buffer[client_id]
        weights = np.exp(np.linspace(0, 1, len(buffer)))
        weights = weights / weights.sum()
        
        smoothed = np.average(buffer, axis=0, weights=weights)
        smoothed = smoothed / (np.linalg.norm(smoothed) + 1e-6)
        return smoothed

    def reset_buffer(self, client_id: str):
        """重置声纹缓存"""
        self.emb_buffer[client_id] = []
        self.match_history[client_id] = []

    def _get_dynamic_threshold(self, count: int) -> tuple:
        """动态阈值"""
        base_low = 0.48
        base_high = 0.58
        adjustment = min(0.05, count * 0.005)
        return base_low + adjustment, base_high + adjustment

    def compare_and_identify(self, current_emb, client_id: str) -> str:
        """说话人匹配与识别"""
        if current_emb is None: 
            return "Unknown"
        
        MIN_SAMPLES_FOR_EDGE = 3
        
        smoothed_emb = self.get_smoothed_embedding(current_emb, client_id)
        emb_list = smoothed_emb.tolist()

        results = self.collection.query(
            query_embeddings=[emb_list],
            n_results=1,
            where={"session_id": client_id}
        )

        if results['distances'] and len(results['distances'][0]) > 0:
            min_dist = results['distances'][0][0]
            best_id = results['ids'][0][0]
            metadata = results['metadatas'][0][0]
            count = metadata.get("count", 1)
            
            low_threshold, high_threshold = self._get_dynamic_threshold(count)
            
            print(f"[MATCH] Dist={min_dist:.4f}, Low={low_threshold:.2f}, High={high_threshold:.2f}, Best={best_id}, Count={count}")
            
            # 高置信度匹配
            if min_dist < low_threshold:
                old_mean = np.array(
                    self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                )
                
                weight = min(0.12, 0.8 / (count + 1))
                new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                
                self.collection.update(
                    ids=[best_id],
                    embeddings=[new_mean.tolist()],
                    metadatas=[{"session_id": client_id, "count": count + 1, "last_update": time.time()}]
                )
                print(f"[MATCHED] {best_id} (sim: {1-min_dist:.0%})")
                return best_id
            
            # 边缘匹配
            if min_dist < high_threshold:
                self.match_history[client_id].append((best_id, min_dist))
                if len(self.match_history[client_id]) > self.HISTORY_SIZE:
                    self.match_history[client_id].pop(0)
                
                recent_matches = [m[0] for m in self.match_history[client_id]]
                same_speaker_count = recent_matches.count(best_id)
                
                if same_speaker_count >= 2 or count >= MIN_SAMPLES_FOR_EDGE:
                    old_mean = np.array(
                        self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                    )
                    
                    weight = min(0.08, 0.5 / (count + 1))
                    new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                    new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                    
                    self.collection.update(
                        ids=[best_id],
                        embeddings=[new_mean.tolist()],
                        metadatas=[{"session_id": client_id, "count": count + 1, "last_update": time.time()}]
                    )
                    print(f"[EDGE OK] {best_id} (连续确认 {same_speaker_count} 次)")
                    return best_id
                
                print(f"[EDGE?] Dist={min_dist:.4f} 待确认 (连续匹配 {same_speaker_count} 次)")
        
        # 注册新说话人
        new_id = f"Spk_{int(time.time() * 1000) % 10000}"
        self.collection.add(
            ids=[new_id],
            embeddings=[emb_list],
            metadatas=[{"session_id": client_id, "count": 1, "last_update": time.time()}]
        )
        print(f"[NEW SPEAKER] {new_id}")
        return new_id