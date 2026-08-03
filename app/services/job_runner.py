"""Single-process durable job runner for local deployments."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.services.meeting_processor import JobCancelled, PermanentJobError


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
            if not self._task.done():
                return
            self._task = None
        recovered = self.job_repo.recover_interrupted()
        if recovered:
            logger.warning("恢复 %s 个中断任务", recovered)
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="matrix-job-runner")
        self.notify()

    async def stop(self) -> bool:
        """Request a graceful stop without cancelling uninterruptible model work.

        Returns ``True`` only after the runner has really exited.  On timeout
        the task is deliberately retained: cancelling an asyncio wrapper does
        not cancel a provider's worker thread.
        """
        self._stopping = True
        self._wake.set()
        task = self._task
        if task is None:
            return True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self.shutdown_timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "任务执行器未在 %.1f 秒内退出；保留当前推理直到工作线程自然结束",
                self.shutdown_timeout,
            )
            return False
        self._task = None
        return True

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
                try:
                    self.job_repo.update(
                        job["id"], status="cancelled", stage="cancelled",
                        finished_at=datetime.now(timezone.utc).isoformat(),
                    )
                    self.meeting_repo.update(
                        job["meeting_id"], status="failed", error_message="任务已取消"
                    )
                except Exception:
                    logger.exception("更新 cancelled 状态失败 job=%s", job["id"])
            except Exception as exc:
                logger.exception("任务 %s 处理失败", job["id"])
                try:
                    self.job_repo.update(
                        job["id"], status="failed", stage="failed",
                        error_message=str(exc),
                        finished_at=datetime.now(timezone.utc).isoformat(),
                    )
                except Exception:
                    logger.exception("更新 failed 状态失败 job=%s", job["id"])
                # 瞬时异常自动重排(最多 MAX_AUTO_RETRIES 次),数据/取消类错误不重试。
                # 重排路径异常不能逸出 while 循环,否则后台任务整体死亡。
                try:
                    requeued = self.job_repo.requeue_for_retry(
                        job["id"], retryable=not isinstance(exc, PermanentJobError)
                    )
                except Exception:
                    logger.exception("requeue_for_retry 失败 job=%s", job["id"])
                    requeued = False
                if requeued:
                    try:
                        retry_count = int(self.job_repo.get(job["id"])["retry_count"] or 0)
                        backoff = min(2 ** retry_count, 8)  # 2,4,8s 指数退避,上限 8s
                        logger.info(
                            "任务 %s 失败,自动重排队重试(第 %d 次,退避 %ds): %s",
                            job["id"], retry_count, backoff, str(exc)[:200],
                        )
                        await asyncio.sleep(backoff)
                    except Exception:
                        logger.exception("重试退避流程异常 job=%s", job["id"])
                else:
                    try:
                        self.meeting_repo.update(
                            job["meeting_id"], status="failed", error_message=str(exc)
                        )
                    except Exception:
                        logger.exception("meeting 落 failed 失败 job=%s", job["id"])
