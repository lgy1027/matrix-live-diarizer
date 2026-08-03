from pathlib import Path
import io

import numpy as np
import pytest
import soundfile as sf

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.jobs import router as jobs_router
from app.api.meetings import router as meetings_router
from app.api.people import router as people_router
from app.repositories.database import Database
from app.repositories.jobs import JobRepository
from app.repositories.meetings import MeetingRepository
from app.repositories.people import PeopleRepository


def make_client(tmp_path):
    db = Database(str(tmp_path / "api.db"))
    db.init_schema()
    app = FastAPI()
    app.state.meeting_repo = MeetingRepository(db)
    app.state.job_repo = JobRepository(db)
    app.state.people_repo = PeopleRepository(db)
    app.include_router(meetings_router)
    app.include_router(jobs_router)
    app.include_router(people_router)
    return TestClient(app), app


def valid_wav_bytes() -> bytes:
    output = io.BytesIO()
    sf.write(output, np.zeros(16000, dtype=np.float32), 16000, format="WAV")
    return output.getvalue()


def test_meeting_correction_journey(tmp_path):
    client, app = make_client(tmp_path)
    meeting_id = app.state.meeting_repo.create(source="upload", title="设计评审")
    segment_id = app.state.meeting_repo.insert_segment(
        meeting_id,
        segment_index=0,
        text="确认交付范围",
        start_time=0,
        end_time=2,
        speaker_label="Speaker A",
    )
    speaker_id = app.state.meeting_repo.detail(meeting_id)["speakers"][0]["id"]

    person = client.post("/v1/people", json={"name": "王敏"})
    assert person.status_code == 201
    assert person.json()["sample_count"] == 0
    assert person.json()["total_sample_duration"] == 0.0
    person_id = person.json()["id"]

    confirm = client.patch(
        f"/v1/meetings/{meeting_id}/speakers/{speaker_id}/person",
        json={"person_id": person_id},
    )
    assert confirm.status_code == 200
    detail = client.get(f"/v1/meetings/{meeting_id}").json()
    assert detail["segments"][0]["person_name"] == "王敏"

    unassign = client.patch(
        f"/v1/meetings/{meeting_id}/segments/speaker",
        json={"segment_ids": [segment_id], "meeting_speaker_id": None},
    )
    assert unassign.json()["updated"] == 1
    assert client.get(f"/v1/meetings/{meeting_id}").json()["segments"][0]["speaker_label"] is None

    corrected = client.patch(
        f"/v1/meetings/{meeting_id}/segments/{segment_id}",
        json={"text": "确认最终交付范围"},
    )
    assert corrected.status_code == 200
    segment = client.get(f"/v1/meetings/{meeting_id}").json()["segments"][0]
    assert segment["text"] == "确认最终交付范围"
    assert segment["manually_edited"] == 1


def test_people_api_rejects_blank_names(tmp_path):
    client, _app = make_client(tmp_path)

    response = client.post("/v1/people", json={"name": "   "})

    assert response.status_code == 422


