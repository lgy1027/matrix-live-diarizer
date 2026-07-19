"""Small security boundary for the browser-hosted local application."""
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_trusted_browser_origin(origin: str | None, allowed_origins=()) -> bool:
    """Allow native/no-Origin clients and explicitly trusted browser origins.

    无 Origin 视为可信是**有意为之**:浏览器对同源 fetch/XHR 在部分实现
    (如 Firefox)下不携带 Origin 头,本地模式的 SPA 在这些浏览器里靠这个
    放行。强制要求 Origin 会直接打断 SPA。

    CSRF 防护不靠"必须有 Origin",而是靠"Origin 存在时必须是可信的":
    不可信的跨站 Origin(如 evil.example)在此返回 False,中间件会拒绝
    bypass 并要求 Bearer token。

    注意:本机攻击者可任意伪造 Origin/Sec-Fetch-* 头,header 层无法区分
    "合法本机工具"与"恶意本机进程"。真正的本机隔离需走 DEPLOYMENT_MODE=lan
    或 LOCAL_AUTH_DISABLED=false(强制 token),这是文档化的威胁模型。
    """
    if not origin:
        return True
    if origin in allowed_origins:
        return True
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and parsed.hostname in LOOPBACK_HOSTS


def _connect_src_csp() -> str:
    """L2: 动态构建 connect-src。

    前端 WebSocket 用 window.location.host(同源),所以 WS host = 页面 host。
    - 默认 CORS 通配("*"):无法枚举具体 host,只能保留 `ws: wss:`(不改现状,
      避免误伤;通配模式本就信任任意来源)。
    - 显式 ALLOWED_ORIGINS(硬化部署 / LAN 模式):派生 ws/wss host,
      收紧到"同源 + 显式放行的 host",不再放行任意 ws 服务器,
      降低 XSS 经 WS 外泄的风险。

    loopback(127.0.0.1 / localhost)始终放行,保证本地 SPA 即便未配 origin 也能连。
    """
    from app.config import config
    try:
        origins = config.cors.allowed_origins
    except AttributeError:
        origins = ()
    if not origins or "*" in origins:
        return "connect-src 'self' ws: wss:;"
    ws_hosts = {"127.0.0.1", "localhost"}
    for origin in origins:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            continue
        if parsed.hostname:
            ws_hosts.add(parsed.hostname)
    parts = ["'self'"]
    for host in sorted(ws_hosts):
        # IPv6 host 在 CSP host-source 里必须带方括号(CSP3 规范),
        # 否则 ws://::1:* 会被解析器拒绝,WS 被浏览器拦。
        host_repr = f"[{host}]" if ":" in host else host
        parts.append(f"ws://{host_repr}:*")
        parts.append(f"wss://{host_repr}:*")
    return "connect-src " + " ".join(parts) + ";"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; media-src 'self' blob:; " + _connect_src_csp() +
            " frame-ancestors 'none'; base-uri 'self'",
        )
        return response
