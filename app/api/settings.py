"""设置/存储相关端点"""
import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class AsrSwitchRequest(BaseModel):
    """ASR 切换请求."""
    engine_type: str = Field(..., min_length=1, max_length=64, description="ASR 引擎类型")


class AsrSwitchResponse(BaseModel):
    success: bool
    engine_type: str
    previous_type: Optional[str] = None
    engine_info: Optional[Dict[str, Any]] = None
    already_active: bool = False
    downloaded: bool = False
    switched: bool = False
    error: Optional[str] = None


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
    result = await asyncio.to_thread(manager.switch_engine, body.engine_type)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "ASR 切换失败"))

    new_engine = manager.get_engine()
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is not None:
        runtime.set_asr(new_engine)
    # ASR 引擎统一由 runtime 管理。

    return AsrSwitchResponse(**result)
