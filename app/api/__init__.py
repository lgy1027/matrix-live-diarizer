"""API 路由"""
from fastapi import APIRouter
from app.api.websocket import router as ws_router
from app.api.upload import router as upload_router

api_router = APIRouter()
api_router.include_router(ws_router)
api_router.include_router(upload_router)