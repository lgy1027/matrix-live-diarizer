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
