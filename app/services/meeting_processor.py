"""One processing path for every uploaded recording."""
from __future__ import annotations

import asyncio
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

from app.config import config
from app.services.audio_files import split_audio_into_chunks
from app.services.speaker_alignment import align_speakers_to_segments


logger = logging.getLogger("Matrix_MeetingProcessor")


def normalize_offline_asr_result(value: object, audio_duration: float) -> dict:
    """Offline jobs may only persist finalized provider hypotheses."""
    from engine.asr.contracts import normalize_asr_result

    result = normalize_asr_result(value, audio_duration=audio_duration)
    if not result["is_final"]:
        raise PermanentJobError(
            "ASR engine returned a non-final result for offline transcription"
        )
    return result


def merge_overlapping_text(previous: str, current: str, max_chars: int = 80) -> str:
    """Remove only an exact suffix/prefix overlap; never guess at fuzzy text."""
    previous = previous or ""
    current = current or ""
    limit = min(len(previous), len(current), max_chars)
    # range 终止于 1(不含),改为含 size=1 以去掉单字重叠(中文高频字"的/了/是"
    # 在 chunk 边界常出现)。单字去重有极小概率误删合法单字重复(如口吃"是是"),
    # 但 chunk 边界重叠区本就是衔接处,误删代价远低于不去重导致的整字重复。
    for size in range(limit, 0, -1):
        if previous[-size:] == current[:size]:
            return current[size:].lstrip()
    return current


class JobCancelled(Exception):
    pass


class PermanentJobError(RuntimeError):
    """A deterministic input/contract failure that automatic retry cannot fix."""


