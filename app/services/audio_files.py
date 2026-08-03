"""Audio ingestion primitives shared by APIs and background processing."""
import asyncio
from pathlib import Path
from typing import BinaryIO

import numpy as np


ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma"}
UPLOAD_READ_SIZE = 1024 * 1024


class UploadTooLargeError(ValueError):
    """Raised after an upload crosses its configured byte limit."""


async def persist_upload(upload, target: Path, *, max_bytes: int) -> int:
    """Stream an UploadFile to disk without blocking the event loop on writes."""
    size = 0
    output: BinaryIO | None = None
    try:
        output = await asyncio.to_thread(target.open, "wb")
        while chunk := await upload.read(UPLOAD_READ_SIZE):
            size += len(chunk)
            if size > max_bytes:
                raise UploadTooLargeError
            await asyncio.to_thread(output.write, chunk)
        await asyncio.to_thread(output.flush)
        return size
    finally:
        if output is not None:
            await asyncio.to_thread(output.close)


def validate_audio_file(path: str | Path, *, max_duration_sec: float | None = None) -> float:
    """Decode a small prefix and return duration, rejecting mislabeled/non-audio files."""
    import librosa

    path = str(path)
    # 用前 1 秒探测是否可解码(快速失败);时长独立用 get_duration 精确计算。
    # 注意:get_duration(path=path) 不可用时的 fallback 不能复用只加载了 1 秒的
    # audio,否则几小时的长音频会被误判为 1 秒。fallback 重新无 duration 限制加载。
    audio, sample_rate = librosa.load(path, sr=None, mono=True, duration=1.0)
    if sample_rate <= 0 or len(audio) == 0:
        raise ValueError("音频中没有可解码的采样")
    get_duration = getattr(librosa, "get_duration", None)
    if get_duration is not None:
        duration = float(get_duration(path=path))
    else:
        # fallback(旧 librosa 无 get_duration):只解码到 max_duration+1 秒上限,
        # 避免几小时的长音频被全量解码进内存 OOM。若实际更长,下面 max 检查会拒绝。
        cap = (max_duration_sec + 1.0) if max_duration_sec else 1.0
        full_audio, _ = librosa.load(path, sr=None, mono=True, duration=cap)
        duration = len(full_audio) / float(sample_rate)
    if duration <= 0:
        raise ValueError("音频时长无效")
    if max_duration_sec and duration > max_duration_sec:
        raise ValueError(f"音频超过 {max_duration_sec:g} 秒限制")
    return duration


def split_audio_into_chunks(
    audio: np.ndarray,
    sample_rate: int,
    chunk_duration: float,
    overlap_duration: float,
) -> list[tuple[np.ndarray, float, float]]:
    if sample_rate <= 0 or chunk_duration <= 0 or overlap_duration < 0:
        raise ValueError("音频分段配置无效")
    chunk_samples = int(chunk_duration * sample_rate)
    step_samples = chunk_samples - int(overlap_duration * sample_rate)
    if chunk_samples <= 0 or step_samples <= 0:
        raise ValueError("分段重叠必须小于分段时长")
    chunks = []
    start = 0
    while start < len(audio):
        end = min(start + chunk_samples, len(audio))
        chunk = audio[start:end]
        if len(chunk) >= sample_rate * 0.5:
            chunks.append((chunk, start / sample_rate, end / sample_rate))
        start += step_samples
        if len(audio) - start < sample_rate * 0.5:
            break
    return chunks
