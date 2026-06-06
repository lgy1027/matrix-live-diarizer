"""Exports API 测试 — 用 sys.modules mock 绕过真实引擎加载"""
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

    # fake engine.asr_engine
    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    sys.modules["engine.asr_engine"] = fake_asr

    # fake engine.speaker（含 speaker_factory）
    fake_speaker_pkg = types.ModuleType("engine.speaker")
    fake_speaker_pkg.__path__ = []  # 让它表现为包
    # 包级别也暴露 get_speaker_engine / get_engine_info（被 app/__init__.py 使用）
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
    """恢复原始 sys.modules 状态"""
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod


@pytest.fixture
def client(tmp_path):
    """每个测试用独立的 app，避免状态污染 + 不污染其他测试的 sys.modules"""
    saved = _install_fake_engines()
    try:
        os.environ["STORAGE_DB_PATH"] = str(tmp_path / "test.db")
        # reload config (用 import_module 拿到真正的模块对象,
        # 因为 app/__init__.py 里 `from app.config import config`
        # 会把 app.config 这个名字覆盖为 AppConfig 实例)
        cfg_mod = importlib.import_module("app.config")
        importlib.reload(cfg_mod)
        app_mod = importlib.import_module("app")
        importlib.reload(app_mod)
        from fastapi.testclient import TestClient
        yield TestClient(app_mod.create_app())
    finally:
        _restore_fake_engines(saved)


def test_export_srt_endpoint(client):
    app = client.app
    sid = app.state.transcript_repo.create_session(
        source="upload", original_filename="a.wav", duration_sec=5.0, title="test"
    )
    app.state.transcript_repo.insert_segment(
        sid, segment_index=0, text="你好", start_time=0.0, end_time=1.5
    )

    resp = client.get(f"/v1/exports/{sid}?format=srt")
    assert resp.status_code == 200
    assert "00:00:00,000 --> 00:00:01,500" in resp.text
    assert "你好" in resp.text
    assert "attachment" in resp.headers["content-disposition"]


def test_export_invalid_format(client):
    resp = client.get("/v1/exports/any?format=xml")
    # FastAPI 的 Query(pattern=...) 触发 Pydantic 验证,返回 422
    assert resp.status_code == 422


def test_export_nonexistent_session(client):
    resp = client.get("/v1/exports/nonexistent?format=srt")
    assert resp.status_code == 404
