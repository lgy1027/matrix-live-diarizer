"""ASR 引擎工厂测试."""
import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_asr_manager_state():
    from engine.asr.factory import ASREngineManager
    ASREngineManager.reset()
    yield
    ASREngineManager.reset()


def test_asr_config_engine_default():
    from app.config import AudioConfig
    cfg = AudioConfig.from_env()
    assert cfg.asr_engine == "qwen3"


def test_asr_config_engine_from_env(monkeypatch):
    monkeypatch.setenv("ASR_ENGINE", "SenseVoice")
    from app.config import AudioConfig
    cfg = AudioConfig.from_env()
    assert cfg.asr_engine == "sensevoice"


def test_asr_factory_default_uses_qwen_module(monkeypatch):
    fake_asr = types.ModuleType("engine.asr_engine")
    expected = MagicMock()
    fake_asr.ASREngine = MagicMock(return_value=expected)
    monkeypatch.setitem(sys.modules, "engine.asr_engine", fake_asr)

    from engine.asr.factory import get_asr_engine
    assert get_asr_engine("qwen3") is expected
    fake_asr.ASREngine.assert_called_once()


def test_asr_factory_aliases():
    from engine.asr.factory import get_asr_engine_info
    assert get_asr_engine_info("qwen")["type"] == "qwen3"
    assert get_asr_engine_info("sensevoice-small")["type"] == "sensevoice"
    assert get_asr_engine_info("paraformer-large")["type"] == "paraformer"
    assert get_asr_engine_info("funasr-streaming")["type"] == "paraformer_streaming"


def test_get_all_asr_engines_shape():
    from engine.asr.factory import ASREngineManager
    ASREngineManager.reset()

    from engine.asr import get_all_asr_engines
    data = get_all_asr_engines()
    assert data["current"] == "qwen3"
    assert "qwen3" in data["engines"]
    assert "sensevoice" in data["engines"]
    assert "paraformer" in data["engines"]
    assert "paraformer_streaming" in data["engines"]
    assert "sherpa_onnx" not in data["engines"]
    assert data["switching"] is False
    assert data["pending"] is None
    assert data["cached"] == []


def test_asr_engine_capabilities_are_explicit():
    from engine.asr.factory import get_asr_engine_info

    qwen = get_asr_engine_info("qwen3")
    streaming = get_asr_engine_info("paraformer_streaming")

    assert qwen["capabilities"]["word_timestamps"] is True
    assert qwen["capabilities"]["speaker_diarization"] is False
    assert streaming["capabilities"]["upload"] is True
    assert streaming["capabilities"]["true_streaming"] == "adapter_not_yet"
    assert streaming["capabilities"]["word_timestamps"] is False


def test_asr_engine_capabilities_can_be_overridden(monkeypatch):
    monkeypatch.setenv(
        "ASR_CAPABILITIES_JSON",
        '{"qwen3":{"description":"Custom deployment","capabilities":{"word_timestamps":false,"notes":"本部署关闭字级时间戳"}}}',
    )
    from engine.asr.factory import get_asr_engine_info

    info = get_asr_engine_info("qwen3")
    assert info["customized"] is True
    assert info["description"] == "Custom deployment"
    assert info["capabilities"]["word_timestamps"] is False
    assert info["capabilities"]["speaker_diarization"] is False
    assert info["capabilities"]["notes"] == "本部署关闭字级时间戳"


def test_asr_manager_switch_success_after_load(monkeypatch):
    from engine.asr import factory

    factory.ASREngineManager.reset()
    monkeypatch.setenv("ASR_ENGINE", "qwen3")
    engines = {"qwen3": object(), "sensevoice": object()}

    def fake_load(engine_type=None):
        return engines[engine_type or "qwen3"]

    monkeypatch.setattr(factory, "get_asr_engine", fake_load)
    monkeypatch.setattr(factory.importlib.util, "find_spec", lambda _name: object())

    manager = factory.get_asr_manager()
    assert manager.get_engine() is engines["qwen3"]

    result = manager.switch_engine("sensevoice")
    assert result["success"] is True
    assert result["previous_type"] == "qwen3"
    assert result["engine_type"] == "sensevoice"
    assert manager.current_type == "sensevoice"
    assert manager.get_engine() is engines["sensevoice"]


def test_asr_manager_switch_failure_keeps_current(monkeypatch):
    from engine.asr import factory

    factory.ASREngineManager.reset()
    monkeypatch.setenv("ASR_ENGINE", "qwen3")
    current = object()

    def fake_load(engine_type=None):
        if engine_type == "sensevoice":
            raise RuntimeError("download failed")
        return current

    monkeypatch.setattr(factory, "get_asr_engine", fake_load)
    monkeypatch.setattr(factory.importlib.util, "find_spec", lambda _name: object())

    manager = factory.get_asr_manager()
    assert manager.get_engine() is current

    result = manager.switch_engine("sensevoice")
    assert result["success"] is False
    assert "download failed" in result["error"]
    assert manager.current_type == "qwen3"
    assert manager.get_engine() is current


def test_asr_dependency_status_marks_missing_funasr(monkeypatch):
    from engine.asr import factory

    factory.ASREngineManager.reset()

    def fake_find_spec(name):
        if name == "funasr":
            return None
        return object()

    monkeypatch.setattr(factory.importlib.util, "find_spec", fake_find_spec)

    info = factory.get_asr_engine_info("sensevoice")
    assert info["available"] is False
    assert info["dependency"] == "funasr"
    assert "funasr" in info["install_hint"]


def test_asr_manager_switch_missing_dependency_does_not_load(monkeypatch):
    from engine.asr import factory

    factory.ASREngineManager.reset()
    current = object()

    def fake_find_spec(name):
        if name == "funasr":
            return None
        return object()

    def fake_load(engine_type=None):
        return current

    monkeypatch.setattr(factory.importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setattr(factory, "get_asr_engine", fake_load)

    manager = factory.get_asr_manager()
    assert manager.get_engine() is current

    result = manager.switch_engine("sensevoice")
    assert result["success"] is False
    assert result["dependency"] == "funasr"
    assert manager.current_type == "qwen3"
    assert manager.get_engine() is current
