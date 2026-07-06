"""WebSocket 命名 + 存档 测试"""
import sys
import types
import os
import tempfile
import asyncio
import numpy as np
from unittest.mock import AsyncMock, MagicMock

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


def test_process_speech_segment_archives_real_time_offsets(fake_engines, monkeypatch, tmp_path):
    """实时存档应使用会话内真实时间轴,而不是固定写 0.0."""
    client = _make_client(monkeypatch, tmp_path)
    app = client.app

    import app.api.websocket as ws_mod

    asr = MagicMock()
    asr.run_asr = AsyncMock(return_value={
        "text": "第二段内容",
        "words": [{"text": "第", "start": 0.1, "end": 0.2}],
    })
    speaker = MagicMock()
    speaker.extract_feat.return_value = ([0.1] * 192, 1.0)
    speaker.compare_and_identify.return_value = ("Spk_001", 0.95)

    monkeypatch.setattr(ws_mod, "asr_engine", asr)
    monkeypatch.setattr(ws_mod, "get_speaker_engine", lambda: speaker)

    class DummyWebSocket:
        def __init__(self, app):
            self.app = app
            self.sent = []

        async def send_json(self, msg):
            self.sent.append(msg)

    ws = DummyWebSocket(app)
    ctx = ws_mod.SessionContext("test_user")
    audio = (np.ones(16000, dtype=np.float32) * 0.1)
    asyncio.run(
        ws_mod._process_speech_segment(
            ws, ctx, audio, "test_user", 16000, segment_start_time=12.5
        )
    )

    sid = ws._session_id
    segments = app.state.transcript_repo.list_segments(sid)
    assert segments[0]["start_time"] == 12.5
    assert segments[0]["end_time"] == 13.5
    assert segments[0]["words"][0]["start"] == 12.6
