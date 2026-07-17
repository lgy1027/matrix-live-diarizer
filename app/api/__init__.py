"""API 路由"""
from fastapi import APIRouter
from app.api.websocket import router as ws_router
from app.api.engines import router as engines_router
from app.api.health import router as health_router
from app.api.llm import router as llm_router
from app.api.auth import router as auth_router
from app.api.settings import router as settings_router
from app.api.meetings import router as meetings_router
from app.api.jobs import router as jobs_router
from app.api.people import router as people_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)  # 鉴权路由(白名单,中间件不拦截)
api_router.include_router(ws_router)
api_router.include_router(engines_router)
api_router.include_router(llm_router)
api_router.include_router(settings_router)
api_router.include_router(meetings_router)
api_router.include_router(jobs_router)
api_router.include_router(people_router)
