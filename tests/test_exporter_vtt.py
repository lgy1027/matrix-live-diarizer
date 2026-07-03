from app.services.exporter import export_vtt


def test_export_vtt_header():
    segs = [{"speaker_id": None, "text": "hi", "start_time": 0.0, "end_time": 1.0}]
    out = export_vtt(segs, speaker_aliases={})
    assert out.startswith("WEBVTT\n\n")


def test_export_vtt_speaker_uses_v_tag():
    segs = [{"speaker_id": "Spk_001", "text": "hi", "start_time": 0.0, "end_time": 1.0}]
    out = export_vtt(segs, speaker_aliases={"Spk_001": "Alice"})
    assert "<v Alice>hi</v>" in out


def test_export_vtt_time_uses_dot():
    segs = [{"speaker_id": None, "text": "x", "start_time": 1.234, "end_time": 2.567}]
    out = export_vtt(segs, speaker_aliases={})
    assert "00:00:01.234" in out
    assert "00:00:02.567" in out


def test_export_vtt_skips_empty():
    segs = [
        {"speaker_id": None, "text": "", "start_time": 0.0, "end_time": 1.0},
        {"speaker_id": None, "text": "ok", "start_time": 1.0, "end_time": 2.0},
    ]
    out = export_vtt(segs, speaker_aliases={})
    # 不应该有两个时间码块
    assert out.count("-->") == 1


def test_export_vtt_word_level_one_cue_per_word():
    """字级:每个字一个 cue,带 speaker <v> 标签"""
    segs = [{
        "speaker_id": "Spk_001",
        "text": "你好",
        "start_time": 0.0,
        "end_time": 2.0,
        "words": [
            {"text": "你", "start": 0.0, "end": 1.0},
            {"text": "好", "start": 1.0, "end": 2.0},
        ],
    }]
    out = export_vtt(segs, speaker_aliases={"Spk_001": "Alice"})
    assert "<v Alice>你</v>" in out
    assert "<v Alice>好</v>" in out
    # 2 个 cue,各自 1 个时间码
    assert out.count("-->") == 2


def test_export_vtt_word_level_offsets():
    """字级:start/end 是 segment 内偏移,需要 +segment.start_time"""
    segs = [{
        "speaker_id": None,
        "text": "ab",
        "start_time": 60.0,
        "end_time": 62.0,
        "words": [
            {"text": "a", "start": 0.0, "end": 1.0},
            {"text": "b", "start": 1.0, "end": 2.0},
        ],
    }]
    out = export_vtt(segs, speaker_aliases={})
    assert "00:01:00.000 --> 00:01:01.000" in out
    assert "00:01:01.000 --> 00:01:02.000" in out
