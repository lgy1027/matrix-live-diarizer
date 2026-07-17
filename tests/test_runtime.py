import asyncio
import importlib.metadata

from app.runtime import (
    ApplicationRuntime,
    InferenceCoordinator,
    diagnose_audio_dependencies,
)


def test_engine_snapshot_is_stable_after_runtime_switch():
    old_asr, old_speaker = object(), object()
    runtime = ApplicationRuntime(old_asr, old_speaker)
    snapshot = runtime.snapshot()

    runtime.set_asr(object())
    runtime.set_speaker(object())

    assert snapshot.asr is old_asr
    assert snapshot.speaker is old_speaker


def test_live_inference_runs_before_queued_offline_work():
    async def scenario():
        coordinator = InferenceCoordinator()
        first_started = asyncio.Event()
        release_first = asyncio.Event()
        order = []

        async def first_offline():
            async with coordinator.offline():
                first_started.set()
                await release_first.wait()

        async def live():
            async with coordinator.live():
                order.append("live")

        async def second_offline():
            async with coordinator.offline():
                order.append("offline")

        first = asyncio.create_task(first_offline())
        await first_started.wait()
        live_task = asyncio.create_task(live())
        await asyncio.sleep(0)
        offline_task = asyncio.create_task(second_offline())
        await asyncio.sleep(0)
        release_first.set()
        await asyncio.gather(first, live_task, offline_task)
        assert order == ["live", "offline"]

    asyncio.run(scenario())


def test_runtime_close_releases_engine_hooks_once():
    class Engine:
        def __init__(self):
            self.calls = 0

        def close(self):
            self.calls += 1

    asr = Engine()
    speaker = Engine()
    runtime = ApplicationRuntime(asr, speaker)

    asyncio.run(runtime.close())
    asyncio.run(runtime.close())

    assert asr.calls == 1
    assert speaker.calls == 1


def test_audio_dependency_diagnostics_marks_optional_components(monkeypatch):
    versions = {
        "torch": "2.11.0",
        "torchaudio": "2.11.0",
        "torchvision": "0.26.0",
        "pyannote.audio": "4.0.5",
    }

    def fake_version(name):
        if name == "torchcodec":
            raise importlib.metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    monkeypatch.setattr("app.runtime.shutil.which", lambda name: None)

    report = diagnose_audio_dependencies()

    assert report.compatible is True
    assert report.pyannote_available is True
    assert report.torchcodec_available is False
    assert report.ffmpeg_available is False
    assert "in-memory" in report.message


def test_audio_dependency_diagnostics_detects_mismatched_torch_family(monkeypatch):
    versions = {
        "torch": "2.11.0",
        "torchaudio": "2.10.0",
        "torchvision": "0.26.0",
        "pyannote.audio": "4.0.5",
        "torchcodec": "0.8.1",
    }
    monkeypatch.setattr(importlib.metadata, "version", lambda name: versions[name])
    monkeypatch.setattr("app.runtime.shutil.which", lambda name: "ffmpeg")

    report = diagnose_audio_dependencies()

    assert report.compatible is False
    assert "torchaudio" in report.message
