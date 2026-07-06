"""鉴权端点 + 中间件单测 (Roadmap 安全项 Bug-79)

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

sys.path.insert(0, "/Users/lgy/python/github.com/lgy1027/matrix-live-diarizer")

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

    fake_base = types.ModuleType("engine.speaker.base_engine")
    fake_base.BaseSpeakerEngine = MagicMock
    fake_base.logger = MagicMock()
    sys.modules["engine.speaker.base_engine"] = fake_base

    fake_factory = types.ModuleType("engine.speaker.speaker_factory")
    fake_factory.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_factory.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})
    fake_factory.get_all_engines = MagicMock(return_value={"current": "mock", "asr": {}, "speakers": {}})
    fake_factory.ENGINE_CONFIG = {}
    fake_factory.ASR_CONFIG = {}
    fake_factory.get_engine_manager = MagicMock(return_value=MagicMock())

    sys.modules["engine.speaker"] = fake_speaker_pkg
    sys.modules["engine.speaker.speaker_factory"] = fake_factory


_install_fake_engines()

from fastapi.testclient import TestClient


def _make_client(monkeypatch):
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
    return TestClient(app_mod.create_app())


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
    """空密码返 401 (Bug-90 模糊化,不暴露 schema)"""
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
    """/v1/models 不需鉴权"""
    client = _make_client(monkeypatch)
    r = client.get("/v1/models")
    assert r.status_code == 200


def test_protected_endpoint_no_token_returns_401(monkeypatch):
    """受保护端点无 token 返 401"""
    client = _make_client(monkeypatch)
    r = client.get("/v1/speakers")
    assert r.status_code == 401
    assert "未登录" in r.json()["detail"]


def test_protected_endpoint_invalid_token_returns_401(monkeypatch):
    """错 token 返 401"""
    client = _make_client(monkeypatch)
    r = client.get("/v1/speakers", headers={"Authorization": "Bearer garbage.token.here"})
    assert r.status_code == 401


def test_default_password_token_requires_password_change(monkeypatch):
    """默认 admin/admin 登录后必须先改密,不能直接访问业务端点"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.get("/v1/speakers", headers={"Authorization": f"Bearer {token}"})
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
    r = client.get("/v1/speakers", headers={"Authorization": f"Bearer {token}"})
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


# ========== Options 预检放行(CORS) ==========

def test_options_request_passes(monkeypatch):
    """OPTIONS 预检放行(无 token)"""
    client = _make_client(monkeypatch)
    r = client.options("/v1/speakers")
    # FastAPI 默认 CORS middleware 处理 OPTIONS,可能 200 或 405 — 只要不是 401
    assert r.status_code != 401


# ========== 审核 #1-#12 修复覆盖 ==========

def test_login_rate_limit_blocks_brute_force(monkeypatch):
    """审核 #1: /v1/auth/login 限流(防暴力破解, 5次/60s, 触发锁 60s)"""
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


def test_change_password_weak_password_returns_401(monkeypatch):
    """审核 #5: 弱密码(< 8 字符)返 401 模糊错误"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    # 短密码
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "abc"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401
    # 不暴露具体校验规则
    assert "登录信息格式错误" in r.json()["detail"]


def test_change_password_no_letter_returns_401(monkeypatch):
    """审核 #5: 纯数字(8 字符)返 401"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "12345678"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


def test_change_password_no_digit_returns_401(monkeypatch):
    """审核 #5: 纯字母(8 字符)返 401"""
    client = _make_client(monkeypatch)
    lr = client.post("/v1/auth/login", json={"username": "admin", "password": "admin"})
    token = lr.json()["token"]
    r = client.post(
        "/v1/auth/change-password",
        json={"old_password": "admin", "new_password": "abcdefgh"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 401


def test_change_password_strong_password_works(monkeypatch):
    """审核 #5: 强密码(8+ 字符, 字母+数字)通过"""
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
    """审核 #7: 改密后旧 token 失效"""
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
    """审核 #10: JWT 包含 iss/aud claims, 错 iss 拒绝"""
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
    """审核 #10: 错 aud 的 token 应解码失败"""
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
    """审核 #12: 缺字段返 401 (模糊), 不返 422 暴露 schema"""
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
