"""pyannote 离线说话人分离服务

定位: 上传录音文件时的"高准确度"说话人识别模式。
- 延迟: 2-5 秒 (需整段音频后处理,不能实时)
- 依赖: pyannote.audio >= 4.0.4 + HF_TOKEN 环境变量
- 模型: pyannote/speaker-diarization-community-1 (CC-BY-4.0)

调研依据:
- Community-1: 使用完整音频上下文的本地离线 diarization pipeline
- 公开会议集 DER 约 12-20%，且会随麦克风、噪声和重叠语音显著变化
- 本项目仅在完整文件上传路径启用，不影响实时 WebSocket 延迟

用法:
    diar = PyannoteDiarizer()
    segments = diar.diarize("audio.wav")  # [(start, end, "SPEAKER_00"), ...]
"""
import logging
import os
import warnings
from pathlib import Path
from typing import List, Tuple

import numpy as np

# Backward-compatible public import.  The alignment implementation lives in a
# dependency-free module so meeting processing can use it without initializing
# pyannote, but existing integrations historically imported it from here.
from app.services.speaker_alignment import (
    align_speakers_to_segments as align_speakers_to_segments,
)

# pyannote/audio 在边界帧(样本数<=1、空切片)上会触发数值统计退化:
#   - std(): degrees of freedom <= 0  (pooling.py:103)
#   - Mean of empty slice / invalid value encountered in divide
# 这些是 pyannote 内部已知行为,结果用 0/NaN 兜底,不影响最终分离。
# 加载模型前过滤掉,避免污染日志、干扰排查真问题。
warnings.filterwarnings("ignore", message="std\\(\\).*degrees of freedom", category=UserWarning)
warnings.filterwarnings("ignore", message="Mean of empty slice", category=RuntimeWarning)
warnings.filterwarnings("ignore", message="invalid value encountered in divide", category=RuntimeWarning)


logger = logging.getLogger("Matrix_Pyannote")
PYANNOTE_REVISION = os.environ.get(
    "PYANNOTE_MODEL_REVISION", "3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"
)


