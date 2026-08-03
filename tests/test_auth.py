"""鉴权端点和中间件测试。

覆盖:
- 默认 admin 初始化
- POST /v1/auth/login: 成功返 token,失败 401
- POST /v1/auth/change-password: 改密 + 清除 must_change_password
- 鉴权中间件: 白名单 / 401 无 token / 401 错 token / 200 有效 token
- 401 时清 token (前端依赖)
"""
import sys
import os
import time
import types
import tempfile
import pytest
from unittest.mock import MagicMock

# 临时关掉 conftest 的 TEST_AUTH_BYPASS,让真鉴权跑
@pytest.fixture(autouse=True)
def _disable_auth_bypass(monkeypatch):
    monkeypatch.delenv("TEST_AUTH_BYPASS", raising=False)


def _install_fake_engines():
    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    sys.modules["engine.asr_engine"] = fake_asr

    fake_speaker_pkg = types.ModuleType("engine.speaker")
    fake_speaker_pkg.__path__ = []
    fake_speaker_pkg.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_speaker_pkg.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})
    fake_speaker_pkg.get_all_engines = MagicMock(
        return_value={"current": "mock", "engines": {}}
    )

    fake_base = types.ModuleType("engine.speaker.base_engine")
    fake_base.BaseSpeakerEngine = MagicMock
    fake_base.logger = MagicMock()
    sys.modules["engine.speaker.base_engine"] = fake_base

    fake_factory = types.ModuleType("engine.speaker.speaker_factory")
    fake_factory.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_factory.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})
    fake_factory.get_all_engines = MagicMock(return_value={"current": "mock", "asr": {}, "speakers": {}})
    fake_factory.ENGINE_CONFIG = {}
    fake_factory.get_engine_manager = MagicMock(return_value=MagicMock())

    sys.modules["engine.speaker"] = fake_speaker_pkg
    sys.modules["engine.speaker.speaker_factory"] = fake_factory


@pytest.fixture(autouse=True)
def _fake_engine_modules():
    names = (
        "engine.asr_engine",
        "engine.speaker",
        "engine.speaker.base_engine",
        "engine.speaker.speaker_factory",
    )
    previous = {name: sys.modules.get(name) for name in names}
    _install_fake_engines()
    yield
    for name, module in previous.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def _make_client(monkeypatch, client_host="testclient"):
    """建 TestClient (不走 conftest 的 TEST_AUTH_BYPASS fixture,走真鉴权)"""
    tmp = tempfile.mkdtemp()
    os.environ["STORAGE_DB_PATH"] = os.path.join(tmp, "test.db")
    os.environ["UPLOAD_CHUNK_DURATION"] = "30"
    # 重要: 用稳定 secret 测 JWT 编解码
    os.environ["JWT_SECRET"] = "test-secret-for-unit-tests"
    import importlib
    cfg_mod = importlib.import_module("app.config")
    importlib.reload(cfg_mod)
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    return TestClient(app_mod.create_app(), client=(client_host, 50000))


def test_auth_bypass_rejected_in_lan_mode_even_when_debug(monkeypatch, tmp_path):
    """LAN/public 部署声明后,TEST_AUTH_BYPASS 不允许绕过鉴权."""
    import importlib

    monkeypatch.setenv("STORAGE_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-unit-tests")
    monkeypatch.setenv("DEPLOYMENT_MODE", "lan")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000")
    monkeypatch.setenv("TEST_AUTH_BYPASS", "1")
    cfg_mod = importlib.import_module("app.config")
    importlib.reload(cfg_mod)
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)

    with pytest.raises(RuntimeError, match="TEST_AUTH_BYPASS"):
        app_mod.create_app()


# ========== 默认 admin 初始化 ==========

def test_default_admin_created_on_init(monkeypatch, tmp_path):
    """首次启动自动创建 admin/admin (must_change_password=1)"""
    import importlib
    from app.repositories.database import Database
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    with db.connect() as conn:
        row = conn.execute("SELECT username, must_change_password FROM users").fetchone()
    assert row["username"] == "admin"
    assert row["must_change_password"] == 1


def test_default_admin_not_duplicated(monkeypatch, tmp_path):
    """第二次 init_schema 不重复插 admin"""
    from app.repositories.database import Database
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    db.init_schema()  # 第二次
    with db.connect() as conn:
        n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert n == 1


# ========== AuthService 单元测试 ==========

