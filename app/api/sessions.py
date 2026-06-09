"""单个会话详情 API"""
import re
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional

from app.services.statistics import compute_statistics


router = APIRouter()


class SessionDetailResponse(BaseModel):
    session: dict
    segments: list[dict]
    statistics: dict


# title 输入约束:防超长字符串污染 DB / 响应
_TITLE_MAX_LEN = 200
# is_archived 必须是 0 或 1


def _strip_control_chars(v: str) -> str:
    """剥除控制字符(保留中英文/标点/数字/emoji)

    防止:
    - 日志注入(\\r\\n)
    - 终端颜色控制字符
    - 不可打印字符污染响应
    """
    if not v:
        return v
    return "".join(c for c in v if c.isprintable() or c == " ")


class UpdateSessionRequest(BaseModel):
    title: Optional[str] = Field(
        None,
        max_length=_TITLE_MAX_LEN,
        description=f"会话标题,最大 {_TITLE_MAX_LEN} 字符,自动过滤控制字符",
    )
    is_archived: Optional[int] = Field(
        None,
        ge=0,
        le=1,
        description="0/1,True/False 自动转 int",
    )


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
    raw = body.model_dump()
    # title 自动剥除控制字符
    fields = {}
    for k, v in raw.items():
        if v is None:
            continue
        if k == "title" and isinstance(v, str):
            fields[k] = _strip_control_chars(v)
        else:
            fields[k] = v
    if fields:
        repo.update_session(session_id, **fields)
    return {"message": "ok", "session": repo.get_session(session_id)}
