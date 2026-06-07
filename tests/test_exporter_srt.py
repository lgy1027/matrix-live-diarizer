from app.services.exporter import export_srt


def test_export_srt_single_segment_no_speaker():
    segs = [{"speaker_id": None, "text": "你好", "start_time": 0.0, "end_time": 3.5}]
    out = export_srt(segs, speaker_aliases={})
    assert out == "1\n00:00:00,000 --> 00:00:03,500\n你好\n"


def test_export_srt_with_speaker_prefix():
    segs = [{"speaker_id": "Spk_001", "text": "你好", "start_time": 0.0, "end_time": 3.5}]
    out = export_srt(segs, speaker_aliases={"Spk_001": "张三"})
    assert "00:00:00,000 --> 00:00:03,500" in out
    assert "[张三] 你好" in out


def test_export_srt_multiple_segments_indexed():
    segs = [
        {"speaker_id": "Spk_001", "text": "第一句", "start_time": 0.0, "end_time": 2.0},
        {"speaker_id": "Spk_002", "text": "第二句", "start_time": 2.5, "end_time": 5.0},
    ]
    out = export_srt(segs, speaker_aliases={"Spk_001": "A", "Spk_002": "B"})
    lines = out.strip().split("\n")
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:02,000"
    assert lines[2] == "[A] 第一句"
    assert lines[3] == ""
    assert lines[4] == "2"
    assert lines[5] == "00:00:02,500 --> 00:00:05,000"
    assert lines[6] == "[B] 第二句"


def test_export_srt_skips_empty_text():
    segs = [
        {"speaker_id": None, "text": "", "start_time": 0.0, "end_time": 1.0},
        {"speaker_id": None, "text": "有效", "start_time": 1.0, "end_time": 2.0},
    ]
    out = export_srt(segs, speaker_aliases={})
    # 第一个空段被跳过
    assert "1\n00:00:01,000" in out


def test_export_srt_time_format_uses_comma():
    segs = [{"speaker_id": None, "text": "x", "start_time": 1.234, "end_time": 2.567}]
    out = export_srt(segs, speaker_aliases={})
    # 毫秒部分
    assert "00:00:01,234" in out
    assert "00:00:02,567" in out


def test_export_srt_long_audio_uses_hours():
    segs = [{"speaker_id": None, "text": "x", "start_time": 3661.5, "end_time": 3662.0}]
    out = export_srt(segs, speaker_aliases={})
    # 3661.5s = 01:01:01,500
    assert "01:01:01,500" in out
