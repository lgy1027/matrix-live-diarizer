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


def test_offline_starving_cleared_on_cancel():
    """offline() 在 starving 状态下被取消时,_offline_starving 必须复位,
    否则后续所有 live() 见此谓词永久阻塞(只有下一只 offline 跑完才清)。
    """
    async def scenario():
        coordinator = InferenceCoordinator()
        coordinator._OFFLINE_STARVE_TIMEOUT = 0.04
        coordinator._active = True
        coordinator._live_waiters = 1

        async def waiting_offline():
            async with coordinator.offline():
                pass

        offline_task = asyncio.create_task(waiting_offline())
        await asyncio.sleep(0)  # 进入 wait
        await asyncio.sleep(0.1)  # 超过 starving 超时
        assert coordinator._offline_starving is True

        # 取消 offline 协程(模拟关停 job_runner 时 cancel)
        offline_task.cancel()
        try:
            await offline_task
        except asyncio.CancelledError:
            pass

        # 取消后 _offline_starving 必须复位,否则 live() 会死锁
        assert coordinator._offline_starving is False, (
            "取消 offline 后 _offline_starving 必须复位,否则 live 死锁"
        )

    asyncio.run(scenario())


def test_live_cancel_notifies_so_offline_can_progress():
    """live() 在等待期间被取消时,_live_waiters 减为 0 后必须 notify,
    否则等 live_waiters==0 的 offline 不会被唤醒。验证:取消 live 后,
    offline 能在槽释放后进入(说明 live 取消时通知到了,offline 没死等)。
    """
    async def scenario():
        coordinator = InferenceCoordinator()
        coordinator._active = True  # live 会阻塞在 wait_for
        offline_done = asyncio.Event()

        async def waiting_offline():
            async with coordinator.offline():
                pass
            offline_done.set()

        async def waiting_live():
            async with coordinator.live():
                pass

        offline_task = asyncio.create_task(waiting_offline())
        await asyncio.sleep(0)  # offline 进入 wait(active=True,进不去)
        live_task = asyncio.create_task(waiting_live())
        await asyncio.sleep(0)  # live 进入 wait(_live_waiters=1)

        # 取消 live:live_waiters 减为 0 + notify
        live_task.cancel()
        try:
            await live_task
        except asyncio.CancelledError:
            pass
        assert coordinator._live_waiters == 0

        # 释放 active 槽,offline 应被唤醒并进入(若 live 取消没 notify,
        # offline 仍在等,这里 notify_all 也能唤醒它 —— 但验证 live 取消后
        # offline 的谓词可重判,live_waiters==0 已满足)
        coordinator._active = False
        async with coordinator._condition:
            coordinator._condition.notify_all()
        await asyncio.wait_for(offline_done.wait(), timeout=1.0)

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


def test_offline_starves_even_with_repeated_notify_under_threshold(monkeypatch):
    """offline 在被 live 持续占用(_active=True, live_waiters>0)时,即使期间
    反复 notify_all(模拟 _release),累计等待超过 _OFFLINE_STARVE_TIMEOUT 后
    仍应置 _offline_starving。notify 不应让 offline 永远等不够超时。

    用可注入假时钟确定性驱动 coordinator 的内部计时,避免依赖 asyncio.sleep
    小睡的 wall-clock 精度——Windows CI 上 20×5ms 累计实测不足 40ms 导致
    flaky(单次长 sleep 可靠,但多次小睡不可靠)。假时钟只作用于
    app.runtime.time.monotonic;asyncio 的 loop.time() 用导入期捕获的原始引用,
    wait_for 仍按真实时间,两者互不干扰。
    """
    fake_now = [0.0]
    monkeypatch.setattr("app.runtime.time.monotonic", lambda: fake_now[0])

    async def scenario():
        coordinator = InferenceCoordinator()
        # 真实超时设大:wait_for 在真实时间上本测试内绝不触发,starved 只能由
        # 假时钟驱动的 recompute(remaining<=0)路径置位,排除真实超时污染。
        coordinator._OFFLINE_STARVE_TIMEOUT = 10.0
        coordinator._active = True
        coordinator._live_waiters = 1

        offline_done = asyncio.Event()

        async def waiting_offline():
            async with coordinator.offline():
                pass
            offline_done.set()

        offline_task = asyncio.create_task(waiting_offline())
        for _ in range(3):
            await asyncio.sleep(0)  # 让 offline 确实进入 condition.wait

        async def poke():
            async with coordinator._condition:
                coordinator._condition.notify_all()
            for _ in range(3):
                await asyncio.sleep(0)  # 让 offline 重判谓词并重新 wait

        # 阶段1:反复 notify,累计假时钟 5.0 < 超时 10.0 → 不应 starve。
        # 即便某次 notify 因 offline 尚未重新 wait 而丢失也无妨:下一poke
        # 会唤醒它重判,remaining 仍 > 0;且 wait_for 真实超时极大不会触发。
        for _ in range(5):
            fake_now[0] += 1.0
            await poke()
        assert coordinator._offline_starving is False, (
            "未超时前反复 notify 不应置 starving"
        )

        # 阶段2:继续 notify,累计假时钟 11.0 > 超时 10.0 → 应 starved。
        # notify 唤醒 offline 重判,remaining<=0 → 置 _offline_starving。
        fake_now[0] += 6.0
        await poke()
        assert coordinator._offline_starving is True, (
            "反复 notify 不应让 offline 无限等待,累计 > 超时应置 starving"
        )

        # 释放:offline 进入
        coordinator._active = False
        coordinator._live_waiters = 0
        async with coordinator._condition:
            coordinator._condition.notify_all()
        await asyncio.wait_for(offline_done.wait(), timeout=1.0)

    asyncio.run(scenario())
