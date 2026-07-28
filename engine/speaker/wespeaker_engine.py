"""Wespeaker ResNet34 声纹引擎

模型: iic/speech_resnet34_sv_zh-cn_3dspeaker_16k
EER: 1.05% (VoxCeleb), 6.92% (CNCeleb)
"""
import numpy as np
import torch
import chromadb
from chromadb.config import Settings
import time
import logging
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from engine.speaker.base_engine import BaseSpeakerEngine
from engine.speaker.speaker_factory import ENGINE_CONFIG

logger = logging.getLogger("Matrix_Speaker")


class WespeakerEngine(BaseSpeakerEngine):
    """Wespeaker ResNet34 声纹引擎 - 继承基类"""
    
    def __init__(self):
        self.device = "cpu"
        self._init_model()
        self.chroma_client = chromadb.EphemeralClient(
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name="speaker_fingerprints_wespeaker",
            metadata={"hnsw:space": "cosine"}
        )
        self.emb_buffer = defaultdict(list)
        self.EMB_BUFFER_SIZE = 5
        self.match_history = defaultdict(list)
        self.HISTORY_SIZE = 3
        self.ENGINE_NAME = "Wespeaker"
        logger.info("[Wespeaker] 初始化完成")

    def _init_model(self):
        """初始化模型"""
        logger.info("[Wespeaker] 加载模型...")
        from modelscope.models import Model
        from app.services.model_resolver import resolve_modelscope
        model_id = 'iic/speech_resnet34_sv_zh-cn_3dspeaker_16k'
        local = resolve_modelscope(
            model_id, "speaker", "wespeaker",
            revision=ENGINE_CONFIG["wespeaker"]["model_revision"],
        )
        logger.info("[Wespeaker] 从本地路径加载: %s", local)
        self.model = Model.from_pretrained(local, device='cpu')
        self.model.eval()
        logger.info("[Wespeaker] ResNet34 模型加载成功")

    @property
    def _model_name(self) -> str:
        return "Wespeaker"

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
            logger.error(f"[Wespeaker] 提取异常: {e}")
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
        logger.info(f"[Wespeaker] 已清理客户端 {client_id} 的缓冲区")

    # compare_and_identify + _get_dynamic_threshold 已上提到 BaseSpeakerEngine,
    # 这里只提供本引擎的阈值基线 (reliable_low, reliable_high, unreliable_low, unreliable_high)
    THRESHOLD_PROFILE = (0.44, 0.54, 0.54, 0.64)
