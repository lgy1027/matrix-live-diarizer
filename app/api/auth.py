"""鉴权端点 (Roadmap 安全项)

POST /v1/auth/login
POST /v1/auth/logout
POST /v1/auth/change-password
GET  /v1/auth/me
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.auth import AuthService

router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=6, max_length=200)


def _auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


@router.post("/v1/auth/login")
def login(body: LoginRequest, request: Request):
    """登录: 校验 username/password, 返 token + user"""
    auth: AuthService = _auth_service(request)
    user = auth.authenticate(body.username, body.password)
    if not user:
        # 模糊错误:不暴露是 username 还是 password 错
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = auth.create_token(user["id"], user["username"])
    return {
        "token": token,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "must_change_password": bool(user["must_change_password"]),
        },
    }


@router.post("/v1/auth/logout")
def logout(request: Request):
    """退出登录: 客户端删 localStorage token;服务端无状态(简化为 noop)"""
    # 未来可加 token 黑名单 (Revoke) 端,目前依赖短 TTL
    return {"message": "已退出登录"}


@router.get("/v1/auth/me")
def me(request: Request):
    """当前用户信息(需鉴权)"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    auth: AuthService = _auth_service(request)
    user = auth.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user


@router.post("/v1/auth/change-password")
def change_password(body: ChangePasswordRequest, request: Request):
    """改密(需鉴权)"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    auth: AuthService = _auth_service(request)
    user = auth.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    # 验证旧密码(走 authenticate 校验)
    candidate = auth.authenticate(user["username"], body.old_password)
    if not candidate:
        raise HTTPException(status_code=400, detail="旧密码错误")
    ok = auth.change_password(user_id, body.new_password)
    if not ok:
        raise HTTPException(status_code=500, detail="改密失败")
    # 改密后签发新 token
    new_token = auth.create_token(user_id, user["username"])
    return {
        "message": "密码已修改",
        "token": new_token,
        "user": {
            "id": user_id,
            "username": user["username"],
            "must_change_password": False,
        },
    }
