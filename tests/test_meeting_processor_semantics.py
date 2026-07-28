from app.services.meeting_processor import (
    MeetingProcessor,
    merge_overlapping_text,
    normalize_offline_asr_result,
    reconcile_chunk_boundary,
    segments_from_asr_result,
)
from contextlib import asynccontextmanager
from types import SimpleNamespace

import numpy as np
import pytest


def test_exact_chunk_boundary_overlap_is_removed():
    assert merge_overlapping_text("今天讨论发布计划", "发布计划下周执行") == "下周执行"


def test_non_exact_text_is_not_deleted():
    assert merge_overlapping_text("发布计划", "发布规划") == "发布规划"


def test_single_char_overlap_at_boundary_is_removed():
    """单字重叠(中文高频字"的")在 chunk 边界也应去重,而非整字重复。

    回归:原 range(limit, 1, -1) 不含 size=1,单字重叠不去重。
    """
    assert merge_overlapping_text("我们讨论的", "的执行方案") == "执行方案"
    # 双重确认:无单字重叠时仍按原样
    assert merge_overlapping_text("我们讨论", "执行方案") == "执行方案"


def test_offline_processing_rejects_non_final_provider_result():
    with pytest.raises(RuntimeError, match="non-final"):
        normalize_offline_asr_result(
            {"text": "partial", "is_final": False}, audio_duration=2.0
        )


def test_unavailable_diarization_stays_anonymous(monkeypatch):
    class Disabled:
        enabled = False
        last_error = "HF_TOKEN 未设置"

    monkeypatch.setattr(
        "app.services.pyannote_diarization.get_pyannote_diarizer", lambda: Disabled()
    )
    processor = MeetingProcessor(None, None, None)
    segments = [{"text": "多人会议", "start": 0, "end": 2, "speaker": None}]
    result, status, error = processor._offline_diarize("missing.wav", segments)
    assert result == segments
    assert status == "unavailable"
    assert error == "HF_TOKEN 未设置"


def test_native_asr_segment_timestamps_are_offset_from_chunk():
    result = {
        "text": "你好",
        "timestamp_granularity": "segment",
        "segments": [{
            "text": "你好",
            "start": 0.4,
            "end": 1.2,
            "speaker": "native-0",
            "words": None,
        }],
    }

    segments = segments_from_asr_result(result, 30.0, 60.0)

    assert segments == [{
        "text": "你好",
        "start": 30.4,
        "end": 31.2,
        "speaker": None,
        "words": None,
    }]


def test_word_timestamps_define_text_boundary_instead_of_full_chunk():
    result = {
        "text": "hello",
        "timestamp_granularity": "word",
        "segments": None,
        "words": [{"text": "hello", "start": 1.0, "end": 1.5}],
    }

    segment = segments_from_asr_result(result, 10.0, 40.0)[0]

    assert segment["start"] == 11.0
    assert segment["end"] == 11.5
    assert segment["words"][0]["start"] == 11.0


def test_stream_origin_is_not_offset_twice_and_stream_speaker_is_preserved():
    result = {
        "text": "hello",
        "timestamp_origin": "stream",
        "speaker_scope": "stream",
        "segments": [{
            "text": "hello", "start": 11.0, "end": 11.5,
            "speaker": "SPEAKER_00", "words": None,
        }],
    }

    segment = segments_from_asr_result(result, 10.0, 40.0)[0]

    assert segment["start"] == 11.0
    assert segment["speaker"] == "SPEAKER_00"


def test_invalid_provider_times_are_clamped_or_discarded():
    result = {
        "text": "bad ok",
        "segments": [
            {"text": "past", "start": 99, "end": 100},
            {"text": "ok", "start": -1, "end": 1},
            {"text": "nan", "start": float("nan"), "end": 2},
        ],
    }

    segments = segments_from_asr_result(result, 10.0, 12.0)

    assert segments == [{
        "text": "ok", "start": 10.0, "end": 11.0,
        "speaker": None, "words": None,
    }]


