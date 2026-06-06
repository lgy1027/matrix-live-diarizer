"""Sessions API 测试 — 用 sys.modules mock 绕过真实引擎加载"""
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
    """注入 fake 引擎模块，返回 saved_state 用于恢复"""
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


def test_get_session_includes_segments_and_stats(client):
    app = client.app
    sid = app.state.transcript_repo.create_session(
        source="websocket", title="周会", duration_sec=10.0
    )
    app.state.transcript_repo.insert_segment(
        sid, 0, "你好", 0.0, 1.5, speaker_id="Spk_001"
    )
    app.state.transcript_repo.insert_segment(
        sid, 1, "hello", 2.0, 4.0, speaker_id="Spk_002"
    )

    resp = client.get(f"/v1/sessions/{sid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["session"]["id"] == sid
    assert data["session"]["title"] == "周会"
    assert len(data["segments"]) == 2
    assert data["statistics"]["speech_duration_sec"] == 3.5
    assert data["statistics"]["turn_taking_count"] == 1


def test_get_session_not_found(client):
    resp = client.get("/v1/sessions/nonexistent")
    assert resp.status_code == 404


def test_update_session_title(client):
    app = client.app
    sid = app.state.transcript_repo.create_session(source="websocket")
    resp = client.patch(f"/v1/sessions/{sid}", json={"title": "新标题"})
    assert resp.status_code == 200
    assert app.state.transcript_repo.get_session(sid)["title"] == "新标题"
