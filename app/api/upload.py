"""文件上传 API - 支持长音频分段处理"""
import asyncio
import uuid
import os
import logging
import time
from typing import List, Tuple, Set
import numpy as np

from fastapi import APIRouter, UploadFile, File, HTTPException, Query

from app.config import config
from app.constants import FILE_UPLOAD_SESSION
from app.schemas import UploadResponse, ModelsResponse, SegmentResult
from engine.speaker.speaker_factory import get_speaker_engine

logger = logging.getLogger("Matrix_Core")

router = APIRouter()

asr_engine = None
inference_lock = None
current_dir = None
transcript_repo = None

# 文件上传安全配置
ALLOWED_EXTENSIONS: Set[str] = {'.wav', '.mp3', '.m4a', '.flac', '.ogg', '.aac', '.wma'}
MAX_FILE_SIZE: int = 500 * 1024 * 1024  # 500MB


def init_engines(asr, spk, lock, base_dir: str, repo=None):
    """初始化引擎实例

    Note: spk 参数保留用于兼容，但实际使用 get_speaker_engine() 动态获取
    """
    global asr_engine, inference_lock, current_dir, transcript_repo
    asr_engine = asr
    # spk_engine 通过 get_speaker_engine() 动态获取，支持运行时切换
    inference_lock = lock
    current_dir = base_dir
    transcript_repo = repo


def split_audio_into_chunks(
    audio: np.ndarray,
    sample_rate: int,
    chunk_duration: float,
    overlap_duration: float
) -> List[Tuple[np.ndarray, float, float]]:
    """音频分段，返回 [(chunk, start_time, end_time), ...]"""
    chunk_samples = int(chunk_duration * sample_rate)
    overlap_samples = int(overlap_duration * sample_rate)
    step_samples = chunk_samples - overlap_samples
    
    chunks = []
    start = 0
    
    while start < len(audio):
        end = min(start + chunk_samples, len(audio))
        chunk = audio[start:end]
        
        start_time = start / sample_rate
        end_time = end / sample_rate
        
        # 最小分段 0.5 秒
        if len(chunk) >= sample_rate * 0.5:
            chunks.append((chunk, start_time, end_time))
        
        start += step_samples
        
        if len(audio) - start < sample_rate * 0.5:
            break
    
    return chunks


def merge_text_with_overlap(prev_text: str, new_text: str, overlap_chars: int = 50) -> str:
    """合并两段文本，自动去除重叠部分"""
    if not prev_text:
        return new_text
    if not new_text:
        return prev_text
    
    prev_clean = prev_text.strip()
    new_clean = new_text.strip()
    
    max_overlap = min(len(prev_clean), len(new_clean), overlap_chars * 3)
    
    for overlap_len in range(max_overlap, 0, -1):
        if prev_clean[-overlap_len:] == new_clean[:overlap_len:]:
            return prev_clean + new_clean[overlap_len:]
    
    return prev_clean + " " + new_text


async def process_audio_chunk_with_diarization(
    chunk: np.ndarray,
    start_time: float,
    end_time: float
) -> SegmentResult:
    """分段处理：ASR + 说话人识别"""
    audio_duration = end_time - start_time
    
    text = await asr_engine.run_asr(chunk, use_preprocessing=True)
    emb_result = await asyncio.get_event_loop().run_in_executor(
        None, get_speaker_engine().extract_feat, chunk
    )
    
    # 处理 tuple 返回值
    if isinstance(emb_result, tuple):
        embedding, _ = emb_result
    else:
        embedding = emb_result
    
    spk_id = get_speaker_engine().compare_and_identify(embedding, FILE_UPLOAD_SESSION, audio_duration)
    
    return SegmentResult(
        speaker=spk_id,
        text=text or "",
        start_time=start_time,
        end_time=end_time
    )


async def process_audio_chunk_asr_only(
    chunk: np.ndarray,
    start_time: float,
    end_time: float
) -> SegmentResult:
    """分段处理：仅 ASR"""
    text = await asr_engine.run_asr(chunk, use_preprocessing=True)
    
    return SegmentResult(
        speaker="SPEAKER",
        text=text or "",
        start_time=start_time,
        end_time=end_time
    )