def test_word_timestamps_own_overlap_and_text_is_rebuilt_consistently():
    previous = [{
        "text": "今天发布计划", "start": 25.0, "end": 31.0, "speaker": None,
        "words": [
            {"text": "今天", "start": 25.0, "end": 27.0},
            {"text": "发布", "start": 28.0, "end": 29.5},
            {"text": "计划", "start": 30.0, "end": 31.0},
        ],
    }]
    current = [{
        "text": "发布计划下周执行", "start": 28.0, "end": 34.0, "speaker": None,
        "words": [
            {"text": "发布", "start": 28.0, "end": 29.5},
            {"text": "计划", "start": 30.0, "end": 31.0},
            {"text": "下周", "start": 31.0, "end": 32.0},
            {"text": "执行", "start": 32.0, "end": 34.0},
        ],
    }]

    left, right = reconcile_chunk_boundary(previous, current, boundary=30.0)

    assert left[0]["text"] == "今天发布"
    assert right[0]["text"] == "计划下周执行"
    assert left[0]["text"] == "".join(w["text"] for w in left[0]["words"])
    assert right[0]["text"] == "".join(w["text"] for w in right[0]["words"])


def test_mixed_none_to_word_overlap_does_not_duplicate_boundary_text():
    previous = [{
        "text": "今天发布计划", "start": 0.0, "end": 30.0,
        "speaker": None, "words": None,
    }]
    current = [{
        "text": "发布计划下周执行", "start": 28.0, "end": 34.0,
        "speaker": None,
        "words": [
            {"text": "发布", "start": 28.0, "end": 29.0},
            {"text": "计划", "start": 30.0, "end": 31.0},
            {"text": "下周", "start": 31.0, "end": 32.0},
            {"text": "执行", "start": 32.0, "end": 34.0},
        ],
    }]

    left, right = reconcile_chunk_boundary(previous, current, boundary=30.0)

    assert left[0]["text"] + right[0]["text"] == "今天发布计划下周执行"


def test_mixed_word_to_none_overlap_does_not_duplicate_boundary_text():
    previous = [{
        "text": "今天发布计划", "start": 25.0, "end": 31.0, "speaker": None,
        "words": [
            {"text": "今天", "start": 25.0, "end": 27.0},
            {"text": "发布", "start": 28.0, "end": 29.5},
            {"text": "计划", "start": 30.0, "end": 31.0},
        ],
    }]
    current = [{
        "text": "发布计划下周执行", "start": 28.0, "end": 34.0,
        "speaker": None, "words": None,
    }]

    left, right = reconcile_chunk_boundary(previous, current, boundary=30.0)

    assert left[0]["text"] + right[0]["text"] == "今天发布计划下周执行"


@pytest.mark.asyncio
async def test_offline_identity_matching_persists_strict_auto_match(monkeypatch):
    suggestions = []

    class MeetingRepo:
        def suggest_speaker(self, *args, **kwargs):
            suggestions.append((args, kwargs))

    class PeopleRepo:
        def matching_samples(self, _model_id, _dimension):
            return [
                {
                    "person_id": "alice",
                    "embedding": np.array([1, 0, 0], dtype=np.float32).tobytes(),
                    "model_id": "speaker:test:v1:dim=3:norm=l2",
                    "quality_score": 1.0,
                    "effective_speech_sec": 5.0,
                },
                {
                    "person_id": "alice",
                    "embedding": np.array([0.99, 0.01, 0], dtype=np.float32).tobytes(),
                    "model_id": "speaker:test:v1:dim=3:norm=l2",
                    "quality_score": 1.0,
                    "effective_speech_sec": 5.0,
                },
            ]

    class SpeakerEngine:
        def extract_feat(self, _audio):
            return np.array([1, 0, 0], dtype=np.float32)

    @asynccontextmanager
    async def offline():
        yield

    runtime = SimpleNamespace(inference=SimpleNamespace(offline=offline))
    processor = MeetingProcessor(MeetingRepo(), None, runtime, PeopleRepo())
    monkeypatch.setattr(
        "engine.speaker.speaker_factory.embedding_model_id",
        lambda _engine, _dimension: "speaker:test:v1:dim=3:norm=l2",
    )
    monkeypatch.setattr(
        "app.services.meeting_processor.config.speaker.person_match_policy",
        lambda _model_id: (0.78, 0.03),
    )
    monkeypatch.setattr(
        "app.services.meeting_processor.config.speaker.person_auto_match_policy",
        lambda _model_id: (0.88, 0.08),
    )

    await processor._match_known_people(
        "meeting-1",
        np.zeros(6 * 16000, dtype=np.float32),
        [{"speaker": "SPEAKER_00", "start": 0.0, "end": 6.0}],
        SpeakerEngine(),
    )

    assert suggestions[0][0][:3] == ("meeting-1", "SPEAKER_00", "alice")
    assert suggestions[0][1]["identity_status"] == "auto_matched"


