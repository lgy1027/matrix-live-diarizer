"""WebSocket 命名 + 存档 测试"""
import sys
import types
import os
import tempfile
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_engines(monkeypatch):
    """注入 fake engine 模块，并测试结束后清理。"""
    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "engine.asr_engine", fake_asr)

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

    monkeypatch.setitem(sys.modules, "engine.speaker", fake_speaker_pkg)
    monkeypatch.setitem(sys.modules, "engine.speaker.speaker_factory", fake_factory)
    yield


def _make_client(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))
    from importlib import reload, import_module
    cfg_mod = import_module("app.config")
    reload(cfg_mod)
    app_mod = import_module("app")
    reload(app_mod)
    from fastapi.testclient import TestClient
    return TestClient(app_mod.create_app())


def test_websocket_rename_creates_session(fake_engines, monkeypatch, tmp_path):
    from app.config import config
    monkeypatch.setattr(config.storage, "history_enabled", True)

    client = _make_client(monkeypatch, tmp_path)
    with client.websocket_connect("/ws/v1/stream/test_user") as ws:
        ws.send_json({"action": "rename", "title": "项目周会"})
        # 立即收到 renamed 响应
        resp = ws.receive_json()
        assert resp["type"] == "renamed"
        assert resp["title"] == "项目周会"


def test_websocket_rename_with_no_title(fake_engines, monkeypatch, tmp_path):
    from app.config import config
    monkeypatch.setattr(config.storage, "history_enabled", True)

    client = _make_client(monkeypatch, tmp_path)
    with client.websocket_connect("/ws/v1/stream/test_user2") as ws:
        ws.send_json({"action": "rename", "title": None})
        resp = ws.receive_json()
        assert resp["type"] == "renamed"
