import numpy as np

from app.services.voice_matcher import classify_person_match, match_person


def sample(
    person_id, vector, model_id="speaker:test:v1:dim=3:norm=l2",
    quality_score=1.0, effective_speech_sec=5.0,
):
    array = np.asarray(vector, dtype=np.float32)
    return {
        "person_id": person_id,
        "embedding": array.tobytes(),
        "model_id": model_id,
        "quality_score": quality_score,
        "effective_speech_sec": effective_speech_sec,
    }


def test_strong_separated_voice_match_is_suggested():
    person_id, score = match_person(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        [sample("alice", [0.99, 0.05, 0]), sample("bob", [0, 1, 0])],
        model_id="speaker:test:v1:dim=3:norm=l2",
    )
    assert person_id == "alice"
    assert score > 0.99


def test_weak_or_ambiguous_voice_stays_anonymous():
    assert match_person(
        np.array([1.0, 0.0], dtype=np.float32),
        [sample("alice", [0.7, 0.7], "speaker:test:v1:dim=2:norm=l2")],
        threshold=0.8,
        model_id="speaker:test:v1:dim=2:norm=l2",
    )[0] is None
    assert match_person(
        np.array([1.0, 0.0], dtype=np.float32),
        [
            sample("alice", [1, 0], "speaker:test:v1:dim=2:norm=l2"),
            sample("bob", [0.999, 0.01], "speaker:test:v1:dim=2:norm=l2"),
        ],
        model_id="speaker:test:v1:dim=2:norm=l2",
    )[0] is None


def test_no_compatible_sample_stays_anonymous():
    assert match_person(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        [sample("alice", [1.0, 0.0])],
        model_id="speaker:test:v1:dim=3:norm=l2",
    ) == (None, 0.0)


def test_different_embedding_model_is_never_compared():
    assert match_person(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        [sample("alice", [1.0, 0.0, 0.0], "speaker:other:v1:dim=3:norm=l2")],
        model_id="speaker:test:v1:dim=3:norm=l2",
    ) == (None, 0.0)
    assert match_person(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        [
            sample("alice", [1.0, 0.0, 0.0]),
            sample("bob", [1.0, 0.0, 0.0], "speaker:other:v1:dim=3:norm=l2"),
        ],
    ) == (None, 0.0)


def test_engine_specific_margin_can_reject_close_runner_up():
    samples = [
        sample("alice", [1.0, 0.0], "speaker:test:v1:dim=2:norm=l2"),
        sample("bob", [0.98, 0.2], "speaker:test:v1:dim=2:norm=l2"),
    ]
    assert match_person(
        np.array([1.0, 0.0], dtype=np.float32),
        samples,
        threshold=0.7,
        margin=0.03,
        model_id="speaker:test:v1:dim=2:norm=l2",
    )[0] is None
    assert match_person(
        np.array([1.0, 0.0], dtype=np.float32),
        samples,
        threshold=0.7,
        margin=0.01,
        model_id="speaker:test:v1:dim=2:norm=l2",
    )[0] == "alice"


def test_two_strong_samples_and_enough_speech_are_auto_matched():
    decision = classify_person_match(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        [
            sample("alice", [0.999, 0.02, 0]),
            sample("alice", [0.995, -0.03, 0]),
            sample("bob", [0, 1, 0]),
        ],
        model_id="speaker:test:v1:dim=3:norm=l2",
        speech_duration=7.0,
        suggestion_threshold=0.78,
        suggestion_margin=0.03,
        auto_threshold=0.90,
        auto_margin=0.08,
    )

    assert decision.person_id == "alice"
    assert decision.status == "auto_matched"
    assert decision.score > 0.99


def test_single_sample_or_short_speech_stays_a_suggestion():
    common = dict(
        embedding=np.array([1.0, 0.0, 0.0], dtype=np.float32),
        model_id="speaker:test:v1:dim=3:norm=l2",
        suggestion_threshold=0.78,
        suggestion_margin=0.03,
        auto_threshold=0.90,
        auto_margin=0.08,
    )
    one_sample = classify_person_match(
        samples=[sample("alice", [1, 0, 0])], speech_duration=8.0, **common
    )
    short_speech = classify_person_match(
        samples=[sample("alice", [1, 0, 0]), sample("alice", [0.99, 0.01, 0])],
        speech_duration=3.0,
        **common,
    )

    assert one_sample.status == "suggested"
    assert short_speech.status == "suggested"


def test_auto_match_requires_two_independently_strong_samples():
    decision = classify_person_match(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        [sample("alice", [1, 0, 0]), sample("alice", [0.5, 0.866, 0])],
        model_id="speaker:test:v1:dim=3:norm=l2",
        speech_duration=8.0,
        suggestion_threshold=0.78,
        suggestion_margin=0.03,
        auto_threshold=0.90,
        auto_margin=0.08,
    )

    assert decision.person_id == "alice"
    assert decision.status == "suggested"


def test_low_quality_enrollment_is_not_enough_for_auto_match():
    decision = classify_person_match(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        [
            sample("alice", [1, 0, 0], quality_score=1.0),
            sample("alice", [0.99, 0.01, 0], quality_score=0.2),
        ],
        model_id="speaker:test:v1:dim=3:norm=l2",
        speech_duration=8.0,
        suggestion_threshold=0.78,
        suggestion_margin=0.03,
        auto_threshold=0.90,
        auto_margin=0.08,
    )

    assert decision.status == "suggested"


def test_short_effective_enrollment_is_not_enough_for_auto_match():
    decision = classify_person_match(
        np.array([1.0, 0.0, 0.0], dtype=np.float32),
        [
            sample("alice", [1, 0, 0]),
            sample("alice", [0.99, 0.01, 0], effective_speech_sec=1.0),
        ],
        model_id="speaker:test:v1:dim=3:norm=l2",
        speech_duration=8.0,
        suggestion_threshold=0.78,
        suggestion_margin=0.03,
        auto_threshold=0.90,
        auto_margin=0.08,
    )

    assert decision.status == "suggested"
