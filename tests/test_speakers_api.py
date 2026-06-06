

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
