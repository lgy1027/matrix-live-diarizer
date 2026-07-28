import pytest
import asyncio
import socket
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


def test_call_llm_rejects_redirect_response(monkeypatch):
    """#14: follow_redirects=False,3xx 重定向响应直接抛 EndpointSecurityError,
    不跟随(防被劫持的 LLM endpoint 借 302 SSRF 外发会议文本)。"""
    import app.services.llm_gateway as gw_mod

    captured = {}

    class FakeResp:
        status_code = 302
        def raise_for_status(self): pass
        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *a, **kw):
            # 验证 follow_redirects=False 被传入
            captured["follow_redirects"] = kw.get("follow_redirects")
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers=None):
            return FakeResp()

    async def fake_probe(self):
        return True
    monkeypatch.setattr(LLMGateway, "_probe", fake_probe)
    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", FakeClient)

    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1",
                    api_key=None, mock=False)
    gw = LLMGateway(cfg)
    with pytest.raises(EndpointSecurityError, match="重定向"):
        asyncio.run(gw._call_llm("hi"))
    assert captured["follow_redirects"] is False


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


def test_llm_transcript_uses_only_trusted_person_names():
    gateway = LLMGateway(LLMConfig(enabled=False))
    transcript = gateway._segments_to_text([
        {
            "text": "建议内容", "speaker_label": "SPEAKER_00",
            "person_name": "张三", "identity_status": "suggested",
        },
        {
            "text": "自动内容", "speaker_label": "SPEAKER_01",
            "person_name": "李四", "identity_status": "auto_matched",
        },
        {
            "text": "确认内容", "speaker_label": "SPEAKER_02",
            "person_name": "王五", "identity_status": "confirmed",
        },
    ])

    assert transcript.splitlines() == [
        "[SPEAKER_00] 建议内容",
        "[李四] 自动内容",
        "[王五] 确认内容",
    ]


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

def test_rejects_dns_rebind_between_init_and_request(monkeypatch):
    """H1: init 时刻 DNS 返回私网 IP(通过校验),请求时刻 rebind 到公网 IP。
    pinning 应锁死到 init 缓存的私网 IP,且 _assert_no_dns_rebind 检测到
    不一致后拒绝调用(降级到 extractive),绝不连到攻击者 rebind 出的公网。
    """
    calls = {"n": 0}

    def fake_gethostbyname(h):
        calls["n"] += 1
        # 第 1 次(init 校验 + 缓存):私网 → 通过;后续 rebind 到公网
        return "127.0.0.1" if calls["n"] == 1 else "8.8.8.8"

    monkeypatch.setattr(socket, "gethostbyname", fake_gethostbyname)
    cfg = LLMConfig(enabled=True, endpoint="http://evil.example:80/v1")
    gw = LLMGateway(cfg)
    assert gw._pinned_ip == "127.0.0.1"  # 缓存了 init 时的私网 IP
    # 请求时 rebind:当前解析 8.8.8.8 != 缓存 127.0.0.1 → 拒绝
    with pytest.raises(EndpointSecurityError):
        asyncio.run(gw._call_llm("hi"))


def test_no_rebind_check_for_allow_public(monkeypatch):
    """allow_public=True 不做 rebinding 校验(用户已显式接受公网)。"""
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "8.8.8.8")
    cfg = LLMConfig(
        enabled=True, endpoint="https://api.example/v1",
        allow_public=True, api_key="sk-test",
    )
    gw = LLMGateway(cfg)
    # 不应抛 EndpointSecurityError
    gw._assert_no_dns_rebind()
    assert gw._pinned_ip is None  # allow_public 不缓存


def test_socket_patch_install_uninstall():
    """_install_socket_patch / _uninstall_socket_patch 不污染全局"""
    from app.services.llm_gateway import LLMGateway
    import socket as _socket
    
    orig = _socket.getaddrinfo
    LLMGateway._install_socket_patch("https://api.edgefn.net/v1", "198.18.0.51")
    assert LLMGateway._socket_patch_active is True
    assert LLMGateway._pinned_map["api.edgefn.net"] == ("198.18.0.51", 443)
    # getaddrinfo 应被替换
    assert _socket.getaddrinfo is not orig

    LLMGateway._uninstall_socket_patch()
    assert LLMGateway._socket_patch_active is False
    assert LLMGateway._pinned_map == {}
    assert _socket.getaddrinfo is orig


