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
        logger.info("[ERes2NetV2] 从本地路径加载: %s", local)
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

    # compare_and_identify + _get_dynamic_threshold 已上提到 BaseSpeakerEngine,
    # 这里只提供本引擎的阈值基线 (reliable_low, reliable_high, unreliable_low, unreliable_high)
    THRESHOLD_PROFILE = (0.38, 0.48, 0.48, 0.58)
