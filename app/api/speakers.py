"""说话人管理 API"""
from fastapi import APIRouter, HTTPException, Query, Path
from typing import Optional

from engine.speaker.speaker_factory import get_speaker_engine
from app.schemas.response import (
    SpeakerListResponse,
    SpeakerResponse,
    SpeakerUpdateRequest,
    SpeakerDeleteResponse,
)

router = APIRouter()

# speaker_id 路径参数验证
SPEAKER_ID_PATH = Path(
    ...,
    min_length=4,
    max_length=50,
    pattern=r"^Spk_[a-zA-Z0-9_]+$",
    description="说话人ID，格式: Spk_xxx",
    examples=["Spk_001", "Spk_session_a_user1"],
)


@router.get("/v1/speakers", response_model=SpeakerListResponse)
async def list_speakers(
    session_id: Optional[str] = Query(None, max_length=100, description="会话ID，不传则返回所有"),
):
    """获取说话人列表"""
    engine = get_speaker_engine()
    speakers = engine.list_speakers(session_id)
    return SpeakerListResponse(speakers=speakers, total=len(speakers))


@router.get("/v1/speakers/{speaker_id}", response_model=SpeakerResponse)
async def get_speaker(speaker_id: str = SPEAKER_ID_PATH):
    """获取单个说话人信息"""
    engine = get_speaker_engine()
    speaker = engine.get_speaker(speaker_id)
    if not speaker:
        raise HTTPException(status_code=404, detail=f"说话人 {speaker_id} 不存在")
    return SpeakerResponse(speaker=speaker)


@router.patch("/v1/speakers/{speaker_id}", response_model=SpeakerResponse)
async def rename_speaker(
    speaker_id: str = SPEAKER_ID_PATH,
    body: SpeakerUpdateRequest = None,
):
    """重命名说话人"""
    engine = get_speaker_engine()
    speaker = engine.get_speaker(speaker_id)
    if not speaker:
        raise HTTPException(status_code=404, detail=f"说话人 {speaker_id} 不存在")

    success = engine.rename_speaker(speaker_id, body.name.strip())
    if not success:
        raise HTTPException(status_code=500, detail="重命名失败")

    updated = engine.get_speaker(speaker_id)
    return SpeakerResponse(speaker=updated)


@router.delete("/v1/speakers/{speaker_id}", response_model=SpeakerDeleteResponse)
async def delete_speaker(speaker_id: str = SPEAKER_ID_PATH):
    """删除说话人"""
    engine = get_speaker_engine()
    speaker = engine.get_speaker(speaker_id)
    if not speaker:
        raise HTTPException(status_code=404, detail=f"说话人 {speaker_id} 不存在")

    success = engine.delete_speaker(speaker_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")

    return SpeakerDeleteResponse(message=f"已删除说话人 {speaker_id}")