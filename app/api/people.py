"""People and registered voice samples API."""
import asyncio
import hashlib
import logging
import math
import uuid
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from app.config import config
from app.services.audio_files import (
    ALLOWED_AUDIO_EXTENSIONS,
    UploadTooLargeError,
    persist_upload,
    validate_audio_file,
)
from app.services.voice_sample_quality import assess_voice_sample
from app.services.voice_matcher import (
    STRONG_SAMPLE_MIN_QUALITY,
    STRONG_SAMPLE_MIN_SPEECH_SEC,
)
from app.repositories.people import DuplicateVoiceSampleError
from engine.speaker.speaker_factory import embedding_model_id


logger = logging.getLogger("Matrix_People")

router = APIRouter(prefix="/v1/people", tags=["people"])


class PersonBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    notes: str | None = Field(None, max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("人物姓名不能为空")
        return value

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, value: str | None) -> str | None:
        # strip 后纯空白归一为 None,防 "   " 原样入库
        if value is None:
            return None
        value = value.strip()
        return value or None


@router.get("")
def list_people(request: Request):
    items = request.app.state.people_repo.list()
    return {"total": len(items), "items": items}


@router.post("", status_code=201)
def create_person(body: PersonBody, request: Request):
    person_id = request.app.state.people_repo.create(body.name, body.notes)
    return request.app.state.people_repo.get(person_id)


@router.get("/{person_id}")
def get_person(person_id: str, request: Request):
    person = request.app.state.people_repo.get(person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="人物不存在")
    person["samples"] = request.app.state.people_repo.list_samples(person_id)
    return person


@router.patch("/{person_id}")
def update_person(person_id: str, body: PersonBody, request: Request):
    if not request.app.state.people_repo.update(
        person_id, name=body.name, notes=body.notes
    ):
        raise HTTPException(status_code=404, detail="人物不存在")
    return request.app.state.people_repo.get(person_id)


@router.delete("/{person_id}")
def delete_person(person_id: str, request: Request):
    if not request.app.state.people_repo.delete(person_id):
        raise HTTPException(status_code=404, detail="人物不存在")
    return {"message": "人物和本地声音样本已删除"}


