import json
from app.services.exporter import export_json


def test_export_json_lossless():
    session = {
        "id": "s1",
        "title": "周会",
        "source": "websocket",
        "duration_sec": 120.5,
        "created_at": "2026-06-06T14:30:00",
    }
    segs = [
        {"segment_index": 0, "speaker_id": "Spk_001", "text": "hi",
         "start_time": 0.0, "end_time": 1.5, "confidence": 0.95},
    ]
    speakers = [{"id": "Spk_001", "display_name": "Alice"}]
    out = export_json(session, segs, speakers)
    data = json.loads(out)
    assert data["session"]["id"] == "s1"
    assert data["session"]["title"] == "周会"
    assert data["speakers"][0]["display_name"] == "Alice"
    assert data["segments"][0]["text"] == "hi"
    assert data["segments"][0]["start_time"] == 0.0


def test_export_json_unicode_preserved():
    session = {"id": "s", "title": "中文标题", "source": "upload", "duration_sec": 1.0,
               "created_at": "2026-01-01"}
    out = export_json(session, [], [])
    # 不应该是 \uXXXX 转义
    assert "中文标题" in out
