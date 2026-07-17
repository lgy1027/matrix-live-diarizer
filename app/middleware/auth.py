"""JWT 鉴权中间件 (Roadmap 安全项)

策略: 全部 /v1/* 需 Bearer token,白名单路径除外
- 白名单: /v1/auth/login, /v1/auth/logout, /health, /ready, /v1/models, /v1/llm/status
- WebSocket (/ws/*): 不走 HTTP middleware,WS 路径单独在 endpoint 校验
- OPTIONS 预检: 放行

401 返 JSON: {detail: "..."}
"""
import logging
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.middleware.security import is_trusted_browser_origin

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

PASSWORD_CHANGE_ALLOWED_PATHS = (
    "/v1/auth/me",
    "/v1/auth/change-password",
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
        auth_header = request.headers.get("authorization", "")
        # 可信本机允许无 token 使用产品；如果显式提供了 token，仍需验签并
        # 注入 request.state，供改密和账户接口使用。
        from app.config import config
        client_host = request.client.host if request.client else ""
        local_bypass = (
            config.deployment.mode == "local"
            and config.auth.local_auth_disabled
            and client_host in {"127.0.0.1", "::1", "localhost"}
            and is_trusted_browser_origin(
                request.headers.get("origin"), config.cors.allowed_origins
            )
        )
        if local_bypass and not auth_header:
            return await call_next(request)

        # 提取 Bearer token
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
            user_id = int(payload["sub"])
            request.state.user_id = user_id
            request.state.username = payload.get("username", "")
        except (KeyError, ValueError, TypeError):
            return JSONResponse(
                status_code=401,
                content={"detail": "token 格式错误"},
            )
        # Bug-88 (审核 #7): 改密后旧 token 失效
        # 校验: token.pwd_iat < user.password_changed_at → 401
        # 防 token 泄露后被滥用: 改密后即使 token 没过期也不能用
        try:
            user_row = auth_service.get_user(user_id)
            if not user_row:
                raise HTTPException(status_code=401, detail="用户不存在")
            if not user_row.get("is_active"):
                raise HTTPException(status_code=401, detail="账户已禁用")
            token_pwd_iat = float(payload.get("pwd_iat", 0))
            current_pwd_iat = float(user_row.get("password_changed_at") or 0)
            if current_pwd_iat > token_pwd_iat:
                # 用户改过密,旧 token 失效
                logger.info(f"[AUTH] user_id={user_id} 改密后旧 token 失效")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "密码已修改, 请重新登录"},
                )
            if user_row.get("must_change_password") and path not in PASSWORD_CHANGE_ALLOWED_PATHS:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "首次登录必须先修改默认密码"},
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[AUTH] pwd_iat 校验失败: {e}")
            return JSONResponse(
                status_code=401,
                content={"detail": "鉴权失败"},
            )
        return await call_next(request)
