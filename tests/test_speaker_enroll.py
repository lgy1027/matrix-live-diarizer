"""回归测试:POST /v1/speakers/enroll 端到端

之前前端"Enroll New Voice"按钮无效(只 toast 提示),后端无 API。
加 enroll 端点 + add_speaker 公开方法让用户能主动注册声纹。
"""
import sys
import types
import os
import tempfile
import importlib
import numpy as np
import soundfile as sf
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
    return TestClient(app_mod.create_app())


def _make_wav(seconds: float = 2.0) -> bytes:
    """生成一个测试 wav 文件字节流"""
    import io
    sr = 16000
    t = np.linspace(0, seconds, int(sr * seconds))
    audio = (np.sin(2 * np.pi * 440 * t) * 0.3).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format='WAV')
    buf.seek(0)
    return buf


# ========== add_speaker 单元测试 ==========

def _make_engine_with_collection():
    """创建带 fake collection 的具体子类实例"""
    from engine.speaker.base_engine import BaseSpeakerEngine

    class _FakeSubEngine(BaseSpeakerEngine):
        """具体子类,实现所有 abstract method(不调 super().__init__)"""

        def __init__(self):
            # 不调 super().__init__,只设 collection
            self.collection = MagicMock()
            self.emb_buffer = MagicMock()
            self.chroma_client = MagicMock()
            self.model = MagicMock()
            self.pending_speakers = MagicMock()

        def extract_feat(self, audio_data):
            return (np.zeros(192, dtype=np.float32), 1.0)

        def compare_and_identify(self, current_emb, client_id, audio_duration=0):
            return "Unknown"

        @property
        def _model_name(self):
            return "FakeTestEngine"

    engine = _FakeSubEngine()
    return engine, engine.collection


def test_add_speaker_rejects_invalid_speaker_id():
    """speaker_id 不匹配 Spk_xxx 格式应被拒"""
    engine, fake_collection = _make_engine_with_collection()
    emb = np.zeros(192, dtype=np.float32)

    for bad_id in ["evil", "Spk_", "Spk_a" * 100, "user_001", ""]:
        assert engine.add_speaker(bad_id, emb) is False
    # upsert 不应被调
    fake_collection.upsert.assert_not_called()


def test_add_speaker_strips_control_chars_in_name():
    """add_speaker 内部应剥除 name 中的控制字符"""
    engine, fake_collection = _make_engine_with_collection()
    captured = {}
    fake_collection.upsert = lambda **kw: captured.update(kw)
    emb = np.zeros(192, dtype=np.float32)

    # 即使外部没剥,add_speaker 也应兜底
    engine.add_speaker("Spk_test_001", emb, name="evil\r\nX-Injected")
    assert "\r" not in captured["metadatas"][0]["name"]
    assert "\n" not in captured["metadatas"][0]["name"]


def test_add_speaker_name_falls_back_to_id():
    """name 全是控制字符时,降级到 speaker_id"""
    engine, fake_collection = _make_engine_with_collection()
    captured = {}
    fake_collection.upsert = lambda **kw: captured.update(kw)
    emb = np.zeros(192, dtype=np.float32)

    engine.add_speaker("Spk_fallback", emb, name="\r\n\r\n")
    assert captured["metadatas"][0]["name"] == "Spk_fallback"


# ========== enroll 端点测试 ==========

def test_enroll_endpoint_rejects_short_audio(monkeypatch):
    """音频 < 0.5s 应 400(通过 monkeypatch librosa.load 返短数组测)"""
    import librosa
    client = _make_client(monkeypatch)
    # conftest 默认 fake librosa.load 返 1s, 这里强制返 0.1s 触发 duration < 0.5
    monkeypatch.setattr(
        librosa, "load",
        lambda path, sr=None, *a, **kw: (np.zeros(800, dtype=np.float32), 16000),
    )
    wav_buf = _make_wav(0.1)
    resp = client.post(
        "/v1/speakers/enroll?speaker_id=Spk_short",
        files={"file": ("test.wav", wav_buf, "audio/wav")},
    )
    assert resp.status_code == 400
    assert "太短" in resp.json()["detail"]


def test_enroll_endpoint_rejects_unsupported_ext(monkeypatch):
    """不支持的扩展名应 400"""
    client = _make_client(monkeypatch)
    resp = client.post(
        "/v1/speakers/enroll?speaker_id=Spk_x",
        files={"file": ("test.txt", b"fake", "text/plain")},
    )
    assert resp.status_code == 400
    assert "不支持" in resp.json()["detail"]


def test_enroll_endpoint_rejects_invalid_speaker_id_format(monkeypatch):
    """speaker_id 不匹配 Spk_xxx 格式应 422"""
    client = _make_client(monkeypatch)
    wav_buf = _make_wav(2.0)
    resp = client.post(
        "/v1/speakers/enroll?speaker_id=bad_format",
        files={"file": ("test.wav", wav_buf, "audio/wav")},
    )
    assert resp.status_code == 422


def test_enroll_endpoint_rejects_empty_file(monkeypatch):
    """空文件应 400"""
    client = _make_client(monkeypatch)
    resp = client.post(
        "/v1/speakers/enroll?speaker_id=Spk_empty",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert resp.status_code == 400


def test_enroll_endpoint_requires_speaker_id(monkeypatch):
    """缺 speaker_id query param 应 422"""
    client = _make_client(monkeypatch)
    wav_buf = _make_wav(2.0)
    resp = client.post(
        "/v1/speakers/enroll",
        files={"file": ("test.wav", wav_buf, "audio/wav")},
    )
    assert resp.status_code == 422


def test_enroll_endpoint_requires_file(monkeypatch):
    """缺 file 字段应 422"""
    client = _make_client(monkeypatch)
    resp = client.post("/v1/speakers/enroll?speaker_id=Spk_nofile")
    assert resp.status_code == 422
