"""LLM API 测试 — 用 monkeypatch 切换 config.llm.enabled / mock"""
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
    fake_speaker_pkg.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})

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
    """重建 config + app，并把 monkeypatch fixture 重新应用到新 config 上"""
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("STORAGE_DB_PATH", os.path.join(tmp, "test.db"))
    cfg_mod = importlib.import_module("app.config")
    importlib.reload(cfg_mod)
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    return TestClient(app_mod.create_app()), cfg_mod.config


def test_llm_status_disabled(monkeypatch):
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", False)
    monkeypatch.setattr(config.llm, "mock", False)

    resp = client.get("/v1/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["available"] is False


def test_llm_status_enabled_mock(monkeypatch):
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", True)
    monkeypatch.setattr(config.llm, "mock", True)

    resp = client.get("/v1/llm/status")
    data = resp.json()
    assert data["enabled"] is True
    assert data["available"] is True
    assert data["mock"] is True


def test_summarize_returns_503_when_disabled(monkeypatch):
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", False)

    resp = client.post("/v1/llm/summarize", json={"session_id": "any"})
    assert resp.status_code == 503


def test_summarize_works_in_mock_mode(monkeypatch):
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", True)
    monkeypatch.setattr(config.llm, "mock", True)

    app = client.app
    sid = app.state.transcript_repo.create_session(source="websocket")
    app.state.transcript_repo.insert_segment(sid, 0, "hi", 0.0, 1.0)

    resp = client.post("/v1/llm/summarize", json={"session_id": sid})
    assert resp.status_code == 200
    data = resp.json()
    assert "MOCK" in data["text"]


def test_get_prompts(monkeypatch):
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", False)
    resp = client.get("/v1/llm/prompts")
    assert resp.status_code == 200
    data = resp.json()
    assert "summarize" in data
    assert "action_items" in data
    assert "minutes" in data
