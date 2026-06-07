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
import logging
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from engine.speaker.base_engine import BaseSpeakerEngine

logger = logging.getLogger("Matrix_Speaker")
current_dir = os.path.dirname(os.path.abspath(__file__))


class CamPlusEngine(BaseSpeakerEngine):
    """CamPlus 声纹引擎 - 继承基类
    
    优化策略：
    1. 短音频处理：不足2秒的音频标记为"临时说话人"
    2. 延迟注册：需要多个样本确认新说话人
    3. 智能合并：相似度高的临时说话人自动合并
    """
    
    _instance = None
    
    # 最小音频长度（秒）用于可靠声纹提取
    MIN_AUDIO_DURATION = 1.5
    
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
            cls._instance.EMB_BUFFER_SIZE = 5  # 增加平滑窗口
            
            # 临时说话人缓存：存储待确认的说话人
            # {client_id: [(emb, audio_duration), ...]}
            cls._instance.pending_speakers = defaultdict(list)
            cls._instance.PENDING_THRESHOLD = 3  # 需要3个样本才确认新说话人
            
            cls._instance.ENGINE_NAME = "CamPlus"
            
            logger.info("[CamPlus] 引擎初始化完成")
        return cls._instance

    @property
    def _model_name(self) -> str:
        return "CamPlus"

    def extract_feat(self, audio_data: np.ndarray) -> Tuple[np.ndarray, float]:
        """提取声纹特征，返回 (embedding, 音频时长)"""
        try:
            audio_duration = len(audio_data) / 16000.0  # 假设16kHz采样率
            
            tensor = torch.FloatTensor(audio_data).unsqueeze(0)
            with torch.no_grad():
                outputs = self.model(tensor)
                emb = outputs['spk_embedding'] if isinstance(outputs, dict) else outputs
                final_emb = emb.cpu().numpy().flatten()
                final_emb = final_emb / (np.linalg.norm(final_emb) + 1e-6)
                return final_emb, audio_duration
        except Exception as e:
            logger.error(f"[CamPlus] 提取异常: {e}")
            return None, 0

    def get_smoothed_embedding(self, emb: np.ndarray, client_id: str) -> np.ndarray:
        """滑动窗口平均声纹（仅实时流使用，文件上传应直接用原 embedding）"""
        self.emb_buffer[client_id].append(emb)
        if len(self.emb_buffer[client_id]) > self.EMB_BUFFER_SIZE:
            self.emb_buffer[client_id].pop(0)

        smoothed = np.mean(self.emb_buffer[client_id], axis=0)
        smoothed = smoothed / (np.linalg.norm(smoothed) + 1e-6)
        return smoothed

    def reset_buffer(self, client_id: str):
        """重置声纹缓存"""
        self.emb_buffer[client_id] = []
        # 不重置 pending_speakers，保留累积信息

    def cleanup_client(self, client_id: str):
        """清理客户端资源（连接断开时调用）"""
        if client_id in self.emb_buffer:
            del self.emb_buffer[client_id]
        if client_id in self.pending_speakers:
            del self.pending_speakers[client_id]
        logger.info(f"[CamPlus] 已清理客户端 {client_id} 的缓冲区")

    def _check_pending_speakers(self, emb: np.ndarray, client_id: str) -> Optional[str]:
        """检查临时说话人缓存，看是否匹配已有的临时说话人"""
        if client_id not in self.pending_speakers:
            return None

        pending_list = self.pending_speakers[client_id]

        for i, (pending_emb, _, spk_id, count) in enumerate(pending_list):
            # 计算相似度
            similarity = np.dot(emb, pending_emb)
            distance = 1 - similarity

            if distance < 0.40:  # 相似度 > 60%
                # 更新临时说话人
                new_count = count + 1
                # 更新平均 embedding
                new_emb = (pending_emb * count + emb) / new_count
                new_emb = new_emb / (np.linalg.norm(new_emb) + 1e-6)

                pending_list[i] = (new_emb, 0, spk_id, new_count)

                # 如果累积足够样本，正式注册
                if new_count >= self.PENDING_THRESHOLD:
                    self.collection.add(
                        ids=[spk_id],
                        embeddings=[new_emb.tolist()],
                        metadatas=[{"session_id": client_id, "count": new_count, "last_update": time.time(), "confirmed": True}]
                    )
                    logger.info(f"[CONFIRMED] {spk_id} (samples={new_count})")
                    pending_list.pop(i)
                    return spk_id

                logger.debug(f"[PENDING MATCH] {spk_id} (samples={new_count}/{self.PENDING_THRESHOLD})")
                return spk_id

        return None

    def compare_and_identify(self, current_emb, client_id: str, audio_duration: float = 0, use_buffer: bool = True) -> str:
        """说话人匹配与识别 - 优化版

        Args:
            current_emb: 当前声纹特征
            client_id: 客户端ID
            audio_duration: 音频时长（秒），用于判断可靠性
            use_buffer: 是否使用滑动窗口平滑。
                - True (默认): 实时流场景，同一 client 持续说话，buffer 平滑抖动
                - False: 文件上传场景，每次上传是独立 speaker 查询，buffer 残留会污染
        """
        if current_emb is None:
            return "Unknown"

        # 确定是否为可靠样本
        is_reliable = audio_duration >= self.MIN_AUDIO_DURATION

        # 阈值: 距离越小越相似
        # 放宽高置信度阈值，收紧边缘阈值
        LOW_THRESHOLD = 0.40      # 高置信度 (相似度 > 60%)
        HIGH_THRESHOLD = 0.50     # 边缘区域 (相似度 > 50%)
        MIN_SAMPLES_FOR_EDGE = 2  # 降低边缘匹配样本要求

        # 实时流：用滑动窗口平滑（抖动场景）
        # 文件上传：直接用当前 embedding（避免 buffer 跨文件污染）
        if use_buffer:
            smoothed_emb = self.get_smoothed_embedding(current_emb, client_id)
        else:
            smoothed_emb = current_emb
        emb_list = smoothed_emb.tolist()

        # 先检查临时说话人缓存
        pending_spk = self._check_pending_speakers(smoothed_emb, client_id)
        if pending_spk:
            return pending_spk

        # 查询已确认的说话人
        results = self.collection.query(
            query_embeddings=[emb_list],
            n_results=3,  # 获取前3个候选
            where={"session_id": client_id}
        )

        if results['distances'] and len(results['distances'][0]) > 0:
            # 找最佳匹配
            best_dist = results['distances'][0][0]
            best_id = results['ids'][0][0]
            best_meta = results['metadatas'][0][0]
            best_count = best_meta.get("count", 1)
            
            # 对于可靠样本，使用更严格的阈值
            # 对于不可靠样本，使用更宽松的阈值（倾向于匹配已有说话人）
            low_thresh = LOW_THRESHOLD if is_reliable else LOW_THRESHOLD + 0.10
            high_thresh = HIGH_THRESHOLD if is_reliable else HIGH_THRESHOLD + 0.10
            
            logger.debug(f"[MATCH] Dist={best_dist:.4f}, Best={best_id}, Count={best_count}, Reliable={is_reliable}")
            
            # 高置信度匹配
            if best_dist < low_thresh:
                old_mean = np.array(
                    self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                )
                
                # 自适应权重：样本越多更新越保守
                weight = min(0.15, 1.5 / (best_count + 1))
                new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                
                self.collection.update(
                    ids=[best_id],
                    embeddings=[new_mean.tolist()],
                    metadatas=[{"session_id": client_id, "count": best_count + 1, "last_update": time.time(), "confirmed": True}]
                )
                logger.info(f"[MATCHED] {best_id} (sim: {1-best_dist:.0%}, samples={best_count+1})")
                return best_id
            
            # 边缘匹配：需要已有足够样本
            if best_dist < high_thresh and best_count >= MIN_SAMPLES_FOR_EDGE:
                old_mean = np.array(
                    self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                )
                
                weight = min(0.10, 1.0 / (best_count + 1))
                new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                
                self.collection.update(
                    ids=[best_id],
                    embeddings=[new_mean.tolist()],
                    metadatas=[{"session_id": client_id, "count": best_count + 1, "last_update": time.time(), "confirmed": True}]
                )
                logger.info(f"[EDGE OK] {best_id} (sim: {1-best_dist:.0%}, samples={best_count+1})")
                return best_id
            
            # 检查第二、第三候选（可能有更好的匹配）
            for i in range(1, min(3, len(results['distances'][0]))):
                dist = results['distances'][0][i]
                spk_id = results['ids'][0][i]
                meta = results['metadatas'][0][i]
                count = meta.get("count", 1)
                
                if dist < high_thresh and count >= MIN_SAMPLES_FOR_EDGE:
                    old_mean = np.array(
                        self.collection.get(ids=[spk_id], include=['embeddings'])['embeddings'][0]
                    )
                    
                    weight = min(0.10, 1.0 / (count + 1))
                    new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                    new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                    
                    self.collection.update(
                        ids=[spk_id],
                        embeddings=[new_mean.tolist()],
                        metadatas=[{"session_id": client_id, "count": count + 1, "last_update": time.time(), "confirmed": True}]
                    )
                    logger.info(f"[ALT MATCH] {spk_id} (sim: {1-dist:.0%}, samples={count+1})")
                    return spk_id
            
            if best_dist < high_thresh:
                logger.debug(f"[EDGE?] Dist={best_dist:.4f} 样本不足({best_count}<{MIN_SAMPLES_FOR_EDGE})")
            else:
                logger.debug(f"[NEW?] Dist={best_dist:.4f}")

        # 注册新说话人（但可能还在待确认状态）
        new_id = f"Spk_{int(time.time_ns() % (1 << 31))}"
        
        if is_reliable:
            # 可靠样本：直接注册
            self.collection.add(
                ids=[new_id],
                embeddings=[emb_list],
                metadatas=[{"session_id": client_id, "count": 1, "last_update": time.time(), "confirmed": True}]
            )
            logger.info(f"[NEW SPEAKER] {new_id} (reliable, {audio_duration:.1f}s)")
        else:
            # 不可靠样本：放入待确认缓存
            self.pending_speakers[client_id].append((smoothed_emb, audio_duration, new_id, 1))
            logger.info(f"[PENDING] {new_id} (unreliable, {audio_duration:.1f}s, need {self.PENDING_THRESHOLD} samples)")
            
            # 如果待确认缓存超过限制，强制注册最老的一个
            if len(self.pending_speakers[client_id]) > 5:
                old_emb, _, old_id, old_count = self.pending_speakers[client_id].pop(0)
                self.collection.add(
                    ids=[old_id],
                    embeddings=[old_emb.tolist()],
                    metadatas=[{"session_id": client_id, "count": old_count, "last_update": time.time(), "confirmed": False}]
                )
                logger.info(f"[FORCE REGISTER] {old_id} (pending overflow)")
        
        return new_id
