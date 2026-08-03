from app.repositories.database import Database
from app.repositories.meetings import MeetingRepository
from app.repositories.jobs import JobRepository


def test_live_meeting_can_be_appended_renamed_and_finalized(tmp_path):
    db = Database(str(tmp_path / "live.db"))
    db.init_schema()
    repo = MeetingRepository(db)
    meeting_id = repo.create(source="live", title="实时记录", status="processing")

    repo.append_live_segment(
        meeting_id, text="第一句话", start_time=0.2, end_time=2.4,
        speaker_label="Speaker A", confidence=0.81,
    )
    repo.append_live_segment(
        meeting_id, text="第二句话", start_time=2.5, end_time=4.0,
        speaker_label="Speaker B", confidence=0.78,
    )
    repo.update(meeting_id, title="产品评审")
    assert repo.finalize_live(meeting_id)

    detail = repo.detail(meeting_id)
    assert detail["meeting"]["status"] == "ready"
    assert detail["meeting"]["duration_sec"] == 4.0
    assert detail["meeting"]["title"] == "产品评审"
    assert [item["segment_index"] for item in detail["segments"]] == [0, 1]
    assert [item["speaker_label"] for item in detail["segments"]] == ["Speaker A", "Speaker B"]


def test_live_meeting_refinement_is_queued_once(tmp_path):
    db = Database(str(tmp_path / "live-refine.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    audio = tmp_path / "live.wav"
    audio.write_bytes(b"RIFF")
    meeting_id = meetings.create(
        source="live", title="实时记录", audio_path=str(audio), status="processing"
    )

    # live 会话结束时 WS finalize 路径排队 refinement,需 allow_live=True
    # (默认拒绝 status=processing 的 meeting,防 refinement 与活跃 WS 写并发)
    job_id, created = jobs.enqueue_refinement(meeting_id, allow_live=True)
    same_job_id, created_again = jobs.enqueue_refinement(meeting_id, allow_live=True)

    assert created is True
    assert created_again is False
    assert same_job_id == job_id
    meeting = meetings.get(meeting_id)
    assert meeting["status"] == "processing"
    assert meeting["processing_mode"] == "meeting"
    assert meeting["diarization_status"] == "pending"
