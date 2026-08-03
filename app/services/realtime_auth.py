"""Authentication boundary for the realtime WebSocket protocol."""
import asyncio
import collections
import ipaddress
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
# 信任的反代 CIDR(与 RateLimitMiddleware 默认一致)。仅当 WS 直连 IP 落在这些
# 网段时才采纳 X-Forwarded-For,防客户端伪造 XFF 绕过限流。反代部署(lan/public)
# 在 .env 显式配置 TRUSTED_PROXIES 为具体反代 IP。
_WS_TRUSTED_NETWORKS = [
    ipaddress.ip_network(c, strict=False)
    for c in os.environ.get("TRUSTED_PROXIES", "127.0.0.0/8,::1/128").split(",")
    if c.strip()
]
_ws_connect_log: dict[str, collections.deque] = {}
# 进程级 IP 字典容量上限,防公网扫描/IPv6 轮换 never-again 的 IP 永驻内存。
_WS_MAX_TRACKED_IPS = 50_000

# 已建立的 WS 长连接复验凭证的间隔。HTTP 每请求都查 revoked/pwd_iat,
# 但 WS 长连接在 logout/改密后默认不会断,盗号者可继续导出实时转写/声纹。
# 每 N 秒在主接收循环复验一次,失效即 close(4401)。
_WS_REVALIDATE_INTERVAL = 10.0


def _ws_sweep_tracked() -> None:
    """全局容量上限淘汰:超 _WS_MAX_TRACKED_IPS 时按最近连接时间 LRU 丢弃。"""
    if len(_ws_connect_log) <= _WS_MAX_TRACKED_IPS:
        return
    ranked = sorted(
        _ws_connect_log.items(),
        key=lambda kv: kv[1][-1] if kv[1] else 0.0,
    )
    drop = len(_ws_connect_log) - _WS_MAX_TRACKED_IPS
    for ip, _ in ranked[:drop]:
        _ws_connect_log.pop(ip, None)


def _ws_client_ip(websocket) -> str:
    """解析 WS 客户端 IP:直连来自可信反代时读 X-Forwarded-For,否则用 socket peer。

    与 RateLimitMiddleware._get_client_ip 同策略。反代后所有 WS 直连都是 proxy IP,
    不读 XFF 会导致全站共享同一限流桶(单点 DoS);但无条件信任 XFF 又可被伪造。
    仅在直连 IP ∈ trusted_proxies 时采纳。

    注意:local 模式直连恒为 loopback(命中默认 trusted_proxies),此时也采纳 XFF,
    以支持"本机起反代(如 nginx)再回连"的部署形态。local 威胁模型假定本机可信;
    若担心本机进程伪造 XFF 绕限流,应切 lan/public 模式 + 显式配 TRUSTED_PROXIES。
    """
    direct = websocket.client.host if websocket.client else ""
    if direct and _is_ws_trusted(direct):
        forwarded = websocket.headers.get("X-Forwarded-For")
        if forwarded:
            return _canonical_ip(forwarded.split(",")[0])
        real_ip = websocket.headers.get("X-Real-IP")
        if real_ip:
            return _canonical_ip(real_ip)
    return _canonical_ip(direct)


def _canonical_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except (ValueError, AttributeError):
        return "unknown"


