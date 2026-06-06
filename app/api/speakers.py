"""说话人管理 API"""
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel
from typing import Optional, List

from engine.speaker.speaker_factory import get_speaker_engine, get_engine_manager
from app.schemas.response import (
    SpeakerListResponse,
    SpeakerResponse,
    SpeakerUpdateRequest,
    SpeakerDeleteResponse,
    EngineSwitchRequest,
    EngineSwitchResponse,
    EnginesListResponse,
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


class CleanupRequest(BaseModel):
    """清理声纹请求"""
    session_id: Optional[str] = None         # None=全部 session
    max_count: int = 5                       # 只删 count <= 此值的（默认 5，删低质量/单样本）
    speaker_ids: Optional[List[str]] = None   # 显式指定要删的 ID（覆盖 max_count 过滤）
    dry_run: bool = True                      # True=只返回将删的，不真删


class CleanupResponse(BaseModel):
    """清理声纹响应"""
    dry_run: bool
    candidates: List[str]                    # 匹配条件的 ID
    deleted: List[str]                       # 实际删除的（dry_run=True 时为空）
    total_before: int
    total_after: int


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


@router.post("/v1/speakers/cleanup", response_model=CleanupResponse)
async def cleanup_speakers(body: CleanupRequest):
    """批量清理声纹（修复重复/低质量样本）

    三种过滤模式（优先级从高到低）：
    1. speaker_ids: 显式指定要删的 ID（精确控制）
    2. session_id + max_count: 删某 session 下 count <= max_count 的
    3. 仅 max_count: 删所有 session 中 count <= max_count 的

    默认 dry_run=True（先看候选再删）。
    """
    engine = get_speaker_engine()
    all_speakers = engine.list_speakers(session_id=body.session_id)
    total_before = len(all_speakers)

    # 选候选
    if body.speaker_ids:
        # 显式指定：只保留列表里的
        id_set = set(body.speaker_ids)
        candidates = [s for s in all_speakers if s["id"] in id_set]
    else:
        # 按 count 过滤
        candidates = [s for s in all_speakers if s.get("sample_count", 1) <= body.max_count]

    candidate_ids = [s["id"] for s in candidates]

    if body.dry_run:
        return CleanupResponse(
            dry_run=True,
            candidates=candidate_ids,
            deleted=[],
            total_before=total_before,
            total_after=total_before,
        )

    # 真删
    deleted = []
    for sid in candidate_ids:
        if engine.delete_speaker(sid):
            deleted.append(sid)

    total_after = total_before - len(deleted)
    return CleanupResponse(
        dry_run=False,
        candidates=candidate_ids,
        deleted=deleted,
        total_before=total_before,
        total_after=total_after,
    )


# ========== 引擎管理 API ==========

@router.get("/v1/engines", response_model=EnginesListResponse)
async def list_engines():
    """获取所有引擎信息"""
    manager = get_engine_manager()
    info = manager.get_all_engines_info()
    return EnginesListResponse(current=info["current"], engines=info["engines"])


@router.put("/v1/engine", response_model=EngineSwitchResponse)
async def switch_engine(body: EngineSwitchRequest):
    """切换声纹引擎"""
    manager = get_engine_manager()
    result = manager.switch_engine(body.engine_type)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "切换失败"))
    
    return EngineSwitchResponse(**result)