import asyncio

from fastapi import FastAPI

from app import _configure_event_loop
from app import _is_expected_windows_transport_reset
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

    class App:
        class state:
            ws_background_tasks = None

    asyncio.run(_shutdown_application(Runner(), Runtime(), App()))

    assert events == ["jobs", "engines"]


def test_windows_proactor_connection_reset_is_expected():
    error = ConnectionResetError(10054, "connection reset")
    context = {
        "message": (
            "Exception in callback "
            "_ProactorBasePipeTransport._call_connection_lost(None)"
        ),
        "exception": error,
    }

    assert _is_expected_windows_transport_reset(context)
    assert not _is_expected_windows_transport_reset(
        {**context, "message": "Exception in another callback"}
    )
    assert not _is_expected_windows_transport_reset(
        {**context, "exception": ConnectionResetError(10053, "aborted")}
    )


def test_event_loop_handler_delegates_unrelated_errors(monkeypatch):
    delegated = []

    class Loop:
        handler = None

        def get_exception_handler(self):
            return lambda _loop, context: delegated.append(context)

        def set_exception_handler(self, handler):
            self.handler = handler

    loop = Loop()
    monkeypatch.setattr("app.sys.platform", "win32")
    monkeypatch.setattr("app.asyncio.get_running_loop", lambda: loop)

    _configure_event_loop()
    context = {"message": "unrelated", "exception": RuntimeError("boom")}
    loop.handler(loop, context)

    assert delegated == [context]

    expected_reset = {
        "message": (
            "Exception in callback "
            "_ProactorBasePipeTransport._call_connection_lost(None)"
        ),
        "exception": ConnectionResetError(10054, "connection reset"),
    }
    loop.handler(loop, expected_reset)

    assert delegated == [context]
