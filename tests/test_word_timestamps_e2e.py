"""字级时间戳端到端集成测试(mock 引擎,无 ASR 模型依赖)

QA 复现:
- 上传路径: POST /v1/upload → 响应 text → SQLite words_json → SRT 字级
- 导出路径: GET /v1/exports/{id}?format=srt|vtt|json

mock 方案:monkeypatch asr_engine.run_asr 返 {text, words} 走 FastAPI TestClient
关键:patch 必须在 _make_client() **之后**(避免 importlib.reload 失效)
"""
import sys
import os
import types
import tempfile
import importlib
import numpy as np
import soundfile as sf
from unittest.mock import MagicMock


# ========== fake engines ==========

def _install_fake_engines():
    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    sys.modules["engine.asr_engine"] = fake_asr

    fake_speaker_pkg = types.ModuleType("engine.speaker")
    fake_speaker_pkg.__path__ = []
    fake_speaker_pkg.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_speaker_pkg.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})

    fake_base = types.ModuleType("engine.speaker.base_engine")
    fake_base.BaseSpeakerEngine = MagicMock
    fake_base.logger = MagicMock()
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


# ========== helpers ==========

def _make_client():
    """创建 TestClient,DB 走 tmp。**重要**:必须在 patch 之前调用"""
    tmp = tempfile.mkdtemp()
    os.environ["STORAGE_DB_PATH"] = os.path.join(tmp, "test.db")
    os.environ["UPLOAD_CHUNK_DURATION"] = "30"
    cfg_mod = importlib.import_module("app.config")
    importlib.reload(cfg_mod)
    app_mod = importlib.import_module("app")
    importlib.reload(app_mod)
    return TestClient(app_mod.create_app())


def _make_wav(path: str, duration_sec: float = 1.0, sr: int = 16000):
    """0.3 振幅 sine,让 ASR 不被判静音"""
    t = np.arange(int(duration_sec * sr)) / sr
    audio = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    sf.write(path, audio, sr)


# 字级 ASR mock 数据
WORD_LEVEL_RESULT = {
    "text": "你好世界",
    "words": [
        {"text": "你", "start": 0.0, "end": 0.6},
        {"text": "好", "start": 0.6, "end": 1.0},
        {"text": "世", "start": 1.0, "end": 1.5},
        {"text": "界", "start": 1.5, "end": 2.0},
    ],
}


def _setup_word_level_mocks(monkeypatch, with_words=True):
    """**必须在 _make_client() 之后调用**。返回 (client, wav_path)"""
    import app.api.upload as upload_mod
    import app.services.transcribe as transcribe_mod

    # ASR mock
    asr_mock = MagicMock()
    async def _run_asr(audio, use_preprocessing=True):
        return WORD_LEVEL_RESULT if with_words else "你好世界"
    asr_mock.run_asr = _run_asr
    upload_mod.asr_engine = asr_mock
    transcribe_mod.asr_engine = asr_mock

    # Speaker mock
    spk_mock = MagicMock()
    spk_mock.extract_feat.return_value = (np.zeros(192, dtype=np.float32), 1.0)
    spk_mock.compare_and_identify.return_value = ("Spk_test", 0.95)
    upload_mod.get_speaker_engine = lambda: spk_mock
    transcribe_mod.get_speaker_engine = lambda: spk_mock


# ========== 端到端测试 ==========

