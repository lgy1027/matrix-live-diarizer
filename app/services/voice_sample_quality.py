"""Lightweight, engine-independent checks for enrolled voice samples."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VoiceSampleAssessment:
    quality_score: float
    effective_speech_sec: float
    speech_ratio: float
    rms: float
    clipping_ratio: float
    noise_like: bool


def assess_voice_sample(audio: np.ndarray, sample_rate: int) -> VoiceSampleAssessment:
    """Estimate whether decoded mono PCM contains usable enrollment speech.

    This intentionally does not depend on a specific speaker engine.  It rejects
    obvious silence, severe clipping, and stationary broadband noise before an
    expensive embedding call.  The score is a conservative enrollment signal,
    not a speech-quality MOS prediction.
    """
    samples = np.asarray(audio, dtype=np.float32).reshape(-1)
    samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    if sample_rate <= 0 or samples.size == 0:
        return VoiceSampleAssessment(0.0, 0.0, 0.0, 0.0, 0.0, False)

    frame_size = max(1, int(sample_rate * 0.02))
    frame_count = samples.size // frame_size
    if frame_count == 0:
        frames = samples.reshape(1, -1)
        frame_duration = samples.size / sample_rate
    else:
        frames = samples[: frame_count * frame_size].reshape(frame_count, frame_size)
        frame_duration = frame_size / sample_rate

    frame_rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    threshold = max(0.006, min(0.03, rms * 0.35))
    voiced = frame_rms >= threshold
    effective_speech_sec = float(np.count_nonzero(voiced) * frame_duration)
    duration_sec = samples.size / sample_rate
    effective_speech_sec = min(duration_sec, effective_speech_sec)
    speech_ratio = effective_speech_sec / duration_sec if duration_sec else 0.0
    clipping_ratio = float(np.mean(np.abs(samples) >= 0.99))

    spectral_flatness = 0.0
    voiced_frames = frames[voiced]
    if voiced_frames.size:
        selected = voiced_frames[: min(64, len(voiced_frames))]
        spectrum = np.abs(np.fft.rfft(selected * np.hanning(selected.shape[1]), axis=1))
        spectrum = np.maximum(spectrum, 1e-10)
        flatness = np.exp(np.mean(np.log(spectrum), axis=1)) / np.mean(spectrum, axis=1)
        spectral_flatness = float(np.median(flatness))
    noise_like = spectral_flatness >= 0.75

    duration_score = min(1.0, effective_speech_sec / 5.0)
    speech_score = min(1.0, speech_ratio / 0.6)
    level_score = min(1.0, rms / 0.03) * min(1.0, 0.5 / max(rms, 1e-8))
    spectral_score = max(0.0, min(1.0, (0.75 - spectral_flatness) / 0.45))
    clipping_score = max(0.0, 1.0 - clipping_ratio / 0.02)
    quality = (
        0.25 * duration_score
        + 0.15 * speech_score
        + 0.20 * level_score
        + 0.30 * spectral_score
        + 0.10 * clipping_score
    )
    if noise_like:
        quality = min(quality, 0.25)
    if clipping_ratio >= 0.02:
        quality = min(quality, 0.25)
    if effective_speech_sec < 0.5 or rms < 0.003:
        quality = 0.0
    return VoiceSampleAssessment(
        quality_score=round(float(max(0.0, min(1.0, quality))), 4),
        effective_speech_sec=round(effective_speech_sec, 3),
        speech_ratio=round(float(speech_ratio), 4),
        rms=round(rms, 6),
        clipping_ratio=round(clipping_ratio, 6),
        noise_like=noise_like,
    )
