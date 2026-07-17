"""LLM API 端点 — LLM 关闭/失败时静默降级到 extractive,响应带 source 字段"""
import importlib
import logging
import os
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.config import LLMConfig
from app.services.llm_gateway import LLMGateway, EndpointSecurityError
from app.services.llm_prompts import PROMPTS

logger = logging.getLogger("Matrix_LLM_API")

router = APIRouter()


LLM_SETTING_PREFIX = "llm."


def _llm_config_fingerprint(cfg: LLMConfig) -> tuple:
    """Identify the non-secret settings a connection test applies to."""
    return (
        cfg.enabled,
        cfg.endpoint.rstrip("/"),
        cfg.model,
        cfg.mock,
        cfg.allow_public,
    )


def _recent_probe(request: Request, cfg: LLMConfig) -> dict | None:
    result = getattr(request.app.state, "llm_probe_result", None)
    if not result or result.get("fingerprint") != _llm_config_fingerprint(cfg):
        return None
    return result


def _store_probe(
    request: Request,
    cfg: LLMConfig,
    *,
    available: bool,
    error: str | None = None,
) -> dict:
    result = {
        "fingerprint": _llm_config_fingerprint(cfg),
        "available": available,
        "last_tested_at": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }
    request.app.state.llm_probe_result = result
    return result


def _env_llm_cfg():
    """动态获取当前 config.llm(每次访问,便于测试 reload/monkeypatch)"""
    return importlib.import_module("app.config").config.llm


def _settings_repo(request: Request):
    return getattr(request.app.state, "settings_repo", None)


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in ("true", "1", "yes", "on")


def _to_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _effective_llm_cfg(repo=None) -> tuple[LLMConfig, str, Optional[str]]:
    """返回页面覆盖后的 LLMConfig.

    .env 提供默认值; settings 表里的 llm.* 键覆盖默认值。
    """
    base = _env_llm_cfg()
    if repo is None:
        return base, "env", None

    provider = repo.get(f"{LLM_SETTING_PREFIX}provider")
    has_override = any(k.startswith(LLM_SETTING_PREFIX) for k in repo.all_keys())
    if not has_override:
        return base, "env", provider

    cfg = replace(
        base,
        enabled=_to_bool(repo.get(f"{LLM_SETTING_PREFIX}enabled"), base.enabled),
        endpoint=repo.get(f"{LLM_SETTING_PREFIX}endpoint") or base.endpoint,
        model=repo.get(f"{LLM_SETTING_PREFIX}model") or base.model,
        # Secrets are environment-owned and are never loaded from SQLite.
        api_key=base.api_key,
        timeout_sec=_to_int(repo.get(f"{LLM_SETTING_PREFIX}timeout_sec"), base.timeout_sec),
        max_input_tokens=_to_int(repo.get(f"{LLM_SETTING_PREFIX}max_input_tokens"), base.max_input_tokens),
        mock=_to_bool(repo.get(f"{LLM_SETTING_PREFIX}mock"), base.mock),
        allow_public=_to_bool(repo.get(f"{LLM_SETTING_PREFIX}allow_public"), base.allow_public),
    )
    return cfg, "settings", provider


def _get_gateway(request: Request) -> LLMGateway:
    cfg, _source, _provider = _effective_llm_cfg(_settings_repo(request))
    try:
        return LLMGateway(cfg)
    except EndpointSecurityError as e:
        logger.warning(f"[LLM] endpoint 安全校验失败,降级本地摘要: {e}")
        return LLMGateway(replace(cfg, enabled=False))


def _is_authenticated_status_request(request: Request) -> bool:
    """LLM status 是白名单端点;这里手动判断是否可返回完整配置."""
    if os.environ.get("TEST_AUTH_BYPASS") == "1":
        return True
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return False
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return False
    auth_service = getattr(request.app.state, "auth_service", None)
    if auth_service is None:
        return False
    decoded = auth_service.decode_token(token)
    if not decoded:
        return False
    try:
        user = auth_service.get_user(int(decoded["sub"]))
    except (KeyError, TypeError, ValueError):
        return False
    if not user or not user.get("is_active") or user.get("must_change_password"):
        return False
    try:
        token_pwd_iat = float(decoded.get("pwd_iat", 0))
        current_pwd_iat = float(user.get("password_changed_at") or 0)
    except (TypeError, ValueError):
        return False
    return current_pwd_iat <= token_pwd_iat