def test_jobs_api_exposes_cancel_and_retry(tmp_path):
    client, app = make_client(tmp_path)
    meeting_id = app.state.meeting_repo.create(
        source="upload", title="任务", status="processing"
    )
    job_id = app.state.job_repo.create(meeting_id)

    assert client.post(f"/v1/jobs/{job_id}/cancel").status_code == 200
    app.state.job_repo.update(job_id, status="cancelled")
    retried = client.post(f"/v1/jobs/{job_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"


def test_processing_detail_exposes_job_and_locks_draft_mutations(tmp_path):
    client, app = make_client(tmp_path)
    meeting_id = app.state.meeting_repo.create(
        source="live", title="后台精修", status="processing"
    )
    segment_id = app.state.meeting_repo.insert_segment(
        meeting_id,
        segment_index=0,
        text="实时草稿",
        start_time=0,
        end_time=2,
        speaker_label="Spk_1",
    )
    speaker_id = app.state.meeting_repo.detail(meeting_id)["speakers"][0]["id"]
    person_id = app.state.people_repo.create("张三")
    job_id = app.state.job_repo.create(meeting_id)

    detail = client.get(f"/v1/meetings/{meeting_id}")

    assert detail.status_code == 200
    assert detail.json()["processing_job"]["id"] == job_id
    assert detail.json()["processing_job"]["stage"] == "queued"
    assert client.patch(
        f"/v1/meetings/{meeting_id}/segments/{segment_id}",
        json={"text": "不应写入"},
    ).status_code == 409
    assert client.patch(
        f"/v1/meetings/{meeting_id}/segments/speaker",
        json={"segment_ids": [segment_id], "meeting_speaker_id": speaker_id},
    ).status_code == 409
    assert client.patch(
        f"/v1/meetings/{meeting_id}/speakers/{speaker_id}/person",
        json={"person_id": person_id},
    ).status_code == 409
    assert client.post(
        f"/v1/meetings/{meeting_id}/notes/summary"
    ).status_code == 409
    assert client.put(
        f"/v1/meetings/{meeting_id}/notes/summary",
        json={"content": "不应保存"},
    ).status_code == 409


def test_retry_immediately_restores_processing_write_lock(tmp_path):
    client, app = make_client(tmp_path)
    meeting_id = app.state.meeting_repo.create(
        source="live", title="失败草稿", status="failed"
    )
    segment_id = app.state.meeting_repo.insert_segment(
        meeting_id, segment_index=0, text="保留草稿", start_time=0, end_time=1
    )
    job_id = app.state.job_repo.create(meeting_id)
    app.state.job_repo.update(job_id, status="failed", stage="failed")

    retried = client.post(f"/v1/jobs/{job_id}/retry")

    assert retried.status_code == 200
    meeting = app.state.meeting_repo.get(meeting_id)
    assert meeting["status"] == "processing"
    assert meeting["diarization_status"] == "pending"
    assert client.patch(
        f"/v1/meetings/{meeting_id}/segments/{segment_id}",
        json={"text": "竞态写入"},
    ).status_code == 409


def test_meeting_audio_and_delete(tmp_path):
    client, app = make_client(tmp_path)
    audio = tmp_path / "recording.wav"
    audio.write_bytes(b"RIFF fake")
    meeting_id = app.state.meeting_repo.create(
        source="upload",
        title="带音频",
        audio_path=str(audio),
        original_filename="recording.wav",
    )

    response = client.get(f"/v1/meetings/{meeting_id}/audio")
    assert response.status_code == 200
    assert response.content == b"RIFF fake"
    assert client.delete(f"/v1/meetings/{meeting_id}").status_code == 200
    assert not audio.exists()


def test_upload_immediately_creates_durable_job(tmp_path, monkeypatch):
    from app.api import meetings as meetings_api

    client, app = make_client(tmp_path)
    monkeypatch.setattr(meetings_api.config.storage, "media_dir", str(tmp_path / "media"))
    response = client.post(
        "/v1/meetings/upload?mode=meeting",
        files={"file": ("planning.wav", valid_wav_bytes(), "audio/wav")},
    )

    assert response.status_code == 202
    payload = response.json()
    meeting = app.state.meeting_repo.get(payload["meeting_id"])
    job = app.state.job_repo.get(payload["job_id"])
    assert meeting["title"] == "planning"
    assert meeting["status"] == "processing"
    assert Path(meeting["audio_path"]).is_file()
    assert job["status"] == "queued"


def test_upload_removes_meeting_and_audio_when_job_creation_fails(tmp_path, monkeypatch):
    from app.api import meetings as meetings_api

    client, app = make_client(tmp_path)
    media_dir = tmp_path / "media"
    monkeypatch.setattr(meetings_api.config.storage, "media_dir", str(media_dir))
    # 原子化后 meeting+job 在同一事务,mock meeting_repo.create_with_job 抛错
    # → meeting 和 audio 都不应残留
    monkeypatch.setattr(
        app.state.meeting_repo,
        "create_with_job",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("queue unavailable")),
    )

    with pytest.raises(RuntimeError, match="queue unavailable"):
        client.post(
            "/v1/meetings/upload",
            files={"file": ("planning.wav", valid_wav_bytes(), "audio/wav")},
        )

    assert app.state.meeting_repo.list()[0] == 0
    assert list(media_dir.glob("*")) == []


def test_processing_meeting_must_be_cancelled_before_delete(tmp_path):
    client, app = make_client(tmp_path)
    meeting_id = app.state.meeting_repo.create(
        source="upload", title="处理中", status="processing"
    )
    app.state.job_repo.create(meeting_id)

    response = client.delete(f"/v1/meetings/{meeting_id}")

    assert response.status_code == 409
    assert app.state.meeting_repo.get(meeting_id) is not None


def test_live_recording_without_job_cannot_be_deleted(tmp_path):
    client, app = make_client(tmp_path)
    meeting_id = app.state.meeting_repo.create(
        source="live", title="录制中", status="processing"
    )

    response = client.delete(f"/v1/meetings/{meeting_id}")

    assert response.status_code == 409
    assert app.state.meeting_repo.get(meeting_id) is not None


