import asyncio

from app.repositories.database import Database
from app.repositories.jobs import JobRepository
from app.repositories.meetings import MeetingRepository
from app.services.job_runner import JobRunner


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
        await asyncio.wait_for(runner.stop(), timeout=0.2)
        await asyncio.sleep(0)

        assert jobs.get(job_id)["status"] == "running"
        assert jobs.recover_interrupted() == 1

    asyncio.run(scenario())
