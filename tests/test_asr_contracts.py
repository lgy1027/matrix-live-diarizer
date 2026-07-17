"""ASR engine result contract and provider metadata preservation."""
from __future__ import annotations

import asyncio
import numpy as np


def test_empty_result_has_stable_backward_compatible_shape():
    from engine.asr.contracts import empty_asr_result

    result = empty_asr_result()

    assert result["text"] == ""
    assert result["words"] is None
    assert result["segments"] is None
    assert result["timestamp_granularity"] == "none"
    assert result["language"] is None
    assert result["provider_metadata"] is None


def test_runtime_normalizer_rejects_invalid_enums_and_timestamps():
    from engine.asr.contracts import normalize_asr_result

    result = normalize_asr_result({
        "text": "hello",
        "timestamp_origin": "guessed",
        "speaker_scope": "global-person",
        "words": [
            {"text": "bad", "start": float("nan"), "end": 1},
            {"text": "ok", "start": -1, "end": 99},
        ],
    }, audio_duration=2.0)

    assert result["timestamp_origin"] == "chunk"
    assert result["speaker_scope"] == "none"
    assert result["words"] == [{"text": "ok", "start": 0.0, "end": 2.0}]


def test_result_contract_infers_word_and_segment_granularity():
    from engine.asr.contracts import make_asr_result

    with_words = make_asr_result(
        "hello",
        words=[{"text": "hello", "start": 0.1, "end": 0.5}],
    )
    with_segments = make_asr_result(
        "hello",
        segments=[{"text": "hello", "start": 0.1, "end": 0.5, "speaker": None}],
    )

    assert with_words["timestamp_granularity"] == "word"
    assert with_segments["timestamp_granularity"] == "segment"
    assert with_words["timestamp_unit"] == "seconds"
    assert with_words["timestamp_origin"] == "chunk"
    assert with_words["is_final"] is True


def test_funasr_does_not_delete_legitimate_words_with_a_global_blocklist():
    from engine.asr.contracts import make_asr_result
    from engine.asr.funasr_engine import FunASREngine

    engine = object.__new__(FunASREngine)
    engine.evaluate_audio_quality = lambda _audio: {"score": 100}
    engine.is_silent = lambda _audio: False
    engine._transcribe_sync = lambda _audio: make_asr_result("谢谢导演在 YouTube 分享")

    result = asyncio.run(engine.run_asr(np.ones(16000, dtype=np.float32)))

    assert result["text"] == "谢谢导演在 YouTube 分享"


def test_funasr_preserves_native_timestamps_and_normalizes_speakers():
    from engine.asr.funasr_engine import FunASREngine

    engine = object.__new__(FunASREngine)
    engine.kind = "paraformer"
    engine._postprocess = None
    engine.model = _FakeFunASRModel([
        {
            "key": "demo",
            "text": "你好世界",
            "timestamp": [[0, 240], [240, 520], [520, 760], [760, 1000]],
            "sentence_info": [
                {
                    "text": "你好",
                    "start": 0,
                    "end": 520,
                    "spk": 0,
                    "timestamp": [[0, 240], [240, 520]],
                },
                {
                    "text": "世界",
                    "start": 520,
                    "end": 1000,
                    "speaker": "SPEAKER_01",
                    "timestamp": [[520, 760], [760, 1000]],
                },
            ],
        }
    ])

    result = engine._transcribe_sync(np.zeros(16000, dtype=np.float32))

    assert result["text"] == "你好世界"
    assert result["timestamp_granularity"] == "segment"
    assert result["segments"] == [
        {"text": "你好", "start": 0.0, "end": 0.52, "speaker": "0", "words": None},
        {
            "text": "世界",
            "start": 0.52,
            "end": 1.0,
            "speaker": "SPEAKER_01",
            "words": None,
        },
    ]
    metadata = result["provider_metadata"]
    assert metadata["provider"] == "funasr"
    assert metadata["items"][0]["timestamp"] == [
        [0, 240], [240, 520], [520, 760], [760, 1000]
    ]
    assert metadata["items"][0]["sentence_info"][0]["spk"] == 0


def test_funasr_normalizes_explicit_token_timestamps_as_words():
    from engine.asr.funasr_engine import FunASREngine

    engine = object.__new__(FunASREngine)
    engine.kind = "paraformer"
    engine._postprocess = None
    engine.model = _FakeFunASRModel({
        "text": "hi there",
        "timestamp": [
            {"text": "hi", "start": 100, "end": 300},
            {"token": "there", "start": 300, "end": 800},
        ],
    })

    result = engine._transcribe_sync(np.zeros(16000, dtype=np.float32))

    assert result["words"] == [
        {"text": "hi", "start": 0.1, "end": 0.3},
        {"text": "there", "start": 0.3, "end": 0.8},
    ]
    assert result["timestamp_granularity"] == "word"


class _FakeFunASRModel:
    def __init__(self, result):
        self.result = result

    def generate(self, **_kwargs):
        return self.result
