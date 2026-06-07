import pytest
import asyncio
from app.services.llm_gateway import LLMGateway, EndpointSecurityError
from app.config import LLMConfig


def test_disabled_gateway_returns_none_for_all():
    cfg = LLMConfig(enabled=False)
    gw = LLMGateway(cfg)
    assert asyncio.run(gw.is_available()) is False
    assert asyncio.run(gw.summarize([])) is None


def test_rejects_public_endpoint_on_init():
    # 用 IP literal 避免依赖 DNS（公网 8.8.8.8）
    cfg = LLMConfig(enabled=True, endpoint="https://8.8.8.8/v1")
    with pytest.raises(EndpointSecurityError):
        LLMGateway(cfg)


def test_allows_localhost():
    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1")
    gw = LLMGateway(cfg)
    assert gw is not None


def test_allows_private_ip():
    cfg = LLMConfig(enabled=True, endpoint="http://192.168.1.100:8080/v1")
    gw = LLMGateway(cfg)
    assert gw is not None


def test_allows_localhost_by_name():
    cfg = LLMConfig(enabled=True, endpoint="http://localhost:11434/v1")
    gw = LLMGateway(cfg)
    assert gw is not None


def test_rejects_dns_that_resolves_to_public(monkeypatch):
    import socket
    monkeypatch.setattr(
        socket, "gethostbyname",
        lambda h: "8.8.8.8" if h == "evil.example.com" else "127.0.0.1"
    )
    cfg = LLMConfig(enabled=True, endpoint="http://evil.example.com:80/v1")
    with pytest.raises(EndpointSecurityError):
        LLMGateway(cfg)


# ========== allow_public 开关 ==========

def test_allow_public_lets_public_endpoint_through(monkeypatch):
    """allow_public=True 时,公网域名/IP 都放行(用户显式开公网)"""
    import socket
    monkeypatch.setattr(
        socket, "gethostbyname",
        lambda h: "8.8.8.8" if h == "api.openai.com" else "127.0.0.1"
    )
    cfg = LLMConfig(
        enabled=True,
        endpoint="https://api.openai.com/v1",
        allow_public=True,
        api_key="sk-test",
    )
    gw = LLMGateway(cfg)
    assert gw is not None
    assert gw.config.api_key == "sk-test"


def test_allow_public_false_default_rejects(monkeypatch):
    """allow_public 默认 False → 仍拒公网(默认隐私优先)"""
    import socket
    monkeypatch.setattr(
        socket, "gethostbyname",
        lambda h: "8.8.8.8" if h == "api.deepseek.com" else "127.0.0.1"
    )
    cfg = LLMConfig(enabled=True, endpoint="https://api.deepseek.com/v1")
    assert cfg.allow_public is False
    with pytest.raises(EndpointSecurityError):
        LLMGateway(cfg)


# ========== LLMConfig.api_key 透传 ==========

def test_api_key_default_none():
    cfg = LLMConfig()
    assert cfg.api_key is None


def test_api_key_preserved():
    cfg = LLMConfig(api_key="sk-abc123")
    assert cfg.api_key == "sk-abc123"


def test_api_key_in_call_llm_authorization_header(monkeypatch):
    """_call_llm 发送 Authorization: Bearer <key> 当 api_key 非空"""
    import app.services.llm_gateway as gw_mod

    captured = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResp()

    async def fake_probe(self):
        return True
    monkeypatch.setattr(LLMGateway, "_probe", fake_probe)
    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", FakeClient)

    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1",
                    api_key="sk-abc", mock=False)
    gw = LLMGateway(cfg)
    asyncio.run(gw._call_llm("hi"))
    assert captured["headers"]["Authorization"] == "Bearer sk-abc"


def test_no_api_key_omits_authorization_header(monkeypatch):
    """无 api_key 时不发送 Authorization header(本机 Ollama/vLLM)"""
    import app.services.llm_gateway as gw_mod

    captured = {}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers=None):
            captured["headers"] = headers or {}
            return FakeResp()

    async def fake_probe(self):
        return True
    monkeypatch.setattr(LLMGateway, "_probe", fake_probe)
    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", FakeClient)

    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1",
                    api_key=None, mock=False)
    gw = LLMGateway(cfg)
    asyncio.run(gw._call_llm("hi"))
    assert "Authorization" not in captured["headers"]


# ========== from_env ==========

def test_from_env_allow_public(monkeypatch):
    """LLM_ALLOW_PUBLIC=true → LLMConfig.allow_public=True"""
    monkeypatch.setenv("LLM_ALLOW_PUBLIC", "true")
    monkeypatch.setenv("LLM_API_KEY", "sk-from-env")
    cfg = LLMConfig.from_env()
    assert cfg.allow_public is True
    assert cfg.api_key == "sk-from-env"
    monkeypatch.delenv("LLM_ALLOW_PUBLIC", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)


def test_from_env_empty_api_key_becomes_none(monkeypatch):
    """LLM_API_KEY 空字符串 → None(避免 header 变成 'Bearer ')"""
    monkeypatch.setenv("LLM_API_KEY", "")
    cfg = LLMConfig.from_env()
    assert cfg.api_key is None
    monkeypatch.delenv("LLM_API_KEY", raising=False)
