"""Pytest 全局 fixture — 防 sys.modules 注入污染

某些测试 (test_llm_api, test_upload_returns_session_id) 用 sys.modules
注入假的 engine.* 模块绕过 torch/modelscope 依赖。但 importlib 缓存
会污染后续测试 (test_base_engine / test_logging 找不到真正的子模块)。

autouse fixture 在每个测试**前**清掉之前注入的 fake 模块,确保隔离。
"""
import sys
import pytest

_FAKE_MODULES = (
    "engine.asr_engine",
    "engine.speaker",
    "engine.speaker.base_engine",
    "engine.speaker.speaker_factory",
)


@pytest.fixture(autouse=True)
def _clean_fake_engine_modules():
    """在每个测试前清掉 sys.modules 里的 fake engine.* 模块。

    注:只清"fake"模块,不动真实模块(我们用 file source 标识)。
    实际做法:在每个测试**开始时**比对当前 sys.modules,
    如果包含 _FAKE_MODULES 但指向的位置不对(非本仓库路径),则 del。
    """
    yield  # 先跑测试
    # 测试结束后清理
    for mod_name in _FAKE_MODULES:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        # 真实模块的 __file__ 在本仓库内;fake 模块没有 __file__ 或不是源码
        mod_file = getattr(mod, "__file__", None) or ""
        if "matrix-live-diarizer" not in mod_file:
            # 是 fake,清掉
            del sys.modules[mod_name]
