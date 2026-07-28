"""JWT 鉴权中间件 (Roadmap 安全项)

策略: 全部 /v1/* 需 Bearer token,白名单路径除外
- 白名单: /v1/auth/login, /v1/auth/logout, /health, /ready, /v1/models, /v1/llm/status
- WebSocket (/ws/*): 不走 HTTP middleware,WS 路径单独在 endpoint 校验
- OPTIONS 预检: 放行

401/403 返 JSON: {detail: "..."};跨源时带 CORS 头(否则浏览器拿不到响应,
前端无法区分"未登录"与"网络错误",不能自动跳登录页)。
"""
import logging
from fastapi import Request
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
    "/v1/engines",
    "/v1/llm/status",
)

PASSWORD_CHANGE_ALLOWED_PATHS = (
    "/v1/auth/me",
    "/v1/auth/change-password",
)


def _auth_error_response(request: Request, status_code: int, detail: str) -> JSONResponse:
    """构造鉴权错误响应。跨源请求带 Access-Control-Allow-Origin,否则浏览器
    因缺 CORS 头把它当网络错误,前端无法读取 401/403 跳登录页。

    仅当请求 Origin 在 allowed_origins(或通配且 local 模式)时回填 ACAO,
    避免给任意 Origin 回填造成跨源信息泄露。复用 is_trusted_browser_origin。
    """
    from app.config import config
    origin = request.headers.get("origin")
    headers = {}
    if origin and is_trusted_browser_origin(origin, config.cors.allowed_origins):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return JSONResponse(status_code=status_code, content={"detail": detail}, headers=headers)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 测试环境通过 TEST_AUTH_BYPASS=1 跳过鉴权(conftest 设置),让现有
        # 测试 client fixture 不必每个都带 token。
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
            and client_host in {"127.0.0.1", "::1"}
            and is_trusted_browser_origin(
                request.headers.get("origin"), config.cors.allowed_origins
            )
        )
        if local_bypass and not auth_header:
            return await call_next(request)

        # 提取 Bearer token
        if not auth_header.lower().startswith("bearer "):
            return _auth_error_response(request, 401, "未登录或登录已过期,请重新登录")
        token = auth_header.split(" ", 1)[1].strip()
        if not token:
            return _auth_error_response(request, 401, "Bearer token 缺失")
        # 校验
        auth_service = request.app.state.auth_service
        payload = auth_service.decode_token(token)
        if not payload:
            return _auth_error_response(request, 401, "token 无效或已过期")
        # 把 user_id 注入 request.state 给 endpoint 用
        try:
            user_id = int(payload["sub"])
            request.state.user_id = user_id
            request.state.username = payload.get("username", "")
        except (KeyError, ValueError, TypeError):
            return _auth_error_response(request, 401, "token 格式错误")
        # 改密后旧 token 立即失效: token 里记录的 pwd_iat 早于用户的
        # password_changed_at → 401。避免泄露的 token 在原 TTL 内继续可用。
        try:
            user_row = auth_service.get_user(user_id)
            if not user_row:
                return _auth_error_response(request, 401, "用户不存在")
            if not user_row.get("is_active"):
                return _auth_error_response(request, 401, "账户已禁用")
            token_pwd_iat = float(payload.get("pwd_iat", 0))
            current_pwd_iat = float(user_row.get("password_changed_at") or 0)
            if current_pwd_iat > token_pwd_iat:
                # 用户改过密,旧 token 失效
                logger.info(f"[AUTH] user_id={user_id} 改密后旧 token 失效")
                return _auth_error_response(request, 401, "密码已修改, 请重新登录")
            if user_row.get("must_change_password") and path not in PASSWORD_CHANGE_ALLOWED_PATHS:
                return _auth_error_response(request, 403, "首次登录必须先修改默认密码")
        except Exception as e:
            # pwd_iat / user 校验异常 → 统一降级 401(不暴露内部错误)。
            # 本块不再 raise HTTPException(L3 后改 return JSONResponse),
            # 故无需单独 except HTTPException。
            logger.warning(f"[AUTH] pwd_iat 校验失败: {e}")
            return _auth_error_response(request, 401, "鉴权失败")
        return await call_next(request)
