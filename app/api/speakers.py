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
    SpeakerImpactResponse,
    EngineSwitchRequest,
    EngineSwitchResponse,
    EnginesListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

ENROLL_MAX_FILE_SIZE: int = 50 * 1024 * 1024
ENROLL_UPLOAD_CHUNK_SIZE: int = 1024 * 1024

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
    session_id: Optional[str] = Field(None, max_length=100, description="会话ID,最多 100 字符")
    max_count: int = Field(5, ge=0, le=10000, description="count <= 此值的被删,默认 5,范围 0-10000")
    speaker_ids: Optional[List[str]] = Field(
        None,
        max_length=1000,                      # 一次最多删 1000 个,防 DoS
        description="显式指定要删的 ID(覆盖 max_count 过滤),最多 1000 个",
    )
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


@router.get("/v1/speakers/{speaker_id}/impact", response_model=SpeakerImpactResponse)
async def get_speaker_impact(
    speaker_id: str = SPEAKER_ID_PATH,
    request: Request = None,
):
    """预览删除声纹的影响 (segments 数 / sessions 数)

    整改: 前端删声纹前调用此接口, 弹 confirm 显示"将清空 N 个 segment 引用,
    涉及 M 个 session", 避免盲目删声纹导致历史文稿归属丢失.
    """
    engine = get_speaker_engine()
    speaker = engine.get_speaker(speaker_id)
    if not speaker:
        raise HTTPException(status_code=404, detail=f"说话人 {speaker_id} 不存在")

    transcript_repo = request.app.state.transcript_repo
    segments_count = transcript_repo.count_segments_with_speaker(speaker_id)
    sessions_count = transcript_repo.count_sessions_with_speaker(speaker_id)
    return SpeakerImpactResponse(
        speaker_id=speaker_id,
        segments_count=segments_count,
        sessions_count=sessions_count,
    )


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
async def delete_speaker(
    speaker_id: str = SPEAKER_ID_PATH,
    cascade: bool = True,
    request: Request = None,
):
    """删除说话人

    整改: 默认 cascade=True, 删除声纹前先清空 segments.speaker_id 引用
    (与 POST /v1/speakers/cleanup cascade 行为一致), 避免孤立 Spk_xxx 引用.
    cascade=false 时只删 ChromaDB, segments 引用保留 (允许用户主动保留历史归属).
    """
    engine = get_speaker_engine()
    speaker = engine.get_speaker(speaker_id)
    if not speaker:
        raise HTTPException(status_code=404, detail=f"说话人 {speaker_id} 不存在")

    # cascade: 先清 segments 引用
    cascade_cleared = 0
    affected_sessions = 0
    if cascade and request is not None:
        transcript_repo = getattr(request.app.state, "transcript_repo", None)
        try:
            if transcript_repo is not None:
                cascade_cleared = transcript_repo.clear_speaker_id_from_segments(speaker_id)
                # 统计受影响的 session 数 (segments.speaker_id 清空后, 哪些 session 还有过这个 speaker)
                if cascade_cleared > 0:
                    affected_sessions = transcript_repo.count_sessions_with_speaker(speaker_id)
        except Exception as e:
            logger.warning(f"[DELETE-SPEAKER] cascade 清空失败 {speaker_id}: {e}")

    # 再删 ChromaDB
    success = engine.delete_speaker(speaker_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除失败")

    msg = f"已删除说话人 {speaker_id}"
    if cascade_cleared > 0:
        msg += f", 已清空 {cascade_cleared} 个 segment 引用 (涉及 {affected_sessions} 个 session)"

    return SpeakerDeleteResponse(
        message=msg,
        cascade_segments_cleared=cascade_cleared,
        affected_sessions=affected_sessions,
    )


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


# ========== 说话人合并 / 拆分 API ==========

class MergeSpeakersRequest(BaseModel):
    """合并多个 source 声纹到 target"""
    target_id: str = Field(
        ...,
        pattern=r"^Spk_[a-zA-Z0-9_]{1,50}$",
        description="保留的声纹 ID(目标)",
        examples=["Spk_001"],
    )
    source_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="要并入 target 的 source ID 列表(1-20 个)",
        examples=[["Spk_007", "Spk_013"]],
    )


class MergeSpeakersResponse(BaseModel):
    target_id: str
    merged_source_ids: list[str]
    segments_updated: int
    new_count: int


