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
