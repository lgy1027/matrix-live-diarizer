import asyncio

from fastapi import FastAPI

from app import _register_lifecycle_handlers
from app import _shutdown_application


async def _startup():
    return None


async def _shutdown():
    return None


def test_lifecycle_registration_does_not_require_fastapi_convenience_method():
    app = FastAPI()
    _register_lifecycle_handlers(app, startup=_startup, shutdown=_shutdown)

    assert _startup in app.router.on_startup
    assert _shutdown in app.router.on_shutdown


def test_shutdown_stops_jobs_before_releasing_engines():
    events = []

    class Runner:
        async def stop(self):
            events.append("jobs")

    class Runtime:
        async def close(self):
            events.append("engines")

    asyncio.run(_shutdown_application(Runner(), Runtime()))

    assert events == ["jobs", "engines"]
