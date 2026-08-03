from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import llm as llm_api
from app.config import LLMConfig
from app.services.llm_gateway import EndpointSecurityError


class MemorySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)

    def all_keys(self):
        return list(self.values)


def test_plaintext_database_api_key_is_ignored(monkeypatch):
    repo = MemorySettings({"llm.api_key": "stale-plaintext", "llm.enabled": "true"})
    monkeypatch.setattr(
        llm_api,
        "_env_llm_cfg",
        lambda: LLMConfig(api_key="env-secret"),
    )

    cfg, _, _ = llm_api._effective_llm_cfg(repo)

    assert cfg.api_key == "env-secret"


def test_settings_endpoint_rejects_persisting_api_key():
    app = FastAPI()
    app.state.settings_repo = MemorySettings()
    app.include_router(llm_api.router)
    client = TestClient(app)

    response = client.put(
        "/v1/llm/settings",
        json={
            "provider": "openai-compatible",
            "enabled": True,
            "endpoint": "https://example.com/v1",
            "model": "example",
            "api_key": "secret",
            "allow_public": True,
        },
    )

    assert response.status_code == 400
    assert app.state.settings_repo.values == {}


def _llm_app(values=None):
    app = FastAPI()
    app.state.settings_repo = MemorySettings(values)
    app.include_router(llm_api.router)
    return app


def test_status_is_passive_and_does_not_construct_gateway(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_BYPASS", "1")
    monkeypatch.setattr(
        llm_api,
        "_env_llm_cfg",
        lambda: LLMConfig(
            enabled=True,
            endpoint="http://127.0.0.1:11434/v1",
            model="test-model",
        ),
    )

    class UnexpectedGateway:
        def __init__(self, _cfg):
            raise AssertionError("GET /v1/llm/status must not create a gateway")

    monkeypatch.setattr(llm_api, "LLMGateway", UnexpectedGateway)
    response = TestClient(_llm_app()).get("/v1/llm/status")

    assert response.status_code == 200
    assert response.json()["available"] is None
    assert response.json()["last_tested_at"] is None


def test_explicit_test_calls_probe_once_and_status_reuses_result(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_BYPASS", "1")
    monkeypatch.setattr(
        llm_api,
        "_env_llm_cfg",
        lambda: LLMConfig(
            enabled=True,
            endpoint="http://127.0.0.1:11434/v1",
            model="test-model",
        ),
    )
    calls = {"count": 0}

    class FakeGateway:
        def __init__(self, _cfg):
            pass

        async def is_available(self):
            calls["count"] += 1
            return True

    monkeypatch.setattr(llm_api, "LLMGateway", FakeGateway)
    client = TestClient(_llm_app())

    tested = client.post("/v1/llm/test")
    status = client.get("/v1/llm/status")

    assert tested.status_code == 200
    assert tested.json()["available"] is True
    assert tested.json()["last_tested_at"]
    assert status.json()["available"] is True
    assert status.json()["last_tested_at"] == tested.json()["last_tested_at"]
    assert calls["count"] == 1


def test_connection_test_does_not_expose_endpoint_security_details(monkeypatch):
    monkeypatch.setenv("TEST_AUTH_BYPASS", "1")
    monkeypatch.setattr(
        llm_api,
        "_env_llm_cfg",
        lambda: LLMConfig(
            enabled=True,
            endpoint="http://127.0.0.1:11434/v1",
            model="test-model",
        ),
    )

    class UnsafeGateway:
        def __init__(self, _cfg):
            pass

        async def is_available(self):
            raise EndpointSecurityError("resolved host contains internal-secret.example")

    monkeypatch.setattr(llm_api, "LLMGateway", UnsafeGateway)
    response = TestClient(_llm_app()).post("/v1/llm/test")

    assert response.status_code == 200
    assert response.json()["error"] == "LLM endpoint 配置不安全"
    assert "internal-secret" not in response.text


def test_saving_settings_clears_probe_without_testing(monkeypatch):
    app = _llm_app()
    app.state.llm_probe_result = {"available": True}

    class UnexpectedGateway:
        def __init__(self, _cfg):
            raise AssertionError("saving settings must not create a gateway")

    monkeypatch.setattr(llm_api, "LLMGateway", UnexpectedGateway)
    response = TestClient(app).put(
        "/v1/llm/settings",
        json={
            "provider": "ollama",
            "enabled": True,
            "endpoint": "http://127.0.0.1:11434/v1",
            "model": "test-model",
            "allow_public": False,
        },
    )

    assert response.status_code == 200
    assert app.state.llm_probe_result is None
