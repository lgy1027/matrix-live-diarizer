from app.services.exporter import export_markdown


def test_export_markdown_header():
    segs = [{"speaker_id": None, "text": "hi", "start_time": 0.0, "end_time": 1.0}]
    out = export_markdown(
        segs,
        speaker_aliases={},
        title="测试",
        duration_sec=1.0,
        speaker_count=1,
    )
    assert out.startswith("# 测试")
    assert "**Duration**: 00:01" in out


def test_export_markdown_groups_by_speaker():
    segs = [
        {"speaker_id": "Spk_001", "text": "A1", "start_time": 0.0, "end_time": 1.0},
        {"speaker_id": "Spk_002", "text": "B1", "start_time": 1.5, "end_time": 2.5},
        {"speaker_id": "Spk_001", "text": "A2", "start_time": 3.0, "end_time": 4.0},
    ]
    out = export_markdown(
        segs,
        speaker_aliases={"Spk_001": "Alice", "Spk_002": "Bob"},
        title="t",
        duration_sec=4.0,
        speaker_count=2,
    )
    assert "## Alice" in out
    assert "## Bob" in out
    # Alice 段应在 Bob 之前（先出现）
    assert out.index("## Alice") < out.index("## Bob")
    # 时间戳格式
    assert "[00:00]" in out
    assert "[00:01]" in out or "[00:01.500]" in out or "[00:01.5]" in out
