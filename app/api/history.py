"""历史会话 API"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel


router = APIRouter()


class HistoryListResponse(BaseModel):
    total: int
    items: list[dict]


@router.get("/v1/history", response_model=HistoryListResponse)
def list_history(
    request: Request,
    source: Optional[str] = Query(None, pattern="^(websocket|upload)$"),
    q: Optional[str] = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    repo = request.app.state.transcript_repo
    offset = (page - 1) * page_size
    items = repo.list_sessions(
        source=source, q=q, limit=page_size, offset=offset
    )
    # 简单 total 计数（v0.2 MVP：不分页时全表 count；数据量大时再优化）
    all_items = repo.list_sessions(source=source, q=q, limit=10_000, offset=0)
    return HistoryListResponse(total=len(all_items), items=items)


@router.delete("/v1/history/{session_id}")
def delete_history(session_id: str, request: Request):
    repo = request.app.state.transcript_repo
    if repo.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    repo.delete_session(session_id)
    return {"message": f"已删除 {session_id}"}
