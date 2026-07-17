"""Meeting list, detail, correction, audio, and deletion API."""
import asyncio
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from app.config import config
from app.services.audio_files import (
    ALLOWED_AUDIO_EXTENSIONS,
    MAX_AUDIO_FILE_SIZE,
    UploadTooLargeError,
    persist_upload,
    validate_audio_file,
)
from app.services.exporter import export_meeting as render_meeting_export


router = APIRouter(prefix="/v1/meetings", tags=["meetings"])


class MeetingUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class SegmentAssignment(BaseModel):
    segment_ids: list[int] = Field(min_length=1, max_length=500)
    meeting_speaker_id: str | None = None


class SpeakerConfirmation(BaseModel):
    person_id: str | None = None


class SegmentTextUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class NoteUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


def _require_mutable_meeting(request: Request, meeting_id: str) -> dict:
    meeting = request.app.state.meeting_repo.get(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    if meeting.get("status") == "processing":
        raise HTTPException(
            status_code=409,
            detail="后台精修中，草稿暂时只读；完成后再修改",
        )
    return meeting


@router.get("")
def list_meetings(
    request: Request,
    q: str | None = Query(None, max_length=100),
    status: str | None = Query(None, pattern="^(draft|processing|ready|failed)$"),
    source: str | None = Query(None, pattern="^(live|upload)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    total, items = request.app.state.meeting_repo.list(
        q=q,
        status=status,
        source=source,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {"total": total, "items": items}


@router.post("/upload", status_code=202)
async def create_upload_meeting(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Query("meeting", pattern="^(quick|meeting)$"),
):
    """Persist audio and immediately return a durable meeting/job pair."""
    filename = Path(file.filename or "recording.wav").name
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持的音频格式")
    media_dir = Path(config.storage.media_dir).resolve()
    media_dir.mkdir(parents=True, exist_ok=True)
    target = media_dir / f"{uuid.uuid4().hex}{extension}"
    meeting_id = None
    try:
        try:
            size = await persist_upload(file, target, max_bytes=MAX_AUDIO_FILE_SIZE)
        except UploadTooLargeError:
            raise HTTPException(status_code=400, detail="文件超过 500MB 限制") from None
        if size == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
        try:
            await asyncio.to_thread(
                validate_audio_file,
                target,
                max_duration_sec=config.audio.upload_max_duration,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"音频无法解码: {exc}") from None
        meeting_id = request.app.state.meeting_repo.create(
            source="upload",
            title=Path(filename).stem or "未命名会议",
            original_filename=filename,
            audio_path=str(target),
            processing_mode=mode,
            status="processing",
        )
        job_id = request.app.state.job_repo.create(meeting_id)
        runner = getattr(request.app.state, "job_runner", None)
        if runner is not None:
            runner.notify()
        return {
            "meeting_id": meeting_id,
            "job_id": job_id,
            "status": "queued",
        }
    except Exception:
        if meeting_id is not None:
            request.app.state.meeting_repo.delete(meeting_id, delete_audio=False)
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@router.get("/search")
def search_meetings(
    request: Request,
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(50, ge=1, le=200),
):
    hits = request.app.state.meeting_repo.search(q, limit=limit)
    return {"query": q, "total": len(hits), "hits": hits}


@router.get("/{meeting_id}")
def get_meeting(meeting_id: str, request: Request):
    detail = request.app.state.meeting_repo.detail(meeting_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    detail["processing_job"] = request.app.state.job_repo.latest_for_meeting(
        meeting_id
    )
    return detail


@router.patch("/{meeting_id}")
def update_meeting(meeting_id: str, body: MeetingUpdate, request: Request):
    if not request.app.state.meeting_repo.update(meeting_id, title=body.title.strip()):
        raise HTTPException(status_code=404, detail="会议不存在")
    return request.app.state.meeting_repo.get(meeting_id)


@router.delete("/{meeting_id}")
def delete_meeting(meeting_id: str, request: Request):
    if request.app.state.job_repo.has_active_for_meeting(meeting_id):
        raise HTTPException(status_code=409, detail="会议仍在处理中，请先取消任务")
    if not request.app.state.meeting_repo.delete(meeting_id):
        raise HTTPException(status_code=404, detail="会议不存在")
    return {"message": "会议及本地音频已删除"}


@router.post("/{meeting_id}/reprocess", status_code=202)
def reprocess_meeting(meeting_id: str, request: Request):
    meeting = request.app.state.meeting_repo.get(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    path = Path(meeting.get("audio_path") or "")
    if not path.is_file():
        raise HTTPException(status_code=409, detail="会议没有可重新处理的本地音频")
    try:
        job_id, created = request.app.state.job_repo.enqueue_refinement(meeting_id)
    except FileNotFoundError:
        raise HTTPException(status_code=409, detail="会议音频不可用") from None
    if not created:
        raise HTTPException(status_code=409, detail="会议已经在处理中")
    runner = getattr(request.app.state, "job_runner", None)
    if runner is not None:
        runner.notify()
    return {"meeting_id": meeting_id, "job_id": job_id, "status": "queued"}


@router.get("/{meeting_id}/audio")
def meeting_audio(meeting_id: str, request: Request):
    meeting = request.app.state.meeting_repo.get(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    path = Path(meeting.get("audio_path") or "")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="会议音频不可用")
    return FileResponse(path, filename=meeting.get("original_filename") or path.name)


@router.get("/{meeting_id}/export")
def export_meeting(
    meeting_id: str,
    request: Request,
    format: str = Query("markdown", pattern="^(markdown|json|srt|vtt)$"),
):
    detail = request.app.state.meeting_repo.detail(meeting_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    title = detail["meeting"]["title"]
    safe_name = "".join(c for c in title if c.isalnum() or c in "-_ ").strip() or meeting_id
    content = render_meeting_export(detail, format)
    media_type, suffix = {
        "json": ("application/json", "json"),
        "srt": ("application/x-subrip", "srt"),
        "vtt": ("text/vtt", "vtt"),
        "markdown": ("text/markdown", "md"),
    }[format]
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="meeting.{suffix}"; '
                f"filename*=UTF-8''{quote(f'{safe_name}.{suffix}')}"
            )
        },
    )


@router.post("/{meeting_id}/notes/{note_type}")
async def generate_meeting_note(
    meeting_id: str,
    note_type: str,
    request: Request,
):
    if note_type not in {"summary", "minutes", "actions"}:
        raise HTTPException(status_code=400, detail="不支持的会议产出类型")
    _require_mutable_meeting(request, meeting_id)
    detail = request.app.state.meeting_repo.detail(meeting_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="会议不存在")
    segments = detail["segments"]
    if not segments:
        raise HTTPException(status_code=409, detail="会议还没有可用文字")
    from app.api.llm import _get_gateway

    gateway = _get_gateway(request)
    operation = {
        "summary": "summarize",
        "actions": "action_items",
        "minutes": "minutes",
    }[note_type]
    content, source = await gateway._generate(operation, segments)
    note = request.app.state.meeting_repo.save_note(
        meeting_id, note_type, content, source
    )
    return note


@router.put("/{meeting_id}/notes/{note_type}")
def update_meeting_note(
    meeting_id: str, note_type: str, body: NoteUpdate, request: Request
):
    if note_type not in {"summary", "minutes", "actions"}:
        raise HTTPException(status_code=400, detail="不支持的会议产出类型")
    _require_mutable_meeting(request, meeting_id)
    return request.app.state.meeting_repo.save_note(
        meeting_id, note_type, body.content.strip(), "manual"
    )


@router.patch("/{meeting_id}/segments/speaker")
def assign_segment_speaker(
    meeting_id: str,
    body: SegmentAssignment,
    request: Request,
):
    _require_mutable_meeting(request, meeting_id)
    try:
        updated = request.app.state.meeting_repo.assign_segments(
            meeting_id, body.segment_ids, body.meeting_speaker_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"updated": updated}


@router.patch("/{meeting_id}/segments/{segment_id}")
def update_segment_text(
    meeting_id: str, segment_id: int, body: SegmentTextUpdate, request: Request
):
    _require_mutable_meeting(request, meeting_id)
    if not request.app.state.meeting_repo.update_segment_text(
        meeting_id, segment_id, body.text.strip()
    ):
        raise HTTPException(status_code=404, detail="文字片段不存在")
    return {"message": "文字已保存"}


@router.patch("/{meeting_id}/speakers/{speaker_id}/person")
def confirm_meeting_speaker(
    meeting_id: str,
    speaker_id: str,
    body: SpeakerConfirmation,
    request: Request,
):
    _require_mutable_meeting(request, meeting_id)
    try:
        updated = request.app.state.meeting_repo.confirm_speaker(
            meeting_id, speaker_id, body.person_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="人物不存在") from exc
    if not updated:
        raise HTTPException(status_code=404, detail="会议说话人不存在")
    return {"message": "说话人身份已确认"}
