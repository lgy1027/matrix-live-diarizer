"""WebSocket 命名 + 存档 测试"""
import sys
import types
import os
import tempfile
import asyncio
import numpy as np
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def fake_engines(monkeypatch):
    """注入 fake engine 模块，并测试结束后清理。"""
    fake_asr = types.ModuleType("engine.asr_engine")
    fake_asr.ASREngine = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "engine.asr_engine", fake_asr)

    fake_speaker_pkg = types.ModuleType("engine.speaker")
    fake_speaker_pkg.__path__ = []
    fake_speaker_pkg.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_speaker_pkg.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})
    fake_factory = types.ModuleType("engine.speaker.speaker_factory")
    fake_factory.get_speaker_engine = MagicMock(return_value=MagicMock())
    fake_factory.get_engine_info = MagicMock(return_value={"name": "Mock", "model": "mock"})
    fake_factory.get_all_engines = MagicMock(return_value={"current": "mock", "asr": {}, "speakers": {}})
    fake_factory.ENGINE_CONFIG = {}
    fake_factory.get_engine_manager = MagicMock(return_value=MagicMock())
    fake_factory.resolve_embedding_model_id = MagicMock(return_value="speaker:mock:v1:dim=192:norm=l2")
    fake_factory.embedding_model_id = MagicMock(return_value="speaker:mock:v1:dim=192:norm=l2")
    fake_factory.engine_type_for = MagicMock(return_value="mock")

    monkeypatch.setitem(sys.modules, "engine.speaker", fake_speaker_pkg)
    monkeypatch.setitem(sys.modules, "engine.speaker.speaker_factory", fake_factory)
    yield


def _make_client(monkeypatch, tmp_path):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("STORAGE_DB_PATH", str(db_path))
    from importlib import reload, import_module
    cfg_mod = import_module("app.config")
    reload(cfg_mod)
    app_mod = import_module("app")
    reload(app_mod)
    from fastapi.testclient import TestClient
    return TestClient(app_mod.create_app())


def test_websocket_rename_creates_meeting(fake_engines, monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path)
    with client.websocket_connect("/ws/v1/stream/test_user") as ws:
        ws.send_json({"action": "rename", "title": "项目周会"})
        # 立即收到 renamed 响应
        resp = ws.receive_json()
        assert resp["type"] == "renamed"
        assert resp["title"] == "项目周会"
        assert client.app.state.meeting_repo.get(resp["meeting_id"])["title"] == "项目周会"


def test_websocket_rename_with_no_title(fake_engines, monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path)
    with client.websocket_connect("/ws/v1/stream/test_user2") as ws:
        ws.send_json({"action": "rename", "title": None})
        resp = ws.receive_json()
        assert resp["type"] == "renamed"


def test_process_speech_segment_archives_real_time_offsets(fake_engines, monkeypatch, tmp_path):
    """实时存档应使用会话内真实时间轴,而不是固定写 0.0."""
    client = _make_client(monkeypatch, tmp_path)
    app = client.app

    import app.api.websocket as ws_mod

    asr = MagicMock()
    asr.run_asr = AsyncMock(return_value={
        "text": "第二段内容",
        "words": [{"text": "第", "start": 0.1, "end": 0.2}],
    })
    speaker = MagicMock()
    speaker.extract_feat.return_value = ([0.1] * 192, 1.0)
    speaker.compare_and_identify.return_value = ("Spk_001", 0.95)

    app.state.runtime.set_asr(asr)
    app.state.runtime.set_speaker(speaker)

    class DummyWebSocket:
        def __init__(self, app):
            self.app = app
            self.sent = []

        async def send_json(self, msg):
            self.sent.append(msg)

    ws = DummyWebSocket(app)
    ctx = ws_mod.SessionContext("test_user")
    audio = (np.ones(16000, dtype=np.float32) * 0.1)
    asyncio.run(
        ws_mod._process_speech_segment(
            ws, ctx, audio, "test_user", 16000, segment_start_time=12.5
        )
    )

    meeting_id = ws._meeting_id
    segments = app.state.meeting_repo.detail(meeting_id)["segments"]
    assert segments[0]["start_time"] == 12.6
    assert segments[0]["end_time"] == 12.7
    assert segments[0]["words"][0]["start"] == 12.6
    result = next(message for message in ws.sent if message.get("text") == "第二段内容")
    assert result["timebase"] == "meeting"
    assert result["is_final"] is True
    assert result["words"][0]["start"] == 12.6


