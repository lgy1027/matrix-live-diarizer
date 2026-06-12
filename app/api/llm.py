"""LLM API 端点 — LLM 关闭/失败时静默降级到 extractive,响应带 source 字段"""
import asyncio
import importlib
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.services.llm_gateway import LLMGateway
from app.services.llm_prompts import PROMPTS

logger = logging.getLogger("Matrix_LLM_API")

router = APIRouter()


def _llm_cfg():
    """动态获取当前 config.llm(每次访问,便于测试 reload/monkeypatch)"""
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
        "fallback": "extractive-textrank",  # 🆕 永远可用的兜底
    }


@router.get("/v1/llm/prompts")
def get_prompts():
    return PROMPTS


@router.put("/v1/llm/prompts")
def update_prompts(payload: dict, request: Request):
    client = request.client
    if not client or client.host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="仅本机可修改 prompts")
    # Bug-06: 之前静默忽略未知字段,改为 422 显式报错
    unknown_keys = set(payload.keys()) - set(PROMPTS.keys())
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail=f"未知 prompt 字段: {sorted(unknown_keys)};合法字段: {sorted(PROMPTS.keys())}",
        )
    for k, v in payload.items():
        if k in PROMPTS:
            PROMPTS[k] = v
    return PROMPTS


@router.post("/v1/llm/summarize")
async def summarize(body: SummarizeRequest, request: Request):
    repo = request.app.state.transcript_repo
    if repo.get_session(body.session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    segments = repo.list_segments(body.session_id)
    gw = _get_gateway()
    text, source = await gw._generate("summarize", segments, max_words=body.max_words)
    return {"text": text, "source": source}


@router.post("/v1/llm/action-items")
async def action_items(body: SummarizeRequest, request: Request):
    repo = request.app.state.transcript_repo
    if repo.get_session(body.session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    segments = repo.list_segments(body.session_id)
    gw = _get_gateway()
    text, source = await gw._generate("action_items", segments)
    if source == "llm":
        # LLM 返回是 "line1\nline2" 字符串,拆成 list
        items = [line.strip("-* ").strip() for line in text.split("\n") if line.strip()]
    else:
        # 降级路径直接返 list
        items = gw._extractive_fallback_action_items(segments)
    return {"items": items, "source": source}


@router.post("/v1/llm/minutes")
async def minutes(body: SummarizeRequest, request: Request):
    repo = request.app.state.transcript_repo
    if repo.get_session(body.session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    segments = repo.list_segments(body.session_id)
    gw = _get_gateway()
    text, source = await gw._generate("minutes", segments)
    return {"text": text, "source": source}
