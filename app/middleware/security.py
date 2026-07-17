"""Small security boundary for the browser-hosted local application."""
from urllib.parse import urlsplit

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_trusted_browser_origin(origin: str | None, allowed_origins=()) -> bool:
    """Allow native/no-Origin clients and explicitly trusted browser origins."""
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
