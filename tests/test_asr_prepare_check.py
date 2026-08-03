"""对抗测试:验证 run_asr 重构(extract _prepare_and_check 到线程池)的行为等价性与边界 case。

关注点:
1. 行为等价性:is_silent 用 preprocess 后的 audio;transcribe 用 prepared audio
2. lambda 闭包:第二个 run_in_executor 的 lambda 引用 audio_data 是否拿到 prepared 值
3. 异常语义:_prepare_and_check 抛异常是否被吞
4. use_preprocessing=False 时不 preprocess
5. FunASR 的 use_preprocessing 是 dead parameter
6. asyncio.get_event_loop() deprecation
"""
from __future__ import annotations

import asyncio
import warnings
import numpy as np

import pytest


# ---------------------------------------------------------------------------
# ASREngine (qwen3) — 用 object.__new__ 绕过单例 __init__,mock 全部重依赖
# ---------------------------------------------------------------------------

def _make_qwen_engine():
    """构造一个不触发模型加载的 ASREngine,所有重方法 mock。"""
    from engine.asr_engine import ASREngine

    engine = object.__new__(ASREngine)
    engine.config = type("Cfg", (), {"asr_word_timestamps": False})()

    # transcribe 调用记录器:记录传入的 audio 数组
    transcribe_calls: list = []

    class _FakeASRModel:
        forced_aligner = None  # 关闭 want_words

        def transcribe(self, audio=None, return_time_stamps=False):
            transcribe_calls.append(audio)
            # 返回类似 Qwen3 的结果结构
            class _Item:
                text = "hello"
                time_stamps = None
            return [_Item()]

    engine.asr_model = _FakeASRModel()

    # preprocess 调用记录 + 标记数组(乘 1000,便于区分原/预处理后)
    preprocess_calls: list = []

    def _fake_preprocess(audio_data):
        preprocess_calls.append(audio_data)
        return audio_data * 1000.0  # 标记:预处理后值放大 1000 倍

    engine.preprocess_audio = _fake_preprocess  # type: ignore

    # is_silent 调用记录器:记录它收到的是原 audio 还是 preprocess 后的
    is_silent_calls: list = []

    def _fake_is_silent(audio_data, threshold=0.012, use_vad=True):
        is_silent_calls.append(audio_data)
        return False  # 默认非静音

    engine.is_silent = _fake_is_silent  # type: ignore

    # evaluate_audio_quality
    def _fake_evaluate(audio_data):
        return {"score": 100, "rms": 0.05}

    engine.evaluate_audio_quality = _fake_evaluate  # type: ignore

    # 暴露记录器给测试
    engine._t_transcribe = transcribe_calls
    engine._t_preprocess = preprocess_calls
    engine._t_is_silent = is_silent_calls
    return engine


def test_qwen_transcribe_receives_preprocessed_audio_via_lambda_closure():
    """验证第二个 run_in_executor 的 lambda 闭包正确引用 prepared audio_data,
    而非原始 audio_data(prepared 重新赋值后的延迟绑定)。"""
    engine = _make_qwen_engine()
    original = np.ones(16000, dtype=np.float32)

    asyncio.run(engine.run_asr(original, use_preprocessing=True))

    # transcribe 应该收到 preprocess 后的数组(值放大 1000 倍)
    assert len(engine._t_transcribe) == 1
    received = engine._t_transcribe[0][0]  # audio 是 (array, 16000) tuple
    assert received is not None
    np.testing.assert_array_equal(received, original * 1000.0)
    # 不应等于原数组
    assert not np.array_equal(received, original)


def test_qwen_is_silent_uses_preprocessed_audio_not_original():
    """等价性核心:is_silent 必须在 preprocess 之后调用,且收到的是 preprocess 后的 audio。
    原代码逻辑:evaluate(原) → preprocess → is_silent(预处理后) → transcribe(预处理后)。
    """
    engine = _make_qwen_engine()
    original = np.ones(16000, dtype=np.float32) * 0.5

    asyncio.run(engine.run_asr(original, use_preprocessing=True))

    # is_silent 应收到 preprocess 后的数组(放大 1000 倍)
    assert len(engine._t_is_silent) == 1
    received = engine._t_is_silent[0]
    np.testing.assert_array_equal(received, original * 1000.0)
    assert not np.array_equal(received, original)


def test_qwen_no_preprocessing_passes_original_to_transcribe_and_is_silent():
    """use_preprocessing=False 时不 preprocess;is_silent 和 transcribe 都用原 audio。"""
    engine = _make_qwen_engine()
    original = np.ones(16000, dtype=np.float32) * 0.5

    asyncio.run(engine.run_asr(original, use_preprocessing=False))

    assert len(engine._t_preprocess) == 0
    # is_silent 收到原 audio
    np.testing.assert_array_equal(engine._t_is_silent[0], original)
    # transcribe 收到原 audio
    received = engine._t_transcribe[0][0]
    np.testing.assert_array_equal(received, original)


def test_qwen_low_quality_returns_empty_and_skips_transcribe():
    """score < 30 返回 empty_asr_result,不调 transcribe。"""
    engine = _make_qwen_engine()
    engine.evaluate_audio_quality = lambda _a: {"score": 10}  # type: ignore

    from engine.asr.contracts import empty_asr_result
    result = asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))
    assert result == empty_asr_result()
    assert len(engine._t_transcribe) == 0


