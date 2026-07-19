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
    """切换声纹引擎。

    L8 说明(per-session 一致性):切换只更新 runtime._speaker / app.state.spk_engine,
    **不触碰已连接 WS 会话** —— 每个会话持有的 EngineSnapshot 是切换瞬间的
    frozen 引用,整场会议用同一引擎,保证 embedding 维度/聚类空间一致。

    切换时**故意不主动 cleanup 旧引擎的 session scope**:进行中的会话仍持有旧
    snapshot,主动 cleanup 会清掉它们正在用的聚类数据。旧引擎的 session 资源由
    两条路径自然释放:(1) 会话断开时,WS endpoint 的 finally 用 _engine_snapshot
    里**该会话自己的引擎**(可能是旧引擎)调 cleanup_client → delete_session_clusters;
    (2) 引擎被 LRU evict 时整体回收。故无需切换时额外清理。

    Embedding 维度变化的 warning 由 manager.switch_engine 在 result 里返回。
    """
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
