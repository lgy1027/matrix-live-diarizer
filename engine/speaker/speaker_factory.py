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
        "embedding_dim": 192,
        "model_revision": os.environ.get("CAMPPLUS_MODEL_REVISION", "v2.0.2"),
        "embedding_contract_version": "1",
        "normalization": "l2",
        "person_match_threshold": 0.78,
        "person_match_margin": 0.03,
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
        "embedding_dim": 192,
        "model_revision": os.environ.get("ERES2NET_MODEL_REVISION", "v1.0.2"),
        "embedding_contract_version": "1",
        "normalization": "l2",
        "person_match_threshold": 0.78,
        "person_match_margin": 0.03,
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
        "embedding_dim": 256,
        "model_revision": os.environ.get(
            "WESPEAKER_MODEL_REVISION",
            "89de0177e452fd9770ce2d4b26085de46dae65a0",
        ),
        "embedding_contract_version": "1",
        "normalization": "l2",
        "person_match_threshold": 0.78,
        "person_match_margin": 0.03,
    }
}

# 有效引擎类型
VALID_ENGINE_TYPES = set(ENGINE_CONFIG.keys())

_ENGINE_ALIASES = {
    "campplus": "campplus",
    "camplus": "campplus",
    "eres2net": "eres2net",
    "eres2netv2": "eres2net",
    "wespeaker": "wespeaker",
    "resnet34": "wespeaker",
}


def engine_type_for(identifier: object) -> str | None:
    """Resolve a configured engine without importing heavyweight model modules."""
    if not isinstance(identifier, str):
        explicit = getattr(identifier, "engine_type", None)
        if isinstance(explicit, str):
            identifier = explicit
        else:
            identifier = getattr(identifier, "_model_name", identifier.__class__.__name__)
    raw_identifier = str(identifier).strip()
    for engine_type, info in ENGINE_CONFIG.items():
        if raw_identifier.startswith(f"modelscope:{info['model']}?"):
            return engine_type
    normalized = raw_identifier.lower().replace("-", "").replace("_", "")
    for alias, engine_type in _ENGINE_ALIASES.items():
        if normalized == alias.replace("_", ""):
            return engine_type
    return None


def embedding_model_id(engine: object, embedding_dim: int | None = None) -> str:
    """Return the stable compatibility identity of an embedding vector.

    This is deliberately stricter than a display name: changing the upstream
    model revision, vector dimension or normalization contract creates a new
    identity and prevents accidental cross-model cosine comparisons.
    """
    engine_type = engine_type_for(engine)
    if engine_type is None:
        # Third-party engines keep their explicit identifier for backwards
        # compatibility. Integrators should expose ``model_id`` themselves.
        descriptor = vars(type(engine)).get("model_id") if not isinstance(engine, str) else None
        explicit = (
            descriptor.__get__(engine, type(engine))
            if hasattr(descriptor, "__get__")
            else descriptor
        )
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        return str(
            engine
            if isinstance(engine, str)
            else getattr(engine, "_model_name", engine.__class__.__name__)
        )
    info = ENGINE_CONFIG[engine_type]
    dimension = int(embedding_dim or info["embedding_dim"])
    return (
        f"modelscope:{info['model']}?revision={info['model_revision']}"
        f"&contract={info['embedding_contract_version']}"
        f"&dim={dimension}&normalization={info['normalization']}"
    )


def resolve_embedding_model_id(
    stored_identifier: str | None,
    embedding_dim: int | None,
) -> str | None:
    """Resolve legacy ``model_name`` values, rejecting incompatible vectors."""
    if not stored_identifier or not embedding_dim:
        return None
    engine_type = engine_type_for(stored_identifier)
    if engine_type is None:
        return stored_identifier
    expected_dim = int(ENGINE_CONFIG[engine_type]["embedding_dim"])
    if int(embedding_dim) != expected_dim:
        return None
    return embedding_model_id(engine_type, expected_dim)


def person_match_defaults(model_identifier: object) -> tuple[float, float]:
    """Return the independently calibratable threshold and runner-up margin."""
    engine_type = engine_type_for(model_identifier)
    info = ENGINE_CONFIG.get(engine_type or "", {})
    return (
        float(info.get("person_match_threshold", 0.78)),
        float(info.get("person_match_margin", 0.03)),
    )


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
            self._current_type: str = _configured_engine_type()
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
        # LRU 淘汰:超过 max_cache 时,evict 非当前引擎(优先释放老模型占的内存)。
        # Python 3.7+ dict 保持插入序,新引擎在末尾,to_evict[:N] 从前面删最旧的,
        # 新引擎不会被自身淘汰逻辑 pop 掉。
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
        previous_model_id = embedding_model_id(previous_type)
        
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
                new_model_id = embedding_model_id(engine_type)
                model_id_changed = previous_model_id != new_model_id
                
                result = {
                    "success": True,
                    "engine_type": engine_type,
                    "engine_info": self._get_engine_info(engine_type),
                    "previous_type": previous_type,
                    "embedding_dim_changed": dim_changed,
                    "embedding_model_changed": model_id_changed,
                    "previous_dim": previous_dim,
                    "new_dim": new_dim,
                    "previous_model_id": previous_model_id,
                    "new_model_id": new_model_id,
                }
                
                if model_id_changed:
                    result["warning"] = (
                        "Embedding model changed. Existing voice samples from the "
                        "previous model will stay stored but will not be compared."
                    )
                
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
        info["model_id"] = embedding_model_id(engine_type)
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


def _configured_engine_type() -> str:
    """读取启动时配置的默认声纹引擎。"""
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
    """返回当前 ASR 和声纹模型目录。"""
    manager = SpeakerEngineManager()
    info = manager.get_all_engines_info()
    from engine.asr import get_all_asr_engines, get_asr_engine_info

    return {
        "current": info["current"],
        "asr": get_asr_engine_info(),
        "asr_engines": get_all_asr_engines(),
        "speakers": info["engines"]
    }


def get_engine_manager() -> SpeakerEngineManager:
    """获取引擎管理器实例"""
    return SpeakerEngineManager()
