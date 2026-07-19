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


def test_offline_not_starved_when_live_keeps_arriving():
    """M2: live 持续持有槽 + live 在排队(live_waiters>0)时,offline 不能被
    无限饿死。offline 饿死超时后置 _offline_starving 标志并放宽进入条件为
    `not active`(不再要求 live_waiters==0),live 释放槽瞬间 offline 即可进入。
    本测试验证:(1) 饿死超时后 _offline_starving 被置位;(2) live 释放后
    offline 能进入(不被持续 live 饿死);(3) offline 先于随后排队的 live。
    """
    async def scenario():
        coordinator = InferenceCoordinator()
        coordinator._OFFLINE_STARVE_TIMEOUT = 0.05  # 极小,快速进入 starving

        order = []
        live_holding = asyncio.Event()
        release_live = asyncio.Event()
        offline_entered = asyncio.Event()

        async def holding_live():
            async with coordinator.live():
                live_holding.set()
                await release_live.wait()

        async def queued_offline():
            async with coordinator.offline():
                order.append("offline")
            offline_entered.set()

        async def queued_live():
            async with coordinator.live():
                order.append("live2")

        holder = asyncio.create_task(holding_live())
        await live_holding.wait()  # live 占住槽
        offline_task = asyncio.create_task(queued_offline())
        await asyncio.sleep(0)  # offline 排队
        live2 = asyncio.create_task(queued_live())  # 第二个 live 也排队
        # 等 offline 饿死超时,置 _offline_starving
        await asyncio.sleep(0.1)
        assert coordinator._offline_starving is True, "饿死超时后应置 starving 标志"
        # 释放 live:此刻 offline(starving)应优先于已排队的 live2 进入
        release_live.set()
        await asyncio.wait_for(offline_entered.wait(), timeout=1.0)
        # offline 必须先于 live2(starving 让位生效)
        assert order.index("offline") < order.index("live2"), (
            f"offline 应先于 live2,实际 {order}"
        )
        await live2

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
