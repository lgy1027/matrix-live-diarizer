from app.services.pyannote_diarization import align_speakers_to_segments


def test_alignment_splits_asr_segment_at_speaker_boundary_with_words():
    diarization = [
        (0.0, 1.0, "SPEAKER_00"),
        (1.0, 2.0, "SPEAKER_01"),
    ]
    asr = [{
        "start": 0.0,
        "end": 2.0,
        "text": "你好世界",
        "speaker": "Spk_fallback",
        "words": [
            {"text": "你好", "start": 0.1, "end": 0.8},
            {"text": "世界", "start": 1.1, "end": 1.8},
        ],
    }]

    aligned = align_speakers_to_segments(diarization, asr)

    assert [item["speaker"] for item in aligned] == ["SPEAKER_00", "SPEAKER_01"]
    assert [item["text"] for item in aligned] == ["你好", "世界"]
    assert [len(item["words"]) for item in aligned] == [1, 1]


def test_alignment_keeps_whole_text_without_word_timestamps():
    diarization = [
        (10.0, 13.0, "SPEAKER_00"),
        (13.0, 14.0, "SPEAKER_01"),
    ]
    asr = [{
        "start": 10.0,
        "end": 14.0,
        "text": "甲乙丙丁",
        "speaker": "Spk_fallback",
    }]

    aligned = align_speakers_to_segments(diarization, asr)

    assert len(aligned) == 1
    assert aligned[0]["text"] == "甲乙丙丁"
    assert aligned[0]["speaker"] == "SPEAKER_00"
    assert aligned[0]["diarization_source"] == "pyannote-segment-overlap"


def test_single_speaker_claims_asr_text_across_small_diarization_gaps():
    diarization = [
        (0.2, 3.6, "SPEAKER_00"),
        (4.4, 7.8, "SPEAKER_00"),
    ]
    asr = [
        {"start": 0.0, "end": 4.4, "text": "甚至出现交易几乎停滞的情况。", "speaker": None},
        {"start": 4.4, "end": 8.0, "text": "一二线城市仍在调整。", "speaker": None},
    ]

    aligned = align_speakers_to_segments(diarization, asr)

    assert all(item["speaker"] == "SPEAKER_00" for item in aligned)
    assert "".join(item["text"] for item in aligned) == "甚至出现交易几乎停滞的情况。一二线城市仍在调整。"
    assert not any(item["text"] in {"甚", "况。"} for item in aligned)


def test_alignment_offsets_chunk_relative_word_timestamps():
    diarization = [(30.0, 31.0, "SPEAKER_00")]
    asr = [{
        "start": 30.0,
        "end": 31.0,
        "text": "测试",
        "speaker": "Spk_fallback",
        "words": [{"text": "测试", "start": 0.1, "end": 0.8}],
    }]

    aligned = align_speakers_to_segments(diarization, asr)

    assert aligned[0]["words"][0]["start"] == 30.1
    assert aligned[0]["words"][0]["end"] == 30.8


def test_alignment_keeps_original_segment_when_diarization_does_not_overlap():
    asr = [{
        "start": 5.0,
        "end": 6.0,
        "text": "保留",
        "speaker": "Spk_original",
    }]

    aligned = align_speakers_to_segments([(0.0, 1.0, "SPEAKER_00")], asr)

    assert aligned == [{
        "start": 5.0,
        "end": 6.0,
        "text": "保留",
        "speaker": "Spk_original",
        "diarization_source": "fallback",
    }]
