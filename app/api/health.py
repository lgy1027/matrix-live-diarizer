"""健康检查 API"""
import time
import logging

from fastapi import APIRouter

logger = logging.getLogger("Matrix_Core")

router = APIRouter()

asr_engine = None
spk_engine = None


def init_health_check(asr, spk):
    """初始化健康检查引擎引用"""
    global asr_engine, spk_engine
    asr_engine = asr
    spk_engine = spk


@router.get("/health")
async def health_check():
    """健康检查端点 - 用于负载均衡器和监控"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
    }


@router.get("/ready")
async def readiness_check():
    """就绪检查端点 - 检查引擎是否已初始化"""
    return {
        "status": "ready" if (asr_engine is not None and spk_engine is not None) else "not_ready",
        "asr": asr_engine is not None,
        "speaker": spk_engine is not None,
        "timestamp": time.time(),
    }
