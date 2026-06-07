"""导出 API：SRT/VTT/Markdown/JSON"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse

from app.services.exporter import export, mime_type, FormatError

router = APIRouter()


@router.get("/v1/exports/{session_id}")
def export_session(
    session_id: str,
    request: Request,
    format: str = Query(..., pattern="^(srt|vtt|markdown|json)$"),
):
    repo = request.app.state.transcript_repo
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    segments = repo.list_segments(session_id)
    speaker_aliases = {}  # v0.2 MVP：从 ChromaDB 读（后续接 alias 表）

    try:
        if format == "json":
            content = export(
                "json",
                session=session,
                segments=segments,
                speakers=[],  # v0.2 MVP
            )
        elif format == "markdown":
            content = export(
                "markdown",
                segments=segments,
                speaker_aliases=speaker_aliases,
                title=session.get("title") or "未命名",
                duration_sec=session.get("duration_sec") or 0,
                speaker_count=len({s.get("speaker_id") for s in segments if s.get("speaker_id")}),
            )
        else:
            content = export(format, segments=segments, speaker_aliases=speaker_aliases)
    except FormatError as e:
        raise HTTPException(status_code=400, detail=str(e))

    title = session.get("title") or session_id[:8]
    ext = {"srt": "srt", "vtt": "vtt", "markdown": "md", "json": "json"}[format]
    filename = f"{title}.{ext}"
    return PlainTextResponse(
        content=content,
        media_type=mime_type(format),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
