"""测试 app.services.transcribe 模块 — 抽 transcribe_file 供 upload API 和 seed 脚本复用"""
import asyncio
import pytest
from unittest.mock import MagicMock
from app.services.transcribe import transcribe_file, TranscriptionResult, TranscribedSegment


def _run(coro):
    """asyncio.run helper — 让 sync 测试能跑 async 函数"""
    return asyncio.run(coro)


def test_transcribe_file_returns_dataclass():
    """transcribe_file 返回 TranscriptionResult 数据类,使用真实 extract_feat API"""
    asr_mock = MagicMock()
    asr_mock.run_asr.return_value = "你好世界"
    spk_mock = MagicMock()
    # 真实引擎 extract_feat 返回 (embedding, duration) tuple
    import numpy as np
    spk_mock.extract_feat.return_value = (np.zeros(192, dtype=np.float32), 1.0)

    # 写入至少 0.2 秒音频(避免被判为空,< 0.1s 走空路径)
    import tempfile, soundfile as sf
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, np.random.uniform(-0.1, 0.1, 3200).astype(np.float32), 16000)

    result = _run(transcribe_file(
        audio_path=tmp.name,
        asr_engine=asr_mock,
        spk_engine=spk_mock,
        session_id="sess_1",
        sample_rate=16000,
    ))
    assert isinstance(result, TranscriptionResult)
    assert result.session_id == "sess_1"
    assert len(result.segments) >= 1
    assert result.segments[0].text == "你好世界"
    # speaker_id 由调用方自行识别,transcribe_file 内部不强制填
    assert result.segments[0].speaker_id is None
    assert result.duration_sec > 0
    # 确认调用了真实 API
    spk_mock.extract_feat.assert_called_once()


def test_transcribe_handles_missing_extract_feat():
    """spk_engine 没有 extract_feat 时不挂,降级返回"""
    asr_mock = MagicMock()
    asr_mock.run_asr.return_value = "hello"
    spk_mock = MagicMock(spec=[])  # 没有任何方法

    import tempfile, soundfile as sf
    import numpy as np
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, np.random.uniform(-0.1, 0.1, 3200).astype(np.float32), 16000)

    result = _run(transcribe_file(
        audio_path=tmp.name,
        asr_engine=asr_mock,
        spk_engine=spk_mock,
        session_id="sess_2",
    ))
    assert len(result.segments) == 1
    assert result.segments[0].text == "hello"
    assert result.segments[0].speaker_id is None


def test_transcribe_short_audio_returns_empty(monkeypatch):
    """< 0.1s 短音频走空路径,segments 为空"""
    asr_mock = MagicMock()
    spk_mock = MagicMock()

    # conftest 的 fake librosa.load 总是返 1 秒 16kHz,这里直接 patch 让它返 0.05s
    import numpy as np
    import librosa
    monkeypatch.setattr(
        librosa, "load",
        lambda path, sr=None, *a, **kw: (np.zeros(800, dtype=np.float32), sr or 16000),
    )

    import tempfile, soundfile as sf
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    # 写入 0.05 秒音频(< 1600 samples)
    sf.write(tmp.name, np.zeros(800, dtype=np.float32), 16000)

    result = _run(transcribe_file(
        audio_path=tmp.name,
        asr_engine=asr_mock,
        spk_engine=spk_mock,
        session_id="sess_3",
    ))
    assert len(result.segments) == 0
    assert result.duration_sec < 0.1
    # 短音频走空路径,不应触发 ASR / extract_feat
    asr_mock.run_asr.assert_not_called()
    spk_mock.extract_feat.assert_not_called()


def test_transcribe_extract_feat_exception_handled():
    """extract_feat 抛异常时不挂,降级返回,日志 warning"""
    asr_mock = MagicMock()
    asr_mock.run_asr.return_value = "test"
    spk_mock = MagicMock()
    spk_mock.extract_feat.side_effect = RuntimeError("embedding 模型挂了")

    import tempfile, soundfile as sf
    import numpy as np
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, np.random.uniform(-0.1, 0.1, 3200).astype(np.float32), 16000)

    result = _run(transcribe_file(
        audio_path=tmp.name,
        asr_engine=asr_mock,
        spk_engine=spk_mock,
        session_id="sess_4",
    ))
    # ASR 文本仍要保留
    assert result.segments[0].text == "test"
    assert result.segments[0].speaker_id is None


# ========== 回归测试:真实 ASR 是 async,必须 await ==========

def test_transcribe_file_awaits_async_run_asr():
    """回归测试:asr_engine.run_asr 是 coroutine function 时,transcribe_file 必须 await
    否则 coroutine 透传到 SQLite binding 报 'coroutine is not supported' 错误。
    """
    import numpy as np
    import tempfile, soundfile as sf
    import asyncio

    asr_mock = MagicMock()
    # 真实 run_asr 是 async,这里 mock 一个 async 函数
    async def async_run_asr(audio):
        return "async 文本"
    asr_mock.run_asr = async_run_asr

    spk_mock = MagicMock()
    spk_mock.extract_feat.return_value = (np.zeros(192, dtype=np.float32), 1.0)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    sf.write(tmp.name, np.random.uniform(-0.1, 0.1, 3200).astype(np.float32), 16000)

    result = _run(transcribe_file(
        audio_path=tmp.name,
        asr_engine=asr_mock,
        spk_engine=spk_mock,
        session_id="sess_5",
    ))
    # 关键断言:text 必须是字符串,不是 coroutine 对象
    assert isinstance(result.segments[0].text, str)
    assert result.segments[0].text == "async 文本"
