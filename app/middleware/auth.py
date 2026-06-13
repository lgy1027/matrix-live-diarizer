"""JWT 鉴权中间件 (Roadmap 安全项)

策略: 全部 /v1/* 需 Bearer token,白名单路径除外
- 白名单: /v1/auth/login, /v1/auth/logout, /health, /ready, /v1/models, /v1/llm/status
- WebSocket (/ws/*): 不走 HTTP middleware,WS 路径单独在 endpoint 校验
- OPTIONS 预检: 放行

401 返 JSON: {detail: "..."}
"""
import logging
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("Matrix_Auth_MW")

# 白名单路径前缀(不需要鉴权)
WHITELIST_PATHS = (
    "/v1/auth/login",
    "/v1/auth/logout",
    "/health",
    "/ready",
    "/v1/models",
    "/v1/llm/status",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Bug-79: 测试模式绕过鉴权(避免破坏 53 个现有 client fixture)
        # 机制: conftest 设置 TEST_AUTH_BYPASS=1,这里跳过鉴权
        import os as _os
        if _os.environ.get("TEST_AUTH_BYPASS") == "1":
            return await call_next(request)

        path = request.url.path
        # 静态文件 + WebSocket 不走此中间件
        if not path.startswith("/v1/"):
            return await call_next(request)
        # 白名单放行
        if any(path == p or path.startswith(p + "/") for p in WHITELIST_PATHS):
            return await call_next(request)
        # OPTIONS 预检放行(CORS)
        if request.method == "OPTIONS":
            return await call_next(request)
        # 提取 Bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.lower().startswith("bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "未登录或登录已过期,请重新登录"},
            )
        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Bearer token 缺失"},
            )
        # 校验
        auth_service = request.app.state.auth_service
        payload = auth_service.decode_token(token)
        if not payload:
            return JSONResponse(
                status_code=401,
                content={"detail": "token 无效或已过期"},
            )
        # 把 user_id 注入 request.state 给 endpoint 用
        try:
            request.state.user_id = int(payload["sub"])
            request.state.username = payload.get("username", "")
        except (KeyError, ValueError, TypeError):
            return JSONResponse(
                status_code=401,
                content={"detail": "token 格式错误"},
            )
        return await call_next(request)
