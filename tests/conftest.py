"""Pytest 全局 fixture — 防 sys.modules / os.environ 污染

两类污染源需要隔离:
1. sys.modules 注入:某些测试 (test_llm_api, test_upload_returns_session_id)
   注入假 engine.* 模块绕过 torch/modelscope 依赖,会污染后续 test_base_engine
2. os.environ 直接赋值:多个测试用 os.environ["STORAGE_DB_PATH"] = ...
   而非 monkeypatch.setenv,测试结束**不会**自动还原,污染后续测试

autouse fixture 在每个测试**后**恢复所有污染。
"""
import os
import sys
import pytest

_FAKE_MODULES = (
    "engine.asr_engine",
    "engine.speaker",
    "engine.speaker.base_engine",
    "engine.speaker.speaker_factory",
)

# 多个测试用 os.environ 直接赋值的 key 列表
_ENV_KEYS_TO_ISOLATE = (
    "STORAGE_DB_PATH",
    "LLM_ENABLED",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_TIMEOUT_SEC",
    "LLM_ALLOWED_HOSTS",
    "LLM_ALLOW_PUBLIC",
    "LLM_MOCK",
)


@pytest.fixture(autouse=True)
def _clean_fake_engine_modules():
    """在每个测试**后**清掉 sys.modules 里的 fake engine.* 模块。

    真实模块的 __file__ 在本仓库内;fake 模块没有 __file__ 或不是源码。
    """
    yield  # 先跑测试
    for mod_name in _FAKE_MODULES:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        mod_file = getattr(mod, "__file__", None) or ""
        if "matrix-live-diarizer" not in mod_file:
            del sys.modules[mod_name]


@pytest.fixture(autouse=True)
def _isolate_os_environ():
    """隔离 os.environ:测试**开始时**清掉关键 key,测试**后**恢复。

    防 test_exports_api / test_sessions_api / test_history_api 等用
    os.environ["..."] = ... 直接赋值的副作用外泄,也防 shell 预设的
    STORAGE_DB_PATH 等污染需要"默认值"的测试。
    """
    # 测试前:记录 shell 设的值,清掉(让测试拿默认值)
    saved = {k: os.environ.get(k) for k in _ENV_KEYS_TO_ISOLATE}
    for k in _ENV_KEYS_TO_ISOLATE:
        os.environ.pop(k, None)
    yield
    # 测试后:恢复
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
