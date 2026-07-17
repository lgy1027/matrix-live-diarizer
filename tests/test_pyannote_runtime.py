from app.services.pyannote_diarization import PyannoteDiarizer


def test_missing_token_is_reported_without_importing_model(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACE_TOKEN", raising=False)
    PyannoteDiarizer._instance = None
    PyannoteDiarizer._pipeline = None
    PyannoteDiarizer._enabled = False
    PyannoteDiarizer._last_error = None

    diarizer = PyannoteDiarizer()

    assert diarizer.enabled is False
    assert diarizer.last_error == "HF_TOKEN 未设置"


def test_diarize_prefers_exclusive_annotation(monkeypatch, tmp_path):
    import sys

    import numpy as np
    import soundfile as sf

    class FakeTensor:
        def __init__(self, value):
            self.value = np.asarray(value)

        @property
        def shape(self):
            return self.value.shape

        def unsqueeze(self, axis):
            self.value = np.expand_dims(self.value, axis)
            return self

    monkeypatch.setattr(
        sys.modules["torch"],
        "as_tensor",
        lambda value, dtype=None: FakeTensor(value),
        raising=False,
    )

    class Turn:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    class Annotation:
        def __init__(self, rows):
            self.rows = rows

        def itertracks(self, yield_label=False):
            assert yield_label is True
            for start, end, speaker in self.rows:
                yield Turn(start, end), None, speaker

    class Output:
        speaker_diarization = Annotation([(0.0, 1.0, "REGULAR")])
        exclusive_speaker_diarization = Annotation([(0.0, 1.0, "EXCLUSIVE")])

    captured = {}

    class Pipeline:
        def __call__(self, audio):
            captured["audio"] = audio
            return Output()

    path = tmp_path / "sample.wav"
    sf.write(str(path), np.zeros(16000, dtype=np.float32), 16000)
    diarizer = object.__new__(PyannoteDiarizer)
    diarizer._enabled = True
    diarizer._pipeline = Pipeline()

    result = diarizer.diarize(str(path))

    assert result == [(0.0, 1.0, "EXCLUSIVE")]
    assert set(captured["audio"]) == {"waveform", "sample_rate"}
    assert tuple(captured["audio"]["waveform"].shape) == (1, 16000)
