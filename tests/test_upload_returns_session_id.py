"""Upload API 返回 session_id 测试"""
import sys
import types
import os
import tempfile
import importlib
import numpy as np
import soundfile as sf
from unittest.mock import MagicMock, AsyncMock


def _install_fake_engines():
    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    sys.modules["engine.asr_engine"] = fake_asr

    fake_speaker_pkg = types.ModuleType("engine.speaker")
    fake_speaker_pkg.__path__ = []
    fake_speaker_pkg.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_speaker_pkg.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})

    # 补全子模块防止污染后续 test_base_engine 的 import
    fake_base = types.ModuleType("engine.speaker.base_engine")
    fake_base.BaseSpeakerEngine = MagicMock
    fake_base.logger = MagicMock()  # 防止 test_logging 失败
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
from app import create_app


def _make_client():
    tmp = tempfile.mkdtemp()
    os.environ["STORAGE_DB_PATH"] = os.path.join(tmp, "test.db")
    os.environ["UPLOAD_CHUNK_DURATION"] = "30"
    cfg_mod = importlib.import_module("app.config")
    importlib.reload(cfg_mod)
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    return TestClient(app_mod.create_app())


def _make_wav(path: str, duration_sec: float = 1.0, sr: int = 16000):
    """生成测试 wav"""
    samples = int(duration_sec * sr)
    audio = np.zeros(samples, dtype=np.float32)
    sf.write(path, audio, sr)


def test_upload_creates_session_in_history(monkeypatch, tmp_path):
    from app.config import config
    monkeypatch.setattr(config.storage, "history_enabled", True)

    wav_path = tmp_path / "test.wav"
    _make_wav(str(wav_path), duration_sec=0.5)

    client = _make_client()

    # 让 asr_engine.run_asr 返回 awaitable（AsyncMock）
    import app.api.upload as upload_mod
    asr_mock = MagicMock()
    asr_mock.run_asr = AsyncMock(return_value="测试文本")
    monkeypatch.setattr(upload_mod, "asr_engine", asr_mock)

    with open(wav_path, "rb") as f:
        resp = client.post(
            "/v1/upload",
            files={"file": ("test.wav", f, "audio/wav")},
            params={"enable_diarization": "false"},
        )
    data = resp.json()
    assert data["status"] == "success"
    assert data.get("session_id") is not None
