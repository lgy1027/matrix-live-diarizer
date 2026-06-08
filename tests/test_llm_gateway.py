import pytest
import asyncio
from app.services.llm_gateway import LLMGateway, EndpointSecurityError
from app.config import LLMConfig


def test_disabled_gateway_falls_back_to_extractive():
    """LLM 关闭时 summarize 不抛错,降级到 extractive 兜底(返回非 None 字符串)"""
    cfg = LLMConfig(enabled=False)
    gw = LLMGateway(cfg)
    assert asyncio.run(gw.is_available()) is False
    result = asyncio.run(gw.summarize([]))
    # 不再返回 None — 走 extractive 兜底,空段落返回 "(无内容)"
    assert result is not None
    assert isinstance(result, str)


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


# ========== extractive fallback ==========

def test_generate_falls_back_to_extractive_when_disabled():
    """LLM 关掉时 _generate 走 extractive 兜底而不是返回 None"""
    from app.services.llm_gateway import LLMGateway
    from app.config import LLMConfig
    cfg = LLMConfig(enabled=False)
    gw = LLMGateway(cfg)
    result = asyncio.run(gw.summarize([{"text": "今天讨论产品方向。张三需要做调研。"}]))
    assert result is not None
    assert len(result) > 0


def test_generate_falls_back_on_llm_error(monkeypatch):
    """LLM 抛错时降级到 extractive(不抛给调用方)"""
    from app.services.llm_gateway import LLMGateway, LLMUnavailableError
    from app.config import LLMConfig
    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1")
    gw = LLMGateway(cfg)

    async def fake_call(self, prompt):
        raise LLMUnavailableError("LLM 不可用")
    monkeypatch.setattr(LLMGateway, "_call_llm", fake_call)

    result = asyncio.run(gw.summarize([{"text": "今天讨论产品方向。张三需要做调研。"}]))
    assert result is not None
    assert len(result) > 0


def test_generate_falls_back_on_timeout(monkeypatch):
    """LLM 超时时降级"""
    from app.services.llm_gateway import LLMGateway, LLMTimeoutError
    from app.config import LLMConfig
    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1")
    gw = LLMGateway(cfg)

    async def fake_call(self, prompt):
        raise LLMTimeoutError("LLM 超时")
    monkeypatch.setattr(LLMGateway, "_call_llm", fake_call)

    result = asyncio.run(gw.summarize([{"text": "今天讨论产品方向。张三需要做调研。"}]))
    assert result is not None


def test_action_items_falls_back_returns_list():
    """行动项降级时返回非空 list"""
    from app.services.llm_gateway import LLMGateway
    from app.config import LLMConfig
    cfg = LLMConfig(enabled=False)
    gw = LLMGateway(cfg)
    result = asyncio.run(gw.extract_action_items([{"text": "张三需要下周完成报告。"}]))
    # 失败的话是 None 或 [],但降级后应返回 list
    # 即使不匹配关键词也是 []
    assert result is not None
    assert isinstance(result, list)


def test_minutes_falls_back():
    """纪要降级返回 string 含议题/决议/行动项"""
    from app.services.llm_gateway import LLMGateway
    from app.config import LLMConfig
    cfg = LLMConfig(enabled=False)
    gw = LLMGateway(cfg)
    result = asyncio.run(gw.generate_minutes([{"text": "今天讨论产品。张三需要做调研。"}]))
    assert result is not None
    assert "议题" in result


# ========== 回归测试: socket-level DNS pinning ==========

def test_socket_patch_install_uninstall():
    """_install_socket_patch / _uninstall_socket_patch 不污染全局"""
    from app.services.llm_gateway import LLMGateway
    import socket as _socket
    
    orig = _socket.getaddrinfo
    LLMGateway._install_socket_patch("https://api.edgefn.net/v1", "198.18.0.51")
    assert LLMGateway._socket_patch_active is True
    assert LLMGateway._pinned_target_host == "api.edgefn.net"
    assert LLMGateway._pinned_target_ip == "198.18.0.51"
    # getaddrinfo 应被替换
    assert _socket.getaddrinfo is not orig
    
    LLMGateway._uninstall_socket_patch()
    assert LLMGateway._socket_patch_active is False
    assert LLMGateway._pinned_target_host is None
    assert LLMGateway._pinned_target_ip is None
    assert _socket.getaddrinfo is orig


def test_socket_patch_pins_target_host_to_pinned_ip():
    """打补丁后,getaddrinfo('api.edgefn.net', ...) 应返回 IP '198.18.0.51' 的结果"""
    from app.services.llm_gateway import LLMGateway
    import socket as _socket
    
    LLMGateway._install_socket_patch("https://api.edgefn.net/v1", "198.18.0.51")
    try:
        # 调用 getaddrinfo 应该走 patched 版本,看到 api.edgefn.net 时返回 198.18.0.51
        results = _socket.getaddrinfo("api.edgefn.net", 443, type=_socket.SOCK_STREAM)
        assert len(results) > 0
        # 所有结果 sockaddr[0] 应是 '198.18.0.51'
        for family, _type, _proto, _canon, sockaddr in results:
            assert sockaddr[0] == "198.18.0.51", f"Expected 198.18.0.51, got {sockaddr}"
    finally:
        LLMGateway._uninstall_socket_patch()


def test_socket_patch_does_not_affect_other_hosts():
    """只 patch 目标域名,其他域名走原 getaddrinfo"""
    from app.services.llm_gateway import LLMGateway
    import socket as _socket
    
    LLMGateway._install_socket_patch("https://api.edgefn.net/v1", "198.18.0.51")
    try:
        # 其他域名应走原 DNS,本机 'localhost' 解析成 127.0.0.1
        results = _socket.getaddrinfo("localhost", 80, type=_socket.SOCK_STREAM)
        ips = {r[4][0] for r in results}
        # localhost 应解析到 127.0.0.1,不被 patch 影响
        assert "127.0.0.1" in ips or "::1" in ips
    finally:
        LLMGateway._uninstall_socket_patch()


def test_socket_patch_skips_ip_literal():
    """URL host 已经是 IP literal 时,不应装 patch(没意义)"""
    from app.services.llm_gateway import LLMGateway
    import socket as _socket
    
    orig = _socket.getaddrinfo
    LLMGateway._install_socket_patch("http://127.0.0.1:11434/v1", "127.0.0.1")
    # 已是 IP literal,patch 不应安装
    assert LLMGateway._socket_patch_active is False
    assert _socket.getaddrinfo is orig
