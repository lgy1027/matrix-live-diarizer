"""声纹引擎工厂与动态切换管理器"""
import os
import threading
import logging
from typing import Dict, Optional, Any

logger = logging.getLogger("Matrix_Core")

ENGINE_CONFIG = {
    "campplus": {
        "name": "CamPlus",
        "model": "damo/speech_campplus_sv_zh-cn_16k-common",
        "description": "速度快，适合实时场景",
        "description_en": "Fast speed, real-time scenes",
        "eer_voxceleb": "0.65%",
        "eer_cnceleb": "6.78%",
        "params": "7.2M",
        "speed": "快",
        "speed_en": "Fast",
        "embedding_dim": 192
    },
    "eres2net": {
        "name": "ERes2NetV2",
        "model": "iic/speech_eres2netv2_sv_zh-cn_16k-common",
        "description": "SOTA 级别精度",
        "description_en": "SOTA-level precision",
        "eer_voxceleb": "0.61%",
        "eer_cnceleb": "6.14%",
        "params": "17.8M",
        "speed": "中等",
        "speed_en": "Medium",
        "embedding_dim": 192
    },
    "wespeaker": {
        "name": "ResNet34",
        "model": "iic/speech_resnet34_sv_zh-cn_3dspeaker_16k",
        "description": "经典稳定",
        "description_en": "Classic, stable",
        "eer_voxceleb": "1.05%",
        "eer_cnceleb": "6.92%",
        "params": "6.34M",
        "speed": "快",
        "speed_en": "Fast",
        "embedding_dim": 256
    }
}

ASR_CONFIG = {
    "name": "Qwen3-ASR",
    "model": "Qwen/Qwen3-ASR-0.6B",
    "description": "阿里通义语音识别模型",
    "description_en": "Alibaba Qwen speech recognition model",
    "languages": "52种语言/方言",
    "languages_en": "52 languages / dialects"
}

# 有效引擎类型
VALID_ENGINE_TYPES = set(ENGINE_CONFIG.keys())


