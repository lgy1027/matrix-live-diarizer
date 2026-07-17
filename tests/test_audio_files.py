import numpy as np
import pytest
import soundfile as sf

from app.services.audio_files import split_audio_into_chunks, validate_audio_file


def test_split_audio_rejects_invalid_overlap():
    with pytest.raises(ValueError):
        split_audio_into_chunks(np.zeros(16000), 16000, 1, 1)


def test_split_audio_returns_absolute_boundaries():
    chunks = split_audio_into_chunks(np.zeros(48000), 16000, 2, 0.5)
    assert [(start, end) for _, start, end in chunks] == [(0, 2), (1.5, 3)]


def test_validate_audio_rejects_mislabeled_file(tmp_path, monkeypatch):
    path = tmp_path / "fake.wav"
    path.write_text("not audio", encoding="utf-8")
    import librosa
    monkeypatch.setattr(librosa, "load", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad audio")))
    with pytest.raises(ValueError):
        validate_audio_file(path)


def test_validate_audio_returns_duration(tmp_path):
    path = tmp_path / "valid.wav"
    sf.write(str(path), np.zeros(16000, dtype=np.float32), 16000)
    assert validate_audio_file(path) == pytest.approx(1.0)
