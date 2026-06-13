"""API 路由"""
from fastapi import APIRouter
from app.api.websocket import router as ws_router
from app.api.upload import router as upload_router
from app.api.speakers import router as speakers_router
from app.api.health import router as health_router
from app.api.exports import router as exports_router
from app.api.history import router as history_router
from app.api.sessions import router as sessions_router
from app.api.llm import router as llm_router
from app.api.search import router as search_router
from app.api.auth import router as auth_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)  # 鉴权路由(白名单,中间件不拦截)
api_router.include_router(ws_router)
api_router.include_router(upload_router)
api_router.include_router(speakers_router)
api_router.include_router(exports_router)
api_router.include_router(history_router)
api_router.include_router(sessions_router)
api_router.include_router(llm_router)
api_router.include_router(search_router)