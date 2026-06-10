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


def test_export_srt_word_level_one_block_per_word():
    """字级时间戳:每个字一个 SRT 块,start/end 来自 words"""
    segs = [{
        "speaker_id": None,
        "text": "你好",
        "start_time": 0.0,
        "end_time": 2.0,
        "words": [
            {"text": "你", "start": 0.0, "end": 1.0},
            {"text": "好", "start": 1.0, "end": 2.0},
        ],
    }]
    out = export_srt(segs, speaker_aliases={})
    # 2 个 SRT 块,索引 1, 2
    assert "1\n00:00:00,000 --> 00:00:01,000\n你" in out
    assert "2\n00:00:01,000 --> 00:00:02,000\n好" in out


def test_export_srt_word_level_offsets_to_segment_start():
    """字级时间戳:字 start/end 是 segment 内偏移,需要 +segment.start_time 校正"""
    segs = [{
        "speaker_id": None,
        "text": "hi",
        "start_time": 10.0,
        "end_time": 12.0,
        "words": [
            {"text": "h", "start": 0.0, "end": 1.0},
            {"text": "i", "start": 1.0, "end": 2.0},
        ],
    }]
    out = export_srt(segs, speaker_aliases={})
    assert "00:00:10,000 --> 00:00:11,000" in out
    assert "00:00:11,000 --> 00:00:12,000" in out


def test_export_srt_word_level_skips_empty():
    """字级:空 text 字段的字跳过"""
    segs = [{
        "speaker_id": None,
        "text": "abc",
        "start_time": 0.0,
        "end_time": 3.0,
        "words": [
            {"text": "a", "start": 0.0, "end": 1.0},
            {"text": "  ", "start": 1.0, "end": 2.0},  # 空白跳过
            {"text": "c", "start": 2.0, "end": 3.0},
        ],
    }]
    out = export_srt(segs, speaker_aliases={})
    # 只有 2 个块(a 和 c),索引 1, 2
    assert "\n2\n00:00:01,000" not in out  # 空白不生成
    assert "00:00:00,000 --> 00:00:01,000" in out
    assert "00:00:02,000 --> 00:00:03,000" in out
