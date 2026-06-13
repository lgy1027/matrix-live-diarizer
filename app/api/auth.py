"""鉴权端点 (Roadmap 安全项)

POST /v1/auth/login
POST /v1/auth/logout
POST /v1/auth/change-password
GET  /v1/auth/me
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, field_validator
import re

from app.services.auth import AuthService

router = APIRouter()


# Bug-90 (审核 #12): 422 (Pydantic 校验) → 401 模糊返, 防 schema 暴露
def _validate_or_401(model_cls, data: dict, request: Request):
    """用 model_cls 校验 dict, 失败抛 401 (不暴露 schema)"""
    try:
        return model_cls(**data)
    except ValidationError as e:
        # 模糊错误 — 不区分 username 太短 / 密码太弱 / 字段缺失
        raise HTTPException(
            status_code=401,
            detail="登录信息格式错误,请检查后重试",
        )


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=200)
    # Bug-86 (审核 #5): 密码强度 — 至少 1 字母 + 1 数字
    # Pydantic 2.x 不支持 regex lookahead, 用 field_validator 实现
    new_password: str = Field(..., min_length=8, max_length=200)

    @field_validator("new_password")
    @classmethod
    def _check_pwd_strength(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("密码必须含至少 1 个字母")
        if not re.search(r"\d", v):
            raise ValueError("密码必须含至少 1 个数字")
        return v


def _auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


@router.post("/v1/auth/login")
def login(body: dict, request: Request):  # 接收 dict 自己校验, 422 → 401
    """登录: 校验 username/password, 返 token + user"""
    payload = _validate_or_401(LoginRequest, body or {}, request)
    auth: AuthService = _auth_service(request)
    user = auth.authenticate(payload.username, payload.password)
    if not user:
        # 模糊错误:不暴露是 username 还是 password 错
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    # Bug-88: 签发带 pwd_iat 的 token (中间件校验改密后旧 token 失效)
    full_user = auth.get_user(user["id"])
    pwd_iat = (full_user or {}).get("password_changed_at") or 0
    token = auth.create_token(user["id"], user["username"], pwd_iat=pwd_iat)
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
    # Bug-87 (审核 #6): 禁用账户不能访问受保护端点
    if not user.get("is_active"):
        raise HTTPException(status_code=401, detail="账户已禁用")
    return user


@router.post("/v1/auth/change-password")
def change_password(body: dict, request: Request):  # 接收 dict 自己校验, 422 → 401 模糊
    """改密(需鉴权)"""
    payload = _validate_or_401(ChangePasswordRequest, body or {}, request)
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    auth: AuthService = _auth_service(request)
    user = auth.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    # Bug-87 (审核 #6): 禁用账户不能改密
    if not user.get("is_active"):
        raise HTTPException(status_code=401, detail="账户已禁用")
    # 验证旧密码(走 authenticate 校验)
    candidate = auth.authenticate(user["username"], payload.old_password)
    if not candidate:
        raise HTTPException(status_code=400, detail="旧密码错误")
    ok = auth.change_password(user_id, payload.new_password)
    if not ok:
        raise HTTPException(status_code=500, detail="改密失败")
    # Bug-88: 改密后签发新 token (pwd_iat 是新值, 旧 token 全部失效)
    fresh = auth.get_user(user_id)
    pwd_iat = (fresh or {}).get("password_changed_at") or 0
    new_token = auth.create_token(user_id, user["username"], pwd_iat=pwd_iat)
    return {
        "message": "密码已修改",
        "token": new_token,
        "user": {
            "id": user_id,
            "username": user["username"],
            "must_change_password": False,
        },
    }
    """改密(需鉴权)"""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    auth: AuthService = _auth_service(request)
    user = auth.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    # Bug-87 (审核 #6): 禁用账户不能改密
    if not user.get("is_active"):
        raise HTTPException(status_code=401, detail="账户已禁用")
    # 验证旧密码(走 authenticate 校验)
    candidate = auth.authenticate(user["username"], body.old_password)
    if not candidate:
        raise HTTPException(status_code=400, detail="旧密码错误")
    ok = auth.change_password(user_id, body.new_password)
    if not ok:
        raise HTTPException(status_code=500, detail="改密失败")
    # Bug-88: 改密后签发新 token (pwd_iat 是新值, 旧 token 全部失效)
    fresh = auth.get_user(user_id)
    pwd_iat = (fresh or {}).get("password_changed_at") or 0
    new_token = auth.create_token(user_id, user["username"], pwd_iat=pwd_iat)
    return {
        "message": "密码已修改",
        "token": new_token,
        "user": {
            "id": user_id,
            "username": user["username"],
            "must_change_password": False,
        },
    }
