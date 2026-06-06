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
    cfg = LLMConfig(enabled=True, endpoint="https://api.openai.com/v1")
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
