"""FastAPI 应用工厂"""
import asyncio
import logging
import os
import sys
from functools import partial
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from transformers import logging as tf_logging

from app.config import config
from app.constants import APP_TITLE
from app.api import api_router
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.auth import AuthMiddleware
from app.middleware.security import SecurityHeadersMiddleware

tf_logging.set_verbosity_error()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("Matrix_Core")


def _is_expected_windows_transport_reset(context: dict) -> bool:
    """Match the harmless Proactor callback error emitted after a peer reset."""
    error = context.get("exception")
    error_code = getattr(error, "winerror", None) or getattr(error, "errno", None)
    return (
        isinstance(error, ConnectionResetError)
        and error_code == 10054
        and "_ProactorBasePipeTransport._call_connection_lost"
        in str(context.get("message", ""))
    )


def _configure_event_loop() -> None:
    """Suppress only the known Windows Proactor connection-close log noise."""
    if sys.platform != "win32":
        return
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    if getattr(previous_handler, "_matrix_transport_reset_filter", False):
        return

    def handle_exception(current_loop, context) -> None:
        if _is_expected_windows_transport_reset(context):
            logger.debug("忽略客户端已重置的 Windows HTTPS 连接")
            return
        if previous_handler is not None:
            previous_handler(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    handle_exception._matrix_transport_reset_filter = True
    loop.set_exception_handler(handle_exception)


def _register_lifecycle_handlers(app: FastAPI, *, startup, shutdown) -> None:
    """Register lifecycle hooks across FastAPI/Starlette versions.

    ``FastAPI.add_event_handler`` is not exposed by every supported FastAPI
    build.  The router-owned callback lists are the underlying Starlette
    lifecycle contract and work for both the older event API and current
    lifespan execution.
    """
    app.router.on_startup.append(startup)
    app.router.on_shutdown.append(shutdown)


async def _shutdown_application(job_runner, runtime, app) -> None:
    """Stop background work before releasing process-local model resources."""
    await job_runner.stop()
    tasks = getattr(app.state, "ws_background_tasks", None)
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await runtime.close()


def _is_running_under_pytest() -> bool:
    import sys
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _validate_runtime_safety() -> None:
    """拒绝明显危险的生产运行配置."""
    mode = config.deployment.mode
    if (
        os.environ.get("TEST_AUTH_BYPASS") == "1"
        and mode in ("lan", "public")
    ):
        raise RuntimeError("DEPLOYMENT_MODE=lan/public 时禁止设置 TEST_AUTH_BYPASS=1")
    if (
        os.environ.get("TEST_AUTH_BYPASS") == "1"
        and not config.server.debug
        and not _is_running_under_pytest()
    ):
        raise RuntimeError("TEST_AUTH_BYPASS=1 只能用于测试环境,禁止在正常服务中启动")
    if mode in ("lan", "public"):
        if not config.auth.jwt_secret:
            raise RuntimeError(f"DEPLOYMENT_MODE={mode} 时必须设置 JWT_SECRET")
        if "*" in config.cors.allowed_origins:
            raise RuntimeError(f"DEPLOYMENT_MODE={mode} 时必须把 ALLOWED_ORIGINS 收紧到可信 Origin")
    if mode == "public":
        logger.warning("DEPLOYMENT_MODE=public: 本项目不推荐公网裸露部署,请确认已启用 HTTPS/反向代理/防火墙")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    _validate_runtime_safety()
    app = FastAPI(
        title=APP_TITLE,
        description="实时音频转写与说话人识别系统",
        version="0.4.0-beta.0"
    )
    
    # 速率限制中间件(从 config.rate_limit 读取,支持 .env 调参)
    app.add_middleware(
        RateLimitMiddleware,
        enabled=config.rate_limit.enabled,
        requests_per_minute=config.rate_limit.requests_per_minute,
        requests_per_hour=config.rate_limit.requests_per_hour,
    )
    
    # CORS — 本地默认全开,LAN 部署可通过 .env 收紧
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.cors.allowed_origins),
        allow_origin_regex=(
            r"https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"
            if config.deployment.mode == "local" else None
        ),
        allow_credentials=config.cors.allow_credentials,
        allow_methods=list(config.cors.allow_methods),
        allow_headers=list(config.cors.allow_headers),
    )

    # Authentication boundary for every product API.
    # 全部 /v1/* 需 Bearer token, 白名单路径除外
    app.add_middleware(AuthMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    _init_engines(app)
    app.include_router(api_router)

    # SPA 接管 /，web/dist/index.html 是唯一前端入口。
    web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
    dist_dir = os.path.join(web_dir, "dist")
    dist_index = os.path.join(dist_dir, "index.html")
    dist_assets = os.path.join(dist_dir, "assets")
    if os.path.isfile(dist_index):
        from fastapi.responses import FileResponse

        # Vue build 产物 /assets/* 走独立 mount, 不被 SPA catch-all 兜
        if os.path.isdir(dist_assets):
            app.mount("/assets", StaticFiles(directory=dist_assets), name="spa-assets")
            logger.info(f"🟢 Vue 静态资源已挂载: /assets → {dist_assets}")

        @app.get("/", include_in_schema=False)
        async def spa_index() -> FileResponse:
            return FileResponse(dist_index)

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_catch_all(full_path: str) -> FileResponse:
            # /v1/* /health /ready /ws 走路由, 已由 API 注册; 这里只兜底 SPA
            if full_path.startswith(("v1/", "health", "ready", "ws", "docs", "openapi.json")):
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(dist_index)

        logger.info(f"🟢 SPA 已挂载: / → {dist_index}")
    else:
        logger.warning(f"⚠️  Vue dist 产物未找到: {dist_index} — SPA 接管 / 失败")

    return app


def _init_engines(app: FastAPI):
    """初始化推理引擎"""
    from engine.asr import get_asr_manager
    from engine.speaker import get_speaker_engine, get_engine_info

    asr_manager = get_asr_manager()
    asr_engine = asr_manager.get_engine()
    spk_engine = get_speaker_engine()

    asr_info = asr_manager.get_engine_info()
    engine_info = get_engine_info()
    logger.info(f"ASR 引擎: {asr_info['name']}, 模型: {asr_info['model']}")
    logger.info(f"声纹引擎: {engine_info['name']}, 模型: {engine_info['model']}")

    from app.runtime import ApplicationRuntime
    from app.runtime import diagnose_audio_dependencies
    runtime = ApplicationRuntime(asr_engine, spk_engine)

    dependency_report = diagnose_audio_dependencies()
    if dependency_report.compatible:
        logger.info("音频运行时诊断: %s", dependency_report.message)
    else:
        logger.warning("音频运行时诊断: %s", dependency_report.message)

    # Product persistence layer.
    from app.repositories.database import Database
    from app.repositories.settings import SettingsRepository
    from app.repositories.meetings import MeetingRepository
    from app.repositories.jobs import JobRepository
    from app.repositories.people import PeopleRepository

    db = Database(
        config.storage.db_path,
        create_default_admin=not config.auth.skip_default_admin,
    )
    db.init_schema()
    settings_repo = SettingsRepository(db)
    meeting_repo = MeetingRepository(db)
    job_repo = JobRepository(db)
    people_repo = PeopleRepository(db)

    app.state.db = db
    app.state.settings_repo = settings_repo
    app.state.meeting_repo = meeting_repo
    app.state.job_repo = job_repo
    app.state.people_repo = people_repo

    # Authentication service.
    from app.services.auth import AuthService
    app.state.auth_service = AuthService(db)

    app.state.runtime = runtime
    # Compatibility aliases for integrations; application code reads runtime.
    app.state.asr_engine = asr_engine
    app.state.asr_manager = asr_manager
    app.state.spk_engine = spk_engine
    app.state.config = config  # SPA 重构: 让 health.py 读 storage 配置

    from app.services.meeting_processor import MeetingProcessor
    from app.services.job_runner import JobRunner

    meeting_processor = MeetingProcessor(
        meeting_repo=meeting_repo,
        job_repo=job_repo,
        runtime=runtime,
        people_repo=people_repo,
    )
    app.state.meeting_processor = meeting_processor
    job_runner = JobRunner(job_repo, meeting_repo, meeting_processor)
    app.state.job_runner = job_runner
    app.router.on_startup.append(_configure_event_loop)
    _register_lifecycle_handlers(
        app,
        startup=job_runner.start,
        shutdown=partial(_shutdown_application, job_runner, runtime, app),
    )

    logger.info(f"💾 数据库已初始化: {config.storage.db_path}")
    logger.info("🔒 音频、文稿和声纹默认仅存储在本机")
    if config.llm.enabled and config.llm.allow_public:
        logger.warning("🌐 LLM 公网访问已启用，会议文本可能发送到: %s", config.llm.endpoint)
    else:
        logger.info("📦 首次启动可能联网下载所选模型；推理完成后可使用本地缓存")