class LLMSettingsRequest(BaseModel):
    provider: str = Field("ollama", max_length=40)
    enabled: bool = False
    endpoint: str = Field(..., min_length=1, max_length=500)
    model: str = Field(..., min_length=1, max_length=200)
    api_key: Optional[str] = Field(None, max_length=500)
    allow_public: bool = False
    timeout_sec: int = Field(60, ge=1, le=600)
    max_input_tokens: int = Field(8000, ge=500, le=200000)
    mock: bool = False

    @field_validator("endpoint")
    @classmethod
    def _endpoint_must_be_openai_compatible_base(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("endpoint 必须以 http:// 或 https:// 开头")
        return value

    @field_validator("provider", "model")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        return value.strip()


@router.get("/v1/llm/status")
async def llm_status(request: Request):
    cfg, source, provider = _effective_llm_cfg(_settings_repo(request))
    if not _is_authenticated_status_request(request):
        return {
            "enabled": cfg.enabled,
            "available": False,
            "fallback": "extractive-textrank",
            "auth_required": True,
        }

    # Status is intentionally passive. It must never trigger DNS resolution or
    # an external LLM request just because a page was opened.
    probe = _recent_probe(request, cfg)
    return {
        "enabled": cfg.enabled,
        "available": probe["available"] if probe else None,
        "last_tested_at": probe["last_tested_at"] if probe else None,
        "endpoint": cfg.endpoint if cfg.enabled else None,
        "model": cfg.model if cfg.enabled else None,
        "mock": cfg.mock,
        "provider": provider or "custom",
        "allow_public": cfg.allow_public,
        "timeout_sec": cfg.timeout_sec,
        "max_input_tokens": cfg.max_input_tokens,
        "has_api_key": bool(cfg.api_key),
        "config_source": source,
        "error": probe["error"] if probe else None,
        "fallback": "extractive-textrank",  # 🆕 永远可用的兜底
    }


@router.post("/v1/llm/test")
async def test_llm_connection(request: Request):
    """Explicitly test the saved LLM configuration once.

    This is the only settings/status endpoint allowed to call the configured
    ``/chat/completions`` service.
    """
    cfg, source, provider = _effective_llm_cfg(_settings_repo(request))
    error = None
    if not cfg.enabled:
        available = False
        error = "LLM 未启用"
    elif cfg.mock:
        available = True
    else:
        try:
            available = await LLMGateway(cfg).is_available()
            if not available:
                error = "LLM 连接测试失败"
        except EndpointSecurityError as exc:
            available = False
            error = str(exc)

    probe = _store_probe(
        request,
        cfg,
        available=available,
        error=error,
    )
    return {
        "enabled": cfg.enabled,
        "available": probe["available"],
        "last_tested_at": probe["last_tested_at"],
        "endpoint": cfg.endpoint if cfg.enabled else None,
        "model": cfg.model if cfg.enabled else None,
        "mock": cfg.mock,
        "provider": provider or "custom",
        "allow_public": cfg.allow_public,
        "timeout_sec": cfg.timeout_sec,
        "max_input_tokens": cfg.max_input_tokens,
        "has_api_key": bool(cfg.api_key),
        "config_source": source,
        "error": probe["error"],
        "fallback": "extractive-textrank",
    }


@router.get("/v1/llm/settings")
def get_llm_settings(request: Request):
    cfg, source, provider = _effective_llm_cfg(_settings_repo(request))
    return {
        "provider": provider or "custom",
        "enabled": cfg.enabled,
        "endpoint": cfg.endpoint,
        "model": cfg.model,
        "allow_public": cfg.allow_public,
        "timeout_sec": cfg.timeout_sec,
        "max_input_tokens": cfg.max_input_tokens,
        "mock": cfg.mock,
        "has_api_key": bool(cfg.api_key),
        "config_source": source,
    }


@router.put("/v1/llm/settings")
def update_llm_settings(body: LLMSettingsRequest, request: Request):
    repo = _settings_repo(request)
    if repo is None:
        raise HTTPException(status_code=500, detail="settings repository unavailable")

    if body.api_key and body.api_key.strip():
        raise HTTPException(
            status_code=400,
            detail="API Key 不写入数据库，请通过 LLM_API_KEY 环境变量配置",
        )

    repo.set(f"{LLM_SETTING_PREFIX}provider", body.provider)
    repo.set(f"{LLM_SETTING_PREFIX}enabled", str(body.enabled).lower())
    repo.set(f"{LLM_SETTING_PREFIX}endpoint", body.endpoint)
    repo.set(f"{LLM_SETTING_PREFIX}model", body.model)
    repo.set(f"{LLM_SETTING_PREFIX}allow_public", str(body.allow_public).lower())
    repo.set(f"{LLM_SETTING_PREFIX}timeout_sec", str(body.timeout_sec))
    repo.set(f"{LLM_SETTING_PREFIX}max_input_tokens", str(body.max_input_tokens))
    repo.set(f"{LLM_SETTING_PREFIX}mock", str(body.mock).lower())
    # Remove plaintext keys left by pre-release builds.
    repo.delete(f"{LLM_SETTING_PREFIX}api_key")
    # A result for the previous endpoint/model must not survive a save. Saving
    # is passive; a new result is created only by POST /v1/llm/test.
    request.app.state.llm_probe_result = None

    return get_llm_settings(request)


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