def test_upload_response_text(monkeypatch, tmp_path):
    """upload 响应含 text(来自 mock run_asr)"""
    from app.config import config
    monkeypatch.setattr(config.storage, "history_enabled", True)

    client = _make_client()
    _setup_word_level_mocks(monkeypatch, with_words=True)

    wav_path = tmp_path / "test.wav"
    _make_wav(str(wav_path), duration_sec=2.0)

    resp = client.post(
        "/v1/upload",
        files={"file": ("test.wav", open(wav_path, "rb"), "audio/wav")},
        params={"enable_diarization": "false"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "session_id" in data
    assert data["text"] == "你好世界"


def test_session_detail_includes_words(monkeypatch, tmp_path):
    """session 详情的 segments 包含 words(从 words_json 解析)"""
    from app.config import config
    monkeypatch.setattr(config.storage, "history_enabled", True)

    client = _make_client()
    _setup_word_level_mocks(monkeypatch, with_words=True)

    wav_path = tmp_path / "test.wav"
    _make_wav(str(wav_path), duration_sec=2.0)

    sid = client.post(
        "/v1/upload",
        files={"file": ("test.wav", open(wav_path, "rb"), "audio/wav")},
        params={"enable_diarization": "false"},
    ).json()["session_id"]

    detail = client.get(f"/v1/sessions/{sid}").json()
    segs = detail["segments"]
    assert len(segs) >= 1, f"应该有 segment,实际 0 段"
    first = segs[0]
    assert first.get("words") is not None, f"segments[0].words 缺失,full: {first}"
    words = first["words"]
    assert len(words) == 4, f"应有 4 个字,实际 {len(words)}: {words}"
    assert words[0]["text"] == "你"
    assert words[0]["start"] == 0.0
    assert words[3]["text"] == "界"
    assert words[3]["end"] == 2.0


def test_srt_export_word_level(monkeypatch, tmp_path):
    """SRT 导出走字级路径(每字一块 + 时间偏移)"""
    from app.config import config
    monkeypatch.setattr(config.storage, "history_enabled", True)

    client = _make_client()
    _setup_word_level_mocks(monkeypatch, with_words=True)

    wav_path = tmp_path / "test.wav"
    _make_wav(str(wav_path), duration_sec=2.0)

    sid = client.post(
        "/v1/upload",
        files={"file": ("test.wav", open(wav_path, "rb"), "audio/wav")},
        params={"enable_diarization": "false"},
    ).json()["session_id"]

    srt = client.get(f"/v1/exports/{sid}?format=srt").text
    blocks = srt.strip().split("\n\n")
    assert len(blocks) >= 4, f"应有 4 个 SRT 块,实际 {len(blocks)}:\n{srt}"
    # 时间码验证
    assert "00:00:00,000 --> 00:00:00,600" in srt  # 你
    assert "00:00:00,600 --> 00:00:01,000" in srt  # 好
    assert "00:00:01,500 --> 00:00:02,000" in srt  # 界
    # 段索引
    assert "1\n" in srt and "2\n" in srt and "3\n" in srt and "4\n" in srt


def test_vtt_export_word_level(monkeypatch, tmp_path):
    """VTT 导出走字级路径 + <v Speaker> 标签"""
    from app.config import config
    monkeypatch.setattr(config.storage, "history_enabled", True)

    client = _make_client()
    _setup_word_level_mocks(monkeypatch, with_words=True)

    wav_path = tmp_path / "test.wav"
    _make_wav(str(wav_path), duration_sec=2.0)

    sid = client.post(
        "/v1/upload",
        files={"file": ("test.wav", open(wav_path, "rb"), "audio/wav")},
        params={"enable_diarization": "false"},
    ).json()["session_id"]

    vtt = client.get(f"/v1/exports/{sid}?format=vtt").text
    assert vtt.startswith("WEBVTT")
    cues = [c for c in vtt.split("\n\n") if "-->" in c]
    assert len(cues) >= 4, f"应有 4 个 cue,实际 {len(cues)}:\n{vtt}"
    # enable_diarization=False → upload 写库时 speaker_id=None
    # 所以 VTT 不带 <v Speaker> 标签(未识别说话人)
    # 验证:字本身在 cue 里
    assert "\n你\n" in vtt or "你" in vtt


def test_json_export_session_id(monkeypatch, tmp_path):
    """JSON 导出基本结构(产品级:JSON 导出含 words 是改进点,本次不强制)"""
    from app.config import config
    monkeypatch.setattr(config.storage, "history_enabled", True)

    client = _make_client()
    _setup_word_level_mocks(monkeypatch, with_words=True)

    wav_path = tmp_path / "test.wav"
    _make_wav(str(wav_path), duration_sec=2.0)

    sid = client.post(
        "/v1/upload",
        files={"file": ("test.wav", open(wav_path, "rb"), "audio/wav")},
        params={"enable_diarization": "false"},
    ).json()["session_id"]

    payload = client.get(f"/v1/exports/{sid}?format=json").json()
    assert "session" in payload
    assert payload["session"]["id"] == sid
    assert len(payload["segments"]) >= 1


def test_srt_fallback_when_no_words(monkeypatch, tmp_path):
    """降级:无 words 时 SRT 走 segment 级(1 块整段)"""
    from app.config import config
    monkeypatch.setattr(config.storage, "history_enabled", True)

    client = _make_client()
    _setup_word_level_mocks(monkeypatch, with_words=False)  # 关键:不返 words

    wav_path = tmp_path / "test.wav"
    _make_wav(str(wav_path), duration_sec=2.0)

    sid = client.post(
        "/v1/upload",
        files={"file": ("test.wav", open(wav_path, "rb"), "audio/wav")},
        params={"enable_diarization": "false"},
    ).json()["session_id"]

    srt = client.get(f"/v1/exports/{sid}?format=srt").text
    blocks = srt.strip().split("\n\n")
    assert len(blocks) == 1, f"降级路径应只有 1 块,实际 {len(blocks)}:\n{srt}"
    assert "你好世界" in srt