@router.post("/v1/speakers/merge", response_model=MergeSpeakersResponse)
async def merge_speakers(body: MergeSpeakersRequest, request: Request):
    """合并声纹:把 source 全部并入 target

    场景: CamPlus 同一物理人在音频条件变化时被识别成多个 ID
    (Spk_001 / Spk_007 / Spk_013),用户确认后一键合并。

    流程:
    1. 引擎层: 加权平均 embedding → target,删 source 的 ChromaDB 记录
    2. SQLite: UPDATE segments SET speaker_id=target WHERE speaker_id IN sources
    3. 返回新 metadata

    ⚠️ 不可逆: source 在 ChromaDB 里被物理删除,embedding 不可恢复
    """
    engine = get_speaker_engine()
    repo = request.app.state.transcript_repo

    # 1. 引擎层合并
    result = engine.merge_speakers(body.target_id, body.source_ids)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "合并失败"))

    # 2. SQLite 改 segments
    segments_updated = 0
    for sid in result["merged_source_ids"]:
        try:
            n = repo.reassign_speaker(sid, body.target_id)
            segments_updated += n
        except Exception as e:
            logger.warning(f"[MERGE] reassign {sid} → {body.target_id} 失败: {e}")

    return MergeSpeakersResponse(
        target_id=body.target_id,
        merged_source_ids=result["merged_source_ids"],
        segments_updated=segments_updated,
        new_count=result["new_count"],
    )


class SplitSpeakerRequest(BaseModel):
    """拆分:把指定 segments 的 speaker_id 改成新值(或清空)"""
    speaker_id: str = Field(
        ...,
        pattern=r"^Spk_[a-zA-Z0-9_]{1,50}$",
        description="原声纹 ID(被拆分的)",
    )
    segment_ids: list[int] = Field(
        ...,
        min_length=1,
        max_length=500,
        description="要拆出去的 segment ID 列表(1-500 个)",
    )
    new_speaker_id: Optional[str] = Field(
        None,
        pattern=r"^Spk_[a-zA-Z0-9_]{1,50}$",
        description="新归属的声纹 ID(可选,None = 标记为未识别)",
    )


class SplitSpeakerResponse(BaseModel):
    segments_updated: int
    new_speaker_id: Optional[str]


@router.post("/v1/speakers/split", response_model=SplitSpeakerResponse)
async def split_speaker(body: SplitSpeakerRequest, request: Request):
    """拆分声纹:把选中的 segments 从 speaker_id 改到 new_speaker_id(或 null)

    场景: 用户发现某 segment 归错人了(比如一段环境音被识别成 Spk_001),
    把它标记为未识别(null),等下次再处理。

    限制: split 不创建新 ChromaDB 记录(因为没有原音频 embedding)。
    选 new_speaker_id 必须对应一个已存在的声纹。
    """
    repo = request.app.state.transcript_repo
    engine = get_speaker_engine()

    # Bug-09: 之前 speaker_id 不存在时静默 200 + 0 updated,改为 404 显式报错
    if not engine.get_speaker(body.speaker_id):
        raise HTTPException(
            status_code=404,
            detail=f"speaker_id {body.speaker_id} 不存在",
        )

    # 验证 new_speaker_id 存在(如果给了)
    if body.new_speaker_id is not None:
        if not engine.get_speaker(body.new_speaker_id):
            raise HTTPException(
                status_code=404,
                detail=f"new_speaker_id {body.new_speaker_id} 不存在",
            )

    # 清空这些 segment 的 speaker_id(仅限原 speaker_id 匹配的)
    updated = repo.clear_segments_speaker(body.segment_ids, speaker_id=body.speaker_id)

    # 如果指定了新 speaker,重新指派
    if body.new_speaker_id is not None:
        for sid in body.segment_ids:
            repo.update_segment_speaker(sid, body.new_speaker_id)

    return SplitSpeakerResponse(
        segments_updated=updated,
        new_speaker_id=body.new_speaker_id,
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

    total_written = 0
    exceeded_limit = False
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name
        while True:
            chunk = await file.read(ENROLL_UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            total_written += len(chunk)
            if total_written > ENROLL_MAX_FILE_SIZE:
                exceeded_limit = True
                break
            tmp.write(chunk)
    if exceeded_limit:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise HTTPException(
            status_code=400,
            detail=f"文件超过 {ENROLL_MAX_FILE_SIZE // (1024 * 1024)}MB,请上传 1-30 秒声纹样本",
        )
    if total_written == 0:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="文件为空")

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
