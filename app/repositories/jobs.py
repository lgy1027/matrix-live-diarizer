"""Durable local processing jobs."""
from __future__ import annotations
import logging
import uuid
from typing import Optional

from .database import Database

logger = logging.getLogger("Matrix_Jobs")


# 失败后自动重排上限(不含首次执行):瞬时异常最多再试这么多次,超限落 failed。
# MPS 死锁表现为 job 挂起(running 不返回),不会进 except,故不会被这里重试;
# 真正进 except 的失败(OOM、ChromaDB 临时错、解码瞬时失败)重试有价值。
MAX_AUTO_RETRIES = 2

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

    def enqueue_refinement(
        self, meeting_id: str, *, allow_live: bool = False
    ) -> tuple[str, bool]:
        """Atomically queue full refinement unless this meeting already has active work.

        allow_live=False(默认)时,若 meeting 当前是 live 会话(status=processing
        且无 active job),拒绝排队 — 避免 refinement 的 replace_generated_transcript
        与 WS 的 append_live_segment 并发写。WS finalize 路径传 allow_live=True。
        """
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            meeting = conn.execute(
                "SELECT audio_path, source FROM meetings WHERE id = ?", (meeting_id,)
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
            # live 会话在 finalize 前没有 job;若 allow_live=False,拒绝排队以防
            # refinement 与活跃 WS 写并发。
            if not allow_live:
                row = conn.execute(
                    "SELECT status FROM meetings WHERE id = ?", (meeting_id,)
                ).fetchone()
                if row is not None and row["status"] == "processing":
                    conn.rollback()
                    raise RuntimeError("会议正在实时录制,无法启动精修")
            job_id = str(uuid.uuid4())
            conn.execute(
                """UPDATE meetings
                   SET status = 'processing', processing_mode = 'meeting',
                       error_message = NULL, transcript_state = 'draft',
                       diarization_status = 'pending',
                       diarization_error = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (meeting_id,),
            )
            conn.execute(
                "INSERT INTO processing_jobs (id, meeting_id) VALUES (?, ?)",
                (job_id, meeting_id),
            )
            conn.commit()
        # 入队后清理每 meeting 堆积的已完成 job,防表无限膨胀
        self.prune_finished()
        return job_id, True

    def prune_finished(self, keep_per_meeting: int = 5) -> int:
        """删除每 meeting 超过 keep_per_meeting 的已完成(cancelled/completed/failed)旧 job。

        防止 processing_jobs 表随 reprocess/重试无限累积。
        """
        from collections import defaultdict
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """SELECT meeting_id, id FROM processing_jobs
                   WHERE status IN ('cancelled', 'completed', 'failed')
                   ORDER BY meeting_id, created_at DESC"""
            ).fetchall()
            seen: dict = defaultdict(int)
            to_delete: list = []
            for row in rows:
                seen[row["meeting_id"]] += 1
                if seen[row["meeting_id"]] > keep_per_meeting:
                    to_delete.append(row["id"])
            deleted = 0
            if to_delete:
                placeholders = ",".join("?" for _ in to_delete)
                cursor = conn.execute(
                    f"DELETE FROM processing_jobs WHERE id IN ({placeholders})",
                    to_delete,
                )
                deleted = cursor.rowcount
            conn.commit()
        return deleted

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
                       transcript_state = 'draft',
                       diarization_status = CASE
                           WHEN processing_mode = 'meeting' THEN 'pending'
                           ELSE 'not_requested' END,
                       diarization_error = NULL, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (job["meeting_id"],),
            )
            conn.commit()
        return cursor.rowcount > 0

    def requeue_for_retry(self, job_id: str, *, retryable: bool = True) -> bool:
        """失败后自动重排队(若未超 MAX_AUTO_RETRIES 且未被用户取消)。

        retry_count 在 enqueue_refinement 时为 0、手动 retry 时 +1。这里再 +1
        标记一次自动重试。超过上限返回 False(调用方落 failed)。
        JobCancelled 不进 except 分支,不会调到这里。
        若用户已 request_cancel,不重排(保留 failed,尊重取消意图)。
        是否可重试由处理器的类型化异常决定；仓储层不解析错误文案。
        """
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                "SELECT retry_count, cancel_requested FROM processing_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if job is None:
                conn.rollback()
                return False
            next_retry_count = int(job["retry_count"] or 0) + 1
            if next_retry_count > MAX_AUTO_RETRIES:
                conn.rollback()
                return False
            if not retryable:
                conn.rollback()
                return False
            # 用户已请求取消:不重排,让调用方落 failed。
            if int(job["cancel_requested"] or 0) == 1:
                conn.rollback()
                return False
            conn.execute(
                """UPDATE processing_jobs
                   SET status = 'queued', stage = 'queued', progress = 0,
                       error_message = NULL, cancel_requested = 0,
                       retry_count = ?,
                       started_at = NULL, finished_at = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (next_retry_count, job_id),
            )
            conn.execute(
                """UPDATE meetings
                   SET status = 'processing', error_message = NULL,
                       transcript_state = 'draft',
                       diarization_status = CASE
                           WHEN processing_mode = 'meeting' THEN 'pending'
                           ELSE 'not_requested' END,
                       diarization_error = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE id = (SELECT meeting_id FROM processing_jobs WHERE id = ?)""",
                (job_id,),
            )
            conn.commit()
        return True

    def claim_next(self) -> Optional[dict]:
        """Atomically claim the oldest queued job for the single local worker."""
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM processing_jobs
                   WHERE status = 'queued' AND cancel_requested = 0
                   ORDER BY created_at ASC, rowid ASC LIMIT 1"""
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
        """Service restarts turn running work back into queued work.

        cancel_requested=1 的 running job:重启前用户已取消,但 processor 未到
        checkpoint。直接终结为 cancelled + meeting failed,避免改回 queued 后
        claim_next 永不领出(cancel_next 过滤 cancel_requested=0)导致 meeting
        永久卡 processing 且用户无恢复路径。
        """
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # 先终结已取消的:重启前已 request_cancel 但未 checkpoint 的 running job
            cancelled_rows = conn.execute(
                """SELECT meeting_id FROM processing_jobs
                   WHERE status = 'running' AND cancel_requested = 1"""
            ).fetchall()
            if cancelled_rows:
                conn.execute(
                    """UPDATE processing_jobs
                       SET status = 'cancelled', stage = 'cancelled',
                           finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                       WHERE status = 'running' AND cancel_requested = 1""",
                )
                for row in cancelled_rows:
                    conn.execute(
                        """UPDATE meetings
                           SET status = 'failed', error_message = '任务已取消',
                               updated_at = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (row["meeting_id"],),
                    )
            # 其余 running(未被取消的)回 queued 重跑
            cursor = conn.execute(
                """UPDATE processing_jobs
                   SET status = 'queued', stage = 'queued', progress = 0,
                       error_message = NULL, started_at = NULL,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE status = 'running'"""
            )
            # 清理崩溃前未 finalize 的 live 孤儿会议(source=live, status=processing,
            # 无 active job):标 failed 让用户可 reprocess/编辑/删除,而非永久卡
            # processing(recover 只恢复 job,漏了无 job 的 live 会议)。
            orphan_cursor = conn.execute(
                """UPDATE meetings
                   SET status = 'failed',
                       error_message = COALESCE(error_message,
                           '实时会话因进程中断未完成'),
                       updated_at = CURRENT_TIMESTAMP
                   WHERE source = 'live' AND status = 'processing'
                     AND id NOT IN (
                       SELECT meeting_id FROM processing_jobs
                       WHERE status IN ('queued', 'running')
                     )"""
            )
            conn.commit()
        if orphan_cursor.rowcount:
            logger.info(
                "[recover] 恢复 %d 个 live 孤儿会议(因中断未完成)",
                orphan_cursor.rowcount,
            )
        return cursor.rowcount
