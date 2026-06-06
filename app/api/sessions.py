"""单个会话详情 API"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from app.services.statistics import compute_statistics


router = APIRouter()


class SessionDetailResponse(BaseModel):
    session: dict
    segments: list[dict]
    statistics: dict


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None


@router.get("/v1/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: str, request: Request):
    repo = request.app.state.transcript_repo
    session = repo.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    segments = repo.list_segments(session_id)
    stats = compute_statistics(
        segments,
        total_duration_sec=session.get("duration_sec") or 0,
    )
    return SessionDetailResponse(
        session=session, segments=segments, statistics=stats
    )


@router.patch("/v1/sessions/{session_id}")
def update_session(session_id: str, body: UpdateSessionRequest, request: Request):
    repo = request.app.state.transcript_repo
    if repo.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if fields:
        repo.update_session(session_id, **fields)
    return {"message": "ok", "session": repo.get_session(session_id)}
