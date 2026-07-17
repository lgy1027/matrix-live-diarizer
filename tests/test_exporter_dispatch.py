import pytest
from app.services.exporter import export, FormatError


def test_export_srt_via_dispatch():
    segs = [{"speaker_id": None, "text": "hi", "start_time": 0.0, "end_time": 1.0}]
    out = export("srt", segments=segs, speaker_aliases={})
    assert "00:00:00,000" in out


def test_export_vtt_via_dispatch():
    segs = [{"speaker_id": None, "text": "hi", "start_time": 0.0, "end_time": 1.0}]
    out = export("vtt", segments=segs, speaker_aliases={})
    assert out.startswith("WEBVTT")


def test_export_markdown_via_dispatch():
    segs = [{"speaker_id": None, "text": "hi", "start_time": 0.0, "end_time": 1.0}]
    out = export(
        "markdown",
        segments=segs,
        speaker_aliases={},
        title="t",
        duration_sec=1.0,
        speaker_count=1,
    )
    assert "# t" in out


def test_export_json_via_dispatch():
    out = export(
        "json",
        session={"id": "s", "title": "t", "source": "upload", "duration_sec": 1, "created_at": "x"},
        segments=[],
        speakers=[],
    )
    assert '"id": "s"' in out


def test_export_invalid_format_raises():
    with pytest.raises(FormatError):
        export("xml", segments=[])


def test_export_mime_type_map():
    from app.services.exporter import mime_type
    assert mime_type("srt") == "text/plain; charset=utf-8"
    assert mime_type("vtt") == "text/vtt; charset=utf-8"
    assert mime_type("markdown") == "text/markdown; charset=utf-8"
    assert mime_type("json") == "application/json; charset=utf-8"


def test_meeting_export_uses_only_auto_matched_or_confirmed_names():
    from app.services.exporter import export_meeting

    detail = {
        "meeting": {"title": "评审"},
        "segments": [{
            "text": "开始", "start_time": 0, "end_time": 1,
            "speaker_label": "SPEAKER_00", "person_name": "张三",
            "manually_confirmed": 0, "identity_status": "suggested",
        }],
    }
    assert "SPEAKER_00" in export_meeting(detail, "markdown")
    assert "张三" not in export_meeting(detail, "markdown")

    detail["segments"][0]["identity_status"] = "auto_matched"
    assert "张三" in export_meeting(detail, "markdown")

    detail["segments"][0]["identity_status"] = "confirmed"
    detail["segments"][0]["manually_confirmed"] = 1
    assert "张三" in export_meeting(detail, "markdown")
