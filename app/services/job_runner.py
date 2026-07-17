"""Single-process durable job runner for local deployments."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.services.meeting_processor import JobCancelled


logger = logging.getLogger("Matrix_Jobs")


class JobRunner:
    def __init__(self, job_repo, meeting_repo, processor, *, shutdown_timeout: float = 5.0):
        self.job_repo = job_repo
        self.meeting_repo = meeting_repo
        self.processor = processor
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._stopping = False
        self.shutdown_timeout = shutdown_timeout

    async def start(self) -> None:
        if self._task is not None:
            return
        recovered = self.job_repo.recover_interrupted()
        if recovered:
            logger.warning("恢复 %s 个中断任务", recovered)
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="matrix-job-runner")
        self.notify()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        task, self._task = self._task, None
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.shutdown_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "任务执行器未在 %.1f 秒内退出，将中断当前任务；下次启动会自动恢复",
                self.shutdown_timeout,
            )
            task.cancel()

    def notify(self) -> None:
        self._wake.set()

    async def _run(self) -> None:
        while not self._stopping:
            job = self.job_repo.claim_next()
            if job is None:
                self._wake.clear()
                await self._wake.wait()
                continue
            try:
                await self.processor(job)
            except JobCancelled:
                self.job_repo.update(
                    job["id"], status="cancelled", stage="cancelled",
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                self.meeting_repo.update(job["meeting_id"], status="failed", error_message="任务已取消")
            except Exception as exc:
                logger.exception("任务 %s 处理失败", job["id"])
                self.job_repo.update(
                    job["id"], status="failed", stage="failed",
                    error_message=str(exc),
                    finished_at=datetime.now(timezone.utc).isoformat(),
                )
                self.meeting_repo.update(
                    job["meeting_id"], status="failed", error_message=str(exc)
                )
