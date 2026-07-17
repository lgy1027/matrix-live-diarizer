"""验证 FastAPI app 启动时正确注入 Database 与 Repository"""
import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def mock_heavy_engines(monkeypatch, tmp_path):
    """避免实际加载 ASR/Speaker 引擎(很慢或环境受限)

    ASREngine / get_speaker_engine 都会触发 scipy/numpy 等重依赖导入。
    即便用 patch 也会先触发目标模块的 import 行为。
    因此在 sys.modules 里预先注入 fake 模块,
    让 _init_engines 内部的 `from engine.asr_engine import ASREngine`
    直接拿到 mock 对象,不再触发真实模块加载。
    """
    monkeypatch.setenv("STORAGE_DB_PATH", str(tmp_path / "test.db"))

    # 重新加载 config 以读取新 env
    from importlib import reload, import_module
    cfg_mod = import_module("app.config")
    reload(cfg_mod)

    # --- 1) 注入 fake engine.asr_engine ---
    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "engine.asr_engine", fake_asr)

    # --- 2) 注入 fake engine.speaker 与 engine.speaker.get_speaker_engine ---
    fake_speaker = types.ModuleType("engine.speaker")
    fake_speaker.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_speaker.get_engine_info = MagicMock(
        return_value={"name": "mock", "model": "mock"}
    )
    monkeypatch.setitem(sys.modules, "engine.speaker", fake_speaker)

    app_mod = import_module("app")
    reload(app_mod)

    yield


def test_app_state_has_db():
    from app import create_app
    app = create_app()
    assert hasattr(app.state, "db")
    assert app.state.db is not None


def test_app_state_has_product_repositories():
    from app import create_app
    app = create_app()
    assert app.state.meeting_repo is not None
    assert app.state.job_repo is not None
    assert app.state.people_repo is not None
    assert not hasattr(app.state, "transcript_repo")


def test_app_state_has_settings_repo():
    from app import create_app
    app = create_app()
    assert hasattr(app.state, "settings_repo")
    assert app.state.settings_repo is not None


def test_app_state_has_asr_engine():
    from app import create_app
    app = create_app()
    assert hasattr(app.state, "asr_engine")
    assert app.state.asr_engine is not None
