"""音频转写核心逻辑 — 供 upload API 和 seed 脚本复用"""
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from app.repositories.transcripts import TranscriptRepository

logger = logging.getLogger("Matrix_Transcribe")


@dataclass
class TranscribedSegment:
    """单个转写段落"""
    start_time: float
    end_time: float
    text: str
    speaker_id: Optional[str] = None
    confidence: float = 1.0


@dataclass
class TranscriptionResult:
    """完整转写结果"""
    session_id: str
    duration_sec: float
    segments: List[TranscribedSegment] = field(default_factory=list)


async def transcribe_file(
    audio_path: str,
    asr_engine,
    spk_engine,
    session_id: str,
    sample_rate: int = 16000,
    repo: Optional["TranscriptRepository"] = None,
) -> TranscriptionResult:
    """把一个音频文件转写完,返回结构化结果。

    不写数据库 — 由调用方决定。seed 脚本可以直接返回,upload API 写库。
    `repo` 形参为预留接口,seed 脚本(Task 7)会用到,upload API 当前在调用方写库。

    注意:`extract_feat` 只返回 embedding 向量,不返回 speaker_id。
    说话人识别由调用方根据 embedding 在 ChromaDB 里搜最近邻(transcribe_file 不强制做)。

    改为 async 因 asr_engine.run_asr 是 async 函数 — 之前 sync 漏 await 会
    把 coroutine 透传到 SQLite 引发 "type 'coroutine' is not supported" 错误。
    """
    import librosa
    audio, _ = librosa.load(audio_path, sr=sample_rate)
    # 空音频或全静音(< 0.1s 阈值)直接返回
    if len(audio) < int(sample_rate * 0.1):
        return TranscriptionResult(session_id=session_id, duration_sec=len(audio) / sample_rate)

    duration = len(audio) / sample_rate
    # 简化: 一次性跑整段(短音频无需分段,后续可扩展)
    # 必须 await — run_asr 是 async,否则 coroutine 透传到下游 SQLite binding
    raw = asr_engine.run_asr(audio)
    asr_result = (await raw) if hasattr(raw, "__await__") else raw
    text = asr_result.get("text", "") if isinstance(asr_result, dict) else (asr_result or "")

    # 声纹: extract_feat 返回 (embedding, duration_sec) tuple。
    # 真实引擎(campplus / eres2net / wespeaker)都遵守此签名。
    try:
        feat_result = spk_engine.extract_feat(audio)
        if isinstance(feat_result, tuple) and len(feat_result) >= 1:
            _embedding = feat_result[0]
        else:
            _embedding = feat_result
    except AttributeError:
        # 旧 mock 引擎可能没 extract_feat,降级返回空
        _embedding = None
    except Exception as e:
        logger.warning(f"[transcribe] extract_feat 失败: {e}")
        _embedding = None

    # speaker_id 留空: 说话人识别是另一回事(基于 embedding 在 ChromaDB 里搜最近邻),
    # 由调用方(上传 API / seed 脚本)用 spk_engine.identify() 自行识别。
    seg = TranscribedSegment(
        start_time=0.0,
        end_time=duration,
        text=text,
        speaker_id=None,
    )
    return TranscriptionResult(
        session_id=session_id,
        duration_sec=duration,
        segments=[seg],
    )
