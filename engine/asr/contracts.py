"""Stable, provider-neutral result contract shared by all ASR engines."""
from __future__ import annotations

from typing import Any, Literal, TypedDict
import math


TimestampGranularity = Literal["none", "segment", "word"]
TimestampOrigin = Literal["chunk", "stream"]
SpeakerScope = Literal["none", "chunk", "stream"]
ASRMode = Literal["batch", "segmented", "streaming"]


class ASRWord(TypedDict):
    text: str
    start: float
    end: float


class ASRSegment(TypedDict):
    text: str
    start: float
    end: float
    speaker: str | None
    words: list[ASRWord] | None


class ASRResult(TypedDict):
    """Dictionary contract kept compatible with existing ``result.get`` callers."""

    text: str
    words: list[ASRWord] | None
    segments: list[ASRSegment] | None
    timestamp_granularity: TimestampGranularity
    language: str | None
    provider_metadata: dict[str, Any] | None
    timestamp_unit: Literal["seconds"]
    timestamp_origin: TimestampOrigin
    speaker_scope: SpeakerScope
    mode: ASRMode
    is_final: bool


def make_asr_result(
    text: str = "",
    *,
    words: list[ASRWord] | None = None,
    segments: list[ASRSegment] | None = None,
    language: str | None = None,
    provider_metadata: dict[str, Any] | None = None,
    timestamp_origin: TimestampOrigin = "chunk",
    speaker_scope: SpeakerScope = "none",
    mode: ASRMode = "segmented",
    is_final: bool = True,
) -> ASRResult:
    """Create a complete result and derive its strongest timestamp granularity."""
    if words:
        granularity: TimestampGranularity = "word"
    elif segments:
        granularity = "segment"
    else:
        granularity = "none"
    return {
        "text": str(text or ""),
        "words": words or None,
        "segments": segments or None,
        "timestamp_granularity": granularity,
        "language": str(language) if language else None,
        "provider_metadata": provider_metadata or None,
        "timestamp_unit": "seconds",
        "timestamp_origin": timestamp_origin,
        "speaker_scope": speaker_scope,
        "mode": mode,
        "is_final": bool(is_final),
    }


def empty_asr_result() -> ASRResult:
    return make_asr_result()


def normalize_asr_result(
    value: object, *, audio_duration: float | None = None
) -> ASRResult:
    """Validate provider output at the adapter boundary.

    All internal timestamps are finite seconds. Chunk-relative timestamps are
    clamped to the supplied audio duration; stream-relative timestamps are only
    checked for ordering because their upper bound belongs to the session.
    """
    raw = value if isinstance(value, dict) else {"text": str(value or "")}
    origin: TimestampOrigin = (
        raw.get("timestamp_origin")
        if raw.get("timestamp_origin") in {"chunk", "stream"}
        else "chunk"
    )
    scope: SpeakerScope = (
        raw.get("speaker_scope")
        if raw.get("speaker_scope") in {"none", "chunk", "stream"}
        else "none"
    )
    mode: ASRMode = (
        raw.get("mode")
        if raw.get("mode") in {"batch", "segmented", "streaming"}
        else "segmented"
    )

    def interval(item: dict) -> tuple[float, float] | None:
        try:
            start = float(item.get("start", 0.0))
            end = float(item.get("end", start))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(start) or not math.isfinite(end):
            return None
        start = max(0.0, start)
        end = max(start, end)
        if origin == "chunk" and audio_duration is not None:
            upper = max(0.0, float(audio_duration))
            start = min(start, upper)
            end = min(max(start, end), upper)
        if end <= start:
            return None
        return start, end

    words: list[ASRWord] = []
    for item in raw.get("words") or []:
        if not isinstance(item, dict) or not str(item.get("text") or ""):
            continue
        bounds = interval(item)
        if bounds:
            words.append({"text": str(item["text"]), "start": bounds[0], "end": bounds[1]})
    words.sort(key=lambda item: (item["start"], item["end"]))

    segments: list[ASRSegment] = []
    for item in raw.get("segments") or []:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        bounds = interval(item)
        if not bounds:
            continue
        segment_words: list[ASRWord] = []
        for word in item.get("words") or []:
            if not isinstance(word, dict) or not str(word.get("text") or ""):
                continue
            word_bounds = interval(word)
            if word_bounds:
                segment_words.append({
                    "text": str(word["text"]),
                    "start": word_bounds[0],
                    "end": word_bounds[1],
                })
        segments.append({
            "text": str(item["text"]).strip(),
            "start": bounds[0],
            "end": bounds[1],
            "speaker": str(item["speaker"]) if item.get("speaker") is not None else None,
            "words": segment_words or None,
        })
    segments.sort(key=lambda item: (item["start"], item["end"]))
    return make_asr_result(
        str(raw.get("text") or ""),
        words=words or None,
        segments=segments or None,
        language=raw.get("language"),
        provider_metadata=raw.get("provider_metadata"),
        timestamp_origin=origin,
        speaker_scope=scope,
        mode=mode,
        is_final=raw.get("is_final", True) is True,
    )
