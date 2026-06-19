"""设置/存储相关端点"""
from fastapi import APIRouter
from app.config import config

router = APIRouter()


@router.get("/v1/storage/status")
async def storage_status():
    """历史存储状态 — SettingsView 显示用"""
    return {
        "history_enabled": config.storage.history_enabled,
        "db_path": config.storage.db_path,
        "source": "env:STORAGE_HISTORY_ENABLED",
    }