"""Pytest 全局 fixture — 防 sys.modules / os.environ 污染 + 注入假重依赖

3 件事:
1. 注入假 torch / modelscope / torchaudio / librosa / scipy / soundfile
   让真实 import engine.speaker.campplus_engine 等不报 ModuleNotFoundError
   (这些包在 CI 环境不装,体积大、下载慢)
2. 隔离 sys.modules:某些测试 (test_llm_api) 注入假 engine.* 模块
   测试结束后清掉,防污染后续 test_base_engine
3. 隔离 os.environ:多个测试用 os.environ["..."] = ... 直接赋值
   不会自动还原,清掉 STORAGE_DB_PATH 等关键 key
"""
import importlib.machinery
import os
import sys
import tempfile
import types
import pytest

# 测试统一把 MODELS_DIR 指到 tmp,避免 resolve_modelscope 把真实缓存物化到
# 仓库 ./models/(污染 + 慢)。必须在 app.config 被 import 前设置。
os.environ.setdefault("MODELS_DIR", os.path.join(tempfile.gettempdir(), "matrix_test_models"))


def _make_spec(name):
    """构造一个真实的 ModuleSpec,避免 Python 内部属性访问错误"""
    spec = importlib.machinery.ModuleSpec(name, None, is_package=True)
    return spec

# 重依赖(下载大、CI 不装)— 注入空 ModuleType 即可
_HEAVY_DEPS = (
    "torch",
    "torch.nn",
    "torch.hub",
    "torchaudio",
    "modelscope",
    "qwen_asr",
    "librosa",
    "soundfile",
    "scipy",
    "scipy.signal",
)


def _install_fake_heavy_deps():
    """在 import 引擎前注入假重依赖,避免 ModuleNotFoundError

    对已知用到的子模块 (torch.cuda / torch.hub / torch.backends / scipy.signal)
    创建 fake sub-module;其它属性返回 _noop sentinel,这样函数调用不出错。
    """
    def _noop(*a, **kw):
        return None

    class _Sentinel:
        """任何属性访问/调用都返回 _noop,可作函数用"""
        def __getattr__(self, name):
            return self
        def __call__(self, *a, **kw):
            return None
        def __iter__(self):
            return iter([])
        def __bool__(self):
            return False
        def __or__(self, other):
            return self
        def __ror__(self, other):
            return self
        def __and__(self, other):
            return self
        __hash__ = None
        def __repr__(self):
            return "<fake>"

    _NOOP = _Sentinel()

    def _make(name, attrs=None, submodules=None):
        m = types.ModuleType(name)
        m.__spec__ = _make_spec(name)
        for k, v in (attrs or {}).items():
            setattr(m, k, v)
        # 注册已知子模块,子模块自身 __getattr__ 也回退到 _NOOP
        for sub in (submodules or []):
            sub_full = f"{name}.{sub}"
            sub_mod = types.ModuleType(sub_full)
            sub_mod.__spec__ = _make_spec(sub_full)
            # 让子模块任意子属性都返回 _NOOP
            def _sub_getattr(_mod, name):
                if name.startswith("_"):
                    raise AttributeError(name)
                return _NOOP
            sub_mod.__getattr__ = _sub_getattr.__get__(sub_mod, type(sub_mod))
            setattr(m, sub, sub_mod)
            sys.modules[sub_full] = sub_mod
        sys.modules[name] = m
        return m

    # 顶层模块
    _make("modelscope", attrs={
        "snapshot_download": (lambda *a, **kw: "/tmp/fake_model"),
        "Model": _NOOP,
    }, submodules=["models"])  # for `from modelscope.models import Model`

    # 单独覆盖 modelscope.models: 需要 Model.from_pretrained 返回有 eval() 的对象
    _models_mod = sys.modules["modelscope.models"]
    _FakeModel = type(
        "Model",
        (),
        {
            "from_pretrained": classmethod(lambda cls, *a, **kw: _NOOP),
            "eval": lambda self: None,
        }
    )
    _models_mod.Model = _FakeModel
    _make("qwen_asr", attrs={
        "Qwen3ASRModel": _NOOP,
    })
    _make("torchaudio")
    _make("transformers", attrs={
        "logging": _NOOP,  # `from transformers import logging`
    })

    # torch: 给 sub-module 让 torch.cuda / torch.hub / torch.backends 等可用
    _make("torch", attrs={
        "no_grad": _noop,
        "FloatTensor": _NOOP,
        "bfloat16": _NOOP,
        "float32": _NOOP,
    }, submodules=["cuda", "hub", "backends", "nn"])

    # librosa: 真实 load 会读 wav 文件,CI 没装 librosa。
    # 用一个能"接受路径返回 (audio, sr) tuple"的 fake,让 upload 测试能跑过
    def _fake_librosa_load(path, sr=None, *a, **kw):
        # 真实写测试 wav 后,这里返回 (audio_array, sr) tuple
        import numpy as np
        # 假装是 1 秒 16kHz 单声道静音
        return np.zeros(sr or 16000, dtype=np.float32), sr or 16000

    _make("librosa", attrs={
        "load": _fake_librosa_load,
        "resample": _noop,
    })

    # soundfile: write 真的写 wav 头(测试读 wav 头验证),read 返空
    def _fake_sf_write(path, data, sr, *a, **kw):
        import wave
        import struct
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            # data 是 float32 [-1, 1],转 int16
            int_data = (data * 32767).astype("int16").tobytes()
            w.writeframes(int_data)
        return path

    def _fake_sf_read(path, *a, **kw):
        import numpy as np
        import wave
        with wave.open(path, "rb") as w:
            sr = w.getframerate()
            n = w.getnframes()
            data = np.frombuffer(w.readframes(n), dtype="int16").astype("float32") / 32767
        return data, sr

    _make("soundfile", attrs={
        "read": _fake_sf_read,
        "write": _fake_sf_write,
    })

    # scipy: signal.butter / signal.sosfilt
    _make("scipy", submodules=["signal"])


