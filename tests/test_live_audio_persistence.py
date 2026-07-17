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
