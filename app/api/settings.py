"""设置/存储相关端点"""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import config

router = APIRouter()


class AsrSwitchRequest(BaseModel):
    """ASR 切换请求."""
    engine_type: str = Field(..., min_length=1, description="ASR 引擎类型")


class AsrSwitchResponse(BaseModel):
    success: bool
    engine_type: str
    previous_type: Optional[str] = None
    engine_info: Optional[Dict[str, Any]] = None
    already_active: bool = False
    downloaded: bool = False
    switched: bool = False
    error: Optional[str] = None


@router.get("/v1/storage/status")
async def storage_status():
    """历史存储状态 — SettingsView 显示用"""
    return {
        "history_enabled": config.storage.history_enabled,
        "db_path": config.storage.db_path,
        "source": "env:STORAGE_HISTORY_ENABLED",
    }


@router.get("/v1/asr/engines")
async def list_asr_engines():
    """获取 ASR 引擎列表和切换状态."""
    from engine.asr import get_asr_manager
    return get_asr_manager().get_all_engines_info()


@router.put("/v1/asr/engine", response_model=AsrSwitchResponse)
async def switch_asr_engine(body: AsrSwitchRequest, request: Request):
    """受控切换 ASR 引擎.

    下载/加载新模型期间旧 ASR 继续服务;只有新模型加载成功后才切换。
    """
    from engine.asr import get_asr_manager

    manager = get_asr_manager()
    result = manager.switch_engine(body.engine_type)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "ASR 切换失败"))

    new_engine = manager.get_engine()
    request.app.state.asr_engine = new_engine
    request.app.state.asr_manager = manager

    # 刷新旧模块级引用,保持现有 websocket/upload/health 代码兼容。
    try:
        from app.api import websocket as ws_api
        from app.api import upload as upload_api
        from app.api import health as health_api
        ws_api.asr_engine = new_engine
        upload_api.asr_engine = new_engine
        health_api.asr_engine = new_engine
    except Exception:
        pass

    return AsrSwitchResponse(**result)
