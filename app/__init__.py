"""FastAPI 应用工厂"""
import asyncio
import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from transformers import logging as tf_logging

from app.config import config
from app.constants import APP_TITLE
from app.api import api_router
from app.api.websocket import init_engines as init_ws_engines
from app.api.upload import init_engines as init_upload_engines
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.auth import AuthMiddleware

tf_logging.set_verbosity_error()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger("Matrix_Core")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    app = FastAPI(
        title=APP_TITLE,
        description="实时音频转写与说话人识别系统",
        version="1.0.0"
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
        allow_credentials=config.cors.allow_credentials,
        allow_methods=list(config.cors.allow_methods),
        allow_headers=list(config.cors.allow_headers),
    )

    # 鉴权中间件 (Roadmap 安全项)
    # 全部 /v1/* 需 Bearer token, 白名单路径除外
    app.add_middleware(AuthMiddleware)

    _init_engines(app)
    app.include_router(api_router)

    # v0.3+: SPA 接管 /, web/dist/index.html 是 Vue 入口
    # 旧的 web/login.html, web/index.html, web/css/studio.css 全部删除 (Vue 全管)
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
    from engine.asr_engine import ASREngine
    from engine.speaker import get_speaker_engine, get_engine_info

    asr_engine = ASREngine()
    spk_engine = get_speaker_engine()

    engine_info = get_engine_info()
    logger.info(f"声纹引擎: {engine_info['name']}, 模型: {engine_info['model']}")

    inference_lock = asyncio.Lock()

    import os
    from app.api.health import init_health_check

    # 持久化层（先于 init_upload_engines，确保 transcript_repo 可被注入）
    from app.repositories.database import Database
    from app.repositories.transcripts import TranscriptRepository
    from app.repositories.settings import SettingsRepository

    db = Database(config.storage.db_path)
    db.init_schema()
    transcript_repo = TranscriptRepository(db)
    settings_repo = SettingsRepository(db)

    app.state.db = db
    app.state.transcript_repo = transcript_repo
    app.state.settings_repo = settings_repo

    # 鉴权服务 (Roadmap 安全项)
    from app.services.auth import AuthService
    app.state.auth_service = AuthService(db)

    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    init_ws_engines(asr_engine, spk_engine, inference_lock)
    init_upload_engines(asr_engine, spk_engine, inference_lock, current_dir, transcript_repo)
    init_health_check(asr_engine, spk_engine)

    app.state.asr_engine = asr_engine
    app.state.spk_engine = spk_engine
    app.state.inference_lock = inference_lock
    app.state.config = config  # SPA 重构: 让 health.py 读 storage 配置

    logger.info(f"💾 数据库已初始化: {config.storage.db_path}")
    logger.info("🔒 完全离线模式:所有数据仅在本机处理")
