import numpy as np

from app.services.voice_sample_quality import assess_voice_sample


def test_clean_voiced_sample_has_enough_effective_speech():
    sample_rate = 16000
    time = np.arange(sample_rate * 6) / sample_rate
    audio = (0.08 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)

    result = assess_voice_sample(audio, sample_rate)

    assert result.effective_speech_sec >= 5.9
    assert result.quality_score >= 0.6
    assert not result.noise_like


def test_silence_and_clipped_audio_are_low_quality():
    silence = assess_voice_sample(np.zeros(16000 * 4, dtype=np.float32), 16000)
    clipped = assess_voice_sample(np.ones(16000 * 4, dtype=np.float32), 16000)

    assert silence.effective_speech_sec == 0
    assert silence.quality_score == 0
    assert clipped.clipping_ratio == 1
    assert clipped.quality_score < 0.35


def test_stationary_broadband_noise_is_rejected():
    audio = np.random.default_rng(7).normal(0, 0.08, 16000 * 6).astype(np.float32)

    result = assess_voice_sample(audio, 16000)

    assert result.noise_like
    assert result.quality_score < 0.35
