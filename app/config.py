"""配置管理

支持从 .env 文件和环境变量加载配置。
优先级：环境变量 > .env 文件 > 默认值
"""
import os
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("Matrix_Core")

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    # 从项目根目录加载 .env
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        logger.info(f"[CONFIG] 已加载 .env 文件: {env_path}")
    else:
        logger.info("[CONFIG] 未找到 .env 文件，使用环境变量和默认值")
except ImportError:
    logger.warning("[CONFIG] python-dotenv 未安装，仅使用环境变量和默认值")


def get_env_str(key: str, default: str = "") -> str:
    """获取字符串类型环境变量"""
    return os.getenv(key, default)


def get_env_int(key: str, default: int) -> int:
    """获取整数类型环境变量"""
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default


def get_env_float(key: str, default: float) -> float:
    """获取浮点数类型环境变量"""
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default


def get_env_bool(key: str, default: bool) -> bool:
    """获取布尔类型环境变量"""
    val = os.getenv(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1  # 单进程，防止 GPU 内存溢出
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
    buffer_threshold: int = 32000      # 2秒音频触发推理
    overlap_samples: int = 4000        # 0.25秒重叠
    silence_threshold: float = 0.008   # 静音检测阈值
    timeout_seconds: float = 30.0      # 无音频超时断开
    # VAD 配置
    vad_threshold: float = 0.5         # VAD 灵敏度
    min_speech_duration_ms: int = 200  # 最小语音时长
    # 增益控制
    target_rms: float = 0.08           # 目标音量
    max_gain: float = 10.0             # 最大增益倍数
    # 音频队列配置
    queue_size: int = 8                # 队列最大容量（帧数）
    skip_frame_threshold: int = 3      # 触发跳帧的队列阈值
    queue_monitor_interval: float = 5.0  # 队列监控间隔（秒）
    # 心跳配置
    heartbeat_interval: int = 10       # 心跳间隔（秒）
    heartbeat_timeout: int = 30        # 心跳超时（秒）
    # 缓冲区上限
    max_buffer_seconds: int = 10       # 音频缓冲区上限（秒）
    # 语音分段配置
    max_segment_seconds: int = 5       # 单个语音段最大长度（秒）
    
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
        )


@dataclass  
class SpeakerConfig:
    """声纹引擎配置"""
    engine_type: str = "campplus"  # campplus, eres2net, wespeaker
    
    @classmethod
    def from_env(cls) -> "SpeakerConfig":
        return cls(
            engine_type=get_env_str("SPEAKER_ENGINE", "campplus").lower()
        )


@dataclass
class AppConfig:
    """应用总配置"""
    server: ServerConfig = field(default_factory=ServerConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    speaker: SpeakerConfig = field(default_factory=SpeakerConfig)
    
    @classmethod
    def load(cls) -> "AppConfig":
        """加载配置，优先使用环境变量"""
        return cls(
            server=ServerConfig.from_env(),
            audio=AudioConfig.from_env(),
            speaker=SpeakerConfig.from_env()
        )


# 全局配置实例
config = AppConfig.load()

# 验证配置
def validate_config():
    """验证配置是否正确加载"""
    try:
        # 验证音频配置
        _ = config.audio.heartbeat_interval
        _ = config.audio.heartbeat_timeout
        _ = config.audio.queue_size
        _ = config.audio.buffer_threshold
        logger.info(f"[CONFIG] 配置加载成功: audio.heartbeat_interval={config.audio.heartbeat_interval}")
        return True
    except AttributeError as e:
        logger.error(f"[CONFIG] 配置加载失败: {e}")
        return False

validate_config()