def test_process_speech_segment_archives_only_incremental_overlap_text(
    fake_engines, monkeypatch, tmp_path
):
    """重叠识别窗口只存新增文本，不能把 full_text 重复写入会议。"""
    client = _make_client(monkeypatch, tmp_path)
    app = client.app

    import app.api.websocket as ws_mod

    asr = MagicMock()
    asr.run_asr = AsyncMock(side_effect=[
        {
            "text": "你好世界",
            "words": [
                {"text": "你好", "start": 0.0, "end": 0.5},
                {"text": "世界", "start": 0.5, "end": 1.0},
            ],
        },
        {
            "text": "你好世界今天",
            "words": [
                {"text": "你好", "start": 0.0, "end": 0.3},
                {"text": "世界", "start": 0.3, "end": 0.6},
                {"text": "今天", "start": 0.6, "end": 1.0},
            ],
        },
    ])
    speaker = MagicMock()
    speaker.extract_feat.return_value = ([0.1] * 192, 1.0)
    speaker.compare_and_identify.return_value = ("Spk_001", 0.95)
    app.state.runtime.set_asr(asr)
    app.state.runtime.set_speaker(speaker)

    class DummyWebSocket:
        def __init__(self, app):
            self.app = app
            self.sent = []

        async def send_json(self, msg):
            self.sent.append(msg)

    ws = DummyWebSocket(app)
    ctx = ws_mod.SessionContext("test_user")
    audio = np.ones(16000, dtype=np.float32) * 0.1

    async def process_both():
        await ws_mod._process_speech_segment(
            ws, ctx, audio, "test_user", 16000, segment_start_time=0.0
        )
        await ws_mod._process_speech_segment(
            ws, ctx, audio, "test_user", 16000, segment_start_time=0.5
        )

    asyncio.run(process_both())

    segments = app.state.meeting_repo.detail(ws._meeting_id)["segments"]
    assert [segment["text"] for segment in segments] == ["你好世界", "今天"]
    assert [word["text"] for word in segments[1]["words"]] == ["今天"]
    assert segments[1]["words"][0]["start"] == 1.1
    assert segments[1]["start_time"] == 1.1
    assert segments[1]["end_time"] == 1.5


def test_speaker_failure_degrades_to_anonymous_without_losing_asr(
    fake_engines, monkeypatch, tmp_path
):
    client = _make_client(monkeypatch, tmp_path)
    app = client.app
    import app.api.websocket as ws_mod

    asr = MagicMock()
    asr.run_asr = AsyncMock(return_value={"text": "文稿必须保留", "words": None})
    speaker = MagicMock()
    speaker.extract_feat.side_effect = RuntimeError("speaker unavailable")
    app.state.runtime.set_asr(asr)
    app.state.runtime.set_speaker(speaker)

    class DummyWebSocket:
        def __init__(self, app):
            self.app = app
            self.sent = []
        async def send_json(self, msg):
            self.sent.append(msg)

    ws = DummyWebSocket(app)
    asyncio.run(ws_mod._process_speech_segment(
        ws, ws_mod.SessionContext("test_user"), np.ones(16000, dtype=np.float32),
        "test_user", 16000, segment_start_time=2.0,
    ))

    segment = app.state.meeting_repo.detail(ws._meeting_id)["segments"][0]
    assert segment["text"] == "文稿必须保留"
    assert segment["speaker_label"] == "Spk_unknown"
    message = next(item for item in ws.sent if item.get("text") == "文稿必须保留")
    assert message["speaker_state"] == "unknown"