@pytest.mark.asyncio
async def test_identity_duration_counts_only_successful_embeddings(monkeypatch):
    suggestions = []

    class MeetingRepo:
        def suggest_speaker(self, *args, **kwargs):
            suggestions.append((args, kwargs))

    class PeopleRepo:
        def matching_samples(self, _model_id, _dimension):
            base = {
                "person_id": "alice",
                "model_id": "speaker:test:v1:dim=3:norm=l2",
                "quality_score": 1.0,
                "effective_speech_sec": 5.0,
            }
            return [
                {**base, "embedding": np.array([1, 0, 0], dtype=np.float32).tobytes()},
                {**base, "embedding": np.array([0.99, 0.01, 0], dtype=np.float32).tobytes()},
            ]

    class SpeakerEngine:
        def extract_feat(self, audio):
            return np.array([1, 0, 0], dtype=np.float32) if len(audio) <= 16000 else None

    @asynccontextmanager
    async def offline():
        yield

    processor = MeetingProcessor(
        MeetingRepo(), None,
        SimpleNamespace(inference=SimpleNamespace(offline=offline)), PeopleRepo(),
    )
    monkeypatch.setattr(
        "engine.speaker.speaker_factory.embedding_model_id",
        lambda _engine, _dimension: "speaker:test:v1:dim=3:norm=l2",
    )
    monkeypatch.setattr(
        "app.services.meeting_processor.config.speaker.person_match_policy",
        lambda _model_id: (0.78, 0.03),
    )
    monkeypatch.setattr(
        "app.services.meeting_processor.config.speaker.person_auto_match_policy",
        lambda _model_id: (0.88, 0.08),
    )

    await processor._match_known_people(
        "meeting-1", np.zeros(7 * 16000, dtype=np.float32),
        [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 6.0},
            {"speaker": "SPEAKER_00", "start": 6.0, "end": 7.0},
        ],
        SpeakerEngine(),
    )

    assert suggestions[0][1]["identity_status"] == "suggested"


@pytest.mark.asyncio
async def test_upload_meeting_publishes_text_draft_before_speaker_refinement(
    monkeypatch,
):
    replacements = []

    class MeetingRepo:
        def get(self, _meeting_id):
            return {
                "id": "meeting-1",
                "source": "upload",
                "audio_path": "recording.wav",
                "processing_mode": "meeting",
                "transcript_state": "draft",
            }

        def update(self, *_args, **_kwargs):
            return True

        def replace_generated_transcript(self, _meeting_id, rows, **kwargs):
            replacements.append((rows, kwargs))
            return list(range(len(rows)))

    class JobRepo:
        def get(self, _job_id):
            return {"cancel_requested": 0}

        def update(self, *_args, **_kwargs):
            return True

    class Asr:
        async def run_asr(self, _audio, use_preprocessing=True):
            assert use_preprocessing
            return {
                "text": "草稿文字",
                "is_final": True,
                "timestamp_granularity": "segment",
                "segments": [{
                    "text": "草稿文字", "start": 0.0, "end": 2.0,
                    "speaker": None, "words": None,
                }],
            }

    @asynccontextmanager
    async def offline():
        yield

    runtime = SimpleNamespace(
        inference=SimpleNamespace(offline=offline),
        snapshot=lambda: SimpleNamespace(asr=Asr(), speaker=None),
    )
    processor = MeetingProcessor(MeetingRepo(), JobRepo(), runtime)
    monkeypatch.setattr("app.services.meeting_processor.os.path.isfile", lambda _p: True)
    monkeypatch.setattr(
        "librosa.load",
        lambda *_args, **_kwargs: (np.zeros(2 * 16000, dtype=np.float32), 16000),
    )
    monkeypatch.setattr(
        processor,
        "_offline_diarize",
        lambda _path, segments: (
            [{**segments[0], "speaker": "SPEAKER_00"}],
            "completed",
            None,
        ),
    )

    await processor({"id": "job-1", "meeting_id": "meeting-1"})

    assert len(replacements) == 2
    assert replacements[0][0][0]["text"] == "草稿文字"
    assert replacements[0][0][0]["speaker_label"] is None
    assert replacements[0][1] == {}
    assert replacements[1][0][0]["speaker_label"] == "SPEAKER_00"
    assert replacements[1][1]["processing_manifest"]["diarization"]["status"] == "completed"
