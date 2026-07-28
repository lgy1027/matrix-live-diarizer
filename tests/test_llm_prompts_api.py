"""LLM prompt 持久化 API 测试

对应 app/api/llm.py GET/PUT /v1/llm/prompts + _load_prompts/_save_prompts
- PUT 持久化到 settings_repo(重启不丢)
- GET 返用户改后的值(缺失用默认)
- 未知字段 422
- 非本机 403
"""
from fastapi.testclient import TestClient

from app.api import llm as llm_api
from app.services.llm_prompts import DEFAULT_PROMPTS


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


def _app(values=None):
    from fastapi import FastAPI
    import os
    os.environ["TEST_AUTH_BYPASS"] = "1"  # bypass auth 中间件(prompt PUT 仍要求本机 host)
    app = FastAPI()
    app.state.settings_repo = MemorySettings(values)
    app.include_router(llm_api.router)
    return app


def _client(app):
    # PUT /v1/llm/prompts 端点内查 client.host ∈ 本机,TestClient 默认 testclient 会 403
    return TestClient(app, client=("127.0.0.1", 50000))


def test_get_prompts_returns_defaults_when_no_custom():
    """无自定义时 GET 返默认 prompt(深拷贝,不暴露模块常量)。"""
    client = _client(_app())
    r = client.get("/v1/llm/prompts")
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == set(DEFAULT_PROMPTS.keys())
    assert data["summarize"] == DEFAULT_PROMPTS["summarize"]


def test_put_prompts_persists_to_settings_repo():
    """PUT 写 settings_repo(重启不丢),GET 立即可见。"""
    app = _app()
    client = _client(app)
    custom = {"summarize": "自定义摘要: {max_words}字以内。{transcript}"}
    r = client.put("/v1/llm/prompts", json=custom)
    assert r.status_code == 200
    # 持久化到 settings_repo
    assert app.state.settings_repo.get("llm.prompt.summarize") == custom["summarize"]
    # GET 返回改后的
    r2 = client.get("/v1/llm/prompts")
    assert r2.json()["summarize"] == custom["summarize"]
    # 其它 op 仍是默认
    assert r2.json()["minutes"] == DEFAULT_PROMPTS["minutes"]


def test_get_prompts_reads_persisted_custom_on_new_app():
    """模拟重启:新 app(新 MemorySettings 加载已存值)GET 仍返用户改的。"""
    persisted = {"llm.prompt.summarize": "重启后仍在的摘要模板 {transcript}"}
    app = _app(persisted)  # 新 app,settings_repo 已有持久化值
    client = _client(app)
    r = client.get("/v1/llm/prompts")
    assert r.json()["summarize"] == "重启后仍在的摘要模板 {transcript}"


def test_put_prompts_rejects_unknown_field():
    """未知字段 422,不静默丢弃。"""
    app = _app()
    client = _client(app)
    r = client.put("/v1/llm/prompts", json={"unknown_op": "xxx"})
    assert r.status_code == 422
    assert app.state.settings_repo.values == {}  # 未写入


def test_load_prompts_merges_custom_over_default():
    """_load_prompts:自定义覆盖默认,缺失的用默认补。"""
    repo = MemorySettings({"llm.prompt.minutes": "自定义纪要 {transcript}"})
    prompts = llm_api._load_prompts(repo)
    assert prompts["minutes"] == "自定义纪要 {transcript}"
    assert prompts["summarize"] == DEFAULT_PROMPTS["summarize"]  # 缺失用默认


def test_load_prompts_none_repo_returns_defaults():
    """settings_repo 为 None(异常情况)返默认,不崩。"""
    prompts = llm_api._load_prompts(None)
    assert prompts == DEFAULT_PROMPTS


def test_put_prompts_rejects_non_string_value():
    """非字符串 prompt 值(如 int)422,不写入(防后续 _render_prompt 抛错)。"""
    app = _app()
    client = _client(app)
    r = client.put("/v1/llm/prompts", json={"summarize": 123})
    assert r.status_code == 422
    assert app.state.settings_repo.values == {}  # 未写入