# 常规单元测试使用轻量替身；真实冒烟测试必须显式退出替身模式。
if os.environ.get("MATRIX_TEST_REAL_DEPENDENCIES") != "1":
    _install_fake_heavy_deps()


_FAKE_MODULES = (
    "engine.asr_engine",
    "engine.speaker",
    "engine.speaker.base_engine",
    "engine.speaker.speaker_factory",
)

_ENV_KEYS_TO_ISOLATE = (
    "STORAGE_DB_PATH",
    "LLM_ENABLED",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_TIMEOUT_SEC",
    "LLM_ALLOWED_HOSTS",
    "LLM_ALLOW_PUBLIC",
    "LLM_MOCK",
    "ASR_ENGINE",
    "ASR_DEVICE",
    "ASR_LOAD_TIMEOUT_SEC",
    "JWT_SECRET",
    "UPLOAD_CHUNK_DURATION",
)
# 注意:MODELS_DIR 不在此列表 — 它由 conftest 模块级 setdefault 设到 tmp,
# 常驻所有测试,让 resolve_modelscope 写 tmp 而非仓库 ./models/。


@pytest.fixture(autouse=True)
def _clean_fake_engine_modules():
    """每个测试**前后**都清 fake engine.* 模块,确保互不污染。

    之前只 yield 后清理,导致第一个测试的 fake 残留到第二个测试。
    """
    # 测试前:清掉残留的 fake
    for mod_name in _FAKE_MODULES:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        mod_file = getattr(mod, "__file__", None) or ""
        if "matrix-live-diarizer" not in mod_file:
            del sys.modules[mod_name]
    yield
    # 测试后:同样清
    for mod_name in _FAKE_MODULES:
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        mod_file = getattr(mod, "__file__", None) or ""
        if "matrix-live-diarizer" not in mod_file:
            del sys.modules[mod_name]


@pytest.fixture(autouse=True)
def _isolate_os_environ():
    """隔离 os.environ:测试前清掉关键 key,测试后恢复。"""
    saved = {k: os.environ.get(k) for k in _ENV_KEYS_TO_ISOLATE}
    for k in _ENV_KEYS_TO_ISOLATE:
        os.environ.pop(k, None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(autouse=True)
def _enable_auth_test_bypass():
    """Bug-79: 鉴权中间件在测试模式放行,避免改所有测试 client fixture

    机制: 设环境变量 TEST_AUTH_BYPASS=1,AuthMiddleware 跳过鉴权。
    这样新加的鉴权不会破坏现有 53 个测试。
    """
    os.environ["TEST_AUTH_BYPASS"] = "1"
    yield
    os.environ.pop("TEST_AUTH_BYPASS", None)


@pytest.fixture(autouse=True)
def _reset_ws_connect_rate_limit():
    """清理 realtime_auth 的进程级 WS 连接限流计数器,防跨测试污染
    (大量 WS 测试共用 'testclient' host 会累积触发限流)。"""
    try:
        from app.services import realtime_auth
        realtime_auth._ws_connect_log.clear()
    except Exception:
        pass
    yield
    try:
        from app.services import realtime_auth
        realtime_auth._ws_connect_log.clear()
    except Exception:
        pass