def test_socket_patch_supports_multiple_hosts_concurrently():
    """M3: 多 host 可同时 pin,互不覆盖。旧单 host 实现第二个 host 会被跳过。"""
    from app.services.llm_gateway import LLMGateway
    import socket as _socket

    LLMGateway._uninstall_socket_patch()  # 确保干净起点
    orig = _socket.getaddrinfo
    LLMGateway._install_socket_patch("https://one.example/v1", "10.0.0.1")
    # 第二个 host 安装时 _socket_patch_active 已 True,旧实现会 return 跳过
    LLMGateway._install_socket_patch("https://two.example/v1", "10.0.0.2")
    try:
        assert LLMGateway._pinned_map["one.example"] == ("10.0.0.1", 443)
        assert LLMGateway._pinned_map["two.example"] == ("10.0.0.2", 443)
        # 两个 host 都应解析到各自 pin 的 IP
        r1 = _socket.getaddrinfo("one.example", 443, type=_socket.SOCK_STREAM)
        r2 = _socket.getaddrinfo("two.example", 443, type=_socket.SOCK_STREAM)
        assert {s[0] for _, _, _, _, s in r1} == {"10.0.0.1"}
        assert {s[0] for _, _, _, _, s in r2} == {"10.0.0.2"}
        # 移除 one 后,two 仍应被 pin(旧实现会一并还原 getaddrinfo 导致 two 失效)
        LLMGateway._remove_socket_pin("https://one.example/v1")
        assert "one.example" not in LLMGateway._pinned_map
        assert LLMGateway._socket_patch_active is True  # two 还在,patch 仍装着
        r2b = _socket.getaddrinfo("two.example", 443, type=_socket.SOCK_STREAM)
        assert {s[0] for _, _, _, _, s in r2b} == {"10.0.0.2"}
    finally:
        LLMGateway._uninstall_socket_patch()
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


def test_concurrent_dns_pinned_requests_are_serialized(monkeypatch):
    """Process-global DNS pinning must never overlap across LLM requests."""
    import app.services.llm_gateway as gw_mod

    active = 0
    max_active = 0

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers=None):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.01)
            active -= 1
            return FakeResp()

    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(socket, "gethostbyname", lambda _host: "198.18.0.51")

    first = LLMGateway(LLMConfig(enabled=True, endpoint="https://one.example/v1", allow_public=True))
    second = LLMGateway(LLMConfig(enabled=True, endpoint="https://two.example/v1", allow_public=True))

    async def run_both():
        await asyncio.gather(first._call_llm("one"), second._call_llm("two"))

    asyncio.run(run_both())
    assert max_active == 1
    assert socket.getaddrinfo is LLMGateway._base_getaddrinfo
    assert LLMGateway._socket_patch_active is False


# ========== #16 prompt 渲染(花括号不触发 KeyError 兜底)==========

def test_render_prompt_with_braces_in_transcript():
    """转写含花括号 { 不再留字面 {max_words}。

    回归:str.format 会把转写里的 {xxx} 当占位符,触发 KeyError → 旧兜底只替
    {transcript},留下 {max_words} 字面发给 LLM("数值未填写"提示)。
    str.replace 不解析,转写花括号安全。
    """
    template = "请生成 {max_words} 字以内摘要: {transcript}"
    transcript = "会议提到 {重要} 内容,还有 {{双括号}}"
    prompt = LLMGateway._render_prompt(template, transcript, {"max_words": 200})
    assert "{max_words}" not in prompt  # 已替换为 200
    assert "200" in prompt
    assert transcript in prompt  # 转写原样保留(含花括号)


def test_render_prompt_without_max_words():
    """action_items/minutes 无 {max_words} 占位符,render 不替换它。"""
    template = "提取行动项: {transcript}"
    prompt = LLMGateway._render_prompt(template, "转写内容", {})
    assert prompt == "提取行动项: 转写内容"


# ========== #17 map-reduce 超长摘要 ==========

