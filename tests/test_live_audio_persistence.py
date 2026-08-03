import asyncio
import wave

from app.api.websocket import _append_live_audio, _close_live_audio
from app.config import config
from app.repositories.database import Database
from app.repositories.meetings import MeetingRepository


class App:
    pass


class Socket:
    def __init__(self, repo):
        self.app = App()
        self.app.state = App()
        self.app.state.meeting_repo = repo
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def test_realtime_pcm_is_saved_as_playable_meeting_wav(tmp_path, monkeypatch):
    db = Database(str(tmp_path / "live-audio.db"))
    db.init_schema()
    repo = MeetingRepository(db)
    socket = Socket(repo)
    monkeypatch.setattr(config.storage, "media_dir", str(tmp_path / "media"))

    asyncio.run(_append_live_audio(socket, "browser", b"\x01\x00" * 1600))
    asyncio.run(_append_live_audio(socket, "browser", b"\x02\x00" * 1600))
    _close_live_audio(socket)

    meeting = repo.get(socket._meeting_id)
    with wave.open(meeting["audio_path"], "rb") as recording:
        assert recording.getframerate() == 16000
        assert recording.getnchannels() == 1
        assert recording.getnframes() == 3200


def test_capped_live_session_keeps_transcript_not_queues_refinement(tmp_path, monkeypatch):
    """写盘上限触发后(WAV 截断但转写继续累积),finalize 应走 finalize_live
    保留直播转写,而非排队精修(精修会用截断 WAV 覆盖转写,丢失超限部分)。"""
    import app.api.websocket as ws_mod
    from app.api.websocket import _finalize_live_session

    db = Database(str(tmp_path / "capped.db"))
    db.init_schema()
    repo = MeetingRepository(db)
    audio = tmp_path / "capped.wav"
    audio.write_bytes(b"RIFF\x00")  # 文件存在(被截断的占位)
    meeting_id = repo.create(
        source="live", title="m", status="processing", audio_path=str(audio),
    )
    repo.insert_segment(
        meeting_id, segment_index=0, text="第二小时的内容",
        start_time=3600.0, end_time=3601.0, speaker_label="A",
    )

    socket = Socket(repo)
    socket._meeting_id = meeting_id
    socket._live_audio_capped = True  # 写盘上限已触发
    # 模拟 job_repo 捕捉是否被调排队精修
    queued = {"called": False}

    class FakeJobRepo:
        def enqueue_refinement(self, *a, **k):
            queued["called"] = True
            raise AssertionError("capped 会话不应排队精修(会丢转写)")

    socket.app.state.job_repo = FakeJobRepo()

    asyncio.run(_finalize_live_session(socket, "c1"))

    assert queued["called"] is False, "capped 会话不应排队精修"
    meeting = repo.get(meeting_id)
    assert meeting["status"] == "ready"  # finalize_live 保留转写
    # 转写未被删
    detail = repo.detail(meeting_id)
    assert any("第二小时" in s["text"] for s in detail["segments"])
    # 通知带 capped 标记
    assert socket.sent[0]["refinement_status"] == "capped"
    # DB 留 truncated 标记(reprocess 检测拒绝)
    assert meeting["processing_manifest"]["truncated"] is True


def test_capped_manifest_write_failure_deletes_truncated_wav(tmp_path, monkeypatch):
    """写 truncated manifest 失败时,删除截断 WAV + 置空 audio_path,
    防 recover 标 failed 后用户 reprocess 用截断 WAV 覆盖完整转写。"""
    import app.api.websocket as ws_mod
    from app.api.websocket import _finalize_live_session

    db = Database(str(tmp_path / "capped2.db"))
    db.init_schema()
    repo = MeetingRepository(db)
    audio = tmp_path / "trunc2.wav"
    audio.write_bytes(b"RIFF\x00")
    meeting_id = repo.create(
        source="live", title="m", status="processing", audio_path=str(audio),
    )
    repo.insert_segment(
        meeting_id, segment_index=0, text="完整转写内容",
        start_time=3600.0, end_time=3601.0, speaker_label="A",
    )

    socket = Socket(repo)
    socket._meeting_id = meeting_id
    socket._live_audio_capped = True

    # 让 update 仅在写 processing_manifest_json 时抛异常,放行其他字段(audio_path=None)
    orig_update = repo.update

    def fail_on_manifest(meeting_id_arg, **fields):
        if "processing_manifest_json" in fields:
            raise RuntimeError("DB busy")
        return orig_update(meeting_id_arg, **fields)

    class FakeRepo:
        get = staticmethod(repo.get)
        update = staticmethod(fail_on_manifest)
        finalize_live = staticmethod(repo.finalize_live)

        def enqueue_refinement(self, *a, **k):
            raise AssertionError("capped 不应排队")

    socket.app.state.meeting_repo = FakeRepo()

    asyncio.run(_finalize_live_session(socket, "c1"))

    # 截断 WAV 被删 + audio_path 置空
    assert not audio.exists()
    meeting = repo.get(meeting_id)
    assert meeting["audio_path"] is None or meeting["audio_path"] == ""
    # 转写保留
    detail = repo.detail(meeting_id)
    assert any("完整转写内容" in s["text"] for s in detail["segments"])