def _is_ws_trusted(ip_str: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(addr in net for net in _WS_TRUSTED_NETWORKS)


def _ws_rate_limited(client_host: str) -> bool:
    """返回 True 表示该 IP 在窗口内 WS 连接数超限。"""
    if not client_host:
        return False
    now = time.time()
    _ws_sweep_tracked()
    dq = _ws_connect_log.setdefault(client_host, collections.deque())
    cutoff = now - _WS_CONNECT_WINDOW
    while dq and dq[0] < cutoff:
        dq.popleft()
    # 队列清空后删除键,防 IP 扩散(NAT/IPv6 扫描)撑爆字典内存。
    if not dq and client_host in _ws_connect_log:
        del _ws_connect_log[client_host]
        dq = _ws_connect_log.setdefault(client_host, collections.deque())
    if len(dq) >= _WS_CONNECT_MAX:
        return True
    dq.append(now)
    return False


async def authenticate_websocket(websocket, client_id: str) -> bool:
    """Authenticate the first WebSocket message, or allow trusted local mode."""
    client_host = _ws_client_ip(websocket)
    # WS 连接限流在鉴权之前,防空打 WS 占 fd/协程
    if _ws_rate_limited(client_host):
        safe_client_host = client_host.replace("\r", r"\r").replace("\n", r"\n")[:64]
        logger.warning("[WS] %s 连接被限流 (%.0fs 内超 %d)", safe_client_host,
                       _WS_CONNECT_WINDOW, _WS_CONNECT_MAX)
        try:
            await websocket.close(code=4429, reason="连接过于频繁")
        except Exception:
            pass
        return False
    # 注意:loopback 集合只含真实本机地址。"testclient"(Starlette TestClient
    # 的固定 host)不得放进生产鉴权路径 —— 那等于为测试开后门,真实客户端
    # 不会用它。WS 测试如需 bypass,走 TEST_AUTH_BYPASS=1 或带真实 token。
    direct_host = websocket.client.host if websocket.client else ""
    local_bypass = (
        config.deployment.mode == "local"
        and config.auth.local_auth_disabled
        and direct_host in ("127.0.0.1", "::1")
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
        # logout 后的 token 立即失效(与 HTTP 中间件一致的 revoked 集合)
        if auth_service.is_revoked(token):
            await websocket.close(code=4401, reason="token 已注销")
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
        # 存 token 供主接收循环周期复验(logout/改密后踢掉盗号长连接)。
        # local/测试 bypass 分支无 token,_auth_token 保持未设,复验直接放行。
        websocket._auth_token = token
        websocket._auth_user_id = user_id
        websocket._auth_checked_at = time.time()
        return True
    except asyncio.TimeoutError:
        await websocket.close(code=4401, reason="auth 超时")
        return False
    except json.JSONDecodeError:
        await websocket.close(code=4401, reason="auth 格式错")
        return False
    except Exception as exc:
        # DB 异常 / decode_token 内部错误等:关闭 WS,避免连接悬空
        logger.warning("[WS] 鉴权内部错误: %s", exc)
        try:
            await websocket.close(code=4401, reason="鉴权内部错误")
        except Exception:
            pass
        return False


async def ws_revalidate(websocket) -> bool:
    """已建立的 WS 长连接周期复验凭证。

    HTTP 每请求都查 is_revoked/pwd_iat,但 WS 长连接在用户 logout 或改密后
    默认不断开,盗号者可继续接收实时转写/说话人数据。主接收循环每
    _WS_REVALIDATE_INTERVAL 秒调一次本函数,失效即由调用方 close(4401)。

    local/测试 bypass 分支无 _auth_token,直接放行(不复验)。
    返 False 表示凭证已失效。DB 异常时不踢(避免瞬时抖动误断合法连接)。
    """
    token = getattr(websocket, "_auth_token", None)
    if not token:
        return True
    now = time.time()
    if now - getattr(websocket, "_auth_checked_at", 0.0) < _WS_REVALIDATE_INTERVAL:
        return True  # 未到复验周期
    websocket._auth_checked_at = now
    app = getattr(websocket, "app", None)
    auth_service = getattr(getattr(app, "state", None), "auth_service", None) if app else None
    if auth_service is None:
        return True
    try:
        if auth_service.is_revoked(token):
            return False
        decoded = auth_service.decode_token(token)
        if not decoded:
            return False
        try:
            user = auth_service.get_user(int(decoded["sub"]))
        except (ValueError, KeyError, TypeError):
            return False
        if not user or not user.get("is_active"):
            return False
        if float(user.get("password_changed_at") or 0) > float(decoded.get("pwd_iat", 0)):
            return False
    except Exception as exc:
        # DB 瞬时抖动:不踢,避免误断合法连接;下次复验再判
        logger.warning("[WS] 复验内部错误(不踢): %s", exc)
        return True
    return True
