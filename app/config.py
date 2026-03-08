"""配置管理"""
import os
from dataclasses import dataclass, field


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
            host=os.getenv("HOST", "0.0.0.0"),
            port=int(os.getenv("PORT", 8000)),
            workers=1,
            debug=os.getenv("DEBUG", "false").lower() == "true"
        )


@dataclass
class AudioConfig:
    """音频处理配置"""
    sample_rate: int = 16000
    buffer_threshold: int = 32000  # 2秒音频触发推理
    overlap_samples: int = 4000    # 0.25秒重叠
    silence_threshold: float = 0.008  # 降低阈值，配合 VAD 使用
    timeout_seconds: float = 30.0
    # VAD 配置
    vad_threshold: float = 0.5     # VAD 灵敏度
    min_speech_duration_ms: int = 200  # 最小语音时长
    # 增益控制
    target_rms: float = 0.08       # 目标音量
    max_gain: float = 10.0         # 最大增益倍数


@dataclass  
class SpeakerConfig:
    """声纹引擎配置"""
    engine_type: str = "campplus"  # campplus, eres2net, wespeaker
    
    @classmethod
    def from_env(cls) -> "SpeakerConfig":
        return cls(
            engine_type=os.getenv("SPEAKER_ENGINE", "campplus").lower()
        )


@dataclass
class AppConfig:
    """应用总配置"""
    server: ServerConfig = field(default_factory=ServerConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    speaker: SpeakerConfig = field(default_factory=SpeakerConfig)
    
    @classmethod
    def load(cls) -> "AppConfig":
        return cls(
            server=ServerConfig.from_env(),
            audio=AudioConfig(),
            speaker=SpeakerConfig.from_env()
        )


config = AppConfig.load()