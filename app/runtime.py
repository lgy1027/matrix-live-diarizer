"""Process-local ownership of inference engines and scheduling."""
from __future__ import annotations

import asyncio
import importlib.metadata
import inspect
import shutil
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional


def _package_version(name: str) -> Optional[str]:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _major_minor(version: Optional[str]) -> Optional[tuple[int, int]]:
    if not version:
        return None
    try:
        major, minor = version.split("+", 1)[0].split(".", 2)[:2]
        return int(major), int(minor)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class AudioDependencyReport:
    """Lightweight dependency report that does not import model libraries."""

    compatible: bool
    torch_version: Optional[str]
    torchaudio_version: Optional[str]
    torchvision_version: Optional[str]
    pyannote_version: Optional[str]
    pyannote_available: bool
    torchcodec_available: bool
    ffmpeg_available: bool
    message: str


def diagnose_audio_dependencies() -> AudioDependencyReport:
    """Report common binary-stack mistakes without making diarization fatal.

    pyannote receives preloaded waveform dictionaries in this application, so
    TorchCodec and FFmpeg are optional for that path.  They remain useful for
    formats decoded outside librosa/soundfile and are reported for support.
    """
    torch = _package_version("torch")
    torchaudio = _package_version("torchaudio")
    torchvision = _package_version("torchvision")
    pyannote = _package_version("pyannote.audio")
    torchcodec = _package_version("torchcodec")
    ffmpeg = shutil.which("ffmpeg") is not None

    compatible = True
    problems: list[str] = []
    torch_mm = _major_minor(torch)
    audio_mm = _major_minor(torchaudio)
    vision_mm = _major_minor(torchvision)
    if torch_mm is None or audio_mm is None:
        compatible = False
        problems.append("torch/torchaudio 未完整安装")
    elif torch_mm != audio_mm:
        compatible = False
        problems.append(f"torchaudio {torchaudio} 必须匹配 torch {torch} 的主次版本")

    # PyTorch's published pairing is torch 2.x -> torchvision 0.(x+15).
    if torch_mm and vision_mm and torch_mm[0] == 2:
        expected_vision = (0, torch_mm[1] + 15)
        if vision_mm != expected_vision:
            compatible = False
            problems.append(
                f"torchvision {torchvision} 与 torch {torch} 不匹配"
                f"（期望 0.{expected_vision[1]}.x）"
            )

    if not problems:
        problems.append(
            f"核心组件匹配: torch={torch}, torchaudio={torchaudio}, "
            f"torchvision={torchvision}"
        )
    if not pyannote:
        problems.append("pyannote 未安装；上传转写仍可用，说话人分离将降级")
    else:
        problems.append(f"pyannote.audio={pyannote}")
    if not torchcodec or not ffmpeg:
        problems.append(
            "TorchCodec/FFmpeg 非必需：pyannote 使用 in-memory waveform 解码"
            f"（torchcodec={'已安装' if torchcodec else '未安装'}, "
            f"ffmpeg={'可用' if ffmpeg else '未发现'}）"
        )

    return AudioDependencyReport(
        compatible=compatible,
        torch_version=torch,
        torchaudio_version=torchaudio,
        torchvision_version=torchvision,
        pyannote_version=pyannote,
        pyannote_available=pyannote is not None,
        torchcodec_available=torchcodec is not None,
        ffmpeg_available=ffmpeg,
        message="；".join(problems),
    )


class InferenceCoordinator:
    """Serialize shared-device inference while giving live audio first access.

    公平性(M2):live 享有优先权,但持续涌入的 live 会无限期饿死已排队的
    offline(refinement job)。offline 等待超过 _OFFLINE_STARVE_TIMEOUT 秒后
    放宽进入条件为 `not active`(不再要求"无 live 在排队"),这样 live 运行
    完释放槽的瞬间,等了很久的 offline 能抢到。live 的实时优先权在常规情况
    下不受影响(只有 offline 饿了很久才让步一次)。
    """

    # offline 饿死超时:超过后放宽进入条件,保证 refinement job 终被调度
    _OFFLINE_STARVE_TIMEOUT = 30.0

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active = False
        self._live_waiters = 0
        # 有 offline 已过饿死超时、正等待让位。live 见此会谦让一次,
        # 保证 starved offline 在下一个槽释放时优先进入。
        self._offline_starving = False
        # 看门狗回调:槽 acquire/release 时通知 ApplicationRuntime 记录时刻 +
        # 当前持有者类型("live"/"offline"),用于区分 live 卡死(可疑泄漏)与
        # offline 长任务(pyannote 分离 1h 音频可能十几分钟,合法长持)。
        # None 时无监控(测试用)。
        self._on_acquired = None
        self._on_released = None

    def bind_watchdog(self, on_acquired, on_released) -> None:
        """绑定槽占用看门狗回调(ApplicationRuntime 注入)。

        on_acquired(holder: str) 收 "live"/"offline";on_released() 无参。
        """
        self._on_acquired = on_acquired
        self._on_released = on_released

    @asynccontextmanager
    async def live(self):
        async with self._condition:
            self._live_waiters += 1
            try:
                await self._condition.wait_for(
                    lambda: not self._active and not self._offline_starving
                )
                self._active = True
                if self._on_acquired is not None:
                    self._on_acquired("live")
            finally:
                self._live_waiters -= 1
                # 等待期间被取消时,live_waiters 已减为 0,但等 live_waiters==0
                # 的 offline 不会被唤醒(没有 release 来 notify)。主动 notify
                # 让 offline 重新评估谓词,避免死锁。
                self._condition.notify_all()
        try:
            yield
        finally:
            await self._release()

    @asynccontextmanager
    async def offline(self):
        async with self._condition:
            starved = False
            wait_start = None
            # 标志位在取消路径上也要复位:协程被 cancel 时若 _offline_starving
            # 残留 True,后续所有 live() 见此谓词永久阻塞,只有下一只 offline
            # 跑完才清。用 try/finally 保证任何退出路径(含 CancelledError)都复位。
            try:
                while True:
                    if not self._active and self._live_waiters == 0:
                        break
                    if starved and not self._active:
                        break
                    if not starved:
                        if wait_start is None:
                            wait_start = time.monotonic()
                        remaining = self._OFFLINE_STARVE_TIMEOUT - (time.monotonic() - wait_start)
                        if remaining <= 0:
                            starved = True
                            self._offline_starving = True
                            continue
                        timeout = remaining
                    else:
                        timeout = None
                    try:
                        await asyncio.wait_for(self._condition.wait(), timeout=timeout)
                    except asyncio.TimeoutError:
                        starved = True
                        self._offline_starving = True
                self._offline_starving = False
                self._active = True
                if self._on_acquired is not None:
                    self._on_acquired("offline")
            finally:
                # 正常退出时上面已清;取消/异常退出时此处兜底复位,避免 _offline_starving
                # 残留 True 导致 live 永久阻塞。无论是否 starved 都 notify_all,
                # 让等待的 live/offline 重新评估谓词,防止丢失唤醒。
                self._offline_starving = False
                self._condition.notify_all()
        try:
            yield
        finally:
            await self._release()

    async def _release(self) -> None:
        async with self._condition:
            self._active = False
            if self._on_released is not None:
                self._on_released()
            self._condition.notify_all()


