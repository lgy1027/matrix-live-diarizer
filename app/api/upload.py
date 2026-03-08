"""文件上传 API 路由"""
import asyncio
import uuid
import os
import shutil
import logging
from fastapi import APIRouter, UploadFile, File

from app.constants import FILE_UPLOAD_SESSION
from app.schemas import UploadResponse, ModelsResponse

logger = logging.getLogger("Matrix_Core")

router = APIRouter()

asr_engine = None
spk_engine = None
inference_lock = None
current_dir = None


def init_engines(asr, spk, lock, base_dir: str):
    """初始化引擎实例"""
    global asr_engine, spk_engine, inference_lock, current_dir
    asr_engine = asr
    spk_engine = spk
    inference_lock = lock
    current_dir = base_dir


@router.post("/v1/upload", response_model=UploadResponse)
async def upload_audio(file: UploadFile = File(...)):
    """处理离线音频文件上传"""
    temp_dir = os.path.join(current_dir, "uploads")
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, f"{uuid.uuid4()}_{file.filename}")
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        import librosa
        audio, _ = librosa.load(file_path, sr=16000)
        
        async with inference_lock:
            full_text = await asr_engine.run_asr(audio)
            embedding = await asyncio.get_event_loop().run_in_executor(
                None, spk_engine.extract_feat, audio
            )
            spk_id = spk_engine.compare_and_identify(embedding, FILE_UPLOAD_SESSION)
        
        return UploadResponse(
            status="success",
            filename=file.filename,
            speaker=spk_id,
            text=full_text
        )
        
    except Exception as e:
        logger.error(f"[UPLOAD ERROR] {e}")
        return UploadResponse(status="error", message=str(e))
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)


@router.get("/v1/models", response_model=ModelsResponse)
async def get_models():
    """获取当前模型信息"""
    from engine.speaker import get_all_engines
    return get_all_engines()