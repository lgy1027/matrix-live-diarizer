"""Authentication boundary for the realtime WebSocket protocol."""
import asyncio
import collections
import json
import logging
import os
import time

from app.config import config
from app.middleware.security import is_trusted_browser_origin


logger = logging.getLogger("Matrix_Core")

# 进程级 WebSocket 连接速率限制。WS 不走 HTTP 中间件,攻击者可空打 WS
# 触发 5s receive 超时占用 fd/协程。鉴权前做 per-IP 滑动窗口,超阈值
# close(4401)。
_WS_CONNECT_WINDOW = 60.0          # 滑动窗口(秒)
_WS_CONNECT_MAX = 20               # 窗口内每 IP 最大连接数
_ws_connect_log: dict[str, collections.deque] = {}


def _ws_rate_limited(client_host: str) -> bool:
    """返回 True 表示该 IP 在窗口内 WS 连接数超限。"""
    if not client_host:
        return False
    now = time.time()
    dq = _ws_connect_log.setdefault(client_host, collections.deque())
    cutoff = now - _WS_CONNECT_WINDOW
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= _WS_CONNECT_MAX:
        return True
    dq.append(now)
    return False


async def authenticate_websocket(websocket, client_id: str) -> bool:
    """Authenticate the first WebSocket message, or allow trusted local mode."""
    client_host = websocket.client.host if websocket.client else ""
    # WS 连接限流在鉴权之前,防空打 WS 占 fd/协程
    if _ws_rate_limited(client_host):
        logger.warning("[WS] %s 连接被限流 (%.0fs 内超 %d)", client_host,
                       _WS_CONNECT_WINDOW, _WS_CONNECT_MAX)
        try:
            await websocket.close(code=4429, reason="连接过于频繁")
        except Exception:
            pass
        return False
    # 注意:loopback 集合只含真实本机地址。"testclient"(Starlette TestClient
    # 的固定 host)不得放进生产鉴权路径 —— 那等于为测试开后门,真实客户端
    # 不会用它。WS 测试如需 bypass,走 TEST_AUTH_BYPASS=1 或带真实 token。
    local_bypass = (
        config.deployment.mode == "local"
        and config.auth.local_auth_disabled
        and client_host in ("127.0.0.1", "::1")
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
