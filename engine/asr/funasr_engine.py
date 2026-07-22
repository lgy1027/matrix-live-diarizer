"""FunASR 系列 ASR 引擎适配器."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import numpy as np

from .common import evaluate_audio_quality, rms_is_silent
from .contracts import ASRResult, ASRSegment, ASRWord, empty_asr_result, make_asr_result

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
        # FunASR AutoModel 内部经 modelscope 下多个模型(SenseVoice + fsmn-vad +
        # punc),无法逐个物化到干净目录。改为加载期间把 MODELSCOPE_CACHE 临时
        # scope 到 models/funasr/,加载后恢复,不影响声纹引擎的缓存路径。
        import os as _os
        from app.services.model_resolver import models_root
        _funasr_cache = _os.path.join(models_root(), "funasr")
        _os.makedirs(_funasr_cache, exist_ok=True)
        _old_ms_cache = _os.environ.get("MODELSCOPE_CACHE")
        _os.environ["MODELSCOPE_CACHE"] = _funasr_cache
        # FunASR AutoModel 内部走 modelscope:本地缓存命中则离线加载,否则首次联网下载。
        _cached_models = _os.path.isdir(_os.path.join(_funasr_cache, "hub", "models"))
        logger.info(
            "[FunASR] MODELSCOPE_CACHE scope → %s (本地%s,首次会联网下载)",
            _funasr_cache, "已缓存,离线加载" if _cached_models else "无缓存",
        )
        try:
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
        finally:
            # 恢复 MODELSCOPE_CACHE,避免影响后续声纹引擎缓存路径
            if _old_ms_cache is None:
                _os.environ.pop("MODELSCOPE_CACHE", None)
            else:
                _os.environ["MODELSCOPE_CACHE"] = _old_ms_cache

    def is_silent(self, audio_data, threshold=0.012, use_vad=True):
        return rms_is_silent(audio_data, threshold=threshold)

    def evaluate_audio_quality(self, audio_data: np.ndarray) -> dict:
        return evaluate_audio_quality(audio_data)

    async def run_asr(self, audio_data, use_preprocessing=True):
        if audio_data is None or len(audio_data) < 1600:
            return empty_asr_result()
        quality = self.evaluate_audio_quality(audio_data)
        if quality["score"] < 30:
            logger.warning(f"[ASR] 音频质量较差: {quality}")
            return empty_asr_result()
        if self.is_silent(audio_data):
            return empty_asr_result()

        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, self._transcribe_sync, audio_data)
        except Exception as e:
            logger.error(f"[ASR] FunASR 推理异常: {e}")
            return empty_asr_result()

    def _transcribe_sync(self, audio_data: np.ndarray) -> ASRResult:
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
        result = self._normalize_result(res)
        if (
            self.kind == "sensevoice"
            and self._postprocess is not None
            and not result.get("words")
            and not result.get("segments")
        ):
            try:
                result["text"] = self._postprocess(result["text"])
            except Exception:
                logger.debug("[ASR] SenseVoice rich postprocess failed", exc_info=True)
        result["text"] = result["text"].strip()
        return result

    @classmethod
    def _normalize_result(cls, result: Any) -> ASRResult:
        """Normalize portable fields while retaining FunASR-specific metadata.

        FunASR timestamps are milliseconds. Pair-only timestamp arrays are kept in
        provider metadata because assigning them to text tokens would require a
        provider tokenizer and guessing here would corrupt alignment.
        """
        if not result:
            return empty_asr_result()
        items = result if isinstance(result, list) else [result]
        text_parts: list[str] = []
        words: list[ASRWord] = []
        segments: list[ASRSegment] = []
        language: str | None = None
        native_items: list[dict[str, Any]] = []

        for raw_item in items:
            if not isinstance(raw_item, dict):
                text_parts.append(str(raw_item or ""))
                continue
            item_text = str(raw_item.get("text", "") or "")
            text_parts.append(item_text)
            if language is None and raw_item.get("language"):
                language = str(raw_item["language"])

            item_words = cls._explicit_words(raw_item.get("timestamp"))
            words.extend(item_words)
            sentence_info = raw_item.get("sentence_info")
            if isinstance(sentence_info, list):
                for sentence in sentence_info:
                    segment = cls._sentence_segment(sentence)
                    if segment is not None:
                        segments.append(segment)
            elif all(key in raw_item for key in ("start", "end")) and item_text:
                segments.append(cls._segment_from_values(raw_item, item_text, item_words))

            preserved = {
                key: cls._to_builtin(raw_item[key])
                for key in (
                    "key", "timestamp", "sentence_info", "speaker", "spk", "language"
                )
                if key in raw_item
            }
            if preserved:
                native_items.append(preserved)

        metadata = {"provider": "funasr", "items": native_items} if native_items else None
        return make_asr_result(
            "".join(text_parts),
            words=words or None,
            segments=segments or None,
            language=language,
            provider_metadata=metadata,
        )

    @classmethod
    def _sentence_segment(cls, value: Any) -> ASRSegment | None:
        if not isinstance(value, dict):
            return None
        text = str(value.get("text", "") or "")
        if not text or "start" not in value or "end" not in value:
            return None
        return cls._segment_from_values(
            value, text, cls._explicit_words(value.get("timestamp"))
        )

    @classmethod
    def _segment_from_values(
        cls, value: dict[str, Any], text: str, words: list[ASRWord]
    ) -> ASRSegment:
        speaker = value.get("speaker", value.get("spk"))
        return {
            "text": text,
            "start": cls._milliseconds_to_seconds(value.get("start")),
            "end": cls._milliseconds_to_seconds(value.get("end")),
            "speaker": str(speaker) if speaker is not None else None,
            "words": words or None,
        }

    @classmethod
    def _explicit_words(cls, timestamps: Any) -> list[ASRWord]:
        if not isinstance(timestamps, (list, tuple)):
            return []
        words: list[ASRWord] = []
        for item in timestamps:
            text: Any = None
            start: Any = None
            end: Any = None
            if isinstance(item, dict):
                text = item.get("text", item.get("word", item.get("token")))
                start, end = item.get("start"), item.get("end")
            elif isinstance(item, (list, tuple)) and len(item) >= 3 and isinstance(item[0], str):
                text, start, end = item[0], item[1], item[2]
            if text is None or start is None or end is None:
                continue
            words.append({
                "text": str(text),
                "start": cls._milliseconds_to_seconds(start),
                "end": cls._milliseconds_to_seconds(end),
            })
        return words

    @staticmethod
    def _milliseconds_to_seconds(value: Any) -> float:
        try:
            return float(value) / 1000.0
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _to_builtin(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._to_builtin(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._to_builtin(item) for item in value]
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        return value

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