def test_ready_meeting_can_be_queued_for_reprocessing(tmp_path):
    client, app = make_client(tmp_path)
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF")
    meeting_id = app.state.meeting_repo.create(
        source="live", title="重新精修", audio_path=str(audio), status="ready"
    )

    response = client.post(f"/v1/meetings/{meeting_id}/reprocess")

    assert response.status_code == 202
    assert app.state.job_repo.get(response.json()["job_id"])["status"] == "queued"
    assert app.state.meeting_repo.get(meeting_id)["diarization_status"] == "pending"


def test_reprocess_rejects_meeting_without_audio(tmp_path):
    client, app = make_client(tmp_path)
    meeting_id = app.state.meeting_repo.create(source="live", title="无音频", status="ready")

    assert client.post(f"/v1/meetings/{meeting_id}/reprocess").status_code == 409


def test_reprocess_rejects_truncated_live_meeting(tmp_path):
    """capped 实时会话(WAV 截断)的 reprocess 应拒绝,防截断 WAV 覆盖完整转写。"""
    client, app = make_client(tmp_path)
    audio = tmp_path / "trunc.wav"
    audio.write_bytes(b"RIFF")
    meeting_id = app.state.meeting_repo.create(
        source="live", title="超长", status="ready", audio_path=str(audio),
    )
    app.state.meeting_repo.update(
        meeting_id, processing_manifest_json='{"truncated": true}',
    )
    r = client.post(f"/v1/meetings/{meeting_id}/reprocess")
    assert r.status_code == 409
    assert "截断" in r.json()["detail"]


