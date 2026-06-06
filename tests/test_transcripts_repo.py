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
