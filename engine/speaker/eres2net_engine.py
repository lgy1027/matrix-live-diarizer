"""ERes2NetV2 声纹引擎

模型: iic/speech_eres2netv2_sv_zh-cn_16k-common
EER: 0.61% (VoxCeleb), 6.14% (CNCeleb)
"""
import numpy as np
import torch
import chromadb
from chromadb.config import Settings
from modelscope.models import Model
import time
import logging
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from engine.speaker.base_engine import BaseSpeakerEngine
from engine.speaker.speaker_factory import ENGINE_CONFIG

logger = logging.getLogger("Matrix_Speaker")


class ERes2NetEngine(BaseSpeakerEngine):
    """ERes2NetV2 声纹引擎 - 继承基类"""
    
    def __init__(self):
        self.device = "cpu"
        logger.info("[ERes2NetV2] 加载模型...")
        from app.services.model_resolver import resolve_modelscope
        model_id = 'iic/speech_eres2netv2_sv_zh-cn_16k-common'
        local = resolve_modelscope(
            model_id, "speaker", "eres2net",
            revision=ENGINE_CONFIG["eres2net"]["model_revision"],
        )
        self.model = Model.from_pretrained(local, device='cpu')
        self.model.eval()
        self.chroma_client = chromadb.EphemeralClient(
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name="speaker_fingerprints_eres2net",
            metadata={"hnsw:space": "cosine"}
        )
        self.emb_buffer = defaultdict(list)
        self.EMB_BUFFER_SIZE = 5
        self.match_history = defaultdict(list)
        self.HISTORY_SIZE = 3
        self.ENGINE_NAME = "ERes2NetV2"
        logger.info("[ERes2NetV2] 初始化完成")

    @property
    def _model_name(self) -> str:
        return "ERes2NetV2"

    def extract_feat(self, audio_data: np.ndarray) -> Tuple[np.ndarray, float]:
        """提取声纹特征，返回 (embedding, 音频时长)"""
        try:
            audio_duration = len(audio_data) / 16000.0
            
            tensor = torch.FloatTensor(audio_data).unsqueeze(0)
            with torch.no_grad():
                outputs = self.model(tensor)
                emb = outputs['spk_embedding'] if isinstance(outputs, dict) else outputs
                final_emb = emb.cpu().numpy().flatten()
                final_emb = final_emb / (np.linalg.norm(final_emb) + 1e-6)
                return final_emb, audio_duration
        except Exception as e:
            logger.error(f"[ERes2NetV2] 提取异常: {e}")
            return None, 0

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

    def cleanup_client(self, client_id: str):
        """清理客户端资源（连接断开时调用）"""
        if client_id in self.emb_buffer:
            del self.emb_buffer[client_id]
        if client_id in self.match_history:
            del self.match_history[client_id]
        self.delete_session_clusters(client_id)
        logger.info(f"[ERes2NetV2] 已清理客户端 {client_id} 的缓冲区")

    def _get_dynamic_threshold(self, count: int, is_reliable: bool = True) -> tuple:
        """动态阈值 - 可靠样本使用更严格阈值"""
        base_low = 0.38 if is_reliable else 0.48
        base_high = 0.48 if is_reliable else 0.58
        adjustment = min(0.05, count * 0.005)
        return base_low + adjustment, base_high + adjustment

    def compare_and_identify(
        self,
        current_emb,
        client_id: str,
        audio_duration: float = 0,
        use_buffer: bool = True,
        default_name: str | None = None,
    ) -> tuple[str, float]:
        """说话人匹配与识别

        Args:
            current_emb: 当前声纹特征
            client_id: 客户端ID
            audio_duration: 音频时长（秒）
            use_buffer: 实时流启用平滑；独立文件识别应关闭
            default_name: 新说话人的默认显示名

        Returns:
            tuple[str, float]: (说话人ID, 置信度 0.0-1.0)
        """
        if current_emb is None:
            # L4: Spk_unknown 符合 ^Spk_ 格式,与下游默认值一致
            return "Spk_unknown", 0.0

        # 判断是否为可靠样本
        is_reliable = audio_duration >= 1.5
        MIN_SAMPLES_FOR_EDGE = 2

        smoothed_emb = (
            self.get_smoothed_embedding(current_emb, client_id)
            if use_buffer
            else current_emb
        )
        emb_list = smoothed_emb.tolist()

        results = self.query_session_candidates(
            emb_list,
            client_id,
            n_results=3,
        )

        if results['distances'] and len(results['distances'][0]) > 0:
            min_dist = results['distances'][0][0]
            best_id = results['ids'][0][0]
            metadata = results['metadatas'][0][0]
            count = metadata.get("count", 1)

            low_threshold, high_threshold = self._get_dynamic_threshold(count, is_reliable)

            logger.debug(f"[MATCH] Dist={min_dist:.4f}, Low={low_threshold:.2f}, High={high_threshold:.2f}, Best={best_id}, Count={count}")

            # 高置信度匹配
            if min_dist < low_threshold:
                update_kwargs = {
                    "ids": [best_id],
                    "metadatas": [self.cluster_metadata(metadata, client_id, count + 1)],
                }
                old_mean = np.array(
                    self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                )
                weight = min(0.12, 0.8 / (count + 1))
                new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                update_kwargs["embeddings"] = [new_mean.tolist()]
                self.collection.update(**update_kwargs)
                logger.info(f"[MATCHED] {best_id} (sim: {1-min_dist:.0%})")
                return best_id, float(1 - min_dist)

            # 边缘匹配
            if min_dist < high_threshold:
                self.match_history[client_id].append((best_id, min_dist))
                if len(self.match_history[client_id]) > self.HISTORY_SIZE:
                    self.match_history[client_id].pop(0)

                recent_matches = [m[0] for m in self.match_history[client_id]]
                same_speaker_count = recent_matches.count(best_id)

                if same_speaker_count >= 2 or count >= MIN_SAMPLES_FOR_EDGE:
                    update_kwargs = {
                        "ids": [best_id],
                        "metadatas": [self.cluster_metadata(metadata, client_id, count + 1)],
                    }
                    old_mean = np.array(
                        self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                    )
                    weight = min(0.08, 0.5 / (count + 1))
                    new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                    new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                    update_kwargs["embeddings"] = [new_mean.tolist()]
                    self.collection.update(**update_kwargs)
                    logger.info(f"[EDGE MATCH] {best_id} (连续确认 {same_speaker_count} 次)")
                    return best_id, float(1 - min_dist)

                logger.debug(f"[EDGE] Dist={min_dist:.4f} 待确认 (连续匹配 {same_speaker_count} 次)")
        else:
            # 空 DB / 无候选 → 新建 Spk 路径,后续 return 用 min_dist=None 兜底
            min_dist = None

        # 注册新说话人
        new_id = f"Spk_{int(time.time_ns() % (1 << 31))}"
        self.collection.add(
            ids=[new_id],
            embeddings=[emb_list],
            metadatas=[{
                "session_id": client_id,
                "count": 1,
                "last_update": time.time(),
                "name": default_name or new_id,
            }]
        )
        logger.info(f"[NEW SPEAKER] {new_id} ({audio_duration:.1f}s)")
        # 新建 Spk 时如果有 best_dist,返 1-best_dist;无候选(空 DB)返 0.0
        new_speaker_score = float(1 - min_dist) if min_dist is not None else 0.0
        return new_id, new_speaker_score