@router.get("/{person_id}/samples/{sample_id}/audio")
def get_voice_sample_audio(person_id: str, sample_id: str, request: Request):
    sample = request.app.state.people_repo.get_sample(person_id, sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="声音样本不存在")
    path = Path(sample["audio_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="声音样本文件不存在")
    return FileResponse(
        path,
        filename=f"voice-sample{path.suffix.lower()}",
        content_disposition_type="inline",
    )


@router.delete("/{person_id}/samples/{sample_id}")
def delete_voice_sample(person_id: str, sample_id: str, request: Request):
    if not request.app.state.people_repo.delete_sample(person_id, sample_id):
        raise HTTPException(status_code=404, detail="声音样本不存在")
    return {"message": "声音样本已删除"}


@router.post("/{person_id}/samples", status_code=201)
async def add_voice_sample(
    person_id: str,
    request: Request,
    file: UploadFile = File(...),
):
    if request.app.state.people_repo.get(person_id) is None:
        raise HTTPException(status_code=404, detail="人物不存在")
    extension = Path(file.filename or "sample.wav").suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的声音样本格式")
    voice_dir = Path(config.storage.media_dir).resolve() / "voices" / person_id
    voice_dir.mkdir(parents=True, exist_ok=True)
    target = voice_dir / f"{uuid.uuid4().hex}{extension}"
    try:
        voice_max_bytes = min(config.audio.upload_max_file_size, 50 * 1024 * 1024)
        try:
            size = await persist_upload(
                file,
                target,
                max_bytes=voice_max_bytes,
            )
        except UploadTooLargeError:
            limit_mb = voice_max_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=400, detail=f"声音样本超过 {limit_mb}MB 限制"
            ) from None
        if size == 0:
            raise HTTPException(status_code=400, detail="声音样本为空")
        import librosa

        # 先用前 1 秒探测 + 元数据算时长,超限在此拒绝,避免超长低码率
        # 样本被全量解码进内存(50MB MP3 可解码成数小时 PCM → OOM)。
        try:
            await asyncio.to_thread(
                validate_audio_file,
                target,
                max_duration_sec=config.audio.upload_max_duration,
            )
        except ValueError as exc:
            msg = str(exc)
            safe_target = str(target).replace("\r", r"\r").replace("\n", r"\n")[:500]
            safe_error = msg.replace("\r", r"\r").replace("\n", r"\n")[:500]
            logger.warning("[voice] 样本校验失败 %s: %s", safe_target, safe_error)
            if "超过" in msg:
                raise HTTPException(
                    status_code=400,
                    detail=f"声音样本超过 {config.audio.upload_max_duration}s 上限",
                ) from None
            raise HTTPException(status_code=400, detail="声音样本无法解码,请检查文件格式") from None
        try:
            audio, _ = await asyncio.to_thread(
                librosa.load, str(target), sr=config.audio.sample_rate, mono=True
            )
        except Exception as exc:
            safe_target = str(target).replace("\r", r"\r").replace("\n", r"\n")[:500]
            safe_error = str(exc).replace("\r", r"\r").replace("\n", r"\n")[:500]
            logger.warning("[voice] 样本解码失败 %s: %s", safe_target, safe_error)
            raise HTTPException(status_code=400, detail="声音样本无法解码,请检查文件格式") from None
        audio = np.asarray(audio, dtype=np.float32)
        duration = len(audio) / config.audio.sample_rate
        # validate_audio_file 已在上游探测时长上限;此处保留双保险。
        if duration > config.audio.upload_max_duration:
            raise HTTPException(
                status_code=400,
                detail=f"声音样本超过 {config.audio.upload_max_duration}s 上限",
            )
        if duration < 2:
            raise HTTPException(status_code=400, detail="声音样本至少需要 2 秒")
        assessment = assess_voice_sample(audio, config.audio.sample_rate)
        if assessment.effective_speech_sec < 2:
            if assessment.effective_speech_sec < 0.5:
                raise HTTPException(
                    status_code=422,
                    detail="未检测到人声，请确认麦克风已连接并对着说话后重录",
                )
            raise HTTPException(status_code=422, detail="有效语音不足 2 秒，请减少静音后重试")
        if assessment.quality_score < 0.35:
            detail = "样本疑似为噪声，请使用清晰人声重新录制" if assessment.noise_like else (
                "声音样本质量过低，请避免音量过小或削波"
            )
            raise HTTPException(status_code=422, detail=detail)
        audio_sha256 = hashlib.sha256(audio.astype("<f4", copy=False).tobytes()).hexdigest()
        if request.app.state.people_repo.has_sample_hash(person_id, audio_sha256):
            raise HTTPException(status_code=409, detail="该人物已注册相同的声音样本")
        runtime = getattr(request.app.state, "runtime", None)
        speaker_engine = (
            runtime.speaker if runtime is not None else request.app.state.spk_engine
        )
        # 引擎降级启动(模型下载失败/损坏)时 speaker 可能为 None。
        # WS 路径有 check_engines 守卫,上传声样路径无,需显式拦截避免
        # AttributeError('NoneType'...) 裸抛成 500。
        if speaker_engine is None:
            raise HTTPException(
                status_code=503, detail="声纹引擎不可用,无法注册声样"
            )
        if runtime is not None:
            async with runtime.inference.offline():
                embedding_result = await asyncio.to_thread(
                    speaker_engine.extract_feat,
                    audio,
                )
        else:
            embedding_result = await asyncio.to_thread(
                speaker_engine.extract_feat,
                audio,
            )
        embedding = (
            embedding_result[0]
            if isinstance(embedding_result, tuple)
            else embedding_result
        )
        if embedding is None:
            raise HTTPException(status_code=422, detail="无法从该样本提取有效声纹")
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if not vector.size or not np.isfinite(vector).all():
            raise HTTPException(status_code=422, detail="无法从该样本提取有效声纹")
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-8 or not math.isfinite(norm):
            raise HTTPException(status_code=422, detail="无法从该样本提取有效声纹")
        vector = vector / norm
        model_name = embedding_model_id(speaker_engine, int(vector.size))
        quality_score = assessment.quality_score
        try:
            sample_id = request.app.state.people_repo.add_sample(
                person_id,
                audio_path=str(target),
                duration_sec=duration,
                embedding=vector.tobytes(),
                embedding_dim=int(vector.size),
                model_name=model_name,
                quality_score=quality_score,
                effective_speech_sec=assessment.effective_speech_sec,
                audio_sha256=audio_sha256,
            )
        except DuplicateVoiceSampleError:
            raise HTTPException(
                status_code=409, detail="该人物已注册相同的声音样本"
            ) from None
        return {
            "id": sample_id,
            "duration_sec": duration,
            "quality_score": quality_score,
            "effective_speech_sec": assessment.effective_speech_sec,
            "model_id": model_name,
            "embedding_status": "ready",
            # 是否达到自动匹配门槛,与 voice_matcher 的 strong_sample 判定一致
            "auto_match_eligible": (
                quality_score >= STRONG_SAMPLE_MIN_QUALITY
                and assessment.effective_speech_sec >= STRONG_SAMPLE_MIN_SPEECH_SEC
            ),
        }
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
