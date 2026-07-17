"""Model catalog and speaker-engine selection API."""
import asyncio
from fastapi import APIRouter, HTTPException, Request

from app.schemas.response import EngineSwitchRequest, EngineSwitchResponse, EnginesListResponse
from engine.speaker.speaker_factory import get_engine_manager


router = APIRouter(tags=["engines"])


@router.get("/v1/models")
async def get_models():
    from engine.speaker import get_all_engines
    return get_all_engines()


@router.get("/v1/engines", response_model=EnginesListResponse)
async def list_engines():
    info = get_engine_manager().get_all_engines_info()
    return EnginesListResponse(current=info["current"], engines=info["engines"])


@router.put("/v1/engine", response_model=EngineSwitchResponse)
async def switch_engine(body: EngineSwitchRequest, request: Request):
    manager = get_engine_manager()
    result = await asyncio.to_thread(manager.switch_engine, body.engine_type)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "切换失败"))
    new_engine = manager.get_engine()
    runtime = getattr(request.app.state, "runtime", None)
    if runtime is not None:
        runtime.set_speaker(new_engine)
    if hasattr(request.app.state, "spk_engine"):
        request.app.state.spk_engine = new_engine
    return EngineSwitchResponse(**result)
