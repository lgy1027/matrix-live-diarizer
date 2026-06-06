"""History API 测试 — 用 sys.modules mock 绕过真实引擎加载"""
import os
import sys
import types
import tempfile
import importlib
from unittest.mock import MagicMock

import pytest


_FAKE_NAMES = (
    "engine.asr_engine",
    "engine.speaker",
    "engine.speaker.speaker_factory",
)


def _install_fake_engines():
    """注入 fake 引擎模块，返回 (saved_state, fake_modules)"""
    saved = {name: sys.modules.get(name) for name in _FAKE_NAMES}

    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    sys.modules["engine.asr_engine"] = fake_asr

    fake_speaker_pkg = types.ModuleType("engine.speaker")
    fake_speaker_pkg.__path__ = []
    fake_speaker_pkg.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_speaker_pkg.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})

    fake_factory = types.ModuleType("engine.speaker.speaker_factory")
    fake_factory.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_factory.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})
    fake_factory.get_all_engines = MagicMock(return_value={"current": "mock", "asr": {}, "speakers": {}})
    fake_factory.get_engine_manager = MagicMock(return_value=MagicMock())
    fake_factory.ENGINE_CONFIG = {}
    fake_factory.ASR_CONFIG = {}

    sys.modules["engine.speaker"] = fake_speaker_pkg
    sys.modules["engine.speaker.speaker_factory"] = fake_factory

    return saved


def _restore_fake_engines(saved):
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


@pytest.fixture
def client(tmp_path):
    """每个测试用独立 db 路径 + 独立 app 实例"""
    saved = _install_fake_engines()
    try:
        os.environ["STORAGE_DB_PATH"] = str(tmp_path / "test.db")
        cfg_mod = importlib.import_module("app.config")
        importlib.reload(cfg_mod)
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from fastapi.testclient import TestClient
        yield TestClient(app_mod.create_app())
    finally:
        _restore_fake_engines(saved)


def test_list_history_empty(client):
    resp = client.get("/v1/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_list_history_with_sessions(client):
    app = client.app
    sid = app.state.transcript_repo.create_session(source="websocket", title="周会")
    app.state.transcript_repo.insert_segment(sid, 0, "hi", 0.0, 1.0)

    resp = client.get("/v1/history")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == sid
    assert data["items"][0]["title"] == "周会"


def test_list_history_filter_by_source(client):
    app = client.app
    app.state.transcript_repo.create_session(source="websocket")
    app.state.transcript_repo.create_session(source="upload", original_filename="x.wav")

    resp = client.get("/v1/history?source=upload")
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["source"] == "upload"


def test_list_history_pagination(client):
    app = client.app
    for _ in range(5):
        app.state.transcript_repo.create_session(source="websocket")

    resp = client.get("/v1/history?page=1&page_size=2")
    data = resp.json()
    assert data["total"] == 5
    assert len(data["items"]) == 2


def test_list_history_keyword_search(client):
    app = client.app
    app.state.transcript_repo.create_session(source="upload", original_filename="项目会议.mp3")
    app.state.transcript_repo.create_session(source="upload", original_filename="random.wav")

    resp = client.get("/v1/history?q=项目")
    data = resp.json()
    assert data["total"] == 1


def test_delete_history(client):
    app = client.app
    sid = app.state.transcript_repo.create_session(source="websocket")
    resp = client.delete(f"/v1/history/{sid}")
    assert resp.status_code == 200
    assert app.state.transcript_repo.get_session(sid) is None


def test_delete_nonexistent(client):
    resp = client.delete("/v1/history/nonexistent")
    assert resp.status_code == 404


def test_list_history_empty_string_source_treated_as_none(client):
    """空字符串 source 应被视作未传 (不过滤)，不报 422"""
    app = client.app
    app.state.transcript_repo.create_session(source="websocket")
    app.state.transcript_repo.create_session(source="upload")

    # 之前会 422，现在应返回所有
    resp = client.get("/v1/history?source=&q=")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


def test_list_history_page_size_up_to_200_allowed(client):
    """page_size=200 应被允许（之前 le=100）"""
    app = client.app
    for _ in range(3):
        app.state.transcript_repo.create_session(source="websocket")

    resp = client.get("/v1/history?page_size=200")
    assert resp.status_code == 200


def test_list_history_invalid_source_returns_400(client):
    """非 websocket/upload 的 source 应返回 400 而不是 422"""
    resp = client.get("/v1/history?source=invalid")
    assert resp.status_code == 400
