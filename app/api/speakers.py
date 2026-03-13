"""说话人管理 API"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from engine.speaker.speaker_factory import get_speaker_engine
from app.schemas.response import SpeakerListResponse, SpeakerResponse, SpeakerUpdateRequest

router = APIRouter()


@router.get("/v1/speakers", response_model=SpeakerListResponse)
async def list_speakers(session_id: Optional[str] = Query(None, description="会话ID，不传则返回所有")):
    """获取说话人列表"""
    engine = get_speaker_engine()
    speakers = engine.list_speakers(session_id)
    return SpeakerListResponse(speakers=speakers, total=len(speakers))


@router.get("/v1/speakers/{speaker_id}", response_model=SpeakerResponse)
async def get_speaker(speaker_id: str):
    """获取单个说话人信息"""
    engine = get_speaker_engine()
    speaker = engine.get_speaker(speaker_id)
    if not speaker:
        raise HTTPException(status_code=404, detail=f"说话人 {speaker_id} 不存在")
    return SpeakerResponse(speaker=speaker)


@router.patch("/v1/speakers/{speaker_id}", response_model=SpeakerResponse)
async def rename_speaker(speaker_id: str, body: SpeakerUpdateRequest):
    """重命名说话人"""
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="名称不能为空")
    
    engine = get_speaker_engine()
    speaker = engine.get_speaker(speaker_id)
    if not speaker:
        raise HTTPException(status_code=404, detail=f"说话人 {speaker_id} 不存在")
    
    success = engine.rename_speaker(speaker_id, body.name.strip())
    if not success:
        raise HTTPException(status_code=500, detail="重命名失败")
    
    updated = engine.get_speaker(speaker_id)
    return SpeakerResponse(speaker=updated)


@router.delete("/v1/speakers/{speaker_id}")
async def delete_speaker(speaker_id: str):
    """删除说话人"""
    engine = get_speaker_engine()
    speaker = engine.get_speaker(speaker_id)
    if not speaker:
        raise HTTPException(status_code=404, detail=f"说话人 {speaker_id} 不存在")
    
    success = engine.delete_speaker(speaker_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")
    
    return {"message": f"已删除说话人 {speaker_id}"}
