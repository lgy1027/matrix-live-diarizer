"""Process-local ownership of inference engines and scheduling."""
from __future__ import annotations

import asyncio
import importlib.metadata
import inspect
import shutil
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
    """Serialize shared-device inference while giving live audio first access."""

    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._active = False
        self._live_waiters = 0

    @asynccontextmanager
    async def live(self):
        async with self._condition:
            self._live_waiters += 1
            try:
                await self._condition.wait_for(lambda: not self._active)
                self._active = True
            finally:
                self._live_waiters -= 1
        try:
            yield
        finally:
            await self._release()

    @asynccontextmanager
    async def offline(self):
        async with self._condition:
            await self._condition.wait_for(
                lambda: not self._active and self._live_waiters == 0
            )
            self._active = True
        try:
            yield
        finally:
            await self._release()

    async def _release(self) -> None:
        async with self._condition:
            self._active = False
            self._condition.notify_all()


@dataclass(frozen=True)
class EngineSnapshot:
    """Immutable engine pair used for one live session or one offline job."""

    asr: object
    speaker: object


class ApplicationRuntime:
    """The application's single source of truth for process-local engines."""

    def __init__(self, asr: object, speaker: object) -> None:
        self._asr = asr
        self._speaker = speaker
        self.inference = InferenceCoordinator()
        self._closed = False

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
