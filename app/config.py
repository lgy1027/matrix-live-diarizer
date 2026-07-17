"""配置管理 - 从 .env 文件和环境变量加载配置"""
import os
import logging
from pathlib import Path
from typing import Optional
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
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1  # 单进程防止 GPU 内存溢出
    debug: bool = False
    
    @classmethod
    def from_env(cls) -> "ServerConfig":
        return cls(
            host=get_env_str("HOST", "127.0.0.1"),
            port=get_env_int("PORT", 8000),
            workers=get_env_int("WORKERS", 1),
            debug=get_env_bool("DEBUG", False)
        )


@dataclass
class DeploymentConfig:
    """部署模式: local / lan / public"""
    mode: str = "local"

    @classmethod
    def from_env(cls) -> "DeploymentConfig":
        mode = get_env_str("DEPLOYMENT_MODE", "local").lower().strip()
        if mode not in ("local", "lan", "public"):
            logger.warning(f"无效 DEPLOYMENT_MODE={mode!r},回退 local")
            mode = "local"
        return cls(mode=mode)


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
    # ASR 设备：auto | cpu | mps | cuda
    # auto 优先 mps，加载超时后回退 cpu
    # ASR 引擎：qwen3 | sensevoice | paraformer | paraformer_streaming
    asr_engine: str = "qwen3"
    asr_device: str = "auto"
    asr_load_timeout_sec: int = 90      # 单设备加载超时（秒）
    # ASR 字级时间戳：开启后额外加载 Qwen3-ForcedAligner-0.6B (~600MB),
    # 用于返回每字的 start/end 时间。关闭则只返回 segment 文本。
    asr_word_timestamps: bool = False

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
            asr_engine=get_env_str("ASR_ENGINE", "qwen3").lower(),
            asr_device=get_env_str("ASR_DEVICE", "auto").lower(),
            asr_load_timeout_sec=get_env_int("ASR_LOAD_TIMEOUT_SEC", 90),
            asr_word_timestamps=get_env_bool("ASR_WORD_TIMESTAMPS", False),
        )


