"""LLM API 端点（仅在 LLM 启用时可用）"""
import asyncio
import importlib

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.llm_gateway import (
    LLMGateway,
    LLMUnavailableError,
    LLMTimeoutError,
    LLMModelMissingError,
)
from app.services.llm_prompts import PROMPTS


router = APIRouter()


def _llm_cfg():
    """动态获取当前 config.llm（每次访问，便于测试 reload/monkeypatch）"""
    return importlib.import_module("app.config").config.llm


def _get_gateway() -> LLMGateway:
    return LLMGateway(_llm_cfg())


class SummarizeRequest(BaseModel):
    session_id: str
    max_words: int = 200


@router.get("/v1/llm/status")
def llm_status():
    cfg = _llm_cfg()
    gw = _get_gateway()
    if not gw.enabled:
        available = False
    elif cfg.mock:
        available = True
    else:
        available = asyncio.run(gw.is_available())
    return {
        "enabled": gw.enabled,
        "available": available,
        "endpoint": cfg.endpoint if gw.enabled else None,
        "model": cfg.model if gw.enabled else None,
        "mock": cfg.mock,
    }


@router.get("/v1/llm/prompts")
def get_prompts():
    return PROMPTS


@router.put("/v1/llm/prompts")
def update_prompts(payload: dict, request: Request):
    # 限本机访问(防横向提权)
    client = request.client
    if not client or client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="仅本机可修改 prompts")
    for k, v in payload.items():
        if k in PROMPTS:
            PROMPTS[k] = v
    return PROMPTS


def _handle_llm_error(e: Exception):
    if isinstance(e, LLMTimeoutError):
        raise HTTPException(status_code=504, detail=f"LLM 响应超时: {e}")
    if isinstance(e, LLMModelMissingError):
        raise HTTPException(status_code=503, detail=str(e))
    if isinstance(e, LLMUnavailableError):
        raise HTTPException(status_code=503, detail=str(e))
    raise HTTPException(status_code=500, detail=str(e))


@router.post("/v1/llm/summarize")
async def summarize(body: SummarizeRequest, request: Request):
    if not _llm_cfg().enabled:
        raise HTTPException(status_code=503, detail="LLM 未启用")
    repo = request.app.state.transcript_repo
    if repo.get_session(body.session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    segments = repo.list_segments(body.session_id)
    gw = _get_gateway()
    try:
        text = await gw.summarize(segments, max_words=body.max_words)
    except (LLMUnavailableError, LLMTimeoutError, LLMModelMissingError) as e:
        _handle_llm_error(e)
    if text is None:
        raise HTTPException(status_code=503, detail="LLM 不可用")
    return {"text": text}


@router.post("/v1/llm/action-items")
async def action_items(body: SummarizeRequest, request: Request):
    if not _llm_cfg().enabled:
        raise HTTPException(status_code=503, detail="LLM 未启用")
    repo = request.app.state.transcript_repo
    if repo.get_session(body.session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    segments = repo.list_segments(body.session_id)
    gw = _get_gateway()
    try:
        items = await gw.extract_action_items(segments)
    except (LLMUnavailableError, LLMTimeoutError, LLMModelMissingError) as e:
        _handle_llm_error(e)
    if items is None:
        raise HTTPException(status_code=503, detail="LLM 不可用")
    return {"items": items}


@router.post("/v1/llm/minutes")
async def minutes(body: SummarizeRequest, request: Request):
    if not _llm_cfg().enabled:
        raise HTTPException(status_code=503, detail="LLM 未启用")
    repo = request.app.state.transcript_repo
    if repo.get_session(body.session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    segments = repo.list_segments(body.session_id)
    gw = _get_gateway()
    try:
        text = await gw.generate_minutes(segments)
    except (LLMUnavailableError, LLMTimeoutError, LLMModelMissingError) as e:
        _handle_llm_error(e)
    if text is None:
        raise HTTPException(status_code=503, detail="LLM 不可用")
    return {"text": text}