def test_reprocess_rejects_truncated_wav_by_duration_mismatch(tmp_path, monkeypatch):
    """双失败兜底:truncated manifest 未写成 + audio_path 未置空时,
    按 WAV 实际时长 < duration_sec 拒绝(防截断 WAV 覆盖完整转写)。"""
    import wave
    client, app = make_client(tmp_path)
    # 造一个真实但极短的 WAV(1s),但 duration_sec 标成 3600(说明转写覆盖 1h)
    audio = tmp_path / "short.wav"
    with wave.open(str(audio), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    meeting_id = app.state.meeting_repo.create(
        source="live", title="长", status="failed", audio_path=str(audio),
    )
    app.state.meeting_repo.update(meeting_id, duration_sec=3600.0)
    r = client.post(f"/v1/meetings/{meeting_id}/reprocess")
    assert r.status_code == 409
    assert "截断" in r.json()["detail"]


def test_search_and_export_use_corrected_identity(tmp_path):
    client, app = make_client(tmp_path)
    meeting_id = app.state.meeting_repo.create(source="upload", title="中文会议")
    app.state.meeting_repo.insert_segment(
        meeting_id, segment_index=0, text="确认七月交付", start_time=1, end_time=3,
        speaker_label="Speaker A",
    )

    search = client.get("/v1/meetings/search", params={"q": "七月"})
    assert search.status_code == 200
    assert search.json()["hits"][0]["meeting_id"] == meeting_id

    exported = client.get(f"/v1/meetings/{meeting_id}/export?format=markdown")
    assert exported.status_code == 200
    assert "确认七月交付" in exported.text
    assert "filename*=UTF-8''" in exported.headers["content-disposition"]


def test_add_voice_sample_extracts_and_persists_embedding(tmp_path, monkeypatch):
    from app.api import people as people_api

    class SpeakerEngine:
        _model_name = "test-speaker"

        def extract_feat(self, audio):
            assert audio.dtype == np.float32
            return np.array([0.1, 0.2, 0.3], dtype=np.float32)

    client, app = make_client(tmp_path)
    app.state.spk_engine = SpeakerEngine()
    monkeypatch.setattr(people_api.config.storage, "media_dir", str(tmp_path / "media"))
    monkeypatch.setattr(
        "librosa.load",
        lambda *args, **kwargs: (
            (0.08 * np.sin(2 * np.pi * 220 * np.arange(96000) / 16000)).astype(np.float32),
            16000,
        ),
    )
    person_id = client.post("/v1/people", json={"name": "陈晨"}).json()["id"]
    response = client.post(
        f"/v1/people/{person_id}/samples",
        files={"file": ("voice.wav", b"RIFF sample", "audio/wav")},
    )

    assert response.status_code == 201
    payload = response.json()
    # 6 秒正弦波:effective_speech_sec >= 5 且 quality 够高,应达到自动匹配门槛
    assert payload["auto_match_eligible"] is True
    detail = client.get(f"/v1/people/{person_id}").json()
    assert detail["samples"][0]["embedding_dim"] == 3
    assert detail["samples"][0]["model_name"] == "test-speaker"
    assert detail["samples"][0]["effective_speech_sec"] >= 5


def test_add_voice_sample_reports_ineligible_when_below_auto_match_threshold(tmp_path, monkeypatch):
    """B1: quality_score < 0.6 或 effective_speech_sec < 3.0 时 auto_match_eligible=False,
    让用户知道样本已注册但达不到自动匹配门槛。"""
    from app.api import people as people_api

    class SpeakerEngine:
        _model_name = "test-speaker"

        def extract_feat(self, _audio):
            return np.array([0.1, 0.2, 0.3], dtype=np.float32)

    client, app = make_client(tmp_path)
    app.state.spk_engine = SpeakerEngine()
    monkeypatch.setattr(people_api.config.storage, "media_dir", str(tmp_path / "media"))
    person_id = client.post("/v1/people", json={"name": "阈值测试"}).json()["id"]

    # 2.5 秒正弦波:duration >= 2 通过校验,但 effective_speech_sec < 3.0 → 不达标
    audio = (0.08 * np.sin(2 * np.pi * 220 * np.arange(40000) / 16000)).astype(np.float32)
    monkeypatch.setattr("librosa.load", lambda *args, **kwargs: (audio, 16000))
    response = client.post(
        f"/v1/people/{person_id}/samples",
        files={"file": ("voice.wav", b"RIFF sample", "audio/wav")},
    )
    assert response.status_code == 201
    assert response.json()["auto_match_eligible"] is False


def test_add_voice_sample_returns_503_when_speaker_engine_unavailable(tmp_path, monkeypatch):
    """声纹引擎降级启动(speaker_engine=None)时,注册声样应返 503 而非 500。"""
    from app.api import people as people_api

    client, app = make_client(tmp_path)
    app.state.spk_engine = None  # 引擎降级
    app.state.runtime = None
    monkeypatch.setattr(people_api.config.storage, "media_dir", str(tmp_path / "media"))
    audio = (0.08 * np.sin(2 * np.pi * 220 * np.arange(48000) / 16000)).astype(np.float32)
    monkeypatch.setattr("librosa.load", lambda *args, **kwargs: (audio, 16000))
    person_id = client.post("/v1/people", json={"name": "无引擎测试"}).json()["id"]
    response = client.post(
        f"/v1/people/{person_id}/samples",
        files={"file": ("voice.wav", b"RIFF sample", "audio/wav")},
    )
    assert response.status_code == 503
    assert "声纹引擎" in response.json()["detail"]


def test_add_voice_sample_rejects_empty_file(tmp_path, monkeypatch):
    """B4: 上传 0 字节文件应返 400 友好提示,而非触发 500 + librosa 报错。"""
    from app.api import people as people_api

    class SpeakerEngine:
        _model_name = "test-speaker"

        def extract_feat(self, _audio):
            return np.array([0.1, 0.2, 0.3], dtype=np.float32)

    client, app = make_client(tmp_path)
    app.state.spk_engine = SpeakerEngine()
    monkeypatch.setattr(people_api.config.storage, "media_dir", str(tmp_path / "media"))
    person_id = client.post("/v1/people", json={"name": "空文件测试"}).json()["id"]

    response = client.post(
        f"/v1/people/{person_id}/samples",
        files={"file": ("empty.wav", b"", "audio/wav")},
    )
    assert response.status_code == 400
    assert "空" in response.json()["detail"]


def test_voice_sample_rejects_silence_and_duplicate_pcm(tmp_path, monkeypatch):
    from app.api import people as people_api

    class SpeakerEngine:
        _model_name = "test-speaker"

        def extract_feat(self, _audio):
            return np.array([0.1, 0.2, 0.3], dtype=np.float32)

    client, app = make_client(tmp_path)
    app.state.spk_engine = SpeakerEngine()
    monkeypatch.setattr(people_api.config.storage, "media_dir", str(tmp_path / "media"))
    person_id = client.post("/v1/people", json={"name": "去重测试"}).json()["id"]

    monkeypatch.setattr(
        "librosa.load", lambda *args, **kwargs: (np.zeros(48000, dtype=np.float32), 16000)
    )
    silent = client.post(
        f"/v1/people/{person_id}/samples",
        files={"file": ("silent.wav", b"silence", "audio/wav")},
    )
    assert silent.status_code == 422

    audio = (0.08 * np.sin(2 * np.pi * 220 * np.arange(96000) / 16000)).astype(np.float32)
    monkeypatch.setattr("librosa.load", lambda *args, **kwargs: (audio, 16000))
    first = client.post(
        f"/v1/people/{person_id}/samples",
        files={"file": ("voice-a.wav", b"first", "audio/wav")},
    )
    duplicate = client.post(
        f"/v1/people/{person_id}/samples",
        files={"file": ("voice-b.wav", b"different-container", "audio/wav")},
    )
    assert first.status_code == 201
    assert duplicate.status_code == 409


def test_voice_sample_can_be_streamed_and_deleted_without_exposing_local_path(tmp_path):
    client, app = make_client(tmp_path)
    person_id = client.post("/v1/people", json={"name": "样本管理"}).json()["id"]
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"RIFF-managed-voice")
    sample_id = app.state.people_repo.add_sample(
        person_id,
        audio_path=str(audio),
        duration_sec=6.5,
        effective_speech_sec=5.8,
        quality_score=0.86,
    )

    detail = client.get(f"/v1/people/{person_id}")
    assert detail.status_code == 200
    assert detail.json()["samples"][0]["id"] == sample_id
    assert "audio_path" not in detail.json()["samples"][0]

    streamed = client.get(f"/v1/people/{person_id}/samples/{sample_id}/audio")
    assert streamed.status_code == 200
    assert streamed.content == b"RIFF-managed-voice"
    assert "inline" in streamed.headers["content-disposition"]

    deleted = client.delete(f"/v1/people/{person_id}/samples/{sample_id}")
    assert deleted.status_code == 200
    assert not audio.exists()
    person = client.get(f"/v1/people/{person_id}").json()
    assert person["sample_count"] == 0
    assert person["samples"] == []
    assert client.get(
        f"/v1/people/{person_id}/samples/{sample_id}/audio"
    ).status_code == 404