def test_auth_service_password_hash_and_verify(tmp_path):
    """bcrypt pbkdf2 哈希 + verify"""
    from app.repositories.database import Database
    from app.services.auth import AuthService
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    svc = AuthService(db)
    h = svc.hash_password("hello123")
    assert h.startswith("pbkdf2:sha256:")
    assert svc.verify_password("hello123", h) is True
    assert svc.verify_password("wrong", h) is False


def test_auth_service_jwt_roundtrip(tmp_path):
    """JWT 签发 + 解码"""
    from app.repositories.database import Database
    from app.services.auth import AuthService
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    svc = AuthService(db)
    token = svc.create_token(42, "alice")
    payload = svc.decode_token(token)
    assert payload is not None
    assert payload["sub"] == "42"
    assert payload["username"] == "alice"


def test_auth_service_invalid_token_returns_none(tmp_path):
    """无效 token 返 None(不抛)"""
    from app.repositories.database import Database
    from app.services.auth import AuthService
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    svc = AuthService(db)
    assert svc.decode_token("garbage") is None
    assert svc.decode_token("") is None


def test_auth_service_default_admin_can_login(tmp_path):
    """默认 admin/admin 能登录,返 must_change_password=true"""
    from app.repositories.database import Database
    from app.services.auth import AuthService
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    svc = AuthService(db)
    user = svc.authenticate("admin", "admin")
    assert user is not None
    assert user["username"] == "admin"
    assert user["must_change_password"] == 1
    # 错密码
    assert svc.authenticate("admin", "wrong") is None
    # 不存在的用户
    assert svc.authenticate("nope", "admin") is None


def test_auth_service_change_password_clears_flag(tmp_path):
    """改密后 must_change_password 清 0"""
    from app.repositories.database import Database
    from app.services.auth import AuthService
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    svc = AuthService(db)
    user = svc.authenticate("admin", "admin")
    assert user["must_change_password"] == 1
    ok = svc.change_password(user["id"], "newpass123")
    assert ok is True
    # 旧密码失败
    assert svc.authenticate("admin", "admin") is None
    # 新密码成功
    user2 = svc.authenticate("admin", "newpass123")
    assert user2 is not None
    assert user2["must_change_password"] == 0


# ========== HTTP 端点 + 鉴权中间件 ==========

def test_login_success_returns_token(monkeypatch):
    """POST /v1/auth/login 返 token + user"""
    client = _make_client(monkeypatch)
    r = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    data = r.json()
    assert "token" in data
    assert data["user"]["username"] == "admin"
    assert data["user"]["must_change_password"] is True


