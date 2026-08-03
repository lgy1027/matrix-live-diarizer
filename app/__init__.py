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
    level=logging.DEBUG if config.server.debug else logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("Matrix_Core")
APP_VERSION = "0.2.0-beta"


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
    # Older embedders may implement ``stop`` without a return value.  Only an
    # explicit False means a provider worker is known to still be alive.
    runner_stopped = await job_runner.stop()
    tasks = getattr(app.state, "ws_background_tasks", None)
    if tasks:
        # 上限对齐 deferred processor 超时(120s),避免推理进行中卸载模型触发
        # use-after-free;超时后显式 cancel 残余 task 再 short-await,再 close。
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            # wait_for 已 cancel gather(传播给内部 task);不直接操作 t(tasks
            # 里可能是裸 coroutine 无 done()/cancel())。120s 对齐 deferred
            # processor 超时,正常应已收尾;极端未完成则由进程退出回收。
            logger.warning(
                "[shutdown] %d 个 WS 后台任务 120s 未完成, 放弃等待",
                len(tasks),
            )
    if runner_stopped is not False:
        await runtime.close()
    else:
        # A provider worker can outlive cancellation of its asyncio wrapper.
        # Closing model objects here would race that worker; process teardown is
        # the safe final resource reclamation path.
        logger.warning("[shutdown] 后台推理仍在运行，跳过显式模型卸载")


def _is_running_under_pytest() -> bool:
    import sys
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _validate_runtime_safety() -> None:
    """拒绝明显危险的生产运行配置."""
    mode = config.deployment.mode
    if config.server.workers != 1:
        raise RuntimeError(
            "WORKERS 必须为 1：任务队列、限流、会话撤销和推理引擎均为进程内状态"
        )
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
        if not getattr(config.server, "enable_https", False):
            logger.warning(
                "DEPLOYMENT_MODE=%s 未启用 HTTPS: JWT 明文传输有 MITM 风险,"
                "请置于 HTTPS 反代后或设置 ENABLE_HTTPS=true", mode,
            )
    if mode == "public":
        logger.warning("DEPLOYMENT_MODE=public: 本项目不推荐公网裸露部署,请确认已启用 HTTPS/反向代理/防火墙")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    _validate_runtime_safety()
    app = FastAPI(
        title=APP_TITLE,
        description="实时音频转写与说话人识别系统",
        version=APP_VERSION,
    )
    
    # 速率限制中间件(从 config.rate_limit 读取,支持 .env 调参)
    # trusted_proxies 与 WS realtime_auth 共用同一 TRUSTED_PROXIES 来源,
    # 避免 LAN 反代下 HTTP 限流不信任 XFF → 全 LAN 共享单桶被单点 DoS。
    app.add_middleware(
        RateLimitMiddleware,
        enabled=config.rate_limit.enabled,
        requests_per_minute=config.rate_limit.requests_per_minute,
        requests_per_hour=config.rate_limit.requests_per_hour,
        trusted_proxies=config.rate_limit.trusted_proxies,
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
            # 只兜底已知 SPA 路由前缀;未知路径(/v2 /api /internal 等)返 404,
            # 避免吞掉未来 v2 路由或让未知 API 调用方拿到 HTML。
            from fastapi import HTTPException
            spa_prefixes = ("live", "meetings", "people", "settings", "login", "tasks")
            first = full_path.split("/")[0] if full_path else ""
            if not full_path or first in spa_prefixes:
                return FileResponse(dist_index)
            raise HTTPException(status_code=404, detail="Not Found")

        logger.info(f"🟢 SPA 已挂载: / → {dist_index}")
    else:
        logger.warning(f"⚠️  Vue dist 产物未找到: {dist_index} — SPA 接管 / 失败")

    return app


def _init_engines(app: FastAPI):
    """初始化推理引擎。

    引擎加载失败不应击穿整个 app:用降级模式(None 引擎)继续启动,
    /ready 自然返 not_ready,前端只读模式可用,而不是进程崩溃。
    """
    from engine.asr import get_asr_manager
    from engine.speaker import get_speaker_engine

    asr_engine = None
    asr_manager = None
    try:
        asr_manager = get_asr_manager()
        asr_engine = asr_manager.get_engine()
    except Exception as exc:
        logger.error("[APP] ASR 引擎初始化失败,降级为无 ASR 模式: %s", exc)
    spk_engine = None
    try:
        spk_engine = get_speaker_engine()
    except Exception as exc:
        logger.error("[APP] 声纹引擎初始化失败,降级为无声纹模式: %s", exc)

    try:
        asr_info = asr_manager.get_engine_info()
    except Exception:
        asr_info = {"name": "unavailable", "model": "unavailable"}
    try:
        from engine.speaker import get_engine_info
        engine_info = get_engine_info()
    except Exception:
        engine_info = {"name": "unavailable", "model": "unavailable"}
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
    # people.py 注册声样时保留 spk_engine 作为兼容入口；其余推理统一由
    # runtime 管理。
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
