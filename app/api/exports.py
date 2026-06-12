"""导出 API：SRT/VTT/Markdown/JSON"""
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import PlainTextResponse

from app.services.exporter import export, mime_type, FormatError

router = APIRouter()


@router.get("/v1/exports/{session_id}")
def export_session(
    session_id: str,
    request: Request,
    # Bug-07: format 给默认值 "json",不再 422
    format: str = Query("json", pattern="^(srt|vtt|markdown|md|json)$"),
):
    # 兼容前端常见写法 md → markdown
    fmt = "markdown" if format == "md" else format
    repo = request.app.state.transcript_repo
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    segments = repo.list_segments(session_id)
    speaker_aliases = {}  # v0.2 MVP：从 ChromaDB 读（后续接 alias 表）

    try:
        if fmt == "json":
            content = export(
                "json",
                session=session,
                segments=segments,
                speakers=[],  # v0.2 MVP
            )
        elif fmt == "markdown":
            content = export(
                "markdown",
                segments=segments,
                speaker_aliases=speaker_aliases,
                title=session.get("title") or "未命名",
                duration_sec=session.get("duration_sec") or 0,
                speaker_count=len({s.get("speaker_id") for s in segments if s.get("speaker_id")}),
            )
        else:
            content = export(fmt, segments=segments, speaker_aliases=speaker_aliases)
    except FormatError as e:
        raise HTTPException(status_code=400, detail=str(e))

    title = session.get("title") or session_id[:8]
    ext = {"srt": "srt", "vtt": "vtt", "markdown": "md", "json": "json"}[fmt]
    # 安全净化 filename: 防 HTTP 头注入(CRLF)、引号转义、防路径遍历
    safe_title = str(title).replace("\r", "").replace("\n", "").replace('"', "'")
    safe_title = "".join(c for c in safe_title if c.isprintable())[:80] or session_id[:8]
    # 中文 / 非 ASCII 字符: HTTP 头默认 latin-1 编码,会抛 UnicodeEncodeError
    # RFC 5987 方式: filename*=UTF-8''xxx(浏览器优先用)
    try:
        filename_ascii = f"{safe_title}.{ext}".encode("latin-1").decode("latin-1")
        cd = f'attachment; filename="{filename_ascii}"'
    except UnicodeEncodeError:
        # 含非 latin-1 字符(中文等),用 RFC 5987 双语 header
        from urllib.parse import quote
        filename_utf8 = f"{safe_title}.{ext}"
        cd = f"attachment; filename=\"download.{ext}\"; filename*=UTF-8''{quote(filename_utf8)}"
    return PlainTextResponse(
        content=content,
        media_type=mime_type(fmt),
        headers={"Content-Disposition": cd},
    )
