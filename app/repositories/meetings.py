"""Product-facing meeting repository."""
from __future__ import annotations
import json
import logging
import re
import sqlite3
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Optional

from .database import Database

logger = logging.getLogger("Matrix_Meetings")


class SpeakerNotFoundError(Exception):
    """目标说话人不存在(API 层据此返 404 而非 400)。"""


def _interval_overlap_seconds(
    left: list[tuple[float, float]], right: list[tuple[float, float]]
) -> float:
    return sum(
        max(0.0, min(left_end, right_end) - max(left_start, right_start))
        for left_start, left_end in left
        for right_start, right_end in right
    )


def _merge_intervals(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def _confirmed_identity_mapping(
    speakers: list[dict],
    old_intervals: dict[str, list[tuple[float, float]]],
    segments: list[dict],
    *,
    min_coverage: float = 0.60,
    min_margin: float = 0.15,
) -> dict[str, str]:
    """Map new diarization labels to confirmed people using timeline evidence.

    Provider labels are arbitrary and may swap between runs. A previous person
    is inherited only when one previously confirmed person clearly owns most
    of the new label's speech. Multiple old labels confirmed as the same person
    are one candidate, not competing identities. Ambiguous mappings become
    anonymous.
    """
    new_intervals: dict[str, list[tuple[float, float]]] = {}
    for segment in segments:
        label = segment.get("speaker_label")
        if label is None:
            continue
        new_intervals.setdefault(str(label), []).append(
            (float(segment["start_time"]), float(segment["end_time"]))
        )
    person_intervals: dict[str, list[tuple[float, float]]] = {}
    for speaker in speakers:
        if not speaker.get("manually_confirmed") or not speaker.get("person_id"):
            continue
        person_intervals.setdefault(str(speaker["person_id"]), []).extend(
            old_intervals.get(str(speaker["id"]), [])
        )
    person_intervals = {
        person_id: _merge_intervals(intervals)
        for person_id, intervals in person_intervals.items()
    }
    mapping: dict[str, str] = {}
    for label, intervals in new_intervals.items():
        new_duration = sum(max(0.0, end - start) for start, end in intervals)
        ranked: list[tuple[float, str]] = []
        for person_id, previous in person_intervals.items():
            old_duration = sum(max(0.0, end - start) for start, end in previous)
            denominator = min(new_duration, old_duration)
            if denominator <= 1e-6:
                continue
            coverage = _interval_overlap_seconds(intervals, previous) / denominator
            ranked.append((min(1.0, coverage), person_id))
        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            continue
        best_score, best_person_id = ranked[0]
        runner_up = ranked[1][0] if len(ranked) > 1 else 0.0
        if best_score >= min_coverage and best_score - runner_up >= min_margin:
            mapping[label] = best_person_id
    return mapping


class MeetingRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(
        self,
        *,
        source: str,
        title: str,
        processing_mode: str = "meeting",
        original_filename: str | None = None,
        audio_path: str | None = None,
        status: str = "draft",
    ) -> str:
        """Create meeting row."""
        meeting_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO meetings
                   (id, source, status, title, original_filename, audio_path,
                    processing_mode, diarization_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meeting_id, source, status, title, original_filename,
                    audio_path, processing_mode,
                    "pending" if processing_mode == "meeting" else "not_requested",
                ),
            )
            conn.commit()
        return meeting_id

    def create_with_job(
        self,
        *,
        source: str,
        title: str,
        processing_mode: str = "meeting",
        original_filename: str | None = None,
        audio_path: str | None = None,
        status: str = "draft",
    ) -> tuple[str, str]:
        """Create meeting + job atomically in one transaction."""
        meeting_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO meetings
                   (id, source, status, title, original_filename, audio_path,
                    processing_mode, diarization_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meeting_id, source, status, title, original_filename,
                    audio_path, processing_mode,
                    "pending" if processing_mode == "meeting" else "not_requested",
                ),
            )
            conn.execute(
                "INSERT INTO processing_jobs (id, meeting_id) VALUES (?, ?)",
                (job_id, meeting_id),
            )
            conn.commit()
        return meeting_id, job_id

    def get(self, meeting_id: str) -> Optional[dict]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
        return self._parse_meeting(row) if row else None

    @staticmethod
    def _parse_meeting(row) -> dict:
        meeting = dict(row)
        raw_manifest = meeting.pop("processing_manifest_json", None)
        try:
            meeting["processing_manifest"] = (
                json.loads(raw_manifest) if raw_manifest else None
            )
        except (TypeError, json.JSONDecodeError):
            meeting["processing_manifest"] = None
        return meeting

    def list(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[int, list[dict]]:
        where = ["1=1"]
        params: list = []
        if q:
            where.append(
                "(m.title LIKE ? ESCAPE '\\' OR m.original_filename LIKE ? ESCAPE '\\')"
            )
            # 转义 LIKE 通配符,防 %/_ 被当模式匹配"意外返回全部"
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.extend([f"%{escaped}%", f"%{escaped}%"])
        if status:
            where.append("m.status = ?")
            params.append(status)
        if source:
            where.append("m.source = ?")
            params.append(source)
        predicate = " AND ".join(where)
        with self.db.connect() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM meetings m WHERE {predicate}", params
            ).fetchone()[0]
            rows = conn.execute(
                f"""SELECT m.*,
                           (SELECT COUNT(*) FROM transcript_segments ts WHERE ts.meeting_id = m.id) AS segment_count,
                           (SELECT COUNT(*) FROM meeting_speakers ms WHERE ms.meeting_id = m.id) AS speaker_count
                    FROM meetings m
                    WHERE {predicate}
                    ORDER BY m.created_at DESC, m.id DESC
                    LIMIT ? OFFSET ?""",
                [*params, limit, offset],
            ).fetchall()
        return total, [self._parse_meeting(row) for row in rows]

    def update(self, meeting_id: str, **fields) -> bool:
        """Update whitelisted meeting fields.

        不在白名单的字段直接抛 ValueError,而非静默丢弃 —— 防新增可写字段
        忘加白名单导致调用方以为写入成功实则数据丢失。新增可写字段时扩展 allowed。
        """
        allowed = {
            "title", "status", "audio_path", "duration_sec", "language",
            "error_message", "processing_mode", "diarization_status",
            "diarization_error", "transcript_state", "processing_manifest_json",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(
                f"不可写入的 meeting 字段: {sorted(unknown)};合法字段: {sorted(allowed)}"
            )
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return False
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.db.connect() as conn:
            cursor = conn.execute(
                f"""UPDATE meetings SET {assignments}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?""",
                [*values.values(), meeting_id],
            )
            conn.commit()
        return cursor.rowcount > 0

    def record_processing_manifest(
        self, meeting_id: str, manifest: Mapping[str, object]
    ) -> bool:
        """Persist the provenance of the last successful generated transcript."""
        return self.update(
            meeting_id,
            processing_manifest_json=json.dumps(
                manifest, ensure_ascii=False, separators=(",", ":")
            ),
        )

    def delete(self, meeting_id: str, *, delete_audio: bool = True) -> bool:
        """Unconditionally delete a meeting (internal cleanup/migration use)."""
        meeting = self.get(meeting_id)
        if meeting is None:
            return False
        audio_path = meeting.get("audio_path")
        with self.db.connect() as conn:
            conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            conn.commit()
        if delete_audio and audio_path:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("[meetings] 删除音频文件失败 %s: %s", audio_path, exc)
        return True

    def delete_if_inactive(self, meeting_id: str) -> str:
        """Atomically delete only a meeting that has no active writer/job.

        Returns ``deleted``, ``not_found`` or ``active``.  The status check and
        delete share one write transaction so a concurrent reprocess enqueue
        cannot slip between an API-level preflight check and the delete.
        """
        audio_path = None
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            meeting = conn.execute(
                "SELECT status, audio_path FROM meetings WHERE id = ?",
                (meeting_id,),
            ).fetchone()
            if meeting is None:
                conn.rollback()
                return "not_found"
            active_job = conn.execute(
                """SELECT 1 FROM processing_jobs
                   WHERE meeting_id = ? AND status IN ('queued', 'running')
                   LIMIT 1""",
                (meeting_id,),
            ).fetchone()
            if meeting["status"] == "processing" or active_job is not None:
                conn.rollback()
                return "active"
            audio_path = meeting["audio_path"]
            conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
            conn.commit()
        if audio_path:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("[meetings] 删除音频文件失败 %s: %s", audio_path, exc)
        return "deleted"

    @staticmethod
    def _ensure_speaker_on_conn(conn, meeting_id: str, label: str) -> str:
        """Get/create a speaker using the caller's existing write transaction."""
        row = conn.execute(
            "SELECT id FROM meeting_speakers WHERE meeting_id = ? AND label = ?",
            (meeting_id, label),
        ).fetchone()
        if row:
            return str(row["id"])
        speaker_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO meeting_speakers (id, meeting_id, label) VALUES (?, ?, ?)",
            (speaker_id, meeting_id, label),
        )
        return speaker_id

    def ensure_speaker(self, meeting_id: str, label: str) -> str:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            speaker_id = self._ensure_speaker_on_conn(conn, meeting_id, label)
            conn.commit()
        return speaker_id

    def insert_segment(
        self,
        meeting_id: str,
        *,
        segment_index: int,
        text: str,
        start_time: float,
        end_time: float,
        speaker_label: str | None = None,
        confidence: float | None = None,
        words: list[dict] | None = None,
    ) -> int:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            meeting_speaker_id = (
                self._ensure_speaker_on_conn(conn, meeting_id, speaker_label)
                if speaker_label
                else None
            )
            cursor = conn.execute(
                """INSERT INTO transcript_segments
                   (meeting_id, segment_index, meeting_speaker_id, text, start_time,
                    end_time, confidence, words_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meeting_id, segment_index, meeting_speaker_id, text,
                    start_time, end_time, confidence,
                    json.dumps(words, ensure_ascii=False) if words else None,
                ),
            )
            conn.commit()
        return cursor.lastrowid

    def replace_generated_transcript(
        self,
        meeting_id: str,
        segments: Sequence[Mapping[str, object]],
        *,
        processing_manifest: Mapping[str, object] | None = None,
    ) -> list[int]:
        """Atomically replace machine-generated transcript segments.

        Provider labels are reused only as storage keys; confirmed identities are
        restored from unambiguous timeline overlap between old people and new
        labels. Any failure rolls back the complete replacement and leaves the
        previous result intact.
        """
        normalized_segments = []
        for segment in segments:
            normalized_segments.append(
                {
                    "segment_index": segment["segment_index"],
                    "text": segment["text"],
                    "start_time": segment["start_time"],
                    "end_time": segment["end_time"],
                    "speaker_label": segment.get("speaker_label"),
                    "confidence": segment.get("confidence"),
                    "words": segment.get("words"),
                }
            )

        with self.db.connect() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                meeting_exists = conn.execute(
                    "SELECT 1 FROM meetings WHERE id = ?", (meeting_id,)
                ).fetchone()
                if meeting_exists is None:
                    raise ValueError("meeting not found")

                speaker_rows = [
                    dict(row)
                    for row in conn.execute(
                        """SELECT id, label, person_id, manually_confirmed
                           FROM meeting_speakers WHERE meeting_id = ?""",
                        (meeting_id,),
                    ).fetchall()
                ]
                old_intervals: dict[str, list[tuple[float, float]]] = {}
                for row in conn.execute(
                    """SELECT meeting_speaker_id, start_time, end_time
                       FROM transcript_segments
                       WHERE meeting_id = ? AND meeting_speaker_id IS NOT NULL""",
                    (meeting_id,),
                ).fetchall():
                    old_intervals.setdefault(str(row["meeting_speaker_id"]), []).append(
                        (float(row["start_time"]), float(row["end_time"]))
                    )
                confirmed_mapping = _confirmed_identity_mapping(
                    speaker_rows, old_intervals, normalized_segments
                )
                existing_speakers = {
                    str(row["label"]): str(row["id"]) for row in speaker_rows
                }
                used_labels = {
                    str(segment["speaker_label"])
                    for segment in normalized_segments
                    if segment["speaker_label"] is not None
                }
                for label in used_labels:
                    if label not in existing_speakers:
                        speaker_id = str(uuid.uuid4())
                        conn.execute(
                            """INSERT INTO meeting_speakers (id, meeting_id, label)
                               VALUES (?, ?, ?)""",
                            (speaker_id, meeting_id, label),
                        )
                        existing_speakers[label] = speaker_id

                # Labels are provider-local and may swap between runs. Clear
                # every active identity, then restore manual confirmations only
                # through the timeline mapping above. Machine matches are always
                # recomputed from the new audio.
                conn.execute(
                    """UPDATE meeting_speakers
                       SET person_id = NULL, confidence = NULL,
                           manually_confirmed = 0,
                           identity_status = 'anonymous',
                           updated_at = CURRENT_TIMESTAMP
                       WHERE meeting_id = ?""",
                    (meeting_id,),
                )
                for label, person_id in confirmed_mapping.items():
                    conn.execute(
                        """UPDATE meeting_speakers
                           SET person_id = ?, confidence = NULL,
                               manually_confirmed = 1,
                               identity_status = 'confirmed',
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (person_id, existing_speakers[label]),
                    )

                conn.execute(
                    "DELETE FROM transcript_segments WHERE meeting_id = ?",
                    (meeting_id,),
                )
                inserted_ids = []
                for segment in normalized_segments:
                    speaker_label = segment["speaker_label"]
                    words = segment["words"]
                    cursor = conn.execute(
                        """INSERT INTO transcript_segments
                           (meeting_id, segment_index, meeting_speaker_id, text,
                            start_time, end_time, confidence, words_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            meeting_id,
                            segment["segment_index"],
                            existing_speakers.get(str(speaker_label))
                            if speaker_label is not None
                            else None,
                            segment["text"],
                            segment["start_time"],
                            segment["end_time"],
                            segment["confidence"],
                            json.dumps(words, ensure_ascii=False)
                            if words is not None
                            else None,
                        ),
                    )
                    inserted_ids.append(cursor.lastrowid)

                if used_labels:
                    placeholders = ",".join("?" for _ in used_labels)
                    conn.execute(
                        f"""DELETE FROM meeting_speakers
                            WHERE meeting_id = ? AND manually_confirmed = 0
                              AND label NOT IN ({placeholders})""",
                        [meeting_id, *sorted(used_labels)],
                    )
                else:
                    conn.execute(
                        """DELETE FROM meeting_speakers
                           WHERE meeting_id = ? AND manually_confirmed = 0""",
                        (meeting_id,),
                    )
                if processing_manifest is not None:
                    conn.execute(
                        """UPDATE meetings
                           SET processing_manifest_json = ?, transcript_state = 'refined',
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (
                            json.dumps(
                                processing_manifest,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            meeting_id,
                        ),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return inserted_ids

    def append_live_segment(
        self,
        meeting_id: str,
        *,
        text: str,
        start_time: float,
        end_time: float,
        speaker_label: str | None = None,
        confidence: float | None = None,
        words: list[dict] | None = None,
    ) -> int:
        """Append one final realtime segment using a repository-owned index.

        SELECT MAX + INSERT 包进 BEGIN IMMEDIATE 写事务:并发写同一 meeting
        (双 WS 会话或 finalize job 并发追加)时序列化,避免读到相同
        segment_index 撞 UNIQUE(meeting_id, segment_index)。WAL + busy_timeout
        5s 下第二个写连接会等待第一个提交而非立即报 locked。
        """
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            meeting_speaker_id = (
                self._ensure_speaker_on_conn(conn, meeting_id, speaker_label)
                if speaker_label
                else None
            )
            next_index = conn.execute(
                """SELECT COALESCE(MAX(segment_index), -1) + 1
                   FROM transcript_segments WHERE meeting_id = ?""",
                (meeting_id,),
            ).fetchone()[0]
            cursor = conn.execute(
                """INSERT INTO transcript_segments
                   (meeting_id, segment_index, meeting_speaker_id, text, start_time,
                    end_time, confidence, words_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meeting_id, next_index, meeting_speaker_id, text, start_time,
                    end_time, confidence,
                    json.dumps(words, ensure_ascii=False) if words else None,
                ),
            )
            conn.execute(
                """UPDATE meetings
                   SET duration_sec = MAX(duration_sec, ?), updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (end_time, meeting_id),
            )
            conn.commit()
        return cursor.lastrowid

    def finalize_live(self, meeting_id: str) -> bool:
        with self.db.connect() as conn:
            segment_count = conn.execute(
                "SELECT COUNT(*) FROM transcript_segments WHERE meeting_id = ?",
                (meeting_id,),
            ).fetchone()[0]
            audio_path = conn.execute(
                "SELECT audio_path FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            audio_path = audio_path["audio_path"] if audio_path else None
            # 缺音频文件却有转写段:标 failed,避免"看起来完成但无法播放/重处理"死胡同。
            # 仅覆盖 audio_path 已写但文件丢失的场景(真实路径下 WS 收到首帧即
            # update(audio_path=...),要产生转写段必先有音频流 → audio_path 恒非 None;
            # audio_path=None 的纯文本会话按既有契约标 ready)。
            # 已被 refinement 处理过(transcript_state='refined')的会议不回退状态。
            if segment_count and audio_path and not Path(audio_path).is_file():
                cursor = conn.execute(
                    """UPDATE meetings
                       SET status = 'failed',
                           error_message = '实时音频文件缺失,无法完成',
                           transcript_state = CASE
                               WHEN transcript_state = 'refined' THEN 'refined'
                               ELSE 'draft' END,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND source = 'live'""",
                    (meeting_id,),
                )
            else:
                cursor = conn.execute(
                    """UPDATE meetings
                       SET status = ?,
                           transcript_state = CASE
                           WHEN transcript_state = 'refined' THEN 'refined'
                           ELSE 'draft' END,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND source = 'live'""",
                    ("ready" if segment_count else "draft", meeting_id),
                )
            conn.commit()
        return cursor.rowcount > 0

    def mark_completed(self, meeting_id: str, job_id: str, finished_at: str) -> None:
        """同事务标记 meeting=ready + job=completed。

        替代原本 meeting_repo.update(ready) + job_repo.update(completed) 的多步提交,
        避免崩溃窗口出现 meeting=ready + job=running 矛盾态(recover 把 running 回
        queued 后重跑会把 ready 降级回 processing)。
        """
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """UPDATE meetings
                   SET status = 'ready', error_message = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (meeting_id,),
            )
            conn.execute(
                """UPDATE processing_jobs
                   SET status = 'completed', stage = 'completed', progress = 100,
                       finished_at = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (finished_at, job_id),
            )
            conn.commit()

    def save_note(
        self, meeting_id: str, note_type: str, content: str, source: str = "local"
    ) -> dict:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO meeting_notes (meeting_id, note_type, content, source)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(meeting_id, note_type) DO UPDATE SET
                     content = excluded.content, source = excluded.source,
                     updated_at = CURRENT_TIMESTAMP""",
                (meeting_id, note_type, content, source),
            )
            row = conn.execute(
                "SELECT * FROM meeting_notes WHERE meeting_id = ? AND note_type = ?",
                (meeting_id, note_type),
            ).fetchone()
            conn.commit()
        return dict(row)

    def detail(self, meeting_id: str) -> Optional[dict]:
        meeting = self.get(meeting_id)
        if meeting is None:
            return None
        with self.db.connect() as conn:
            segments = conn.execute(
                """SELECT ts.*, ms.label AS speaker_label, ms.person_id,
                          ms.manually_confirmed, ms.confidence, ms.identity_status,
                          p.name AS person_name
                   FROM transcript_segments ts
                   LEFT JOIN meeting_speakers ms ON ms.id = ts.meeting_speaker_id
                   LEFT JOIN people p ON p.id = ms.person_id
                   WHERE ts.meeting_id = ? ORDER BY ts.segment_index""",
                (meeting_id,),
            ).fetchall()
            speakers = conn.execute(
                """SELECT ms.*, p.name AS person_name
                   FROM meeting_speakers ms LEFT JOIN people p ON p.id = ms.person_id
                   WHERE ms.meeting_id = ? ORDER BY ms.label""",
                (meeting_id,),
            ).fetchall()
            notes = conn.execute(
                "SELECT * FROM meeting_notes WHERE meeting_id = ?", (meeting_id,)
            ).fetchall()
        parsed_segments = []
        for row in segments:
            item = dict(row)
            item["words"] = json.loads(item["words_json"]) if item.get("words_json") else None
            parsed_segments.append(item)
        return {
            "meeting": meeting,
            "segments": parsed_segments,
            "speakers": [dict(row) for row in speakers],
            "notes": [dict(row) for row in notes],
        }

    def assign_segments(self, meeting_id: str, segment_ids: list[int], speaker_id: str | None) -> int:
        if not segment_ids:
            return 0
        placeholders = ",".join("?" for _ in segment_ids)
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if speaker_id is not None:
                owner = conn.execute(
                    "SELECT 1 FROM meeting_speakers WHERE id = ? AND meeting_id = ?",
                    (speaker_id, meeting_id),
                ).fetchone()
                if owner is None:
                    raise ValueError("speaker does not belong to meeting")
            cursor = conn.execute(
                f"""UPDATE transcript_segments
                    SET meeting_speaker_id = ?, manually_edited = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE meeting_id = ? AND id IN ({placeholders})""",
                [speaker_id, meeting_id, *segment_ids],
            )
            conn.commit()
        return cursor.rowcount

    def update_segment_text(self, meeting_id: str, segment_id: int, text: str) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute(
                """UPDATE transcript_segments
                   SET text = ?, manually_edited = 1, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND meeting_id = ?""",
                (text, segment_id, meeting_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def merge_speakers(self, meeting_id: str, target_id: str, source_ids: list[str]) -> int:
        """合并:把 source speakers 的所有 segments 改指到 target,然后删 source。

        返回迁移的 segment 数。
        """
        if target_id in source_ids:
            raise ValueError("target_id 不能在 source_ids 里")
        if not source_ids:
            return 0
        placeholders = ",".join("?" for _ in source_ids)
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            owner = conn.execute(
                "SELECT 1 FROM meeting_speakers WHERE id = ? AND meeting_id = ?",
                (target_id, meeting_id),
            ).fetchone()
            if owner is None:
                raise SpeakerNotFoundError("target speaker 不存在")
            cursor = conn.execute(
                f"""UPDATE transcript_segments
                    SET meeting_speaker_id = ?, manually_edited = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE meeting_id = ? AND meeting_speaker_id IN ({placeholders})""",
                [target_id, meeting_id, *source_ids],
            )
            migrated = cursor.rowcount
            conn.execute(
                f"""DELETE FROM meeting_speakers
                    WHERE meeting_id = ? AND id IN ({placeholders})""",
                [meeting_id, *source_ids],
            )
            conn.commit()
        return migrated

    def split_speaker(self, meeting_id: str, source_id: str, segment_ids: list[int]) -> str:
        """拆分:给选中的 segments 创建一个新的匿名 meeting_speaker,脱离 source。

        返回新建的 speaker id。
        """
        new_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            source = conn.execute(
                "SELECT label FROM meeting_speakers WHERE id = ? AND meeting_id = ?",
                (source_id, meeting_id),
            ).fetchone()
            if source is None:
                raise SpeakerNotFoundError("source speaker 不存在")
            conn.execute(
                """INSERT INTO meeting_speakers (id, meeting_id, label, identity_status)
                   VALUES (?, ?, ?, 'anonymous')""",
                (new_id, meeting_id, f"{source['label']}_split_{uuid.uuid4().hex[:8]}"),
            )
            placeholders = ",".join("?" for _ in segment_ids)
            conn.execute(
                f"""UPDATE transcript_segments
                    SET meeting_speaker_id = ?, manually_edited = 1,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE meeting_id = ? AND meeting_speaker_id = ?
                      AND id IN ({placeholders})""",
                [new_id, meeting_id, source_id, *segment_ids],
            )
            conn.commit()
        return new_id

    def confirm_speaker(self, meeting_id: str, speaker_id: str, person_id: str | None) -> bool:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if person_id is not None and conn.execute(
                "SELECT 1 FROM people WHERE id = ?", (person_id,)
            ).fetchone() is None:
                raise ValueError("person not found")
            cursor = conn.execute(
                """UPDATE meeting_speakers
                   SET person_id = ?, manually_confirmed = ?, confidence = NULL,
                       identity_status = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND meeting_id = ?""",
                (
                    person_id,
                    1 if person_id is not None else 0,
                    "confirmed" if person_id is not None else "anonymous",
                    speaker_id,
                    meeting_id,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def suggest_speaker(
        self,
        meeting_id: str,
        speaker_label: str,
        person_id: str,
        confidence: float,
        *,
        identity_status: str = "suggested",
    ) -> bool:
        if identity_status not in {"suggested", "auto_matched"}:
            raise ValueError("invalid machine identity status")
        with self.db.connect() as conn:
            cursor = conn.execute(
                """UPDATE meeting_speakers
                   SET person_id = ?, confidence = ?, manually_confirmed = 0,
                       identity_status = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE meeting_id = ? AND label = ? AND manually_confirmed = 0""",
                (
                    person_id,
                    confidence,
                    identity_status,
                    meeting_id,
                    speaker_label,
                ),
            )
            conn.commit()
        return cursor.rowcount > 0

    def search(self, q: str, limit: int = 50) -> list[dict]:
        """全文搜索: FTS5 trigram 主路径 + LIKE 兜底(2 字/特殊字符)"""
        query = q.strip()
        if not query:
            return []

        def _make_snippet(text: str, kw: str) -> str:
            pos = text.lower().find(kw.lower())
            if pos < 0:
                return text[:48]
            start = max(0, pos - 16)
            end = min(len(text), pos + len(kw) + 16)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(text) else ""
            return prefix + text[start:pos] + "[match]" + text[pos:pos + len(kw)] + "[/match]" + text[pos + len(kw):end] + suffix

        def _join_cols(row: dict) -> dict:
            item = dict(row)
            text = item.get("text") or ""
            item["snippet"] = _make_snippet(text, query)
            item["jump_url"] = f"/meetings/{item['meeting_id']}?segment={item['segment_id']}"
            return item

        # 1. FTS5 路径(trigram,3+ 字中文命中率高)
        # 剥离 FTS5 操作符(AND/OR/NOT/NEAR),避免裸操作符触发 MATCH 语法解析失败。
        fts_q = re.sub(r"[^\w一-鿿]+", " ", query, flags=re.UNICODE).strip()
        fts_q = re.sub(r"\b(AND|OR|NOT|NEAR)\b", " ", fts_q, flags=re.IGNORECASE).strip()
        fts_results: list[dict] = []
        if fts_q:
            with self.db.connect() as conn:
                sql = """SELECT ts.id AS segment_id, ts.meeting_id, ts.text,
                                ts.start_time, ts.end_time, m.title AS meeting_title,
                                CASE WHEN ms.identity_status IN ('auto_matched', 'confirmed')
                                          OR (ms.identity_status IS NULL AND ms.manually_confirmed = 1)
                                     THEN COALESCE(p.name, ms.label)
                                     ELSE ms.label END AS speaker_name
                         FROM transcript_segments_fts
                         JOIN transcript_segments ts ON ts.id = transcript_segments_fts.rowid
                         JOIN meetings m ON m.id = ts.meeting_id
                         LEFT JOIN meeting_speakers ms ON ms.id = ts.meeting_speaker_id
                         LEFT JOIN people p ON p.id = ms.person_id
                         WHERE transcript_segments_fts MATCH ?
                         ORDER BY rank LIMIT ?"""
                try:
                    rows = conn.execute(sql, (fts_q + "*", limit)).fetchall()
                    fts_results = [_join_cols(dict(r)) for r in rows]
                except sqlite3.OperationalError:
                    # 畸形 MATCH 语法(trigram 分词边界)降级到 LIKE 兜底,不返 500。
                    fts_results = []

        # 2. LIKE 兜底(2 字/特殊字符场景);转义通配符,与 list() 一致。
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like_results: list[dict] = []
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT ts.id AS segment_id, ts.meeting_id, ts.text,
                          ts.start_time, ts.end_time, m.title AS meeting_title,
                          CASE WHEN ms.identity_status IN ('auto_matched', 'confirmed')
                                    OR (ms.identity_status IS NULL AND ms.manually_confirmed = 1)
                               THEN COALESCE(p.name, ms.label)
                               ELSE ms.label END AS speaker_name
                   FROM transcript_segments ts
                   JOIN meetings m ON m.id = ts.meeting_id
                   LEFT JOIN meeting_speakers ms ON ms.id = ts.meeting_speaker_id
                   LEFT JOIN people p ON p.id = ms.person_id
                   WHERE ts.text LIKE ? ESCAPE '\\' OR m.title LIKE ? ESCAPE '\\'
                   ORDER BY m.created_at DESC, ts.segment_index ASC
                   LIMIT ?""",
                (f"%{escaped}%", f"%{escaped}%", limit),
            ).fetchall()
            like_results = [_join_cols(dict(r)) for r in rows]

        # 3. UNION 去重(FTS5 优先)
        seen: set = set()
        merged: list[dict] = []
        for hit in fts_results + like_results:
            sid = hit["segment_id"]
            if sid not in seen:
                seen.add(sid)
                merged.append(hit)
        return merged[:limit]
