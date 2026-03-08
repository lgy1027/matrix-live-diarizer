"""CamPlus 声纹引擎

模型: damo/speech_campplus_sv_zh-cn_16k-common
EER: 0.65% (VoxCeleb)
"""
import numpy as np
import torch
import chromadb
from modelscope.models import Model
import time
import os
from collections import defaultdict

current_dir = os.path.dirname(os.path.abspath(__file__))


class CamPlusEngine:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CamPlusEngine, cls).__new__(cls)
            
            model_id = 'damo/speech_campplus_sv_zh-cn_16k-common'
            cls._instance.model = Model.from_pretrained(model_id, device='cpu')
            cls._instance.model.eval()
            
            cls._instance.chroma_client = chromadb.PersistentClient(
                path=os.path.join(current_dir, "speaker_db", "campplus")
            )
            cls._instance.collection = cls._instance.chroma_client.get_or_create_collection(
                name="speaker_fingerprints",
                metadata={"hnsw:space": "cosine"}
            )
            
            cls._instance.emb_buffer = defaultdict(list)
            cls._instance.EMB_BUFFER_SIZE = 3
            
            print("[CamPlus] 引擎初始化完成")
        return cls._instance

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
            print(f"[CamPlus] 提取异常: {e}")
            return None

    def get_smoothed_embedding(self, emb: np.ndarray, client_id: str) -> np.ndarray:
        """滑动窗口平均声纹"""
        self.emb_buffer[client_id].append(emb)
        if len(self.emb_buffer[client_id]) > self.EMB_BUFFER_SIZE:
            self.emb_buffer[client_id].pop(0)
        
        smoothed = np.mean(self.emb_buffer[client_id], axis=0)
        smoothed = smoothed / (np.linalg.norm(smoothed) + 1e-6)
        return smoothed

    def reset_buffer(self, client_id: str):
        """重置声纹缓存"""
        self.emb_buffer[client_id] = []

    def compare_and_identify(self, current_emb, client_id: str) -> str:
        """说话人匹配与识别"""
        if current_emb is None: 
            return "Unknown"
        
        # 阈值: 距离越小越相似
        LOW_THRESHOLD = 0.45    # 高置信度
        HIGH_THRESHOLD = 0.55   # 边缘区域
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
            
            print(f"[MATCH] Dist={min_dist:.4f}, Best={best_id}, Count={count}")
            
            # 高置信度匹配
            if min_dist < LOW_THRESHOLD:
                old_mean = np.array(
                    self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                )
                
                weight = min(0.12, 1.0 / (count + 1))
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
            if min_dist < HIGH_THRESHOLD and count >= MIN_SAMPLES_FOR_EDGE:
                old_mean = np.array(
                    self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                )
                
                weight = min(0.08, 1.0 / (count + 1))
                new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                
                self.collection.update(
                    ids=[best_id],
                    embeddings=[new_mean.tolist()],
                    metadatas=[{"session_id": client_id, "count": count + 1, "last_update": time.time()}]
                )
                print(f"[EDGE OK] {best_id} (sim: {1-min_dist:.0%}, samples={count})")
                return best_id
            
            if min_dist < HIGH_THRESHOLD:
                print(f"[EDGE?] Dist={min_dist:.4f} 样本不足({count}<{MIN_SAMPLES_FOR_EDGE})")
            else:
                print(f"[NEW] Dist={min_dist:.4f}")

        # 注册新说话人
        new_id = f"Spk_{int(time.time() * 1000) % 10000}"
        self.collection.add(
            ids=[new_id],
            embeddings=[emb_list],
            metadatas=[{"session_id": client_id, "count": 1, "last_update": time.time()}]
        )
        print(f"[NEW SPEAKER] {new_id}")
        return new_id