@dataclass  
class SpeakerConfig:
    """声纹引擎: campplus / eres2net / wespeaker"""
    engine_type: str = "campplus"
    # Legacy fallback kept for integrations that have not selected an engine.
    person_match_threshold: float = 0.78
    person_match_margin: float = 0.03
    campplus_match_threshold: float = 0.78
    campplus_match_margin: float = 0.03
    eres2net_match_threshold: float = 0.78
    eres2net_match_margin: float = 0.03
    wespeaker_match_threshold: float = 0.78
    wespeaker_match_margin: float = 0.03
    person_auto_match_threshold: float = 0.88
    person_auto_match_margin: float = 0.08
    campplus_auto_match_threshold: float = 0.88
    campplus_auto_match_margin: float = 0.08
    eres2net_auto_match_threshold: float = 0.88
    eres2net_auto_match_margin: float = 0.08
    wespeaker_auto_match_threshold: float = 0.88
    wespeaker_auto_match_margin: float = 0.08
    diarization_device: str = "auto"

    def person_match_policy(self, model_identifier: object) -> tuple[float, float]:
        """Return an engine-specific acceptance threshold and ambiguity margin."""
        from engine.speaker.speaker_factory import engine_type_for

        engine_type = engine_type_for(model_identifier)
        if engine_type == "campplus":
            return self.campplus_match_threshold, self.campplus_match_margin
        if engine_type == "eres2net":
            return self.eres2net_match_threshold, self.eres2net_match_margin
        if engine_type == "wespeaker":
            return self.wespeaker_match_threshold, self.wespeaker_match_margin
        return self.person_match_threshold, self.person_match_margin

    def person_auto_match_policy(self, model_identifier: object) -> tuple[float, float]:
        """Return the stricter policy required to display a name automatically."""
        from engine.speaker.speaker_factory import engine_type_for

        engine_type = engine_type_for(model_identifier)
        if engine_type == "campplus":
            configured = (
                self.campplus_auto_match_threshold,
                self.campplus_auto_match_margin,
            )
        elif engine_type == "eres2net":
            configured = (
                self.eres2net_auto_match_threshold,
                self.eres2net_auto_match_margin,
            )
        elif engine_type == "wespeaker":
            configured = (
                self.wespeaker_auto_match_threshold,
                self.wespeaker_auto_match_margin,
            )
        else:
            configured = (
                self.person_auto_match_threshold,
                self.person_auto_match_margin,
            )
        suggestion = self.person_match_policy(model_identifier)
        return max(configured[0], suggestion[0]), max(configured[1], suggestion[1])
    
    @classmethod
    def from_env(cls) -> "SpeakerConfig":
        diarization_device = get_env_str("PYANNOTE_DEVICE", "auto").lower()
        if diarization_device not in {"auto", "cpu", "cuda"}:
            logger.warning(
                "无效 PYANNOTE_DEVICE=%r，回退 auto", diarization_device
            )
            diarization_device = "auto"
        fallback_threshold = get_env_float("PERSON_MATCH_THRESHOLD", 0.78)
        fallback_margin = get_env_float("PERSON_MATCH_MARGIN", 0.03)
        fallback_auto_threshold = get_env_float("PERSON_AUTO_MATCH_THRESHOLD", 0.88)
        fallback_auto_margin = get_env_float("PERSON_AUTO_MATCH_MARGIN", 0.08)
        return cls(
            engine_type=get_env_str("SPEAKER_ENGINE", "campplus").lower(),
            person_match_threshold=fallback_threshold,
            person_match_margin=fallback_margin,
            campplus_match_threshold=get_env_float(
                "PERSON_MATCH_THRESHOLD_CAMPPLUS", fallback_threshold
            ),
            campplus_match_margin=get_env_float(
                "PERSON_MATCH_MARGIN_CAMPPLUS", fallback_margin
            ),
            eres2net_match_threshold=get_env_float(
                "PERSON_MATCH_THRESHOLD_ERES2NET", fallback_threshold
            ),
            eres2net_match_margin=get_env_float(
                "PERSON_MATCH_MARGIN_ERES2NET", fallback_margin
            ),
            wespeaker_match_threshold=get_env_float(
                "PERSON_MATCH_THRESHOLD_WESPEAKER", fallback_threshold
            ),
            wespeaker_match_margin=get_env_float(
                "PERSON_MATCH_MARGIN_WESPEAKER", fallback_margin
            ),
            person_auto_match_threshold=fallback_auto_threshold,
            person_auto_match_margin=fallback_auto_margin,
            campplus_auto_match_threshold=get_env_float(
                "PERSON_AUTO_MATCH_THRESHOLD_CAMPPLUS", fallback_auto_threshold
            ),
            campplus_auto_match_margin=get_env_float(
                "PERSON_AUTO_MATCH_MARGIN_CAMPPLUS", fallback_auto_margin
            ),
            eres2net_auto_match_threshold=get_env_float(
                "PERSON_AUTO_MATCH_THRESHOLD_ERES2NET", fallback_auto_threshold
            ),
            eres2net_auto_match_margin=get_env_float(
                "PERSON_AUTO_MATCH_MARGIN_ERES2NET", fallback_auto_margin
            ),
            wespeaker_auto_match_threshold=get_env_float(
                "PERSON_AUTO_MATCH_THRESHOLD_WESPEAKER", fallback_auto_threshold
            ),
            wespeaker_auto_match_margin=get_env_float(
                "PERSON_AUTO_MATCH_MARGIN_WESPEAKER", fallback_auto_margin
            ),
            diarization_device=diarization_device,
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
    media_dir: str = "./data/media"

    @classmethod
    def from_env(cls) -> "StorageConfig":
        return cls(
            db_path=get_env_str("STORAGE_DB_PATH", "./data/matrix.db"),
            media_dir=get_env_str("STORAGE_MEDIA_DIR", "./data/media"),
        )


@dataclass
class CORSConfig:
    """Browser origins allowed to call the local API."""
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    allow_credentials: bool = False             # Matrix 不用 cookie 认证,默认 False
    allow_methods: tuple[str, ...] = ("*",)     # 允许所有 HTTP 方法
    allow_headers: tuple[str, ...] = ("*",)     # 允许所有 header

    @classmethod
    def from_env(cls) -> "CORSConfig":
        return cls(
            allowed_origins=get_env_str_list("ALLOWED_ORIGINS", cls.allowed_origins),
            allow_credentials=get_env_bool("CORS_ALLOW_CREDENTIALS", False),
            allow_methods=get_env_str_list("CORS_ALLOW_METHODS", ("*",)),
            allow_headers=get_env_str_list("CORS_ALLOW_HEADERS", ("*",)),
        )


@dataclass
class LLMConfig:
    """LLM 插件配置（默认仅本机，allow_public=True 时可走公网 OpenAI 兼容接口）"""
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen2.5:1.5b"
    api_key: Optional[str] = None           # Bearer token，公网 OpenAI 兼容接口需要
    timeout_sec: int = 60
    max_input_tokens: int = 8000
    mock: bool = False
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "::1", "localhost")
    allow_public: bool = False              # 显式开公网（默认安全 = 仅本机）

    @classmethod
    def from_env(cls) -> "LLMConfig":
        api_key = get_env_str("LLM_API_KEY", "") or None
        return cls(
            enabled=get_env_bool("LLM_ENABLED", False),
            endpoint=get_env_str("LLM_ENDPOINT", "http://127.0.0.1:11434/v1"),
            model=get_env_str("LLM_MODEL", "qwen2.5:1.5b"),
            api_key=api_key,
            timeout_sec=get_env_int("LLM_TIMEOUT_SEC", 60),
            max_input_tokens=get_env_int("LLM_MAX_INPUT_TOKENS", 8000),
            mock=get_env_bool("LLM_MOCK", False),
            allowed_hosts=get_env_str_list("LLM_ALLOWED_HOSTS",
                                          ("127.0.0.1", "::1", "localhost")),
            allow_public=get_env_bool("LLM_ALLOW_PUBLIC", False),
        )