def test_one_hour_meeting_does_not_trigger_mapreduce(monkeypatch):
    """回归:默认 max_input_tokens=8000 下,1 小时会议(~100 段 100 字)
    不触发 map-reduce(单次调用)。阈值 0.95 让日常会议落回单次路径。
    """
    import app.services.llm_gateway as gw_mod
    call_count = {"n": 0}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            call_count["n"] += 1
            return {"choices": [{"message": {"content": "摘要"}}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers=None):
            return FakeResp()

    async def fake_probe(self): return True
    monkeypatch.setattr(LLMGateway, "_probe", fake_probe)
    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", FakeClient)

    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1", max_input_tokens=8000)
    gw = LLMGateway(cfg)
    # 1 小时会议典型量:100 段 × 100 字,加 [spk] 前缀 ≈ 10989 字符 ≈ 7326 token < 7600
    segs = [{"text": "x" * 100, "speaker_id": "Spk_1"} for _ in range(100)]
    text, source = asyncio.run(gw._generate("summarize", segs, max_words=200))
    assert source == "llm"  # 单次,非 map-reduce
    assert call_count["n"] == 1


def test_short_transcript_single_call(monkeypatch):
    """短文本(<= max_input_tokens*0.95)单次 LLM 调用,不 map-reduce。"""
    import app.services.llm_gateway as gw_mod
    call_count = {"n": 0}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "摘要内容"}}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers=None):
            call_count["n"] += 1
            return FakeResp()

    async def fake_probe(self): return True
    monkeypatch.setattr(LLMGateway, "_probe", fake_probe)
    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", FakeClient)

    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1", max_input_tokens=8000)
    gw = LLMGateway(cfg)
    # 短文本(几十字 << 8000*0.8)
    segs = [{"text": "这是一段短转写", "speaker_id": "Spk_1"}]
    text, source = asyncio.run(gw._generate("summarize", segs, max_words=200))
    assert source == "llm"
    assert call_count["n"] == 1  # 单次


def test_long_transcript_triggers_mapreduce(monkeypatch):
    """超长文本(> max_input_tokens*0.8)走 map-reduce,块数+1 次调用。"""
    import app.services.llm_gateway as gw_mod
    call_count = {"n": 0}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self):
            call_count["n"] += 1
            return {"choices": [{"message": {"content": f"块摘要{call_count['n']}"}}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers=None):
            return FakeResp()

    async def fake_probe(self): return True
    monkeypatch.setattr(LLMGateway, "_probe", fake_probe)
    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", FakeClient)

    # max_input_tokens=1000 → 阈值 800 token。造超长文本(每段 50 字,60 段 = 3000 字 ≈ 2000 token > 800)
    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1", max_input_tokens=1000)
    gw = LLMGateway(cfg)
    segs = [{"text": "这是第%d段会议转写内容。" % i * 5, "speaker_id": "Spk_1"} for i in range(60)]
    text, source = asyncio.run(gw._generate("summarize", segs, max_words=200))
    assert source == "llm-mapreduce"
    # map-reduce:块数 + 1 次合并调用。块数 >= 2(因为超长分了多块)
    assert call_count["n"] >= 3  # 至少 2 块 + 1 合并


def test_split_segments_keeps_turn_intact():
    """分块按 segment 整块累加,不切断单个说话人 turn。"""
    segs = [{"text": "x" * 100, "speaker_id": "Spk_1"} for _ in range(10)]
    # 每段 100 字 + 8 前缀 = 108,max_chars=300 → 每块约 2-3 段
    chunks = LLMGateway._split_segments(segs, max_chars_per_chunk=300)
    assert len(chunks) >= 3  # 10 段 / ~2-3 段每块
    # 每块都是完整 segment(没切断)
    flat = [s for chunk in chunks for s in chunk]
    assert len(flat) == 10  # 段数不变,无丢失


def test_custom_prompts_used_when_provided(monkeypatch):
    """用户改的 prompt(从 settings_repo 加载传入)被使用,而非默认。"""
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
            captured["prompt"] = json["messages"][0]["content"]
            return FakeResp()

    async def fake_probe(self): return True
    monkeypatch.setattr(LLMGateway, "_probe", fake_probe)
    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", FakeClient)

    custom = {"summarize": "自定义摘要模板 {max_words} 字: {transcript}"}
    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1")
    gw = LLMGateway(cfg, prompts=custom)
    asyncio.run(gw._generate("summarize", [{"text": "内容"}], max_words=150))
    assert "自定义摘要模板" in captured["prompt"]
    assert "150" in captured["prompt"]  # max_words 已替换
    assert "内容" in captured["prompt"]


def test_adaptive_max_words_by_duration():
    """_adaptive_max_words 按会议总时长算摘要篇幅。"""
    def segs_with_span(start, end):
        # 单段覆盖 [start, end] 秒
        return [{"text": "内容", "speaker_id": "Spk_0", "start_time": start, "end_time": end}]

    # <10min(<600s)→120
    assert LLMGateway._adaptive_max_words(segs_with_span(0, 300)) == 120
    assert LLMGateway._adaptive_max_words(segs_with_span(0, 599)) == 120
    # 10–30min(600–1800s)→200
    assert LLMGateway._adaptive_max_words(segs_with_span(0, 600)) == 200
    assert LLMGateway._adaptive_max_words(segs_with_span(0, 1200)) == 200
    # 30–60min(1800–3600s)→300
    assert LLMGateway._adaptive_max_words(segs_with_span(0, 1800)) == 300
    assert LLMGateway._adaptive_max_words(segs_with_span(0, 3500)) == 300
    # >60min→400
    assert LLMGateway._adaptive_max_words(segs_with_span(0, 3600)) == 400
    assert LLMGateway._adaptive_max_words(segs_with_span(0, 7200)) == 400
    # 时长估不出(无时间戳)→200(中位数兜底)
    assert LLMGateway._adaptive_max_words([{"text": "x", "speaker_id": "Spk_0"}]) == 200
    assert LLMGateway._adaptive_max_words([{"text": "x"}]) == 200


def test_generate_auto_injects_adaptive_max_words(monkeypatch):
    """summarize 未显式传 max_words 时,_generate 自动按时长注入并渲染。"""
    import app.services.llm_gateway as gw_mod
    captured = {"prompt": ""}

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "摘要"}}]}

    class FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json, headers=None):
            captured["prompt"] = json["messages"][0]["content"]
            return FakeResp()

    async def fake_probe(self): return True
    monkeypatch.setattr(LLMGateway, "_probe", fake_probe)
    monkeypatch.setattr(gw_mod.httpx, "AsyncClient", FakeClient)

    cfg = LLMConfig(enabled=True, endpoint="http://127.0.0.1:11434/v1", max_input_tokens=8000)
    gw = LLMGateway(cfg)
    # 35 分钟会议(2100s)→ 应注入 max_words=300,且渲染进 prompt
    segs = [{"text": "x" * 100, "speaker_id": "Spk_0", "start_time": 0, "end_time": 2100}]
    asyncio.run(gw._generate("summarize", segs))  # 不传 max_words
    assert "300" in captured["prompt"], "自适应 max_words 应渲染进 prompt"
    assert "{max_words}" not in captured["prompt"], "占位符不应残留"


