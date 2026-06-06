"""FastAPI 应用工厂"""
import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from transformers import logging as tf_logging

from app.config import config
from app.constants import APP_TITLE
from app.api import api_router
from app.api.websocket import init_engines as init_ws_engines
from app.api.upload import init_engines as init_upload_engines
from app.middleware.rate_limit import RateLimitMiddleware

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
    
    # 速率限制中间件
    app.add_middleware(
        RateLimitMiddleware,
        requests_per_minute=getattr(config.server, 'rate_limit_requests', 100)
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    _init_engines(app)
    app.include_router(api_router)
    
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

    current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    init_ws_engines(asr_engine, spk_engine, inference_lock)
    init_upload_engines(asr_engine, spk_engine, inference_lock, current_dir, transcript_repo)
    init_health_check(asr_engine, spk_engine)

    app.state.asr_engine = asr_engine
    app.state.spk_engine = spk_engine
    app.state.inference_lock = inference_lock

    logger.info(f"💾 数据库已初始化: {config.storage.db_path}")
    logger.info("🔒 完全离线模式:所有数据仅在本机处理")
