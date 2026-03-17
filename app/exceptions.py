"""自定义异常类

提供更精确的异常类型，便于错误处理和日志记录。
"""


class AudioProcessingError(Exception):
    """音频处理错误
    
    用于表示音频处理过程中发生的错误，包含上下文信息。
    """
    
    def __init__(
        self,
        message: str,
        audio_duration: float = None,
        sample_rate: int = None,
        chunk_index: int = None,
    ):
        super().__init__(message)
        self.message = message
        self.audio_duration = audio_duration
        self.sample_rate = sample_rate
        self.chunk_index = chunk_index
    
    def __str__(self):
        parts = [self.message]
        if self.audio_duration is not None:
            parts.append(f"duration={self.audio_duration:.1f}s")
        if self.sample_rate is not None:
            parts.append(f"sample_rate={self.sample_rate}")
        if self.chunk_index is not None:
            parts.append(f"chunk={self.chunk_index}")
        return " | ".join(parts)


class EngineNotInitializedError(Exception):
    """引擎未初始化错误
    
    用于表示 ASR 或声纹引擎未正确初始化。
    """
    
    def __init__(self, engine_name: str, detail: str = None):
        self.engine_name = engine_name
        self.detail = detail
        message = f"{engine_name} 引擎未初始化"
        if detail:
            message += f": {detail}"
        super().__init__(message)


class InvalidAudioFormatError(Exception):
    """无效音频格式错误
    
    用于表示上传的音频文件格式无效或损坏。
    """
    
    def __init__(self, filename: str = None, reason: str = None):
        self.filename = filename
        self.reason = reason
        message = "无效的音频格式"
        if filename:
            message = f"无效的音频格式: {filename}"
        if reason:
            message += f" ({reason})"
        super().__init__(message)


class SpeakerNotFoundError(Exception):
    """说话人不存在错误
    
    用于表示请求的说话人在数据库中不存在。
    """
    
    def __init__(self, speaker_id: str):
        self.speaker_id = speaker_id
        super().__init__(f"说话人 {speaker_id} 不存在")


class SessionNotFoundError(Exception):
    """会话不存在错误
    
    用于表示 WebSocket 会话不存在或已过期。
    """
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"会话 {session_id} 不存在或已过期")


class RateLimitExceededError(Exception):
    """请求频率超限错误
    
    用于表示客户端请求过于频繁。
    """
    
    def __init__(self, retry_after: int = None):
        self.retry_after = retry_after
        message = "请求过于频繁，请稍后重试"
        if retry_after:
            message += f" ({retry_after}秒后重试)"
        super().__init__(message)