def test_voice_sample_routes_are_scoped_to_person(tmp_path):
    client, app = make_client(tmp_path)
    first = client.post("/v1/people", json={"name": "甲"}).json()["id"]
    second = client.post("/v1/people", json={"name": "乙"}).json()["id"]
    audio = tmp_path / "scoped.wav"
    audio.write_bytes(b"voice")
    sample_id = app.state.people_repo.add_sample(
        first, audio_path=str(audio), duration_sec=5
    )

    assert client.get(
        f"/v1/people/{second}/samples/{sample_id}/audio"
    ).status_code == 404
    assert client.delete(
        f"/v1/people/{second}/samples/{sample_id}"
    ).status_code == 404
    assert audio.exists()


def test_meeting_notes_use_corrected_transcript_and_are_editable(tmp_path):
    client, app = make_client(tmp_path)
    app.state.settings_repo = None
    meeting_id = app.state.meeting_repo.create(source="upload", title="复盘")
    app.state.meeting_repo.insert_segment(
        meeting_id, segment_index=0, text="小王负责周五提交最终方案。",
        start_time=0, end_time=3, speaker_label="Speaker A",
    )

    generated = client.post(f"/v1/meetings/{meeting_id}/notes/actions")
    assert generated.status_code == 200
    assert "小王" in generated.json()["content"]

    saved = client.put(
        f"/v1/meetings/{meeting_id}/notes/actions",
        json={"content": "- 小王：周五提交最终方案"},
    )
    assert saved.status_code == 200
    assert saved.json()["source"] == "manual"
    assert client.get(f"/v1/meetings/{meeting_id}").json()["notes"][0]["content"].startswith("- 小王")


def test_summary_endpoint_uses_supported_operation_name(tmp_path):
    client, app = make_client(tmp_path)
    app.state.settings_repo = None
    meeting_id = app.state.meeting_repo.create(source="upload", title="短会议")
    app.state.meeting_repo.insert_segment(
        meeting_id, segment_index=0, text="请登录控制面板，输入。",
        start_time=0, end_time=2,
    )

    response = client.post(f"/v1/meetings/{meeting_id}/notes/summary")

    assert response.status_code == 200
    assert response.json()["source"] == "extractive-fallback"
    assert "本地摘要不可用" not in response.json()["content"]
    assert "请登录控制面板" in response.json()["content"]


def test_actions_endpoint_returns_explanation_instead_of_blank_content(tmp_path):
    client, app = make_client(tmp_path)
    app.state.settings_repo = None
    meeting_id = app.state.meeting_repo.create(source="upload", title="无行动项")
    app.state.meeting_repo.insert_segment(
        meeting_id, segment_index=0, text="今天介绍了产品背景。",
        start_time=0, end_time=2,
    )

    response = client.post(f"/v1/meetings/{meeting_id}/notes/actions")

    assert response.status_code == 200
    assert "未识别到明确行动项" in response.json()["content"]