@dataclass
class AuthConfig:
    """JWT 鉴权配置(Roadmap 安全项)

    jwt_secret: HMAC-SHA256 签名密钥
        ⚠️ 生产部署务必设 JWT_SECRET 环境变量!
        缺失时启动会警告(用随机密钥,token 跨重启失效,但本地 OK)
    token_ttl_hours: token 有效期(小时);过期需重新登录
    skip_default_admin: True 时不自动创建 admin/admin(留空让用户自建)
        默认 False (首次启动自动建)
    """
    jwt_secret: Optional[str] = None
    token_ttl_hours: int = 24
    skip_default_admin: bool = False
    local_auth_disabled: bool = True

    @classmethod
    def from_env(cls) -> "AuthConfig":
        return cls(
            jwt_secret=get_env_str("JWT_SECRET", "") or None,
            token_ttl_hours=get_env_int("TOKEN_TTL_HOURS", 24),
            skip_default_admin=get_env_bool("SKIP_DEFAULT_ADMIN", False),
            local_auth_disabled=get_env_bool("LOCAL_AUTH_DISABLED", True),
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
    cors: CORSConfig = field(default_factory=CORSConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    deployment: DeploymentConfig = field(default_factory=DeploymentConfig)

    @classmethod
    def load(cls) -> "AppConfig":
        return cls(
            server=ServerConfig.from_env(),
            deployment=DeploymentConfig.from_env(),
            audio=AudioConfig.from_env(),
            speaker=SpeakerConfig.from_env(),
            rate_limit=RateLimitConfig.from_env(),
            storage=StorageConfig.from_env(),
            llm=LLMConfig.from_env(),
            cors=CORSConfig.from_env(),
            auth=AuthConfig.from_env(),
        )


config = AppConfig.load()