def test_stream_origin_words_are_not_offset_twice(fake_engines, monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path)
    app = client.app
    import app.api.websocket as ws_mod

    asr = MagicMock()
    asr.run_asr = AsyncMock(return_value={
        "text": "stream",
        "timestamp_origin": "stream",
        "words": [{"text": "stream", "start": 12.6, "end": 12.9}],
    })
    speaker = MagicMock()
    speaker.extract_feat.return_value = ([0.1] * 192, 1.0)
    speaker.compare_and_identify.return_value = ("Spk_001", 0.9)
    app.state.runtime.set_asr(asr)
    app.state.runtime.set_speaker(speaker)

    class DummyWebSocket:
        def __init__(self, app): self.app, self.sent = app, []
        async def send_json(self, msg): self.sent.append(msg)

    ws = DummyWebSocket(app)
    asyncio.run(ws_mod._process_speech_segment(
        ws, ws_mod.SessionContext("test_user"), np.ones(16000, dtype=np.float32),
        "test_user", 16000, segment_start_time=12.5,
    ))

    segment = app.state.meeting_repo.detail(ws._meeting_id)["segments"][0]
    assert segment["words"][0]["start"] == 12.6


@pytest.mark.parametrize(
    ("origin", "native_start", "native_end", "expected_start", "expected_end"),
    [
        ("chunk", 0.2, 0.8, 12.7, 13.3),
        ("stream", 12.7, 13.3, 12.7, 13.3),
    ],
)
def test_segment_only_asr_uses_native_boundaries(
    fake_engines, monkeypatch, tmp_path,
    origin, native_start, native_end, expected_start, expected_end,
):
    client = _make_client(monkeypatch, tmp_path)
    app = client.app
    import app.api.websocket as ws_mod
    asr = MagicMock()
    asr.run_asr = AsyncMock(return_value={
        "text": "segment only",
        "timestamp_origin": origin,
        "segments": [{
            "text": "segment only", "start": native_start, "end": native_end,
            "speaker": None, "words": None,
        }],
    })
    speaker = MagicMock()
    speaker.extract_feat.return_value = ([0.1] * 192, 1.0)
    speaker.compare_and_identify.return_value = ("Spk_001", 0.9)
    app.state.runtime.set_asr(asr)
    app.state.runtime.set_speaker(speaker)

    class DummyWebSocket:
        def __init__(self, app): self.app, self.sent = app, []
        async def send_json(self, msg): self.sent.append(msg)

    ws = DummyWebSocket(app)
    asyncio.run(ws_mod._process_speech_segment(
        ws, ws_mod.SessionContext("test_user"), np.ones(16000, dtype=np.float32),
        "test_user", 16000, segment_start_time=12.5,
    ))

    segment = app.state.meeting_repo.detail(ws._meeting_id)["segments"][0]
    assert segment["start_time"] == pytest.approx(expected_start)
    assert segment["end_time"] == pytest.approx(expected_end)


def test_non_final_asr_is_not_persisted(fake_engines, monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path)
    app = client.app
    import app.api.websocket as ws_mod
    asr = MagicMock()
    asr.run_asr = AsyncMock(return_value={"text": "partial", "is_final": False})
    speaker = MagicMock()
    speaker.extract_feat.return_value = ([0.1] * 192, 1.0)
    app.state.runtime.set_asr(asr)
    app.state.runtime.set_speaker(speaker)

    class DummyWebSocket:
        def __init__(self, app): self.app, self.sent = app, []
        async def send_json(self, msg): self.sent.append(msg)

    ws = DummyWebSocket(app)
    asyncio.run(ws_mod._process_speech_segment(
        ws, ws_mod.SessionContext("test_user"), np.ones(16000, dtype=np.float32),
        "test_user", 16000,
    ))

    assert not hasattr(ws, "_meeting_id")
    assert all(item.get("text") != "partial" for item in ws.sent)


def test_same_accelerator_engines_run_sequentially():
    import app.api.websocket as ws_mod
    events = []

    class ASR:
        device = "cuda"
        async def run_asr(self, *_args, **_kwargs):
            events.extend(["asr-start", "asr-end"])
            return {"text": "ok"}

    class Speaker:
        device = "cuda"
        def extract_feat(self, _audio):
            events.extend(["speaker-start", "speaker-end"])
            return [0.1], 1.0

    result = asyncio.run(ws_mod._run_live_engines(
        ws_mod.EngineSnapshot(asr=ASR(), speaker=Speaker()),
        np.ones(16000, dtype=np.float32),
    ))

    assert not isinstance(result[0], Exception)
    assert events == ["asr-start", "asr-end", "speaker-start", "speaker-end"]