def test_dns_pin_guard_releases_lock_and_pin_on_cancel():
    """协程在 _dns_pin_guard yield 期间被取消时,asyncio.Lock 必须释放、pin
    必须移除,否则后续所有 LLM 调用 acquire 永久阻塞(锁孤立)。

    回归:旧实现用 threading.Lock + asyncio.to_thread(acquire),协程在 acquire
    期间被取消时 worker 线程仍会拿到锁,而协程的 try/finally 不再执行 →
    release 永不调用 → 锁永久持有 → 后续每次 _dns_pin_guard 都挂死在
    acquire 上,LLM 全部退化 extractive。
    """
    import socket as _socket
    LLMGateway._uninstall_socket_patch()
    orig = _socket.getaddrinfo

    async def scenario():
        entered = asyncio.Event()

        async def hold():
            async with LLMGateway._dns_pin_guard(
                "https://api.edgefn.net/v1", "198.18.0.51"
            ):
                entered.set()
                await asyncio.sleep(3600)  # 持锁期间阻塞,直到被外部取消

        holder = asyncio.create_task(hold())
        await entered.wait()
        assert LLMGateway._socket_patch_active is True  # 确实在持锁+装了 pin

        holder.cancel()  # 取消(模拟请求中途被取消)
        try:
            await holder
        except asyncio.CancelledError:
            pass

        # 取消后:guard 的 finally 应已移除本 host 的 pin
        assert "api.edgefn.net" not in LLMGateway._pinned_map

        # 关键:锁应已释放 — 第二只 guard 能立即拿到(不死锁),超时兜底
        done = asyncio.Event()

        async def second():
            async with LLMGateway._dns_pin_guard(
                "https://api.edgefn.net/v1", "198.18.0.51"
            ):
                done.set()
            LLMGateway._remove_socket_pin("https://api.edgefn.net/v1")

        await asyncio.wait_for(second(), timeout=2.0)
        assert done.is_set(), "取消后锁应释放,后续 guard 不应死锁"

    try:
        asyncio.run(scenario())
    finally:
        LLMGateway._uninstall_socket_patch()
        _socket.getaddrinfo = orig
