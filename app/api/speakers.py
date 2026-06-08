"""说话人管理 API"""
import logging
from fastapi import APIRouter, HTTPException, Query, Path, Request, UploadFile, File
from pydantic import BaseModel, Field
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

logger = logging.getLogger(__name__)

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
    cascade: bool = False                     # True 时：真删前先清空 segments.speaker_id 引用


class CleanupResponse(BaseModel):
    """清理声纹响应"""
    dry_run: bool
    candidates: List[str]                    # 匹配条件的 ID
    deleted: List[str]                       # 实际删除的（dry_run=True 时为空）
    total_before: int
    total_after: int
    cascade_segments_cleared: int = 0        # cascade 清掉的 segment 引用数


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
async def cleanup_speakers(body: CleanupRequest, request: Request):
    """批量清理声纹（修复重复/低质量样本）

    三种过滤模式（优先级从高到低）：
    1. speaker_ids: 显式指定要删的 ID（精确控制）
    2. session_id + max_count: 删某 session 下 count <= max_count 的
    3. 仅 max_count: 删所有 session 中 count <= max_count 的

    默认 dry_run=True（先看候选再删）。

    cascade=True 时：真删前先清空 segments.speaker_id 引用（避免孤立 Spk_xxx 引用）。
    cascade_segments_cleared 字段返回清掉的段数。
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
            cascade_segments_cleared=0,
        )

    # 真删
    transcript_repo = request.app.state.transcript_repo
    cascade_segments_cleared = 0
    deleted = []
    for sid in candidate_ids:
        # cascade：先清 segments 引用（避免孤立引用）
        if body.cascade:
            try:
                cleared = transcript_repo.clear_speaker_id_from_segments(sid)
                if cleared > 0:
                    logger.info(f"[CASCADE] {sid}: 清空 {cleared} 个 segment 引用")
                cascade_segments_cleared += cleared
            except Exception as e:
                # 单个 speaker 失败不阻塞整体清理流程
                logger.warning(f"[CASCADE] {sid} 清空失败: {e}")
        # 再删 ChromaDB
        if engine.delete_speaker(sid):
            deleted.append(sid)

    total_after = total_before - len(deleted)
    return CleanupResponse(
        dry_run=False,
        candidates=candidate_ids,
        deleted=deleted,
        total_before=total_before,
        total_after=total_after,
        cascade_segments_cleared=cascade_segments_cleared,
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

# ========== 主动注册声纹(从示例音频 enroll) ==========

class EnrollRequest(BaseModel):
    """主动注册声纹请求体(配合 multipart 文件上传使用)"""
    speaker_id: str = Field(
        ...,
        pattern=r"^Spk_[a-zA-Z0-9_]{1,50}$",
        description="声纹 ID,格式 Spk_xxx",
        examples=["Spk_zhang_001"],
    )
    name: Optional[str] = Field(
        None,
        max_length=100,
        pattern=r"^[\x20-\x7E一-鿿　-〿＀-￯]+$",
        description="显示名称(可选),1-100 字符,过滤控制字符",
    )


class EnrollResponse(BaseModel):
    """主动注册声纹响应"""
    speaker_id: str
    name: Optional[str] = None
    duration_sec: float
    sample_count: int


@router.post("/v1/speakers/enroll", response_model=EnrollResponse)
async def enroll_speaker(
    speaker_id: str = Query(..., pattern=r"^Spk_[a-zA-Z0-9_]{1,50}$", description="声纹 ID,格式 Spk_xxx"),
    name: Optional[str] = Query(None, max_length=100, description="显示名(可选)"),
    file: UploadFile = File(..., description="示例音频 wav/mp3/m4a/flac/ogg/aac/wma,1-30 秒,16kHz"),
):
    """主动注册声纹(从示例音频)

    这是前端 "Enroll New Voice" 按钮一直缺失的 API。
    之前声纹只能靠实时录音被动累积;加此端点让用户能"上传示例音频 + 命名 → 立即入库"。

    流程:
    1. 接收文件 + speaker_id + name
    2. 用 librosa 加载音频(16kHz)
    3. 用当前引擎 extract_feat 提取声纹
    4. upsert 到 ChromaDB(已存在则覆盖)
    5. 返 EnrollResponse
    """
    import tempfile
    import os
    import librosa
    from fastapi import HTTPException

    ALLOWED = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

    # 临时保存(用完即删)
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        content = await file.read()
        if len(content) == 0:
            os.unlink(tmp.name)
            raise HTTPException(status_code=400, detail="文件为空")
        if len(content) > 500 * 1024 * 1024:
            os.unlink(tmp.name)
            raise HTTPException(status_code=400, detail="文件超过 500MB")
        tmp.write(content)
        tmp_path = tmp.name

    try:
        audio, sr = librosa.load(tmp_path, sr=16000)
        duration = len(audio) / sr
        if duration < 0.5:
            raise HTTPException(status_code=400, detail="音频太短(< 0.5s),无法提取声纹")
        if duration > 30:
            raise HTTPException(status_code=400, detail="音频太长(> 30s),请截取 1-10 秒")

        engine = get_speaker_engine()
        feat = engine.extract_feat(audio)
        emb = feat[0] if isinstance(feat, tuple) else feat

        ok = engine.add_speaker(
            speaker_id=speaker_id,
            embedding=emb,
            name=name or speaker_id,
            session_id=None,
        )
        if not ok:
            raise HTTPException(status_code=500, detail="声纹入库失败")

        return EnrollResponse(
            speaker_id=speaker_id,
            name=name or speaker_id,
            duration_sec=duration,
            sample_count=1,
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