def test_login_wrong_password_returns_401(monkeypatch):
    """错密码 401 + 模糊错误信息(不暴露用户是否存在)"""
    client = _make_client(monkeypatch)
    r = client.post("/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401
    assert "用户名或密码错误" in r.json()["detail"]


def test_login_unknown_user_returns_401(monkeypatch):
    """不存在用户也 401 + 同样的模糊错误"""
    client = _make_client(monkeypatch)
    r = client.post("/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert r.status_code == 401
    assert "用户名或密码错误" in r.json()["detail"]


def test_login_validation_short_password(monkeypatch):
    """空密码返回 401，避免暴露登录字段结构。"""
    client = _make_client(monkeypatch)
    r = client.post("/v1/auth/login", json={"username": "admin", "password": ""})
    assert r.status_code == 401
    assert "登录信息格式错误" in r.json()["detail"]


def test_whitelist_health_no_auth(monkeypatch):
    """/health 不需鉴权"""
    client = _make_client(monkeypatch)
    r = client.get("/health")
    assert r.status_code == 200


def test_whitelist_ready_no_auth(monkeypatch):
    """/ready 不需鉴权"""
    client = _make_client(monkeypatch)
    r = client.get("/ready")
    assert r.status_code == 200


def test_whitelist_models_no_auth(monkeypatch):
    """模型目录供启动页使用，不要求登录。"""
    client = _make_client(monkeypatch)
    r = client.get("/v1/models")
    assert r.status_code == 200


def test_local_bypass_rejects_untrusted_browser_origin(monkeypatch):
    client = _make_client(monkeypatch)
    r = client.get("/v1/meetings", headers={"Origin": "https://evil.example"})
    assert r.status_code == 401


def test_local_bypass_allows_trusted_browser_origin(monkeypatch):
    """可信本机 Origin(浏览器 SPA 同源)无 token 仍放行。"""
    client = _make_client(monkeypatch, client_host="127.0.0.1")
    r = client.get("/v1/meetings", headers={"Origin": "http://127.0.0.1:8000"})
    assert r.status_code == 200


def test_local_bypass_allows_no_origin_for_browser_compat(monkeypatch):
    """无 Origin 视为可信是**有意为之**:部分浏览器(Firefox)对同源 fetch
    不携带 Origin,本地 SPA 靠这个放行。该行为是文档化的威胁模型,不是 bug。
    真正的本机隔离请用 DEPLOYMENT_MODE=lan / LOCAL_AUTH_DISABLED=false。
    """
    client = _make_client(monkeypatch, client_host="127.0.0.1")
    r = client.get("/v1/meetings")
    assert r.status_code == 200


def test_websocket_bypass_no_longer_accepts_testclient_host(monkeypatch):
    """H2: 'testclient'(Starlette TestClient host)不得作为本机来源放行 WS。
    删除后,testclient 来源无 auth 消息应被拒(4401),证明后门已堵。
    """
    client = _make_client(monkeypatch)  # client_host 默认 "testclient"
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect("/ws/v1/stream/no_backdoor") as ws:
            ws.send_json({"action": "rename", "title": "should be rejected"})
            ws.receive_json()
    assert caught.value.code == 4401


def test_security_headers_are_present(monkeypatch):
    client = _make_client(monkeypatch)
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_csp_connect_src_tightened_with_explicit_origins(monkeypatch):
    """显式配置 ALLOWED_ORIGINS 时，connect-src 收紧到具体 ws/wss host，
    不再放行任意 ws 服务器(降低 XSS 经 WS 外泄)。"""
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000")
    client = _make_client(monkeypatch)
    r = client.get("/health")
    csp = r.headers["content-security-policy"]
    assert "ws://127.0.0.1:*" in csp
    assert "ws://localhost:*" in csp
    # 不应再出现通配形式 'ws: wss:'
    assert "ws: wss:" not in csp


def test_csp_connect_src_falls_back_to_wildcard_when_star(monkeypatch):
    """ALLOWED_ORIGINS=* 时无法枚举具体 host，回退到 ws: wss:。"""
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    client = _make_client(monkeypatch)
    r = client.get("/health")
    csp = r.headers["content-security-policy"]
    assert "connect-src 'self' ws: wss:;" in csp


def test_csp_connect_src_includes_lan_origin_when_configured(monkeypatch):
    """LAN 部署设置具体 origin 后，CSP 包含对应的 ws/wss 地址。"""
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://192.168.1.50:8000")
    client = _make_client(monkeypatch)
    r = client.get("/health")
    csp = r.headers["content-security-policy"]
    assert "ws://192.168.1.50:*" in csp
    assert "ws: wss:" not in csp


def test_local_websocket_bypass_rejects_untrusted_origin(monkeypatch):
    client = _make_client(monkeypatch)
    with pytest.raises(WebSocketDisconnect) as caught:
        with client.websocket_connect(
            "/ws/v1/stream/origin_test",
            headers={"Origin": "https://evil.example"},
        ) as ws:
            ws.send_json({"action": "rename", "title": "not auth"})
            ws.receive_json()
    assert caught.value.code == 4401


def test_protected_endpoint_no_token_returns_401(monkeypatch):
    """受保护端点无 token 返 401"""
    client = _make_client(monkeypatch)
    r = client.get("/v1/meetings")
    assert r.status_code == 401
    assert "未登录" in r.json()["detail"]


def test_protected_endpoint_invalid_token_returns_401(monkeypatch):
    """错 token 返 401"""
    client = _make_client(monkeypatch)
    r = client.get("/v1/meetings", headers={"Authorization": "Bearer garbage.token.here"})
    assert r.status_code == 401


def test_default_password_token_requires_password_change(monkeypatch):
    """默认 admin/admin 登录后必须先改密,不能直接访问业务端点"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.get("/v1/meetings", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
    assert "修改默认密码" in r.json()["detail"]


def test_protected_endpoint_valid_token_returns_200_after_password_change(monkeypatch):
    """改密后的有效 token 可访问业务端点"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    changed = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "newsecret123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    token = changed.json()["token"]
    r = client.get("/v1/meetings", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_auth_me_returns_user(monkeypatch):
    """/v1/auth/me 返当前用户信息"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    data = r.json()
    assert data["username"] == "admin"
    assert data["must_change_password"] == 1


def test_change_password_full_flow(monkeypatch):
    """完整改密流: login → change-password → 旧密码失败 → 新密码成功 + 标志清除"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "newsecret123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["user"]["must_change_password"] is False
    # 旧密码 401
    lr2 = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert lr2.status_code == 401
    # 新密码 200
    lr3 = client.post("/v1/auth/login", json={"username": "admin", "password": "newsecret123"})
    assert lr3.status_code == 200
    assert lr3.json()["user"]["must_change_password"] is False


def test_loopback_bypass_still_authenticates_explicit_bearer_token(monkeypatch):
    """本机免登录不能跳过显式 token 的用户状态注入。"""
    client = _make_client(monkeypatch, client_host="127.0.0.1")
    logged_in = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "admin"}
    )
    token = logged_in.json()["token"]

    changed = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "newsecret123"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert changed.status_code == 200
    assert changed.json()["user"]["must_change_password"] is False


def test_change_password_wrong_old_returns_400(monkeypatch):
    """旧密码错 400 (不是 401,让前端能区分)"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "WRONG", "new_password": "newsecret123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert "旧密码" in r.json()["detail"]


def test_change_password_no_token_returns_401(monkeypatch):
    """未登录调改密 401"""
    client = _make_client(monkeypatch)
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "newsecret123"},
    )
    assert r.status_code == 401


def test_logout_endpoint(monkeypatch):
    """/v1/auth/logout 返 200(无状态)"""
    client = _make_client(monkeypatch)
    r = client.post("/v1/auth/logout")
    assert r.status_code == 200


def test_logout_with_token_revokes_it(monkeypatch):
    """logout 带 Bearer token 后,该 token 立即失效(/v1/auth/me 返 401)。
    前端 client.ts 注入 token 给 logout 请求,后端 revoke_token 才生效。"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    # logout 带 token
    out = client.post("/v1/auth/logout", headers=headers)
    assert out.status_code == 200
    # 同 token 再访问 /v1/auth/me 应 401(revoked)
    me = client.get("/v1/auth/me", headers=headers)
    assert me.status_code == 401, f"logout 后 token 应已失效: {me.status_code}"


# ========== Options 预检放行(CORS) ==========

def test_options_request_passes(monkeypatch):
    """OPTIONS 预检放行(无 token)"""
    client = _make_client(monkeypatch)
    r = client.options("/v1/meetings")
    # FastAPI 默认 CORS middleware 处理 OPTIONS,可能 200 或 405 — 只要不是 401
    assert r.status_code != 401


# ========== 登录与会话安全回归测试 ==========

def test_login_rate_limit_blocks_brute_force(monkeypatch):
    """登录失败达到阈值后触发限流。"""
    client = _make_client(monkeypatch)
    # 6 次错误登录(同 IP)
    for i in range(6):
        r = client.post("/v1/auth/login", json={"username": "admin", "password": f"wrong{i}"})
        if i < 5:
            # 前 5 次: 401 (错密码)
            assert r.status_code == 401, f"第 {i+1} 次应 401, 实际 {r.status_code}: {r.text}"
        else:
            # 第 6 次: 429 (触发限流)
            assert r.status_code == 429, f"第 6 次应触发限流 429, 实际 {r.status_code}"
            assert "登录尝试过多" in r.json()["detail"]
            assert "Retry-After" in r.headers


def test_login_success_clears_failure_history(monkeypatch):
    """登录成功后清理该 IP 的历史失败记录，避免后续一次输错
    因旧失败累积触发误锁。"""
    client = _make_client(monkeypatch)
    # 先用默认 admin/admin 登录拿 token 改密(满足 must_change_password)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "MatrixTest2026"},
        headers={"Authorization": f"Bearer {token}"},
    )
    # 改密后旧 token 失效,重新登录拿新 token + 清 must_change
    lr2 = client.post("/v1/auth/login", json={"username": "admin", "password": "MatrixTest2026"})
    assert lr2.status_code == 200
    # 制造 4 次失败(不触发 5 次锁)
    for _ in range(4):
        r = client.post("/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
    # 第 5 次成功 → 应清失败记录
    ok = client.post("/v1/auth/login", json={"username": "admin", "password": "MatrixTest2026"})
    assert ok.status_code == 200
    # 再输错 1 次:不应因旧 4 次累积触发锁(应 401 非 429)
    again = client.post("/v1/auth/login", json={"username": "admin", "password": "wrong"})
    assert again.status_code == 401, f"成功登录后旧失败应已清,不应误锁: {again.status_code}"


def test_change_password_weak_password_returns_400_without_invalidating_session(monkeypatch):
    """已登录用户的弱密码是输入错误，不得伪装成鉴权失败。"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    # 短密码
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "abc"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400
    assert "字母" in r.json()["detail"] and "数字" in r.json()["detail"]
    me = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200


def test_change_password_no_letter_returns_400(monkeypatch):
    """纯数字新密码返回可修正的输入错误。"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "12345678"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_change_password_no_digit_returns_400(monkeypatch):
    """纯字母新密码返回可修正的输入错误。"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "abcdefgh"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_change_password_rejects_reusing_current_password(monkeypatch):
    client = _make_client(monkeypatch)
    service = client.app.state.auth_service
    user = service.authenticate("admin", "admin")
    assert user is not None
    assert service.change_password(user["id"], "current123")
    logged_in = client.post(
        "/v1/auth/login", json={"username": "admin", "password": "current123"}
    )
    token = logged_in.json()["token"]

    response = client.post(
        "/v1/auth/change-password",
        json={"old_password": "current123", "new_password": "current123"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]


def test_change_password_strong_password_works(monkeypatch):
    """包含字母和数字的八位以上密码可以通过校验。"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "newpass123"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200


def test_old_token_invalidated_after_password_change(monkeypatch):
    """修改密码后旧 token 失效。"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    old_token = lr.json()["token"]
    # 改密
    cr = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "newpass456"},
        headers={"Authorization": f"Bearer {old_token}"},
    )
    assert cr.status_code == 200
    new_token = cr.json()["token"]
    # 旧 token 调 /me 应 401
    r = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"})
    assert r.status_code == 401
    assert "密码已修改" in r.json()["detail"]
    # 新 token 调 /me 应 200
    r = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert r.status_code == 200


def test_jwt_includes_iss_aud_claims(monkeypatch):
    """JWT 包含 iss/aud claims，错误 issuer 会被拒绝。"""
    import jwt
    # 拿到 token
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    # 解码看 claims
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload.get("iss") == "matrix-live-diarizer"
    assert payload.get("aud") == "matrix-client"


def test_jwt_aud_validation_rejects_wrong_aud():
    """错误 audience 的 token 应解码失败。"""
    import jwt
    from werkzeug.security import generate_password_hash
    secret = "test-secret"
    # 造一个 aud 错的 token
    bad_token = jwt.encode(
        {"sub": "1", "username": "admin", "iss": "matrix-live-diarizer", "aud": "OTHER"},
        secret, algorithm="HS256"
    )
    with pytest.raises(jwt.InvalidAudienceError):
        jwt.decode(bad_token, secret, algorithms=["HS256"],
                   audience="matrix-client", issuer="matrix-live-diarizer")


def test_login_with_bad_password_returns_401_not_422(monkeypatch):
    """登录字段缺失时返回 401，不通过 422 暴露字段结构。"""
    client = _make_client(monkeypatch)
    # 完全没字段
    r = client.post("/v1/auth/login", json={})
    assert r.status_code == 401
    assert "登录信息格式错误" in r.json()["detail"]
    # 缺 password
    r = client.post("/v1/auth/login", json={"username": "admin"})
    assert r.status_code == 401
    # 错类型
    r = client.post("/v1/auth/login", json={"username": 123, "password": []})
    assert r.status_code == 401


def test_unauthorized_response_carries_cors_for_trusted_origin(monkeypatch):
    """可信跨源请求的 401 带 Access-Control-Allow-Origin，否则浏览器会视为网络错误，
    前端无法区分未登录、不能自动跳登录页。"""
    import importlib
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("STORAGE_DB_PATH", os.path.join(tmp, "test.db"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-unit-tests")
    monkeypatch.setenv("DEPLOYMENT_MODE", "lan")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example")
    cfg = importlib.import_module("app.config"); importlib.reload(cfg)
    app_mod = importlib.import_module("app"); importlib.reload(app_mod)
    client = TestClient(app_mod.create_app(), client=("203.0.113.5", 50000))
    # 无 token + 可信 Origin → 401 带 ACAO
    r = client.get("/v1/meetings", headers={"Origin": "https://app.example"})
    assert r.status_code == 401
    assert r.headers.get("access-control-allow-origin") == "https://app.example"


def test_unauthorized_response_no_cors_for_untrusted_origin(monkeypatch):
    """不可信 Origin 的 401 不带 ACAO，避免跨源信息泄露。"""
    import importlib
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("STORAGE_DB_PATH", os.path.join(tmp, "test.db"))
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-unit-tests")
    monkeypatch.setenv("DEPLOYMENT_MODE", "lan")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example")
    cfg = importlib.import_module("app.config"); importlib.reload(cfg)
    app_mod = importlib.import_module("app"); importlib.reload(app_mod)
    client = TestClient(app_mod.create_app(), client=("203.0.113.5", 50000))
    r = client.get("/v1/meetings", headers={"Origin": "https://evil.example"})
    assert r.status_code == 401
    assert r.headers.get("access-control-allow-origin") is None
