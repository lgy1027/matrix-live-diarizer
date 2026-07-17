"""Capability-safe reconciliation of ASR text and anonymous speaker turns."""
from __future__ import annotations

from collections import defaultdict
import re
from typing import Iterable


SpeakerTurn = tuple[float, float, str]


def _join_text(left: str, right: str) -> str:
    if not left or not right or left[-1].isspace() or right[0].isspace():
        return f"{left}{right}"
    # Preserve token separation for Latin/digit transcripts while Chinese and
    # punctuation remain naturally concatenated.
    if re.match(r"[A-Za-z0-9]", left[-1]) and re.match(r"[A-Za-z0-9]", right[0]):
        return f"{left} {right}"
    return f"{left}{right}"


def _valid_turns(turns: Iterable[SpeakerTurn]) -> list[SpeakerTurn]:
    normalized = [
        (float(start), float(end), str(speaker))
        for start, end, speaker in turns
        if float(end) > float(start) and str(speaker)
    ]
    return sorted(normalized, key=lambda item: (item[0], item[1], item[2]))


def _speaker_for_interval(
    start: float,
    end: float,
    turns: list[SpeakerTurn],
    *,
    gap_tolerance: float,
) -> tuple[str | None, str]:
    overlap_by_speaker: dict[str, float] = defaultdict(float)
    for turn_start, turn_end, speaker in turns:
        overlap = min(end, turn_end) - max(start, turn_start)
        if overlap > 0:
            overlap_by_speaker[speaker] += overlap
    if overlap_by_speaker:
        speaker = max(
            overlap_by_speaker,
            key=lambda item: (overlap_by_speaker[item], item),
        )
        return speaker, "pyannote-segment-overlap"

    nearest: tuple[float, str] | None = None
    for turn_start, turn_end, speaker in turns:
        distance = max(turn_start - end, start - turn_end, 0.0)
        candidate = (distance, speaker)
        if nearest is None or candidate < nearest:
            nearest = candidate
    if nearest is not None and nearest[0] <= gap_tolerance:
        return nearest[1], "pyannote-nearest"
    return None, "fallback"


def _absolute_words(segment: dict) -> list[dict]:
    words = segment.get("words") or []
    if not words:
        return []
    start = float(segment.get("start", 0.0))
    end = float(segment.get("end", start))
    duration = max(0.0, end - start)
    word_ends = [float(word.get("end", 0.0)) for word in words]
    relative = start > 0 and max(word_ends, default=0.0) <= duration + 1e-6
    normalized = []
    for word in words:
        copied = dict(word)
        copied["start"] = float(copied.get("start", 0.0)) + (start if relative else 0.0)
        copied["end"] = float(copied.get("end", copied["start"])) + (
            start if relative else 0.0
        )
        normalized.append(copied)
    return normalized


def _merge_adjacent(segments: list[dict], *, gap_tolerance: float) -> list[dict]:
    merged: list[dict] = []
    for segment in segments:
        if not str(segment.get("text") or "").strip():
            continue
        if (
            merged
            and merged[-1].get("speaker") == segment.get("speaker")
            and float(segment.get("start", 0.0))
            <= float(merged[-1].get("end", 0.0)) + gap_tolerance
        ):
            previous = merged[-1]
            previous["end"] = max(
                float(previous.get("end", 0.0)), float(segment.get("end", 0.0))
            )
            previous["text"] = _join_text(
                str(previous.get("text", "")), str(segment.get("text", ""))
            )
            if previous.get("words") is not None and segment.get("words") is not None:
                previous["words"] = [*previous.get("words", []), *segment.get("words", [])]
            else:
                previous.pop("words", None)
            continue
        merged.append(dict(segment))
    return merged


def align_speakers_to_segments(
    diarization_segments: list[SpeakerTurn],
    asr_segments: list[dict],
    *,
    gap_tolerance: float = 0.75,
) -> list[dict]:
    """Assign text to speakers without inventing text inside silence.

    Word-timestamped ASR may be split at word boundaries. Segment-only ASR is
    never split: the complete segment is assigned to the speaker with greatest
    temporal overlap, or conservatively left unchanged when no nearby speaker
    evidence exists.
    """
    turns = _valid_turns(diarization_segments)
    if not turns:
        return [dict(segment) for segment in asr_segments]

    output: list[dict] = []
    for original in asr_segments:
        segment = dict(original)
        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", start))
        words = _absolute_words(segment)
        dominant_speaker, dominant_source = _speaker_for_interval(
            start, end, turns, gap_tolerance=gap_tolerance
        )

        if not words:
            if dominant_speaker is not None:
                segment["speaker"] = dominant_speaker
                segment["diarization_source"] = dominant_source
            else:
                segment["diarization_source"] = "fallback"
            segment.pop("words", None)
            output.append(segment)
            continue

        groups: list[dict] = []
        for word in words:
            word_start = float(word.get("start", start))
            word_end = float(word.get("end", word_start))
            speaker, source = _speaker_for_interval(
                word_start, word_end, turns, gap_tolerance=gap_tolerance
            )
            if speaker is None:
                speaker = dominant_speaker or segment.get("speaker")
                source = dominant_source if dominant_speaker else "fallback"
            if groups and groups[-1]["speaker"] == speaker:
                groups[-1]["words"].append(word)
                groups[-1]["end"] = word_end
            else:
                groups.append({
                    "speaker": speaker,
                    "source": source,
                    "start": word_start,
                    "end": word_end,
                    "words": [word],
                })

        for group in groups:
            item = dict(segment)
            item.update({
                "start": group["start"],
                "end": group["end"],
                "speaker": group["speaker"],
                "diarization_source": "pyannote-word-overlap"
                if group["source"] != "fallback"
                else "fallback",
                "words": group["words"],
                "text": "".join(str(word.get("text", "")) for word in group["words"]),
            })
            output.append(item)

    return _merge_adjacent(output, gap_tolerance=gap_tolerance)
