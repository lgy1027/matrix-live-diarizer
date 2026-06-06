"""配置管理 - 从 .env 文件和环境变量加载配置"""
import os
import logging
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger("Matrix_Core")

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass


def get_env_str(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def get_env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def get_env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def get_env_bool(key: str, default: bool) -> bool:
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


def get_env_str_list(key: str, default: tuple = ()) -> tuple:
    """从逗号分隔的环境变量读取字符串列表"""
    val = os.getenv(key)
    if not val:
        return default
    return tuple(h.strip() for h in val.split(",") if h.strip())


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1  # 单进程防止 GPU 内存溢出
    debug: bool = False
    
    @classmethod
    def from_env(cls) -> "ServerConfig":
        return cls(
            host=get_env_str("HOST", "0.0.0.0"),
            port=get_env_int("PORT", 8000),
            workers=get_env_int("WORKERS", 1),
            debug=get_env_bool("DEBUG", False)
        )


@dataclass
class AudioConfig:
    """音频处理配置"""
    sample_rate: int = 16000
    buffer_threshold: int = 32000       # 2秒触发推理
    overlap_samples: int = 4000         # 0.25秒重叠
    silence_threshold: float = 0.008
    timeout_seconds: float = 30.0
    # VAD
    vad_threshold: float = 0.5
    min_speech_duration_ms: int = 200
    # 增益
    target_rms: float = 0.08
    max_gain: float = 10.0
    # 队列
    queue_size: int = 8
    skip_frame_threshold: int = 3
    queue_monitor_interval: float = 5.0
    # 心跳
    heartbeat_interval: int = 10
    heartbeat_timeout: int = 30
    # 缓冲
    max_buffer_seconds: int = 10
    max_segment_seconds: int = 5
    # 上传
    upload_max_duration: int = 3600     # 1小时
    upload_chunk_duration: int = 30     # 30秒分段
    upload_overlap_duration: float = 1.0
    
    @classmethod
    def from_env(cls) -> "AudioConfig":
        return cls(
            sample_rate=get_env_int("AUDIO_SAMPLE_RATE", 16000),
            buffer_threshold=get_env_int("AUDIO_BUFFER_THRESHOLD", 32000),
            overlap_samples=get_env_int("AUDIO_OVERLAP_SAMPLES", 4000),
            silence_threshold=get_env_float("AUDIO_SILENCE_THRESHOLD", 0.008),
            timeout_seconds=get_env_float("AUDIO_TIMEOUT_SECONDS", 30.0),
            vad_threshold=get_env_float("VAD_THRESHOLD", 0.5),
            min_speech_duration_ms=get_env_int("VAD_MIN_SPEECH_DURATION", 200),
            target_rms=get_env_float("AUDIO_TARGET_RMS", 0.08),
            max_gain=get_env_float("AUDIO_MAX_GAIN", 10.0),
            queue_size=get_env_int("AUDIO_QUEUE_SIZE", 8),
            skip_frame_threshold=get_env_int("AUDIO_SKIP_FRAME_THRESHOLD", 3),
            queue_monitor_interval=get_env_float("AUDIO_QUEUE_MONITOR_INTERVAL", 5.0),
            heartbeat_interval=get_env_int("HEARTBEAT_INTERVAL", 10),
            heartbeat_timeout=get_env_int("HEARTBEAT_TIMEOUT", 30),
            max_buffer_seconds=get_env_int("AUDIO_MAX_BUFFER_SECONDS", 10),
            upload_max_duration=get_env_int("UPLOAD_MAX_DURATION", 3600),
            upload_chunk_duration=get_env_int("UPLOAD_CHUNK_DURATION", 30),
            upload_overlap_duration=get_env_float("UPLOAD_OVERLAP_DURATION", 1.0),
        )


@dataclass  
class SpeakerConfig:
    """声纹引擎: campplus / eres2net / wespeaker"""
    engine_type: str = "campplus"
    
    @classmethod
    def from_env(cls) -> "SpeakerConfig":
        return cls(
            engine_type=get_env_str("SPEAKER_ENGINE", "campplus").lower()
        )


@dataclass
class RateLimitConfig:
    """速率限制配置"""
    enabled: bool = True
    requests_per_minute: int = 60      # 每分钟请求数
    requests_per_hour: int = 1000      # 每小时请求数

    @classmethod
    def from_env(cls) -> "RateLimitConfig":
        return cls(
            enabled=get_env_bool("RATE_LIMIT_ENABLED", True),
            requests_per_minute=get_env_int("RATE_LIMIT_REQUESTS_PER_MINUTE", 60),
            requests_per_hour=get_env_int("RATE_LIMIT_REQUESTS_PER_HOUR", 1000),
        )


@dataclass
class StorageConfig:
    """SQLite 存储配置"""
    db_path: str = "./data/matrix.db"
    history_enabled: bool = True

    @classmethod
    def from_env(cls) -> "StorageConfig":
        return cls(
            db_path=get_env_str("STORAGE_DB_PATH", "./data/matrix.db"),
            history_enabled=get_env_bool("STORAGE_HISTORY_ENABLED", True),
        )


@dataclass
class LLMConfig:
    """本地 LLM 插件配置"""
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen2.5:1.5b"
    timeout_sec: int = 60
    max_input_tokens: int = 8000
    mock: bool = False
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "::1", "localhost")

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            enabled=get_env_bool("LLM_ENABLED", False),
            endpoint=get_env_str("LLM_ENDPOINT", "http://127.0.0.1:11434/v1"),
            model=get_env_str("LLM_MODEL", "qwen2.5:1.5b"),
            timeout_sec=get_env_int("LLM_TIMEOUT_SEC", 60),
            max_input_tokens=get_env_int("LLM_MAX_INPUT_TOKENS", 8000),
            mock=get_env_bool("LLM_MOCK", False),
            allowed_hosts=get_env_str_list("LLM_ALLOWED_HOSTS",
                                          ("127.0.0.1", "::1", "localhost")),
        )


@dataclass
class HistoryConfig:
    """历史存档策略"""
    retention_days: int = 0
    auto_archive: bool = False

    @classmethod
    def from_env(cls) -> "HistoryConfig":
        return cls(
            retention_days=get_env_int("HISTORY_RETENTION_DAYS", 0),
            auto_archive=get_env_bool("HISTORY_AUTO_ARCHIVE", False),
        )


@dataclass
class AppConfig:
    """应用配置"""
    server: ServerConfig = field(default_factory=ServerConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    speaker: SpeakerConfig = field(default_factory=SpeakerConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)

    @classmethod
    def load(cls) -> "AppConfig":
        return cls(
            server=ServerConfig.from_env(),
            audio=AudioConfig.from_env(),
            speaker=SpeakerConfig.from_env(),
            rate_limit=RateLimitConfig.from_env(),
            storage=StorageConfig.from_env(),
            llm=LLMConfig.from_env(),
            history=HistoryConfig.from_env(),
        )


config = AppConfig.load()