def test_parallel_engine_error_waits_for_other_provider_to_finish():
    import time
    import app.api.websocket as ws_mod
    finished = []

    class ASR:
        device = "cuda"
        async def run_asr(self, *_args, **_kwargs):
            raise RuntimeError("asr failed")

    class Speaker:
        device = "cpu"
        def extract_feat(self, _audio):
            time.sleep(0.05)
            finished.append(True)
            return [0.1], 1.0

    asr_result, speaker_result = asyncio.run(ws_mod._run_live_engines(
        ws_mod.EngineSnapshot(asr=ASR(), speaker=Speaker()),
        np.ones(16000, dtype=np.float32),
    ))

    assert isinstance(asr_result, RuntimeError)
    assert speaker_result == ([0.1], 1.0)
    assert finished == [True]


def test_processor_deadline_returns_without_cancelling_model_owner():
    import app.api.websocket as ws_mod

    async def scenario():
        gate = asyncio.Event()

        async def pending_processor():
            await gate.wait()

        task = asyncio.create_task(pending_processor())
        completed = await ws_mod._wait_for_processor(task, timeout=0.01)
        assert completed is False
        assert not task.done()
        gate.set()
        await task

    asyncio.run(scenario())


def test_audio_queue_items_keep_absolute_sample_offsets():
    """即便旧队列条目被丢弃，新条目仍携带完整录音的绝对 sample offset。"""
    import app.api.websocket as ws_mod

    websocket = MagicMock()
    first = ws_mod._make_audio_queue_item(websocket, b"\x01\x00" * 160)
    second = ws_mod._make_audio_queue_item(websocket, b"\x02\x00" * 320)
    third = ws_mod._make_audio_queue_item(websocket, b"\x03\x00" * 80)

    assert first[0] == 0
    assert second[0] == 160
    assert third[0] == 480
    assert third[1] == b"\x03\x00" * 80


def test_audio_processor_starts_new_segment_at_absolute_offset_after_gap(monkeypatch):
    """队列丢帧形成缺口后，下一语音段应对齐完整 WAV，而非压缩后的时间。"""
    import app.api.websocket as ws_mod

    asr = MagicMock()
    asr.is_silent.return_value = False
    speaker = MagicMock()

    class DummyWebSocket:
        def __init__(self):
            self._engine_snapshot = ws_mod.EngineSnapshot(asr=asr, speaker=speaker)
            self.sent = []

        async def send_json(self, msg):
            self.sent.append(msg)

    websocket = DummyWebSocket()
    queue = asyncio.Queue()
    loud_pcm = (np.ones(2000, dtype=np.int16) * 10000).tobytes()
    queue.put_nowait((0, loud_pcm))
    queue.put_nowait((32000, loud_pcm))
    stop_event = asyncio.Event()
    process_segment = AsyncMock()
    monkeypatch.setattr(ws_mod, "_process_speech_segment", process_segment)
    monkeypatch.setattr(ws_mod.config.audio, "skip_frame_threshold", 100)
    monkeypatch.setattr(ws_mod.config.audio, "timeout_seconds", 100)
    monkeypatch.setattr(ws_mod.config.audio, "max_segment_seconds", 5)

    async def run_processor():
        task = asyncio.create_task(
            ws_mod.audio_processor(websocket, queue, "test_user", stop_event)
        )
        while not queue.empty():
            await asyncio.sleep(0)
        stop_event.set()
        await task

    asyncio.run(run_processor())

    starts = [
        call.kwargs["segment_start_time"]
        for call in process_segment.await_args_list
    ]
    assert starts == [0.0, 2.0]


