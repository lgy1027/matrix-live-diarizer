"""历史会话 API"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel


router = APIRouter()


class HistoryListResponse(BaseModel):
    total: int
    items: list[dict]


def _normalize_source(v: Optional[str]) -> Optional[str]:
    """空字符串视作未传"""
    if v is None or v == "":
        return None
    if v not in ("websocket", "upload"):
        raise HTTPException(status_code=400, detail=f"source 必须是 websocket 或 upload，收到: {v!r}")
    return v


def _normalize_q(v: Optional[str]) -> Optional[str]:
    """空字符串视作未传"""
    if v is None or v == "":
        return None
    return v[:100]


@router.get("/v1/history", response_model=HistoryListResponse)
def list_history(
    request: Request,
    source: Optional[str] = Query(None, description="websocket | upload，空字符串=不过滤"),
    q: Optional[str] = Query(None, max_length=100, description="关键词，空字符串=不搜索"),
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(20, ge=1, le=200, description="每页条数，最大 200"),
):
    repo = request.app.state.transcript_repo
    norm_source = _normalize_source(source)
    norm_q = _normalize_q(q)
    offset = (page - 1) * page_size
    # 用 enrich 版本：返回 duration/segments_count/speakers
    total, items = repo.get_enriched_sessions(
        source=norm_source, q=norm_q, limit=page_size, offset=offset
    )
    return HistoryListResponse(total=total, items=items)


@router.delete("/v1/history/{session_id}")
def delete_history(session_id: str, request: Request):
    repo = request.app.state.transcript_repo
    if repo.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    repo.delete_session(session_id)
    return {"message": f"已删除 {session_id}"}
