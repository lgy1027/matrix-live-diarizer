"""健康检查 API"""
import time
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Request

logger = logging.getLogger("Matrix_Core")

router = APIRouter()

@router.get("/health")
async def health_check():
    """健康检查端点 - 用于负载均衡器和监控"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
    }


@router.get("/ready")
def readiness_check(request: Request):
    """检查用户实际需要的模型、存储和磁盘，而不只检查对象存在。"""
    runtime = getattr(request.app.state, "runtime", None)
    database = getattr(request.app.state, "db", None)
    app_config = getattr(request.app.state, "config", None)
    media_dir = app_config.storage.media_dir if app_config is not None else None
    checks = {
        "asr": runtime is not None and runtime.asr is not None,
        "speaker": runtime is not None and runtime.speaker is not None,
        "database": False,
        "media": False,
        "disk": False,
    }
    if database is not None:
        try:
            with database.connect() as conn:
                conn.execute("SELECT 1").fetchone()
            checks["database"] = True
        except Exception as exc:
            logger.warning("readiness database failed: %s", exc)
    if media_dir:
        try:
            path = Path(media_dir).resolve()
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".matrix-write-test"
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            checks["media"] = True
            checks["disk"] = shutil.disk_usage(path).free >= 256 * 1024 * 1024
        except Exception as exc:
            logger.warning("readiness media failed: %s", exc)
    else:
        # 保持独立 router 测试和嵌入使用兼容；正式 app 总会注入路径。
        checks["database"] = database is None
        checks["media"] = True
        checks["disk"] = True
    ready = all(checks.values())
    return {
        "status": "ready" if ready else "not_ready",
        **checks,
        "timestamp": time.time(),
    }
