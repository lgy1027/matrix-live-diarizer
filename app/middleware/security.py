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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; media-src 'self' blob:; connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'; base-uri 'self'",
        )
        return response
