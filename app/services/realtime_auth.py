"""Authentication boundary for the realtime WebSocket protocol."""
import asyncio
import json
import logging
import os

from app.config import config
from app.middleware.security import is_trusted_browser_origin


logger = logging.getLogger("Matrix_Core")


async def authenticate_websocket(websocket, client_id: str) -> bool:
    """Authenticate the first WebSocket message, or allow trusted local mode."""
    client_host = websocket.client.host if websocket.client else ""
    local_bypass = (
        config.deployment.mode == "local"
        and config.auth.local_auth_disabled
        and client_host in ("127.0.0.1", "::1", "localhost", "testclient")
        and is_trusted_browser_origin(
            websocket.headers.get("origin"), config.cors.allowed_origins
        )
    )
    if os.environ.get("TEST_AUTH_BYPASS") == "1" or local_bypass:
        logger.info("[WS] %s 本地/测试模式 bypass 鉴权", client_id)
        return True

    try:
        auth_msg = await asyncio.wait_for(websocket.receive(), timeout=5.0)
        auth_payload = json.loads(auth_msg.get("text", "{}"))
        if not (isinstance(auth_payload, dict) and auth_payload.get("action") == "auth"):
            await websocket.close(code=4401, reason="需要 auth")
            return False
        token = auth_payload.get("token", "")
        if not token:
            await websocket.close(code=4401, reason="缺 token")
            return False
        auth_service = websocket.app.state.auth_service
        decoded = auth_service.decode_token(token)
        if not decoded:
            await websocket.close(code=4401, reason="token 无效")
            return False
        try:
            user_id = int(decoded["sub"])
            user = auth_service.get_user(user_id)
            if not user or not user.get("is_active"):
                await websocket.close(code=4401, reason="用户不存在/禁用")
                return False
            if user.get("must_change_password"):
                await websocket.close(code=4403, reason="首次登录必须先修改默认密码")
                return False
            if float(user.get("password_changed_at") or 0) > float(decoded.get("pwd_iat", 0)):
                await websocket.close(code=4401, reason="密码已修改, 请重新登录")
                return False
        except (ValueError, TypeError, KeyError):
            await websocket.close(code=4401, reason="token 格式错")
            return False
        logger.info("[WS] %s 鉴权通过 (user_id=%s)", client_id, user_id)
        return True
    except asyncio.TimeoutError:
        await websocket.close(code=4401, reason="auth 超时")
        return False
    except json.JSONDecodeError:
        await websocket.close(code=4401, reason="auth 格式错")
        return False
