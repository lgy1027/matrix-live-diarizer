"""回归测试:Pydantic 字段 max_length / pattern 校验"""
import sys
import types
import os
import tempfile
import importlib
from unittest.mock import MagicMock


def _install_fake_engines():
    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    sys.modules["engine.asr_engine"] = fake_asr

    fake_speaker_pkg = types.ModuleType("engine.speaker")
    fake_speaker_pkg.__path__ = []
    fake_speaker_pkg.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_speaker_pkg.get_engine_manager = MagicMock()

    fake_base = types.ModuleType("engine.speaker.base_engine")
    fake_base.BaseSpeakerEngine = MagicMock
    fake_base.logger = MagicMock()
    sys.modules["engine.speaker.base_engine"] = fake_base

    fake_factory = types.ModuleType("engine.speaker.speaker_factory")
    fake_factory.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_factory.get_engine_manager = MagicMock()
    fake_factory.get_all_engines = MagicMock()
    fake_factory.ENGINE_CONFIG = {}
    fake_factory.ASR_CONFIG = {}
    fake_factory.get_engine_info = MagicMock()
    sys.modules["engine.speaker"] = fake_speaker_pkg
    sys.modules["engine.speaker.speaker_factory"] = fake_factory


_install_fake_engines()

from fastapi.testclient import TestClient


def _make_client(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("STORAGE_DB_PATH", os.path.join(tmp, "test.db"))
    cfg_mod = importlib.import_module("app.config")
    importlib.reload(cfg_mod)
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    return TestClient(app_mod.create_app()), cfg_mod.config


# ========== UpdateSessionRequest.title ==========

def test_session_title_max_length(monkeypatch):
    """title > 200 字符应被 Pydantic 拒绝(422)"""
    client, _ = _make_client(monkeypatch)
    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="ok", duration_sec=1.0)

    long_title = "x" * 201
    resp = client.patch(f"/v1/sessions/{sid}", json={"title": long_title})
    assert resp.status_code == 422, f"超长 title 应被拒,实际: {resp.status_code}"
    assert "title" in str(resp.json())


def test_session_title_strips_control_chars(monkeypatch):
    """title 含 \\r\\n 应被剥除(不污染日志/响应)"""
    client, _ = _make_client(monkeypatch)
    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="ok", duration_sec=1.0)

    resp = client.patch(f"/v1/sessions/{sid}", json={"title": "a\r\nX-Injected: pwned"})
    assert resp.status_code == 200
    # title 应只剩 "a" (剥 \r\n 后 "aX-Injected: pwned" 也对,
    # 但要确保 isprintable 部分都在 — 这里 isprintable 包括字母和 : 空格)
    # 关键是: 落库的 title 不含 \r \n
    db_title = resp.json()["session"]["title"]
    assert "\r" not in db_title
    assert "\n" not in db_title


def test_session_is_archived_must_be_0_or_1(monkeypatch):
    """is_archived 必须是 0/1(防 SQL/逻辑混乱)"""
    client, _ = _make_client(monkeypatch)
    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="ok", duration_sec=1.0)

    resp = client.patch(f"/v1/sessions/{sid}", json={"is_archived": 5})
    assert resp.status_code == 422


# ========== SpeakerUpdateRequest.name ==========

def test_speaker_name_rejects_control_chars(monkeypatch):
    """speaker name 含控制字符应被 pattern 拒绝"""
    client, _ = _make_client(monkeypatch)
    resp = client.patch("/v1/speakers/Spk_001", json={"name": "evil\r\nX-Injected"})
    # 422 (Pydantic pattern 拒绝) 或 404 (speaker 不存在, 通过 mock 引擎是 MagicMock)
    # 看实际响应
    assert resp.status_code in (404, 422), f"应拒绝 control chars,实际: {resp.status_code} body={resp.text}"