@dataclass(frozen=True)
class EngineSnapshot:
    """Immutable engine pair used for one live session or one offline job."""

    asr: object
    speaker: object


class ApplicationRuntime:
    """The application's single source of truth for process-local engines."""

    # 槽泄漏看门狗:**只对 live 路径**生效。deferred processor 120s 超时放弃后,
    # to_thread 推理不可取消,live 槽可能被永久占有(InferenceCoordinator._active
    # 卡 True),新 live 会冻死。live 持槽超此阈值标记 unhealthy,/ready 转 not_ready。
    # offline 不受此阈值约束:offline job(pyannote 分离 1h 音频)合法长持槽十几
    # 分钟,固定阈值会误判;offline 卡死由 job_runner 无进度兜底,不在此检测。
    # live 卡死的另一信号是 _finish_deferred_processor 120s 超时直接置位。
    _SLOT_LEAK_THRESHOLD = 600.0  # 10 分钟:远超正常单次 live 推理时长

    def __init__(self, asr: object, speaker: object) -> None:
        self._asr = asr
        self._speaker = speaker
        self.inference = InferenceCoordinator()
        self._closed = False
        # 槽被连续占用的起始 monotonic 时刻;None 表示当前空闲。
        self._slot_held_since: Optional[float] = None
        # 当前槽持有者类型("live"/"offline"/None);看门狗只对 live 启用阈值。
        self._slot_holder: Optional[str] = None
        # 检测到槽泄漏后置 True,直到进程重启。手动恢复需重启服务。
        self._slot_leaked = False
        # 绑定看门狗:coordinator 在 acquire/release 槽时回调本对象记录时刻+持有者。
        self.inference.bind_watchdog(self._mark_slot_acquired, self._mark_slot_released)

    def _mark_slot_acquired(self, holder: str) -> None:
        """推理槽被占用时记录起始时刻 + 持有者类型(看门狗用)。"""
        if self._slot_held_since is None:
            self._slot_held_since = time.monotonic()
            self._slot_holder = holder

    def _mark_slot_released(self) -> None:
        """推理槽释放时清零起始时刻与持有者。"""
        self._slot_held_since = None
        self._slot_holder = None

    @property
    def slot_leaked(self) -> bool:
        """槽是否被泄漏占有(仅 live 路径;offline 长任务不算泄漏)。"""
        if self._slot_leaked:
            return True
        if self._slot_held_since is not None and self._slot_holder == "live":
            held = time.monotonic() - self._slot_held_since
            if held > self._SLOT_LEAK_THRESHOLD:
                self._slot_leaked = True
                return True
        return False

    @property
    def asr(self) -> object:
        return self._asr

    @property
    def speaker(self) -> object:
        return self._speaker

    def snapshot(self) -> EngineSnapshot:
        return EngineSnapshot(asr=self._asr, speaker=self._speaker)

    def set_asr(self, engine: object) -> None:
        self._asr = engine

    def set_speaker(self, engine: object) -> None:
        self._speaker = engine

    async def close(self) -> None:
        """Release optional engine hooks once during application shutdown."""
        if self._closed:
            return
        self._closed = True
        seen: set[int] = set()
        for engine in (self._asr, self._speaker):
            if id(engine) in seen:
                continue
            seen.add(id(engine))
            hook = next(
                (
                    getattr(engine, name, None)
                    for name in ("close", "shutdown", "unload")
                    if callable(getattr(engine, name, None))
                ),
                None,
            )
            if hook is None:
                continue
            result = hook()
            if inspect.isawaitable(result):
                await result
