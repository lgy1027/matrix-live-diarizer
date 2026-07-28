"""Durable local processing jobs."""
from __future__ import annotations
import uuid
from typing import Optional

from .database import Database


class JobRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, meeting_id: str) -> str:
        job_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO processing_jobs (id, meeting_id) VALUES (?, ?)",
                (job_id, meeting_id),
            )
            conn.commit()
        return job_id

    def enqueue_refinement(self, meeting_id: str) -> tuple[str, bool]:
        """Atomically queue full refinement unless this meeting already has active work."""
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            meeting = conn.execute(
                "SELECT audio_path FROM meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            if meeting is None:
                conn.rollback()
                raise ValueError("meeting not found")
            if not meeting["audio_path"]:
                conn.rollback()
                raise FileNotFoundError("meeting audio not found")
            active = conn.execute(
                """SELECT id FROM processing_jobs
                   WHERE meeting_id = ? AND status IN ('queued', 'running')
                   ORDER BY created_at DESC LIMIT 1""",
                (meeting_id,),
            ).fetchone()
            if active is not None:
                conn.commit()
                return active["id"], False
            job_id = str(uuid.uuid4())
            conn.execute(
                """UPDATE meetings
                   SET status = 'processing', processing_mode = 'meeting',
                       error_message = NULL, diarization_status = 'pending',
                       diarization_error = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (meeting_id,),
            )
            conn.execute(
                "INSERT INTO processing_jobs (id, meeting_id) VALUES (?, ?)",
                (job_id, meeting_id),
            )
            conn.commit()
        return job_id, True

    def get(self, job_id: str) -> Optional[dict]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM processing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def list(self, limit: int = 100) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT j.*, m.title AS meeting_title, m.original_filename
                   FROM processing_jobs j JOIN meetings m ON m.id = j.meeting_id
                   ORDER BY j.created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_for_meeting(self, meeting_id: str) -> Optional[dict]:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT * FROM processing_jobs
                   WHERE meeting_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (meeting_id,),
            ).fetchone()
        return dict(row) if row else None

    def has_active_for_meeting(self, meeting_id: str) -> bool:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT 1 FROM processing_jobs
                   WHERE meeting_id = ? AND status IN ('queued', 'running')
                   LIMIT 1""",
                (meeting_id,),
            ).fetchone()
        return row is not None

    def update(self, job_id: str, **fields) -> bool:
        allowed = {
            "status", "stage", "progress", "error_message", "retry_count",
            "cancel_requested", "started_at", "finished_at",
        }
        values = {key: value for key, value in fields.items() if key in allowed}
        if not values:
            return False
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self.db.connect() as conn:
            cursor = conn.execute(
                f"""UPDATE processing_jobs SET {assignments}, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?""",
                [*values.values(), job_id],
            )
            conn.commit()
        return cursor.rowcount > 0

    def request_cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job["status"] in {"completed", "failed", "cancelled"}:
            return False
        if job["status"] == "queued":
            # queued 阶段取消:直接终结为 cancelled,不进 processor。
            # 若仅置 cancel_requested=1 依赖 claim_next 领出+processor 取消,
            # claim_next 已过滤 cancel_requested=0 → 该 job 永不被领出 →
            # 永不终结、meeting 永久卡 processing。故此处直接终结。
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                cursor = conn.execute(
                    """UPDATE processing_jobs
                       SET status = 'cancelled', stage = 'cancelled',
                           cancel_requested = 1, finished_at = CURRENT_TIMESTAMP,
                           updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND status = 'queued'""",
                    (job_id,),
                )
                if cursor.rowcount == 0:
                    # 竞态:claim_next 在此期间已领走(变 running),回退到 running 取消路径
                    conn.rollback()
                else:
                    conn.execute(
                        """UPDATE meetings
                           SET status = 'failed', error_message = '任务已取消',
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (job["meeting_id"],),
                    )
                    conn.commit()
                    return True
            job = self.get(job_id)
            if not job or job["status"] in {"completed", "failed", "cancelled"}:
                return False
        return self.update(job_id, cancel_requested=1)

    def retry(self, job_id: str) -> bool:
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                "SELECT * FROM processing_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None or job["status"] not in {"failed", "cancelled"}:
                conn.rollback()
                return False
            cursor = conn.execute(
                """UPDATE processing_jobs
                   SET status = 'queued', stage = 'queued', progress = 0,
                       error_message = NULL, cancel_requested = 0,
                       retry_count = ?, started_at = NULL, finished_at = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status IN ('failed', 'cancelled')""",
                (int(job["retry_count"]) + 1, job_id),
            )
            conn.execute(
                """UPDATE meetings
                   SET status = 'processing', error_message = NULL,
                       diarization_status = CASE
                           WHEN processing_mode = 'meeting' THEN 'pending'
                           ELSE 'not_requested' END,
                       diarization_error = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (job["meeting_id"],),
            )
            conn.commit()
        return cursor.rowcount > 0

    def claim_next(self) -> Optional[dict]:
        """Atomically claim the oldest queued job for the single local worker."""
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM processing_jobs
                   WHERE status = 'queued' AND cancel_requested = 0
                   ORDER BY created_at ASC LIMIT 1"""
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            cursor = conn.execute(
                """UPDATE processing_jobs
                   SET status = 'running', stage = 'starting', progress = 1,
                       started_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'queued'""",
                (row["id"],),
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
        return self.get(row["id"])

    def recover_interrupted(self) -> int:
        """Service restarts turn running work back into queued work."""
        with self.db.connect() as conn:
            cursor = conn.execute(
                """UPDATE processing_jobs
                   SET status = 'queued', stage = 'queued', progress = 0,
                       error_message = NULL, started_at = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE status = 'running'"""
            )
            conn.commit()
        return cursor.rowcount
