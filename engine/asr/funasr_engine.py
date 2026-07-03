"""FunASR 系列 ASR 引擎适配器."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np

from .common import evaluate_audio_quality, filter_hallucinations, rms_is_silent

logger = logging.getLogger("ASR_Engine")


class FunASREngine:
    """SenseVoice / Paraformer 统一适配器.

    FunASR 是可选依赖。只有 ASR_ENGINE=sensevoice / paraformer /
    paraformer_streaming 时才会 import,默认 Qwen 路径不受影响。
    """

    _instances: dict[str, "FunASREngine"] = {}

    def __new__(cls, kind: str = "sensevoice"):
        key = kind.lower()
        if key not in cls._instances:
            inst = super().__new__(cls)
            inst.initialized = False
            cls._instances[key] = inst
        return cls._instances[key]

    def __init__(self, kind: str = "sensevoice"):
        if self.initialized:
            return
        self.kind = kind.lower()
        from app.config import config
        self.config = config.audio
        self.sample_rate = config.audio.sample_rate
        self.device = self._resolve_device(config.audio.asr_device)
        self.model = None
        self._postprocess = None

        try:
            self._load_model()
            self.initialized = True
            logger.info(f"[ASR] FunASR {self.kind} 加载成功 device={self.device}")
        except ImportError as e:
            raise RuntimeError(
                "ASR_ENGINE 选择了 FunASR 引擎,但未安装 funasr。请执行: pip install funasr"
            ) from e

    @staticmethod
    def _resolve_device(requested: str) -> str:
        requested = (requested or "auto").lower()
        if requested == "auto":
            try:
                import torch
                if torch.cuda.is_available():
                    return "cuda:0"
                if torch.backends.mps.is_available():
                    return "mps"
            except Exception:
                pass
            return "cpu"
        if requested == "cuda":
            return "cuda:0"
        return requested

    def _load_model(self) -> None:
        from funasr import AutoModel
        try:
            from funasr.utils.postprocess_utils import rich_transcription_postprocess
        except Exception:
            rich_transcription_postprocess = None
        self._postprocess = rich_transcription_postprocess

        if self.kind == "sensevoice":
            self.model = AutoModel(
                model="iic/SenseVoiceSmall",
                vad_model="fsmn-vad",
                vad_kwargs={"max_single_segment_time": 30000},
                device=self.device,
            )
        elif self.kind == "paraformer":
            self.model = AutoModel(
                model="paraformer-zh",
                vad_model="fsmn-vad",
                punc_model="ct-punc",
                vad_kwargs={"max_single_segment_time": 30000},
                device=self.device,
            )
        elif self.kind == "paraformer_streaming":
            self.model = AutoModel(
                model="paraformer-zh-streaming",
                device=self.device,
            )
        else:
            raise ValueError(f"Unsupported FunASR kind: {self.kind}")

    def is_silent(self, audio_data, threshold=0.012, use_vad=True):
        return rms_is_silent(audio_data, threshold=threshold)

    def evaluate_audio_quality(self, audio_data: np.ndarray) -> dict:
        return evaluate_audio_quality(audio_data)

    async def run_asr(self, audio_data, use_preprocessing=True):
        if audio_data is None or len(audio_data) < 1600:
            return {"text": "", "words": None}
        quality = self.evaluate_audio_quality(audio_data)
        if quality["score"] < 30:
            logger.warning(f"[ASR] 音频质量较差: {quality}")
            return {"text": "", "words": None}
        if self.is_silent(audio_data):
            return {"text": "", "words": None}

        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, self._transcribe_sync, audio_data)
        return {"text": filter_hallucinations(text), "words": None}

    def _transcribe_sync(self, audio_data: np.ndarray) -> str:
        kwargs: dict[str, Any] = {"input": audio_data.astype(np.float32)}
        if self.kind == "sensevoice":
            kwargs.update({
                "language": "auto",
                "use_itn": True,
                "batch_size_s": 60,
                "merge_vad": True,
                "merge_length_s": 15,
            })
        elif self.kind == "paraformer":
            kwargs.update({
                "batch_size_s": 60,
                "merge_vad": True,
                "merge_length_s": 15,
            })
        else:
            kwargs.update({
                "cache": {},
                "is_final": True,
                "chunk_size": [0, 10, 5],
                "encoder_chunk_look_back": 4,
                "decoder_chunk_look_back": 1,
            })

        res = self.model.generate(**kwargs)
        text = self._extract_text(res)
        if self.kind == "sensevoice" and self._postprocess is not None:
            try:
                text = self._postprocess(text)
            except Exception:
                logger.debug("[ASR] SenseVoice rich postprocess failed", exc_info=True)
        return text.strip()

    @staticmethod
    def _extract_text(result: Any) -> str:
        if not result:
            return ""
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return str(result.get("text", "") or "")
        if isinstance(result, list):
            parts = []
            for item in result:
                if isinstance(item, dict):
                    parts.append(str(item.get("text", "") or ""))
                else:
                    parts.append(str(item or ""))
            return "".join(parts)
        return str(result)
