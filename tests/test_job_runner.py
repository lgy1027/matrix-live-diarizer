import asyncio

from app.repositories.database import Database
from app.repositories.jobs import JobRepository
from app.repositories.meetings import MeetingRepository
from app.services.job_runner import JobRunner
from app.services.meeting_processor import PermanentJobError, await_uninterruptible


def test_runner_completes_queued_job(tmp_path):
    async def scenario():
        db = Database(str(tmp_path / "runner.db"))
        db.init_schema()
        meetings = MeetingRepository(db)
        jobs = JobRepository(db)
        meeting_id = meetings.create(source="upload", title="后台任务", status="processing")
        job_id = jobs.create(meeting_id)

        async def processor(job):
            jobs.update(job["id"], status="completed", stage="completed", progress=100)
            meetings.update(job["meeting_id"], status="ready")

        runner = JobRunner(jobs, meetings, processor)
        await runner.start()
        for _ in range(100):
            if jobs.get(job_id)["status"] == "completed":
                break
            await asyncio.sleep(0.01)
        await runner.stop()

        assert jobs.get(job_id)["status"] == "completed"
        assert meetings.get(meeting_id)["status"] == "ready"

    asyncio.run(scenario())


def test_runner_recovers_interrupted_job(tmp_path):
    db = Database(str(tmp_path / "recovery.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    meeting_id = meetings.create(source="upload", title="恢复任务", status="processing")
    job_id = jobs.create(meeting_id)
    jobs.update(job_id, status="running", stage="transcribing", progress=40)

    assert jobs.recover_interrupted() == 1
    recovered = jobs.get(job_id)
    assert recovered["status"] == "queued"
    assert recovered["progress"] == 0


def test_runner_shutdown_is_bounded_for_long_processing(tmp_path):
    async def scenario():
        db = Database(str(tmp_path / "bounded.db"))
        db.init_schema()
        meetings = MeetingRepository(db)
        jobs = JobRepository(db)
        meeting_id = meetings.create(source="upload", title="长任务", status="processing")
        job_id = jobs.create(meeting_id)
        started = asyncio.Event()

        async def processor(_job):
            started.set()
            await asyncio.Event().wait()

        runner = JobRunner(jobs, meetings, processor, shutdown_timeout=0.01)
        await runner.start()
        await asyncio.wait_for(started.wait(), timeout=1)
        stopped = await asyncio.wait_for(runner.stop(), timeout=0.2)
        await asyncio.sleep(0)

        assert stopped is False
        assert runner._task is not None
        assert not runner._task.done()
        assert jobs.get(job_id)["status"] == "running"
        assert jobs.recover_interrupted() == 1

    asyncio.run(scenario())


def test_uninterruptible_model_work_finishes_before_cancellation_unwinds():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        finished = asyncio.Event()

        async def model_work():
            started.set()
            await release.wait()
            finished.set()

        task = asyncio.create_task(await_uninterruptible(model_work()))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)

        assert not task.done()
        assert not finished.is_set()

        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("outer cancellation must still be delivered")
        assert finished.is_set()

    asyncio.run(scenario())


def test_runner_retries_transient_failure_then_completes(tmp_path):
    """瞬时错误应自动重排重试,最终成功;meeting 不应停在 failed。"""
    async def scenario():
        db = Database(str(tmp_path / "retry.db"))
        db.init_schema()
        meetings = MeetingRepository(db)
        jobs = JobRepository(db)
        meeting_id = meetings.create(source="upload", title="重试任务", status="processing")
        job_id = jobs.create(meeting_id)

        attempts = {"n": 0}

        async def processor(job):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError("瞬时 ChromaDB 临时不可用")
            jobs.update(job["id"], status="completed", stage="completed", progress=100)
            meetings.update(job["meeting_id"], status="ready")

        runner = JobRunner(jobs, meetings, processor)
        await runner.start()
        for _ in range(500):
            if jobs.get(job_id)["status"] == "completed":
                break
            await asyncio.sleep(0.01)
        await runner.stop()

        assert attempts["n"] == 3
        assert jobs.get(job_id)["status"] == "completed"
        assert meetings.get(meeting_id)["status"] == "ready"
        # 自动重试递增了 retry_count(初始 0,重试 2 次 → 2)
        assert int(jobs.get(job_id)["retry_count"]) == 2

    asyncio.run(scenario())


def test_runner_does_not_retry_data_error(tmp_path):
    """'not found' 类数据错误不应重试,直接落 failed。"""
    async def scenario():
        db = Database(str(tmp_path / "noretry.db"))
        db.init_schema()
        meetings = MeetingRepository(db)
        jobs = JobRepository(db)
        meeting_id = meetings.create(source="upload", title="数据错误", status="processing")
        job_id = jobs.create(meeting_id)

        attempts = {"n": 0}

        async def processor(_job):
            attempts["n"] += 1
            raise PermanentJobError("meeting audio not found")

        runner = JobRunner(jobs, meetings, processor)
        await runner.start()
        for _ in range(200):
            if jobs.get(job_id)["status"] == "failed":
                break
            await asyncio.sleep(0.01)
        await runner.stop()

        assert attempts["n"] == 1  # 没重试
        assert jobs.get(job_id)["status"] == "failed"
        assert meetings.get(meeting_id)["status"] == "failed"

    asyncio.run(scenario())


def test_runner_gives_up_after_max_retries(tmp_path):
    """持续瞬时错误超过 MAX_AUTO_RETRIES 次后落 failed。"""
    async def scenario():
        db = Database(str(tmp_path / "maxretry.db"))
        db.init_schema()
        meetings = MeetingRepository(db)
        jobs = JobRepository(db)
        meeting_id = meetings.create(source="upload", title="持续失败", status="processing")
        job_id = jobs.create(meeting_id)

        async def processor(_job):
            raise RuntimeError("持续 OOM 假象")

        runner = JobRunner(jobs, meetings, processor)
        await runner.start()
        for _ in range(500):
            if jobs.get(job_id)["status"] == "failed":
                break
            await asyncio.sleep(0.01)
        await runner.stop()

        # 首次 + MAX_AUTO_RETRIES 次重试 = MAX_AUTO_RETRIES + 1 次尝试
        from app.repositories.jobs import MAX_AUTO_RETRIES
        assert int(jobs.get(job_id)["retry_count"]) == MAX_AUTO_RETRIES
        assert jobs.get(job_id)["status"] == "failed"
        assert meetings.get(meeting_id)["status"] == "failed"

    asyncio.run(scenario())