async def await_uninterruptible(awaitable):
    """Delay task cancellation until model work has actually left its worker.

    ``asyncio.to_thread`` and provider executors cannot stop their underlying
    thread when the awaiting coroutine is cancelled.  Letting cancellation
    unwind an inference-slot context at that point would make the same model
    available to another request (or close it during shutdown) while it is
    still in use.
    """
    task = asyncio.ensure_future(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except asyncio.CancelledError:
            # The child may implement real cancellation itself.  Either way it
            # has now stopped, so it is safe for the caller to release its slot.
            pass
        except Exception:
            # Cancellation is the externally visible outcome.  A provider
            # failure that happens while draining is still useful for logs but
            # must not turn shutdown into a retryable job failure.
            logger.debug("model work failed while draining cancellation", exc_info=True)
        raise


def _normalized_words(
    words: list[dict] | None,
    *,
    offset: float,
    lower: float,
    upper: float,
) -> list[dict] | None:
    if not words:
        return None
    output: list[dict] = []
    for word in words:
        text = str(word.get("text") or "")
        try:
            start = float(word.get("start", 0.0)) + offset
            end = float(word.get("end", word.get("start", 0.0))) + offset
        except (TypeError, ValueError):
            continue
        if not text or not math.isfinite(start) or not math.isfinite(end):
            continue
        start = min(upper, max(lower, start))
        end = min(upper, max(start, end))
        if end <= start:
            continue
        output.append({**word, "text": text, "start": start, "end": end})
    output.sort(key=lambda item: (item["start"], item["end"]))
    return output or None


def _text_from_words(words: list[dict], original: str = "") -> str:
    tokens = [str(word.get("text") or "") for word in words]
    if " " in original and all(not token.startswith(" ") for token in tokens):
        output = ""
        no_leading_space = set(",.!?;:%)]}，。！？；：、")
        for token in (item.strip() for item in tokens if item.strip()):
            if not output or token[0] in no_leading_space:
                output += token
            else:
                output += " " + token
        return output
    return "".join(tokens).strip()


def _trim_words_by_boundary(
    segment: dict, boundary: float, *, keep_before: bool
) -> dict | None:
    words = segment.get("words") or []
    if not words:
        return segment
    kept = [
        word for word in words
        if (((float(word["start"]) + float(word["end"])) / 2 <= boundary) == keep_before)
    ]
    if not kept:
        return None
    return {
        **segment,
        "text": _text_from_words(kept, str(segment.get("text") or "")),
        "start": float(kept[0]["start"]),
        "end": float(kept[-1]["end"]),
        "words": kept,
    }


def _remove_right_text_overlap(left_text: str, segment: dict) -> dict:
    """Trim an exact suffix/prefix overlap without desynchronizing words."""
    right_text = str(segment.get("text") or "")
    trimmed_text = merge_overlapping_text(left_text, right_text)
    removed = len(right_text) - len(trimmed_text)
    if removed <= 0:
        return segment
    words = segment.get("words") or []
    if not words:
        return {**segment, "text": trimmed_text}
    target = right_text[:removed].replace(" ", "")
    consumed = ""
    cut = 0
    for cut, word in enumerate(words, start=1):
        consumed += str(word.get("text") or "").replace(" ", "")
        if consumed == target:
            remaining = words[cut:]
            if not remaining:
                return {**segment, "text": "", "words": []}
            return {
                **segment,
                "text": _text_from_words(remaining, trimmed_text),
                "start": float(remaining[0]["start"]),
                "end": float(remaining[-1]["end"]),
                "words": remaining,
            }
        if not target.startswith(consumed):
            break
    # Token boundaries cannot prove the same removal. Preserve both views rather
    # than creating a text/words contradiction.
    return segment


def reconcile_chunk_boundary(
    previous: list[dict], current: list[dict], boundary: float
) -> tuple[list[dict], list[dict]]:
    """Give timestamped words on each side of an overlap one deterministic owner."""
    left: list[dict] = []
    for segment in previous:
        trimmed = _trim_words_by_boundary(segment, boundary, keep_before=True)
        if trimmed and str(trimmed.get("text") or "").strip():
            left.append(trimmed)
    right: list[dict] = []
    for segment in current:
        trimmed = _trim_words_by_boundary(segment, boundary, keep_before=False)
        if trimmed and str(trimmed.get("text") or "").strip():
            right.append(trimmed)
    if left and right:
        right[0] = _remove_right_text_overlap(left[-1]["text"], right[0])
        right = [item for item in right if str(item.get("text") or "").strip()]
    return left, right


def segments_from_asr_result(
    result: dict[str, Any], chunk_start: float, chunk_end: float
) -> list[dict]:
    """Convert one provider-neutral ASR result into absolute meeting time."""
    native_segments = result.get("segments") or []
    duration = max(0.0, chunk_end - chunk_start)
    origin = str(result.get("timestamp_origin") or "chunk")
    offset = 0.0 if origin == "stream" else chunk_start
    speaker_scope = str(result.get("speaker_scope") or "chunk")
    output: list[dict] = []
    for native in native_segments:
        text = str(native.get("text") or "").strip()
        if not text:
            continue
        try:
            local_start = float(native.get("start", 0.0))
            local_end = float(native.get("end", local_start))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(local_start) or not math.isfinite(local_end):
            continue
        if origin == "chunk":
            local_start = min(duration, max(0.0, local_start))
            local_end = min(duration, max(local_start, local_end))
        start = min(chunk_end, max(chunk_start, local_start + offset))
        end = min(chunk_end, max(start, local_end + offset))
        if end <= start:
            continue
        output.append({
            "start": start,
            "end": end,
            "text": text,
            "speaker": native.get("speaker") if speaker_scope == "stream" else None,
            "words": _normalized_words(
                native.get("words"), offset=offset, lower=start, upper=end
            ),
        })
    if output:
        return output

    text = str(result.get("text") or "").strip()
    if not text:
        return []
    words = _normalized_words(
        result.get("words"), offset=offset, lower=chunk_start, upper=chunk_end
    )
    if words:
        start = min(float(word["start"]) for word in words)
        end = max(float(word["end"]) for word in words)
    else:
        start, end = chunk_start, chunk_end
    return [{
        "start": start,
        "end": end,
        "text": text,
        "speaker": None,
        "words": words,
    }]


def _engine_provenance(engine: object) -> dict[str, str]:
    engine_type = str(getattr(engine, "kind", engine.__class__.__name__))
    model = getattr(engine, "_model_name", None)
    if not isinstance(model, str):
        model = getattr(engine, "model_id", None)
    result = {"engine": engine_type}
    if isinstance(model, str) and model:
        result["model"] = model
    return result


def _asr_provenance(engine: object) -> dict[str, str]:
    result = _engine_provenance(engine)
    try:
        from engine.asr.factory import get_asr_engine_info

        info = get_asr_engine_info(config.audio.asr_engine)
        result["engine"] = str(info.get("type") or config.audio.asr_engine)
        if info.get("model"):
            result["model"] = str(info["model"])
    except Exception:
        logger.debug("ASR provenance metadata unavailable", exc_info=True)
    return result


def _speaker_provenance(engine: object) -> dict[str, str]:
    result = _engine_provenance(engine)
    try:
        from engine.speaker.speaker_factory import embedding_model_id, engine_type_for

        result["engine"] = engine_type_for(engine) or result["engine"]
        result["model_id"] = embedding_model_id(engine)
    except Exception:
        logger.debug("Speaker provenance metadata unavailable", exc_info=True)
    return result


@dataclass
class MeetingProcessor:
    meeting_repo: object
    job_repo: object
    runtime: object
    people_repo: object | None = None

    async def __call__(self, job: dict) -> None:
        engines = self.runtime.snapshot()
        job_id = job["id"]
        meeting_id = job["meeting_id"]
        meeting = self.meeting_repo.get(meeting_id)
        if meeting is None:
            raise PermanentJobError("meeting not found")
        audio_path = meeting.get("audio_path")
        if not audio_path or not os.path.isfile(audio_path):
            raise PermanentJobError("meeting audio not found")

        await self._checkpoint(job_id, "decoding", 5)
        import librosa

        audio, _ = await asyncio.to_thread(
            librosa.load, audio_path, sr=config.audio.sample_rate, mono=True
        )
        if len(audio) == 0:
            raise PermanentJobError("audio contains no samples")
        duration = len(audio) / config.audio.sample_rate
        self.meeting_repo.update(
            meeting_id, status="processing", duration_sec=duration, error_message=None
        )

        chunks = split_audio_into_chunks(
            np.asarray(audio, dtype=np.float32),
            config.audio.sample_rate,
            config.audio.upload_chunk_duration,
            config.audio.upload_overlap_duration,
        )
        asr_segments: list[dict] = []
        observed_granularities: set[str] = set()
        observed_languages: set[str] = set()
        for index, (chunk, start, end) in enumerate(chunks):
            progress = 10 + round(60 * (index / max(1, len(chunks))))
            await self._checkpoint(job_id, "transcribing", progress)
            async with self.runtime.inference.offline():
                result = await await_uninterruptible(
                    engines.asr.run_asr(chunk, use_preprocessing=True)
                )
            result = normalize_offline_asr_result(
                result, audio_duration=len(chunk) / config.audio.sample_rate
            )
            observed_granularities.add(str(result.get("timestamp_granularity", "none")))
            if result.get("language"):
                observed_languages.add(str(result["language"]))
            chunk_segments = segments_from_asr_result(result, start, end)
            if asr_segments and chunk_segments:
                previous_chunk_end = chunks[index - 1][2]
                boundary = (previous_chunk_end + start) / 2.0
                asr_segments, chunk_segments = reconcile_chunk_boundary(
                    asr_segments, chunk_segments, boundary
                )
            asr_segments.extend(
                segment for segment in chunk_segments if segment["text"].strip()
            )

        final_segments = asr_segments
        alignment_method = "none"
        if meeting.get("processing_mode") == "meeting":
            if (
                meeting.get("source") == "upload"
                and meeting.get("transcript_state") == "draft"
                and asr_segments
            ):
                await self._checkpoint(job_id, "publishing-draft", 72)
                self.meeting_repo.replace_generated_transcript(
                    meeting_id,
                    [
                        {
                            "segment_index": index,
                            "text": str(segment.get("text") or ""),
                            "start_time": float(segment.get("start", 0)),
                            "end_time": float(segment.get("end", 0)),
                            "speaker_label": None,
                            "confidence": segment.get("confidence"),
                            "words": segment.get("words"),
                        }
                        for index, segment in enumerate(asr_segments)
                        if str(segment.get("text") or "").strip()
                    ],
                )
            await self._checkpoint(job_id, "identifying-speakers", 75)
            async with self.runtime.inference.offline():
                final_segments, diarization_status, diarization_error = (
                    await await_uninterruptible(
                        asyncio.to_thread(
                            self._offline_diarize, audio_path, asr_segments, audio,
                        )
                    )
                )
            self.meeting_repo.update(
                meeting_id,
                diarization_status=diarization_status,
                diarization_error=diarization_error,
            )
            alignment_method = (
                "word-overlap"
                if any(segment.get("words") for segment in asr_segments)
                else "segment-overlap"
            ) if diarization_status == "completed" else "anonymous"

        await self._checkpoint(job_id, "saving", 92)
        # 全部 chunk 转写后无任何有效文本:音频过短或纯静音。
        # 不应标记 ready,落 failed 让用户知道转写未产出。
        if not final_segments and not asr_segments:
            raise PermanentJobError("音频过短或未识别到有效语音")
        generated_at = datetime.now(timezone.utc).isoformat()
        manifest = {
            "version": 1,
            "strategy": "external-diarization" if alignment_method not in {"none", "anonymous"} else "transcription-only",
            "asr": {
                **_asr_provenance(engines.asr),
                "timestamp_granularity": max(
                    observed_granularities or {"none"},
                    key={"none": 0, "segment": 1, "word": 2}.get,
                ),
                "language": next(iter(observed_languages), None),
            },
            "diarization": {
                "provider": "pyannote-community-1" if meeting.get("processing_mode") == "meeting" else None,
                "status": diarization_status if meeting.get("processing_mode") == "meeting" else "not_requested",
                "alignment": alignment_method,
            },
            "speaker_identity": _speaker_provenance(engines.speaker) if engines.speaker is not None else None,
            "generated_at": generated_at,
        }
        replacement = [
            {
                "segment_index": index,
                "text": str(segment.get("text") or ""),
                "start_time": float(segment.get("start", 0)),
                "end_time": float(segment.get("end", 0)),
                "speaker_label": segment.get("speaker"),
                "confidence": segment.get("confidence"),
                "words": segment.get("words"),
            }
            for index, segment in enumerate(final_segments)
            if str(segment.get("text") or "").strip()
        ]
        self.meeting_repo.replace_generated_transcript(
            meeting_id, replacement, processing_manifest=manifest
        )
        if self.people_repo is not None and engines.speaker is not None:
            try:
                await self._match_known_people(
                    meeting_id, audio, final_segments, engines.speaker
                )
            except Exception:
                logger.warning(
                    "人物声纹建议生成失败；保留已完成的会议文稿",
                    exc_info=True,
                )
        # meeting ready 与 job completed 同事务,避免崩溃窗口 ready+job_running
        # 矛盾态(recover 把 running 回 queued 重跑会把 ready 降级回 processing)。
        # 用 getattr 兼容旧 fake repo(无 mark_completed 时回退多步提交)。
        mark_completed = getattr(self.meeting_repo, "mark_completed", None)
        if mark_completed is not None:
            mark_completed(
                meeting_id,
                job_id,
                datetime.now(timezone.utc).isoformat(),
            )
        else:
            self.meeting_repo.update(meeting_id, status="ready", error_message=None)
            self.job_repo.update(
                job_id,
                status="completed",
                stage="completed",
                progress=100,
                finished_at=datetime.now(timezone.utc).isoformat(),
            )

    def _offline_diarize(
        self,
        audio_path: str,
        segments: list[dict],
        audio: np.ndarray | None = None,
    ) -> tuple[list[dict], str, str | None]:
        """离线说话人分离。

        audio 为调用方已加载的波形时直接复用,避免 pyannote 内部二次
        librosa.load(长会议峰值内存从 ~1.2GB 降到 ~576MB)。audio 为 None
        时回退到从 audio_path 解码。
        """
        try:
            from app.services.pyannote_diarization import get_pyannote_diarizer

            diarizer = get_pyannote_diarizer()
            if diarizer.enabled:
                if audio is not None:
                    turns = diarizer.diarize(
                        audio_path,
                        waveform=audio,
                        sample_rate=config.audio.sample_rate,
                    )
                else:
                    turns = diarizer.diarize(audio_path)
                if turns:
                    return align_speakers_to_segments(turns, segments), "completed", None
                return segments, "unavailable", (
                    diarizer.last_error or "未检测到可用的说话人片段"
                )
            return segments, "unavailable", (
                getattr(diarizer, "last_error", None) or "说话人分离模型未配置"
            )
        except Exception as exc:
            logger.warning("说话人分离不可用: %s", exc)
            return segments, "unavailable", str(exc)[:500]

    async def _checkpoint(self, job_id: str, stage: str, progress: int) -> None:
        job = self.job_repo.get(job_id)
        if job is None or job.get("cancel_requested"):
            raise JobCancelled()
        self.job_repo.update(job_id, stage=stage, progress=progress)

    async def _match_known_people(
        self,
        meeting_id: str,
        audio: np.ndarray,
        segments: list[dict],
        speaker_engine: object,
    ) -> None:
        from app.services.voice_matcher import classify_person_match
        from engine.speaker.speaker_factory import embedding_model_id

        sample_rate = config.audio.sample_rate
        grouped: dict[str, list[tuple[np.ndarray, float]]] = {}
        for segment in segments:
            label = segment.get("speaker")
            if not label:
                continue
            start = max(0, int(float(segment.get("start", 0)) * sample_rate))
            end = min(len(audio), int(float(segment.get("end", 0)) * sample_rate))
            duration = (end - start) / sample_rate
            if duration >= 1.0:
                grouped.setdefault(str(label), []).append((audio[start:end], duration))
        for label, pieces in grouped.items():
            # Discontinuous turns must not be concatenated into an artificial
            # waveform. Use a bounded, duration-weighted prototype instead.
            pieces = sorted(pieces, key=lambda item: item[1], reverse=True)[:8]
            if sum(duration for _, duration in pieces) < 2.0:
                continue
            vectors: list[np.ndarray] = []
            weights: list[float] = []
            successful_durations: list[float] = []
            for speaker_audio, duration in pieces:
                async with self.runtime.inference.offline():
                    result = await await_uninterruptible(
                        asyncio.to_thread(
                            speaker_engine.extract_feat,
                            np.asarray(speaker_audio, dtype=np.float32),
                        )
                    )
                embedding = result[0] if isinstance(result, tuple) else result
                if embedding is None:
                    continue
                vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
                norm = float(np.linalg.norm(vector))
                if not np.isfinite(vector).all() or norm <= 1e-6:
                    continue
                vectors.append(vector / norm)
                weights.append(min(duration, 10.0))
                successful_durations.append(duration)
            if not vectors:
                continue
            vector = np.average(np.stack(vectors), axis=0, weights=weights)
            vector = vector / (np.linalg.norm(vector) + 1e-6)
            model_id = embedding_model_id(speaker_engine, int(vector.size))
            samples = self.people_repo.matching_samples(model_id, int(vector.size))
            threshold, margin = config.speaker.person_match_policy(model_id)
            auto_threshold, auto_margin = config.speaker.person_auto_match_policy(
                model_id
            )
            decision = classify_person_match(
                vector,
                samples,
                model_id=model_id,
                speech_duration=sum(successful_durations),
                suggestion_threshold=threshold,
                suggestion_margin=margin,
                auto_threshold=auto_threshold,
                auto_margin=auto_margin,
            )
            if decision.person_id:
                self.meeting_repo.suggest_speaker(
                    meeting_id,
                    label,
                    decision.person_id,
                    decision.score,
                    identity_status=decision.status,
                )