class SpeakerEngineManager:
    """声纹引擎管理器"""
    
    _instance: Optional['SpeakerEngineManager'] = None
    _initialized: bool = False
    _lock = threading.Lock()
    
    def __new__(cls) -> 'SpeakerEngineManager':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if SpeakerEngineManager._initialized:
            return
            
        with SpeakerEngineManager._lock:
            if SpeakerEngineManager._initialized:
                return
            
            self._engine_cache: Dict[str, Any] = {}
            self._current_type: str = get_engine_type()
            self._current_engine: Optional[Any] = None
            self._switch_lock = threading.Lock()
            self._max_cache = 2  # 最多缓存 2 个引擎实例,避免多引擎切换 OOM
            
            SpeakerEngineManager._initialized = True
            logger.info(f"[EngineManager] 初始化完成，默认引擎: {self._current_type}")
    
    def get_engine(self) -> Any:
        """获取当前引擎实例"""
        if self._current_engine is None:
            with self._switch_lock:
                if self._current_engine is None:
                    self._current_engine = self._load_engine(self._current_type)
        return self._current_engine
    
    def _load_engine(self, engine_type: str) -> Any:
        """加载引擎"""
        if engine_type in self._engine_cache:
            logger.info(f"[EngineManager] 使用缓存的引擎: {engine_type}")
            return self._engine_cache[engine_type]

        logger.info(f"[EngineManager] 加载引擎: {engine_type}")

        if engine_type == "eres2net":
            from .eres2net_engine import ERes2NetEngine
            engine = ERes2NetEngine()
        elif engine_type == "wespeaker":
            from .wespeaker_engine import WespeakerEngine
            engine = WespeakerEngine()
        else:
            from .campplus_engine import CamPlusEngine
            engine = CamPlusEngine()

        self._engine_cache[engine_type] = engine
        # LRU 淘汰:超过 max_cache 时,evict 非当前引擎(优先释放老模型占的内存)
        if len(self._engine_cache) > self._max_cache:
            to_evict = [k for k in self._engine_cache if k != self._current_type]
            for k in to_evict[:len(self._engine_cache) - self._max_cache]:
                logger.info(f"[EngineManager] evict 引擎缓存: {k} (超过 _max_cache={self._max_cache})")
                self._engine_cache.pop(k, None)
        logger.info(f"[EngineManager] 引擎已缓存: {engine_type}")

        return engine
    
    def switch_engine(self, engine_type: str) -> Dict[str, Any]:
        """切换引擎"""
        engine_type = engine_type.lower().strip()
        previous_type = self._current_type
        previous_dim = ENGINE_CONFIG.get(previous_type, {}).get("embedding_dim", 0)
        
        if engine_type not in VALID_ENGINE_TYPES:
            error_msg = f"Invalid engine type: {engine_type}. Valid types: {VALID_ENGINE_TYPES}"
            logger.error(f"[EngineManager] {error_msg}")
            return {
                "success": False,
                "error": error_msg,
                "engine_type": engine_type
            }
        
        if engine_type == self._current_type:
            return {
                "success": True,
                "engine_type": engine_type,
                "engine_info": self._get_engine_info(engine_type),
                "previous_type": previous_type,
                "already_active": True,
                "embedding_dim_changed": False
            }
        
        with self._switch_lock:
            try:
                new_engine = self._load_engine(engine_type)
                self._current_engine = new_engine
                self._current_type = engine_type
                
                new_dim = ENGINE_CONFIG.get(engine_type, {}).get("embedding_dim", 0)
                dim_changed = (previous_dim != new_dim)
                
                result = {
                    "success": True,
                    "engine_type": engine_type,
                    "engine_info": self._get_engine_info(engine_type),
                    "previous_type": previous_type,
                    "embedding_dim_changed": dim_changed,
                    "previous_dim": previous_dim,
                    "new_dim": new_dim
                }
                
                if dim_changed:
                    result["warning"] = f"Embedding dimension changed from {previous_dim} to {new_dim}. Existing speaker data may not be compatible."
                
                logger.info(f"[EngineManager] 切换成功: {previous_type} -> {engine_type}")
                return result
                
            except Exception as e:
                error_msg = f"Failed to switch engine: {str(e)}"
                logger.error(f"[EngineManager] {error_msg}")
                return {
                    "success": False,
                    "error": error_msg,
                    "engine_type": engine_type,
                    "previous_type": previous_type
                }
    
    def _get_engine_info(self, engine_type: str) -> Dict[str, Any]:
        """获取引擎信息"""
        info = ENGINE_CONFIG.get(engine_type, {}).copy()
        info["type"] = engine_type
        return info
    
    @property
    def current_type(self) -> str:
        """当前引擎类型"""
        return self._current_type
    
    @property
    def current_engine(self) -> Any:
        """当前引擎实例"""
        return self.get_engine()
    
    def get_all_engines_info(self) -> Dict[str, Any]:
        """获取所有引擎信息"""
        return {
            "current": self._current_type,
            "engines": ENGINE_CONFIG.copy()
        }
    
    def get_engine_info(self) -> dict:
        """获取当前引擎信息"""
        return self._get_engine_info(self._current_type)
    
    @classmethod
    def reset(cls):
        """重置管理器（仅用于测试）"""
        with cls._lock:
            cls._instance = None
            cls._initialized = False


# ========== 兼容旧 API ==========

def get_engine_type() -> str:
    """获取当前引擎类型"""
    return os.environ.get("SPEAKER_ENGINE", "campplus").lower()


def get_speaker_engine():
    """返回声纹引擎实例 - 使用管理器"""
    manager = SpeakerEngineManager()
    return manager.get_engine()


def get_engine_info() -> dict:
    """获取当前引擎信息"""
    manager = SpeakerEngineManager()
    return manager.get_engine_info()


def get_all_engines() -> dict:
    """获取所有引擎信息"""
    manager = SpeakerEngineManager()
    info = manager.get_all_engines_info()
    return {
        "current": info["current"],
        "asr": ASR_CONFIG,
        "speakers": info["engines"]
    }


def get_engine_manager() -> SpeakerEngineManager:
    """获取引擎管理器实例"""
    return SpeakerEngineManager()
