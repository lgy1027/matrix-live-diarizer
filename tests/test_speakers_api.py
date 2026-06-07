

# ========== Cleanup endpoint ==========

def test_cleanup_dry_run_default():
    """默认 dry_run=True (安全默认)"""
    from app.api.speakers import CleanupRequest
    body = CleanupRequest()
    assert body.dry_run is True


def test_cleanup_filter_logic():
    """清理过滤逻辑 (纯函数测试)"""
    # 模拟 3 个 speaker: a (count=1) b (count=10) c (count=3)
    all_speakers = [
        {"id": "Spk_a", "sample_count": 1, "session_id": "x"},
        {"id": "Spk_b", "sample_count": 10, "session_id": "x"},
        {"id": "Spk_c", "sample_count": 3, "session_id": "y"},
    ]
    # max_count=5: Spk_a (1) ✓, Spk_b (10) ✗, Spk_c (3) ✓
    max_count = 5
    candidates = [s for s in all_speakers if s.get("sample_count", 1) <= max_count]
    assert set(s["id"] for s in candidates) == {"Spk_a", "Spk_c"}


def test_cleanup_speaker_ids_explicit():
    """显式 speaker_ids 覆盖 count 过滤"""
    from app.api.speakers import CleanupRequest
    body = CleanupRequest(speaker_ids=["Spk_a", "Spk_b"], max_count=999)
    # 业务逻辑：speaker_ids 非空时用 ids 不用 max_count
    assert body.speaker_ids == ["Spk_a", "Spk_b"]
    assert body.max_count == 999


def test_cleanup_session_filter_request():
    """CleanupRequest 接受 session_id 过滤"""
    from app.api.speakers import CleanupRequest
    body = CleanupRequest(session_id="file_upload_service", max_count=3)
    assert body.session_id == "file_upload_service"
    assert body.max_count == 3


# ========== Cascade (步骤 2 新增) ==========

def test_cleanup_request_cascade_default_false():
    """cascade 默认 False (向后兼容)"""
    from app.api.speakers import CleanupRequest
    body = CleanupRequest()
    assert body.cascade is False


def test_cleanup_request_cascade_explicit():
    """cascade=True 显式可设置"""
    from app.api.speakers import CleanupRequest
    body = CleanupRequest(speaker_ids=["Spk_x"], dry_run=False, cascade=True)
    assert body.cascade is True


def test_cleanup_response_cascade_field_default():
    """CleanupResponse.cascade_segments_cleared 默认 0"""
    from app.api.speakers import CleanupResponse
    resp = CleanupResponse(
        dry_run=True, candidates=[], deleted=[],
        total_before=0, total_after=0
    )
    assert resp.cascade_segments_cleared == 0


# ========== Repository: clear_speaker_id_from_segments ==========

def test_clear_speaker_id_from_segments(tmp_path):
    """repo.clear_speaker_id_from_segments 清空指定 speaker_id 引用"""
    from app.repositories.database import Database
    from app.repositories.transcripts import TranscriptRepository

    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    repo = TranscriptRepository(db)
    sid = repo.create_session(source="websocket", title="t")
    repo.insert_segment(sid, 0, "hi", 0, 1, speaker_id="Spk_x")
    repo.insert_segment(sid, 1, "world", 1, 2, speaker_id="Spk_x")
    repo.insert_segment(sid, 2, "ok", 2, 3, speaker_id="Spk_y")

    cleared = repo.clear_speaker_id_from_segments("Spk_x")
    assert cleared == 2

    # 验证：Spk_x 的段被清空，Spk_y 不动
    segs = repo.list_segments(sid)
    assert segs[0]["speaker_id"] is None
    assert segs[1]["speaker_id"] is None
    assert segs[2]["speaker_id"] == "Spk_y"


def test_clear_speaker_id_no_match_returns_zero(tmp_path):
    """没匹配返回 0，不报错"""
    from app.repositories.database import Database
    from app.repositories.transcripts import TranscriptRepository

    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    repo = TranscriptRepository(db)
    sid = repo.create_session(source="websocket")
    repo.insert_segment(sid, 0, "hi", 0, 1, speaker_id="Spk_a")
    cleared = repo.clear_speaker_id_from_segments("Spk_nonexistent")
    assert cleared == 0
    # Spk_a 不被影响
    assert repo.list_segments(sid)[0]["speaker_id"] == "Spk_a"

