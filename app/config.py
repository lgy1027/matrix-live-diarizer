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
class AppConfig:
    """应用配置"""
    server: ServerConfig = field(default_factory=ServerConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    speaker: SpeakerConfig = field(default_factory=SpeakerConfig)
    
    @classmethod
    def load(cls) -> "AppConfig":
        return cls(
            server=ServerConfig.from_env(),
            audio=AudioConfig.from_env(),
            speaker=SpeakerConfig.from_env()
        )


config = AppConfig.load()