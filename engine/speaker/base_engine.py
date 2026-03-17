"""声纹引擎基类

提供说话人管理功能的共享实现，子类只需实现核心的声纹提取方法。
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger("Matrix_Core")


class BaseSpeakerEngine(ABC):
    """声纹引擎基类
    
    子类需要实现:
        - extract_feat: 提取声纹特征，返回 (embedding, audio_duration)
        - compare_and_identify: 说话人匹配与识别
        - _model_name: 返回模型名称用于日志
    
    注意: 子类使用 __new__ 单例模式时，所有属性初始化应在 __new__ 中完成
    """
    
    @abstractmethod
    def extract_feat(self, audio_data: np.ndarray) -> Tuple[np.ndarray, float]:
        """提取声纹特征 - 子类必须实现
        
        Returns:
            Tuple[np.ndarray, float]: (embedding, audio_duration)
        """
        pass
    
    @abstractmethod
    def compare_and_identify(self, current_emb, client_id: str, audio_duration: float = 0) -> str:
        """说话人匹配与识别 - 子类必须实现
        
        Args:
            current_emb: 当前声纹特征
            client_id: 客户端ID
            audio_duration: 音频时长（秒），用于判断可靠性
            
        Returns:
            str: 说话人ID
        """
        pass
    
    @property
    @abstractmethod
    def _model_name(self) -> str:
        """模型名称 - 用于日志"""
        pass
    
    def list_speakers(self, session_id: Optional[str] = None) -> List[Dict]:
        """获取说话人列表"""
        try:
            if session_id:
                results = self.collection.get(
                    where={"session_id": session_id},
                    include=["metadatas"]
                )
            else:
                results = self.collection.get(include=["metadatas"])
            
            speakers = []
            for i, speaker_id in enumerate(results['ids']):
                meta = results['metadatas'][i] if results['metadatas'] else {}
                speakers.append({
                    "id": speaker_id,
                    "name": meta.get("name", speaker_id),
                    "session_id": meta.get("session_id", ""),
                    "sample_count": meta.get("count", 1),
                    "last_update": meta.get("last_update", 0)
                })
            
            # 按更新时间倒序
            speakers.sort(key=lambda x: x["last_update"], reverse=True)
            return speakers
        except Exception as e:
            logger.error(f"[{self._model_name}] 获取说话人列表失败: {e}")
            return []
    
    def get_speaker(self, speaker_id: str) -> Optional[Dict]:
        """获取单个说话人信息"""
        try:
            results = self.collection.get(ids=[speaker_id], include=["metadatas"])
            if not results['ids']:
                return None
            
            meta = results['metadatas'][0]
            return {
                "id": speaker_id,
                "name": meta.get("name", speaker_id),
                "session_id": meta.get("session_id", ""),
                "sample_count": meta.get("count", 1),
                "last_update": meta.get("last_update", 0)
            }
        except Exception as e:
            logger.error(f"[{self._model_name}] 获取说话人失败: {e}")
            return None
    
    def rename_speaker(self, speaker_id: str, name: str) -> bool:
        """重命名说话人"""
        try:
            results = self.collection.get(ids=[speaker_id], include=["metadatas", "embeddings"])
            if not results['ids']:
                logger.warning(f"[{self._model_name}] 说话人 {speaker_id} 不存在")
                return False
            
            meta = results['metadatas'][0]
            meta["name"] = name
            
            self.collection.update(
                ids=[speaker_id],
                embeddings=results['embeddings'],
                metadatas=[meta]
            )
            logger.info(f"[{self._model_name}] 已重命名 {speaker_id} -> {name}")
            return True
        except Exception as e:
            logger.error(f"[{self._model_name}] 重命名失败: {e}")
            return False
    
    def delete_speaker(self, speaker_id: str) -> bool:
        """删除说话人"""
        try:
            results = self.collection.get(ids=[speaker_id])
            if not results['ids']:
                logger.warning(f"[{self._model_name}] 说话人 {speaker_id} 不存在")
                return False
            
            self.collection.delete(ids=[speaker_id])
            logger.info(f"[{self._model_name}] 已删除说话人 {speaker_id}")
            return True
        except Exception as e:
            logger.error(f"[{self._model_name}] 删除失败: {e}")
            return False
    
    def get_smoothed_embedding(self, emb: np.ndarray, client_id: str) -> np.ndarray:
        """滑动窗口平均声纹"""
        if client_id not in self.emb_buffer:
            self.emb_buffer[client_id] = []
        
        self.emb_buffer[client_id].append(emb)
        if len(self.emb_buffer[client_id]) > self.EMB_BUFFER_SIZE:
            self.emb_buffer[client_id].pop(0)
        
        smoothed = np.mean(self.emb_buffer[client_id], axis=0)
        smoothed = smoothed / (np.linalg.norm(smoothed) + 1e-6)
        return smoothed
    
    def reset_buffer(self, client_id: str):
        """重置声纹缓存"""
        self.emb_buffer[client_id] = []
    
    def cleanup_client(self, client_id: str):
        """清理客户端资源（连接断开时调用）"""
        if client_id in self.emb_buffer:
            del self.emb_buffer[client_id]
            logger.info(f"[{self._model_name}] 已清理客户端 {client_id} 的缓冲区")