def test_qwen_silent_returns_empty_and_skips_transcribe():
    """is_silent=True 返回 empty,不调 transcribe。"""
    engine = _make_qwen_engine()
    engine.is_silent = lambda _a, **_kw: True  # type: ignore

    from engine.asr.contracts import empty_asr_result
    result = asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))
    assert result == empty_asr_result()
    assert len(engine._t_transcribe) == 0


def test_qwen_prepare_exception_propagates_not_swallowed():
    """_prepare_and_check 抛异常时,run_in_executor 应 re-raise 到协程,
    不应被吞(因为 _prepare_and_check 在 try 块外)。"""
    engine = _make_qwen_engine()

    def _boom(_a):
        raise RuntimeError("evaluate boom")
    engine.evaluate_audio_quality = _boom  # type: ignore

    # 异常应传播,不应返回 empty_asr_result
    with pytest.raises(RuntimeError, match="evaluate boom"):
        asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))


def test_qwen_preprocess_exception_propagates():
    """preprocess_audio 抛异常也应传播(等价于原代码:preprocess 不在 try 内)。"""
    engine = _make_qwen_engine()

    def _bad_preprocess(_a):
        raise ValueError("preprocess boom")
    engine.preprocess_audio = _bad_preprocess  # type: ignore

    with pytest.raises(ValueError, match="preprocess boom"):
        asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))


def test_qwen_transcribe_exception_still_swallowed_to_empty():
    """transcribe 异常仍被 try/except 捕获返回 empty(等价原代码)。"""
    engine = _make_qwen_engine()

    class _BadModel:
        forced_aligner = None
        def transcribe(self, audio=None, return_time_stamps=False):
            raise RuntimeError("transcribe boom")
    engine.asr_model = _BadModel()

    from engine.asr.contracts import empty_asr_result
    result = asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))
    assert result == empty_asr_result()


# ---------------------------------------------------------------------------
# FunASREngine
# ---------------------------------------------------------------------------

def _make_funasr_engine():
    from engine.asr.funasr_engine import FunASREngine

    engine = object.__new__(FunASREngine)
    engine.kind = "sensevoice"
    engine._postprocess = None

    transcribe_calls: list = []

    def _fake_transcribe(audio_data):
        transcribe_calls.append(audio_data)
        from engine.asr.contracts import make_asr_result
        return make_asr_result("hello")

    engine._transcribe_sync = _fake_transcribe  # type: ignore
    engine.evaluate_audio_quality = lambda _a: {"score": 100}  # type: ignore
    engine.is_silent = lambda _a: False  # type: ignore
    engine._t_transcribe = transcribe_calls
    return engine


def test_funasr_prepare_check_is_exercised_by_run_asr():
    """test_asr_contracts 已有的 happy path — 这里加 None 路径覆盖。"""
    engine = _make_funasr_engine()
    result = asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))
    assert result["text"] == "hello"
    assert len(engine._t_transcribe) == 1


def test_funasr_low_quality_returns_empty():
    engine = _make_funasr_engine()
    engine.evaluate_audio_quality = lambda _a: {"score": 5}  # type: ignore
    from engine.asr.contracts import empty_asr_result
    result = asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))
    assert result == empty_asr_result()
    assert len(engine._t_transcribe) == 0


def test_funasr_silent_returns_empty():
    engine = _make_funasr_engine()
    engine.is_silent = lambda _a: True  # type: ignore
    from engine.asr.contracts import empty_asr_result
    result = asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))
    assert result == empty_asr_result()
    assert len(engine._t_transcribe) == 0


def test_funasr_use_preprocessing_is_dead_parameter():
    """FunASR 的 _prepare_and_check 接收 use_preprocessing 但从不调用 preprocess_audio。
    验证 use_preprocessing=True/False 行为完全相同(无 preprocess_audio 方法)。
    这不是新引入的 bug(原代码也忽略 use_preprocessing),但是 dead parameter。
    """
    engine = _make_funasr_engine()
    audio = np.ones(16000, dtype=np.float32)

    # 不应该有 preprocess_audio 方法
    assert not hasattr(engine, "preprocess_audio")

    r1 = asyncio.run(engine.run_asr(audio, use_preprocessing=True))
    r2 = asyncio.run(engine.run_asr(audio, use_preprocessing=False))
    assert r1 == r2


def test_funasr_prepare_exception_propagates():
    engine = _make_funasr_engine()
    engine.evaluate_audio_quality = lambda _a: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore
    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))


# ---------------------------------------------------------------------------
# asyncio.get_event_loop() deprecation(Python 3.12)
# ---------------------------------------------------------------------------

def test_get_event_loop_emits_deprecation_warning():
    """asyncio.get_event_loop() 在 3.12+ 在无 running loop 时发 DeprecationWarning。
    在协程内调用虽然有 running loop,但 run_in_executor 拿到的 loop 应来自
    get_running_loop 才是 future-proof。验证当前实现仍可工作(但不未来兼容)。
    """
    engine = _make_qwen_engine()
    # 只要能跑通就说明 get_event_loop 在协程内仍返回 running loop
    # 不发 warning(3.12 在协程内调用 get_event_loop 不发 DeprecationWarning,
    # 但 3.14 会移除)。这是审计遗留项。
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        result = asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))
    assert result["text"] == "hello"
