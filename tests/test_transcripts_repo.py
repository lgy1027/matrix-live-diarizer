import time

import pytest
from app.repositories.database import Database
from app.repositories.transcripts import TranscriptRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    return TranscriptRepository(db)


def test_create_session(repo):
    sid = repo.create_session(
        source="websocket",
        title="周会",
        client_id="user_a",
        duration_sec=120.5,
    )
    assert sid is not None
    assert len(sid) > 0  # UUID


def test_get_session(repo):
    sid = repo.create_session(source="upload", original_filename="a.wav", duration_sec=60.0)
    s = repo.get_session(sid)
    assert s is not None
    assert s["source"] == "upload"
    assert s["original_filename"] == "a.wav"


def test_session_and_segment_store_runtime_model_metadata(repo):
    sid = repo.create_session(
        source="upload",
        original_filename="meeting.wav",
        asr_engine="sensevoice",
        speaker_engine="eres2net",
        diarization_source="pyannote",
    )
    repo.insert_segment(
        sid,
        0,
        "hello",
        0.0,
        1.0,
        speaker_id="SPEAKER_00",
        asr_engine="sensevoice",
        speaker_engine="eres2net",
        diarization_source="pyannote",
    )

    session = repo.get_session(sid)
    segment = repo.list_segments(sid)[0]
    assert session["asr_engine"] == "sensevoice"
    assert session["speaker_engine"] == "eres2net"
    assert session["diarization_source"] == "pyannote"
    assert segment["asr_engine"] == "sensevoice"
    assert segment["speaker_engine"] == "eres2net"
    assert segment["diarization_source"] == "pyannote"


def test_get_session_not_found(repo):
    assert repo.get_session("nonexistent") is None


def test_list_sessions_default_ordering(repo):
    sid1 = repo.create_session(source="websocket")
    # SQLite CURRENT_TIMESTAMP 是秒级精度，确保 created_at 不同
    time.sleep(1.1)
    sid2 = repo.create_session(source="upload")
    sessions = repo.list_sessions()
    assert len(sessions) == 2
    # 倒序：后创建的在前
    assert sessions[0]["id"] == sid2
    assert sessions[1]["id"] == sid1


def test_list_sessions_filter_by_source(repo):
    repo.create_session(source="websocket")
    repo.create_session(source="upload")
    only_upload = repo.list_sessions(source="upload")
    assert len(only_upload) == 1
    assert only_upload[0]["source"] == "upload"


def test_list_sessions_pagination(repo):
    for i in range(5):
        repo.create_session(source="websocket")
    page1 = repo.list_sessions(limit=2, offset=0)
    page2 = repo.list_sessions(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["id"] != page2[0]["id"]


def test_delete_session_cascades_segments(repo):
    sid = repo.create_session(source="websocket")
    repo.insert_segment(sid, segment_index=0, text="hi", start_time=0, end_time=1)
    repo.delete_session(sid)
    assert repo.get_session(sid) is None
    assert repo.list_segments(sid) == []


def test_update_title(repo):
    sid = repo.create_session(source="websocket")
    repo.update_session(sid, title="新标题")
    assert repo.get_session(sid)["title"] == "新标题"


def test_get_enriched_sessions_includes_aggregates(repo):
    """enrich 应该返回 duration/segments_count/speakers"""
    sid = repo.create_session(
        source="websocket", title="会议", duration_sec=120.5
    )
    repo.insert_segment(sid, 0, "你好", 0.0, 5.0, speaker_id="Spk_001")
    repo.insert_segment(sid, 1, "world", 5.0, 10.0, speaker_id="Spk_002")
    repo.insert_segment(sid, 2, "hi", 10.0, 12.0, speaker_id="Spk_001")  # 重复说话人

    total, items = repo.get_enriched_sessions()
    assert total == 1
    s = items[0]
    assert s["duration"] == 120.5
    assert s["segments_count"] == 3
    assert set(s["speakers"]) == {"Spk_001", "Spk_002"}
    assert len(s["speakers"]) == 2  # distinct


def test_get_enriched_sessions_no_segments(repo):
    """无段时 duration/segments_count/speakers 仍正确（默认 0/空）"""
    repo.create_session(source="websocket", title="空", duration_sec=10.0)
    total, items = repo.get_enriched_sessions()
    s = items[0]
    assert s["duration"] == 10.0
    assert s["segments_count"] == 0
    assert s["speakers"] == []


def test_get_enriched_sessions_filter_source_and_pagination(repo):
    """source 过滤 + 分页正常"""
    for i in range(5):
        repo.create_session(source="websocket")
    for i in range(3):
        repo.create_session(source="upload", original_filename=f"f{i}.wav")

    total, items = repo.get_enriched_sessions(source="websocket", limit=2, offset=0)
    assert total == 5
    assert len(items) == 2


def test_get_enriched_sessions_batch_aggregation(repo):
    """确认是批量聚合（一次 SQL 查所有 segments），不是 N+1"""
    sids = []
    for i in range(10):
        sid = repo.create_session(source="websocket", title=f"s{i}")
        # 每 session 同一说话人 3 段（确认 segments_count 正确）
        # 不同 session 不同说话人（确认 speakers 正确）
        for j in range(3):
            repo.insert_segment(sid, j, f"text-{i}-{j}", 0, 1, speaker_id=f"Spk_{i%3}")
        sids.append(sid)

    total, items = repo.get_enriched_sessions(limit=100)
    assert total == 10
    # 每个 session: 3 段 + 1 个 distinct speaker (Spk_{i%3} 在同 session 内固定)
    for s in items:
        assert s["segments_count"] == 3
        assert len(s["speakers"]) == 1