class PyannoteDiarizer:
    """pyannote 离线匿名说话人分离

    单例懒加载:首次调用 diarize() 时初始化 pipeline(下载模型 ~50MB)。
    失败时不抛异常,返回空列表,让上层保留匿名文稿。
    """

    _instance = None
    _pipeline = None
    _enabled = False
    _last_error = None
    _device = "cpu"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._pipeline is not None:
            return
        self._last_error = None
        # 检查 HF_TOKEN
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            logger.warning(
                "[PYANNOTE] HF_TOKEN 未设置，上传会议将保留匿名说话人"
            )
            self._last_error = "HF_TOKEN 未设置"
            self._enabled = False
            return
        try:
            from pyannote.audio import Pipeline
            import torch
        except Exception as e:
            self._last_error = f"pyannote.audio 无法加载: {e}"
            logger.warning("[PYANNOTE] %s", self._last_error)
            self._enabled = False
            return
        try:
            # 本地化:cache_dir 指向 models/pyannote/,HF pipeline 缓存于此
            # (hashed 结构 models--pyannote--.../snapshots/,在 models/ 下)。
            from app.services.model_resolver import local_path
            import os as _os
            import glob as _glob
            _pyannote_cache = local_path("pyannote", "_cache")
            _os.makedirs(_pyannote_cache, exist_ok=True)
            _repo_dir = _os.path.join(
                _pyannote_cache, "models--pyannote--speaker-diarization-community-1"
            )
            _snapshots = _glob.glob(_os.path.join(_repo_dir, "snapshots", "*"))
            if _snapshots:
                logger.info(
                    "[PYANNOTE] 本地缓存命中,离线加载 pyannote/speaker-diarization-community-1 (cache=%s)",
                    _pyannote_cache,
                )
            else:
                logger.info(
                    "[PYANNOTE] 本地无缓存,联网下载 pyannote/speaker-diarization-community-1 (~50MB) → %s",
                    _pyannote_cache,
                )
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-community-1",
                revision=PYANNOTE_REVISION,
                token=token,
                cache_dir=_pyannote_cache,
            )
            from app.config import config

            requested = config.speaker.diarization_device
            device = "cuda" if requested == "auto" and torch.cuda.is_available() else requested
            if device == "auto":
                device = "cpu"
            if device == "cuda" and not torch.cuda.is_available():
                logger.warning("[PYANNOTE] CUDA 不可用，回退 CPU")
                device = "cpu"
            self._pipeline.to(torch.device(device))
            self._device = device
            self._enabled = True
            logger.info("[PYANNOTE] 加载完成，设备=%s", device)
        except Exception as e:
            self._last_error = f"Community-1 加载失败: {e}"
            logger.error("[PYANNOTE] %s", self._last_error)
            self._enabled = False

    @property
    def enabled(self) -> bool:
        """是否可用(检查 HF_TOKEN + 模型是否加载成功)"""
        return self._enabled

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def device(self) -> str:
        return self._device

    def diarize(
        self,
        audio_path: str,
        *,
        waveform: "np.ndarray | None" = None,
        sample_rate: int | None = None,
    ) -> List[Tuple[float, float, str]]:
        """对音频做离线匿名说话人分离

        Args:
            audio_path: 本地音频路径(可由 librosa/soundfile 解码)。当
                waveform 未提供时用它解码。
            waveform: 调用方已加载的 1D float32 mono 波形。提供时直接
                复用,避免对同一段音频二次 librosa.load(长会议 ~576MB×2
                峰值)。采样率须与 sample_rate 一致。
            sample_rate: waveform 的采样率;未提供时回退到 16kHz。

        Returns:
            List of (start_sec, end_sec, speaker_id) — speaker_id 形如 "SPEAKER_00"
            失败时返回 []
        """
        if not self._enabled:
            return []
        if waveform is None and not Path(audio_path).exists():
            logger.warning(f"[PYANNOTE] 文件不存在: {audio_path}")
            return []
        try:
            import librosa
            import torch

            if waveform is not None:
                sr = int(sample_rate or 16000)
                raw_wave = np.asarray(waveform)
                if raw_wave.ndim != 1:
                    raise ValueError(
                        f"waveform must be 1D mono, got shape={raw_wave.shape}"
                    )
                if np.issubdtype(raw_wave.dtype, np.integer):
                    info = np.iinfo(raw_wave.dtype)
                    scale = float(max(abs(info.min), info.max))
                    wave = raw_wave.astype(np.float32) / scale
                else:
                    wave = raw_wave.astype(np.float32, copy=False)
            else:
                wave, sr = librosa.load(audio_path, sr=None, mono=True)
                wave = np.asarray(wave, dtype=np.float32)
            if int(sr) <= 0:
                raise ValueError(f"sample_rate must be positive, got {sr}")
            if wave.ndim != 1 or wave.size == 0:
                raise ValueError("waveform must be a non-empty 1D mono array")
            if not np.isfinite(wave).all():
                raise ValueError("waveform contains NaN or infinity")
            if float(np.max(np.abs(wave))) > 1.5:
                raise ValueError("float waveform level must be normalized near [-1, 1]")
            audio_input = {
                "waveform": torch.as_tensor(wave, dtype=torch.float32).unsqueeze(0),
                "sample_rate": int(sr),
            }
            output = self._pipeline(audio_input)
            annotation = getattr(
                output,
                "exclusive_speaker_diarization",
                None,
            )
            if annotation is None:
                annotation = getattr(output, "speaker_diarization", output)
            results = []
            for turn, _track, speaker in annotation.itertracks(yield_label=True):
                results.append((float(turn.start), float(turn.end), str(speaker)))
            logger.info(f"[PYANNOTE] {audio_path}: {len(results)} 个说话人段,识别出 {len(set(s[2] for s in results))} 个不同说话人")
            return results
        except Exception as e:
            self._last_error = f"说话人分离执行失败: {e}"
            logger.error("[PYANNOTE] %s", self._last_error)
            return []


def get_pyannote_diarizer() -> PyannoteDiarizer:
    """获取 pyannote 服务单例"""
    return PyannoteDiarizer()