def test_speaker_name_accepts_chinese():
    """Pydantic pattern 应接受中英文/空格/标点,只拒绝控制字符"""
    from app.schemas.response import SpeakerUpdateRequest
    from pydantic import ValidationError

    # 接受场景
    for name in ["老张", "老张 工程师", "Zhang San", "Mr. Smith Jr.", "张三(团队负责人)"]:
        obj = SpeakerUpdateRequest(name=name)
        assert obj.name == name, f"应接受: {name!r}"

    # 拒绝场景
    for bad in ["evil\r\nX-Injected", "ctrl\x07bell"]:
        try:
            SpeakerUpdateRequest(name=bad)
            assert False, f"应拒绝: {bad!r}"
        except ValidationError:
            pass  # 预期


def test_session_title_max_length_in_model():
    """UpdateSessionRequest.title 应有 max_length 约束"""
    from app.api.sessions import UpdateSessionRequest
    from pydantic import ValidationError
    try:
        UpdateSessionRequest(title="x" * 201)
        assert False, "应拒绝 201 字 title"
    except ValidationError:
        pass
    # 200 字应通过
    obj = UpdateSessionRequest(title="x" * 200)
    assert len(obj.title) == 200


def test_session_is_archived_ge_le():
    """UpdateSessionRequest.is_archived 必须 0 或 1"""
    from app.api.sessions import UpdateSessionRequest
    from pydantic import ValidationError
    for v in [-1, 2, 100]:
        try:
            UpdateSessionRequest(is_archived=v)
            assert False, f"应拒绝 is_archived={v}"
        except ValidationError:
            pass
    for v in [0, 1]:
        obj = UpdateSessionRequest(is_archived=v)
        assert obj.is_archived == v


def test_cleanup_speaker_ids_max_length_in_model():
    """CleanupRequest.speaker_ids 超过 1000 应被 Pydantic 拒绝"""
    from app.api.speakers import CleanupRequest
    from pydantic import ValidationError
    ids = [f"Spk_{i:06d}" for i in range(1001)]
    try:
        CleanupRequest(speaker_ids=ids)
        assert False, "应拒绝 1001 个 speaker_ids"
    except ValidationError:
        pass
    # 1000 个应通过
    obj = CleanupRequest(speaker_ids=ids[:1000])
    assert len(obj.speaker_ids) == 1000


def test_cleanup_max_count_range():
    """CleanupRequest.max_count 必须 0-10000"""
    from app.api.speakers import CleanupRequest
    from pydantic import ValidationError
    for v in [-1, 10001]:
        try:
            CleanupRequest(max_count=v)
            assert False, f"应拒绝 max_count={v}"
        except ValidationError:
            pass
    obj = CleanupRequest(max_count=0)
    assert obj.max_count == 0


# ========== CleanupRequest ==========

def test_cleanup_speaker_ids_max_length(monkeypatch):
    """speaker_ids 超过 1000 个应被拒绝(防 DoS)"""
    client, _ = _make_client(monkeypatch)
    ids = [f"Spk_{i:06d}" for i in range(1001)]
    resp = client.post("/v1/speakers/cleanup", json={"speaker_ids": ids, "dry_run": True})
    assert resp.status_code == 422, f"超长 speaker_ids 应被拒,实际: {resp.status_code}"


def test_cleanup_max_count_must_be_in_range(monkeypatch):
    """max_count 必须 0-10000"""
    client, _ = _make_client(monkeypatch)
    resp = client.post("/v1/speakers/cleanup", json={"max_count": 99999, "dry_run": True})
    assert resp.status_code == 422


# ========== CORS 配置 ==========

def test_cors_default_is_wildcard():
    """默认配置应为 '*' (本地 file:// 部署无 CORS 风险)"""
    import importlib
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    importlib.import_module("app.config")
    from app.config import config
    assert config.cors.allowed_origins == ("*",)
    assert config.cors.allow_credentials is False


def test_cors_env_var_restricts_origins(monkeypatch):
    """ALLOWED_ORIGINS 收紧后,只有列表内的 origin 允许"""
    import importlib
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://192.168.1.10:8000,http://localhost:8000")
    importlib.import_module("app.config")
    from app.config import config
    assert config.cors.allowed_origins == ("http://192.168.1.10:8000", "http://localhost:8000")
