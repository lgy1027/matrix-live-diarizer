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


def test_summarize_returns_200_with_extractive_when_disabled(monkeypatch):
    """LLM 关闭时 summarize 端点返回 200 + source=extractive-fallback"""
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", False)

    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="t")
    app.state.transcript_repo.insert_segment(sid, 0, "今天讨论产品。张三需要做调研。", 0.0, 1.0)

    resp = client.post("/v1/llm/summarize", json={"session_id": sid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "extractive-fallback"
    assert len(data["text"]) > 0


def test_action_items_returns_200_with_extractive_when_disabled(monkeypatch):
    """LLM 关闭时 action-items 端点返回 200 + source=extractive-fallback"""
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", False)
    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="t")
    app.state.transcript_repo.insert_segment(sid, 0, "张三需要下周完成报告。", 0.0, 1.0)

    resp = client.post("/v1/llm/action-items", json={"session_id": sid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "extractive-fallback"
    assert isinstance(data["items"], list)


def test_minutes_returns_200_with_extractive_when_disabled(monkeypatch):
    """LLM 关闭时 minutes 端点返回 200 + extractive"""
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", False)
    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="t")
    app.state.transcript_repo.insert_segment(sid, 0, "今天讨论产品。张三需要做调研。", 0.0, 1.0)

    resp = client.post("/v1/llm/minutes", json={"session_id": sid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "extractive-fallback"
    assert "议题" in data["text"]


def test_status_includes_fallback_field(monkeypatch):
    """status 端点总是返回 fallback 字段"""
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", False)
    resp = client.get("/v1/llm/status")
    data = resp.json()
    assert "fallback" in data
    assert data["fallback"] == "extractive-textrank"


def test_llm_status_unauthenticated_is_minimal_and_does_not_probe(monkeypatch):
    """未鉴权访问 status 不返回 endpoint/model,也不触发 LLM 探活."""
    monkeypatch.delenv("TEST_AUTH_BYPASS", raising=False)
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", True)
    monkeypatch.setattr(config.llm, "endpoint", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(config.llm, "model", "private-model")

    from app.services.llm_gateway import LLMGateway

    async def fail_probe(self):
        raise AssertionError("unauthenticated status must not probe LLM")

    monkeypatch.setattr(LLMGateway, "is_available", fail_probe)

    resp = client.get("/v1/llm/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["available"] is False
    assert data["auth_required"] is True
    assert data["fallback"] == "extractive-textrank"
    assert "endpoint" not in data
    assert "model" not in data


def test_get_llm_settings_uses_env_defaults(monkeypatch):
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", False)
    monkeypatch.setattr(config.llm, "endpoint", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(config.llm, "model", "qwen2.5:1.5b")

    resp = client.get("/v1/llm/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["config_source"] == "env"
    assert data["endpoint"] == "http://127.0.0.1:11434/v1"
    assert data["model"] == "qwen2.5:1.5b"


def test_put_llm_settings_overrides_status(monkeypatch):
    client, _config = _make_client(monkeypatch)
    payload = {
        "provider": "lmstudio",
        "enabled": True,
        "endpoint": "http://127.0.0.1:1234/v1",
        "model": "local-model",
        "api_key": "",
        "allow_public": False,
        "timeout_sec": 12,
        "max_input_tokens": 4096,
        "mock": True,
    }

    resp = client.put("/v1/llm/settings", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["config_source"] == "settings"
    assert data["provider"] == "lmstudio"
    assert data["enabled"] is True
    assert data["endpoint"] == "http://127.0.0.1:1234/v1"
    assert data["model"] == "local-model"

    status = client.get("/v1/llm/status").json()
    assert status["enabled"] is True
    assert status["available"] is True
    assert status["mock"] is True
    assert status["config_source"] == "settings"
    assert status["endpoint"] == "http://127.0.0.1:1234/v1"


def test_summarize_includes_source_field_when_llm(monkeypatch):
    """LLM mock 模式下 source=llm"""
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", True)
    monkeypatch.setattr(config.llm, "mock", True)
    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="t")
    app.state.transcript_repo.insert_segment(sid, 0, "hi", 0.0, 1.0)

    resp = client.post("/v1/llm/summarize", json={"session_id": sid})
    data = resp.json()
    assert data["source"] == "llm"


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


# ========== 回归测试: source 字段必须如实反映调用结果 ==========

def test_summarize_source_honest_when_llm_fails(monkeypatch):
    """回归测试: LLM enabled + _call_llm 失败 → source 必须是 'extractive-fallback'
    不能误标 'llm'(会导致前端不带本地摘要前缀,误导用户)
    """
    from app.services.llm_gateway import LLMGateway, LLMUnavailableError
    
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", True)
    monkeypatch.setattr(config.llm, "mock", False)
    
    # monkeypatch LLMGateway._call_llm 抛错
    async def fake_call(self, prompt):
        raise LLMUnavailableError("forced failure")
    monkeypatch.setattr(LLMGateway, "_call_llm", fake_call)
    # 同时清掉 available cache,避免被前序测试污染
    monkeypatch.setattr(LLMGateway, "is_available", lambda self: False)
    
    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="t")
    app.state.transcript_repo.insert_segment(sid, 0, "今天讨论产品。张三需要做调研。", 0.0, 1.0)
    
    resp = client.post("/v1/llm/summarize", json={"session_id": sid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "extractive-fallback", \
        f"LLM 失败时 source 必须如实,不能谎报 'llm'。实际: {data.get('source')}"
    assert len(data["text"]) > 0


def test_action_items_source_honest_when_llm_fails(monkeypatch):
    """行动项端点同 bug 回归测试"""
    from app.services.llm_gateway import LLMGateway, LLMTimeoutError
    
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", True)
    monkeypatch.setattr(config.llm, "mock", False)
    
    async def fake_call(self, prompt):
        raise LLMTimeoutError("forced timeout")
    monkeypatch.setattr(LLMGateway, "_call_llm", fake_call)
    monkeypatch.setattr(LLMGateway, "is_available", lambda self: False)
    
    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="t")
    app.state.transcript_repo.insert_segment(sid, 0, "张三需要下周完成报告。", 0.0, 1.0)
    
    resp = client.post("/v1/llm/action-items", json={"session_id": sid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "extractive-fallback"
    assert isinstance(data["items"], list)


def test_minutes_source_honest_when_llm_fails(monkeypatch):
    """纪要端点同 bug 回归测试"""
    from app.services.llm_gateway import LLMGateway, LLMModelMissingError
    
    client, config = _make_client(monkeypatch)
    monkeypatch.setattr(config.llm, "enabled", True)
    monkeypatch.setattr(config.llm, "mock", False)
    
    async def fake_call(self, prompt):
        raise LLMModelMissingError("model not loaded")
    monkeypatch.setattr(LLMGateway, "_call_llm", fake_call)
    monkeypatch.setattr(LLMGateway, "is_available", lambda self: False)
    
    app = client.app
    sid = app.state.transcript_repo.create_session(source="upload", title="t")
    app.state.transcript_repo.insert_segment(sid, 0, "今天讨论产品。", 0.0, 1.0)
    
    resp = client.post("/v1/llm/minutes", json={"session_id": sid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "extractive-fallback"
    assert "议题" in data["text"]