@router.post("/v1/upload", response_model=UploadResponse)
async def upload_audio(
    file: UploadFile = File(...),
    enable_diarization: bool = Query(True, description="启用说话人识别")
):
    """上传音频文件，支持长音频分段处理
    
    enable_diarization=true: 识别说话人（会议场景）
    enable_diarization=false: 仅转写（单人演讲）
    """
    start_time_total = time.time()
    
    # 1. 验证文件类型
    if file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型: {ext}。支持的格式: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )
    
    # 2. 验证文件大小（先读取内容）
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"文件大小 {len(content) / 1024 / 1024:.1f}MB 超过限制 {MAX_FILE_SIZE / 1024 / 1024:.0f}MB"
        )
    
    # 重置文件指针供后续使用
    await file.seek(0)
    
    temp_dir = os.path.join(current_dir, "uploads")
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{file.filename}")
    
    try:
        import shutil
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        import librosa
        audio, _ = librosa.load(file_path, sr=config.audio.sample_rate)
        duration = len(audio) / config.audio.sample_rate
        
        mode = "说话人识别" if enable_diarization else "快速转写"
        logger.info(f"[UPLOAD] {file.filename}, {duration:.1f}s, {mode}")
        
        if duration > config.audio.upload_max_duration:
            raise HTTPException(
                status_code=400,
                detail=f"音频 {duration:.1f}s 超过限制 {config.audio.upload_max_duration}s"
            )
        
        # 短音频直接处理
        if duration <= config.audio.upload_chunk_duration:
            async with inference_lock:
                text = await asr_engine.run_asr(audio, use_preprocessing=True)
                
                if enable_diarization:
                    emb_result = await asyncio.get_event_loop().run_in_executor(
                        None, get_speaker_engine().extract_feat, audio
                    )
                    # 处理 tuple 返回值
                    if isinstance(emb_result, tuple):
                        embedding, _ = emb_result
                    else:
                        embedding = emb_result
                    spk_id = get_speaker_engine().compare_and_identify(embedding, FILE_UPLOAD_SESSION, duration)
                else:
                    spk_id = "SPEAKER"
            
            logger.info(f"[UPLOAD] 完成, {time.time() - start_time_total:.2f}s")

            # 自动存档
            if transcript_repo and config.storage.history_enabled:
                sid = transcript_repo.create_session(
                    source="upload",
                    title=file.filename,
                    original_filename=file.filename,
                    duration_sec=duration,
                )
                # 短音频：单 segment
                transcript_repo.insert_segment(
                    sid,
                    segment_index=0,
                    text=text or "",
                    start_time=0.0,
                    end_time=duration,
                    speaker_id=spk_id if enable_diarization else None,
                )
                session_id = sid
            else:
                session_id = None

            return UploadResponse(
                status="success",
                filename=file.filename,
                speaker=spk_id,
                text=text or "",
                duration=duration,
                session_id=session_id,
            )
        
        # 长音频分段处理
        chunks = split_audio_into_chunks(
            audio,
            config.audio.sample_rate,
            config.audio.upload_chunk_duration,
            config.audio.upload_overlap_duration
        )
        
        segments: List[SegmentResult] = []
        all_speakers = set()
        
        process_func = (
            process_audio_chunk_with_diarization 
            if enable_diarization 
            else process_audio_chunk_asr_only
        )
        
        for i, (chunk, start_time, end_time) in enumerate(chunks):
            async with inference_lock:
                result = await process_func(chunk, start_time, end_time)
            
            segments.append(result)
            if result.speaker:
                all_speakers.add(result.speaker)
        
        # 合并文本
        if enable_diarization:
            merged_text = ""
            prev_speaker = None
            prev_text = ""
            
            for seg in segments:
                if not seg.text:
                    continue
                
                if seg.speaker == prev_speaker:
                    merged_segment = merge_text_with_overlap(prev_text, seg.text)
                    new_part = merged_segment[len(prev_text):]
                    if new_part:
                        merged_text += new_part
                    prev_text = merged_segment
                else:
                    if merged_text:
                        merged_text += f"\n[{seg.speaker}]: {seg.text}"
                    else:
                        merged_text = f"[{seg.speaker}]: {seg.text}"
                    prev_speaker = seg.speaker
                    prev_text = seg.text
        else:
            merged_text = ""
            prev_text = ""
            for seg in segments:
                if seg.text:
                    merged_text = merge_text_with_overlap(prev_text, seg.text)
                    prev_text = merged_text
        
        elapsed = time.time() - start_time_total
        speaker_info = f", {len(all_speakers)} 说话人" if enable_diarization else ""
        logger.info(f"[UPLOAD] 完成{speaker_info}, {elapsed:.2f}s")

        # 自动存档（长音频批量）
        if transcript_repo and config.storage.history_enabled:
            sid = transcript_repo.create_session(
                source="upload",
                title=file.filename,
                original_filename=file.filename,
                duration_sec=duration,
            )
            for i, seg in enumerate(segments):
                if not seg.text:
                    continue
                transcript_repo.insert_segment(
                    sid,
                    segment_index=i,
                    text=seg.text,
                    start_time=seg.start_time,
                    end_time=seg.end_time,
                    speaker_id=seg.speaker if enable_diarization else None,
                )
            session_id = sid
        else:
            session_id = None

        return UploadResponse(
            status="success",
            filename=file.filename,
            text=merged_text.strip(),
            duration=duration,
            segments=segments,
            speakers=sorted(list(all_speakers)) if enable_diarization else None,
            session_id=session_id,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[UPLOAD ERROR] {e}")
        return UploadResponse(status="error", message=str(e))
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.get("/v1/models", response_model=ModelsResponse)
async def get_models():
    """获取模型信息"""
    from engine.speaker import get_all_engines
    return get_all_engines()