def test_audio_processor_drains_accepted_frames_after_stop(monkeypatch):
    """关闭只停止接收；队列里已经接受的尾音仍必须进入最终 flush。"""
    import app.api.websocket as ws_mod

    asr = MagicMock()
    asr.is_silent.return_value = False
    speaker = MagicMock()

    class DummyWebSocket:
        def __init__(self):
            self._engine_snapshot = ws_mod.EngineSnapshot(asr=asr, speaker=speaker)
            self.sent = []

        async def send_json(self, msg):
            self.sent.append(msg)

    websocket = DummyWebSocket()
    queue = asyncio.Queue()
    loud_pcm = (np.ones(2000, dtype=np.int16) * 10000).tobytes()
    queue.put_nowait((0, loud_pcm))
    queue.put_nowait((2000, loud_pcm))
    stop_event = asyncio.Event()
    stop_event.set()
    process_segment = AsyncMock()
    monkeypatch.setattr(ws_mod, "_process_speech_segment", process_segment)
    monkeypatch.setattr(ws_mod.config.audio, "skip_frame_threshold", 100)
    monkeypatch.setattr(ws_mod.config.audio, "timeout_seconds", 100)
    monkeypatch.setattr(ws_mod.config.audio, "max_segment_seconds", 5)

    asyncio.run(ws_mod.audio_processor(websocket, queue, "test_user", stop_event))

    assert queue.empty()
    assert len(process_segment.await_args.args[2]) == 4000


def test_timeout_flush_does_not_reset_last_full_text(monkeypatch):
    """M4: 超时只是"队列暂空"非"语音段结束"。flush 出去的文本已入库,
    超时后不应清空 ctx.last_full_text —— 否则下一段 ASR 返回的含旧前缀
    文本会因基准清空被当增量重发 → 前端重复字。

    通过 patch SessionContext 构造器注入共享 ctx,驱动超时分支后断言
    last_full_text 不被清空。
    """
    import app.api.websocket as ws_mod

    asr = MagicMock()
    asr.is_silent.return_value = False  # classify_frame 判语音 → 累积 SPEECH
    speaker = MagicMock()
    shared_ctx = ws_mod.SessionContext("test_user")

    class DummyWebSocket:
        def __init__(self):
            self._engine_snapshot = ws_mod.EngineSnapshot(asr=asr, speaker=speaker)
            self._speaker_scope = "test_user"
            self.sent = []

        async def send_json(self, msg):
            self.sent.append(msg)

    websocket = DummyWebSocket()
    queue = asyncio.Queue()
    loud_pcm = (np.ones(2000, dtype=np.int16) * 10000).tobytes()

    async def fake_process(ws, c, audio, cid, sr, *, segment_start_time=0.0):
        # 模拟真实 ASR 流程设置上下文基准
        c.last_full_text = "你好世界"

    monkeypatch.setattr(ws_mod, "_process_speech_segment", fake_process)
    # 让 audio_processor 内部用我们的 shared_ctx
    monkeypatch.setattr(ws_mod, "SessionContext", lambda cid: shared_ctx)
    monkeypatch.setattr(ws_mod.config.audio, "skip_frame_threshold", 100)
    monkeypatch.setattr(ws_mod.config.audio, "timeout_seconds", 100)
    monkeypatch.setattr(ws_mod.config.audio, "max_segment_seconds", 5)

    # 一帧语音进队列 → SILENCE→SPEECH, buffer 累积;之后队列空 + stop_event
    # 触发 0.1s 超时分支(len(speech_buffer) > 0 → flush)。
    queue.put_nowait((0, loud_pcm))
    stop_event = asyncio.Event()

    async def run_processor():
        task = asyncio.create_task(
            ws_mod.audio_processor(websocket, queue, "test_user", stop_event)
        )
        while not queue.empty():
            await asyncio.sleep(0)
        stop_event.set()  # 设 stop → 下次 get timeout=0.1s,触发超时分支
        await task

    asyncio.run(run_processor())

    assert shared_ctx.last_full_text == "你好世界", (
        "超时分支不应重置 last_full_text,否则下一段含旧前缀文本会重发"
    )
    # Low-8: 验证保留的 last_full_text 能正确驱动增量去重 —— 下一段 ASR
    # 若返回含旧前缀文本(你好世界再见),get_incremental_text 应只发"再见",
    # 而非整段重发。这是 M4 修复的核心目的(防前端重复字)。
    # 若有人误把 last_full_text="" 加回超时分支,此处 last_full_text 已清空,
    # get_incremental_text 会返回整段"你好世界再见",断言失败。
    incr = shared_ctx.get_incremental_text("你好世界再见")
    assert incr == "再见", (
        f"保留 last_full_text 后应只发增量,实际 {incr!r}"
    )
