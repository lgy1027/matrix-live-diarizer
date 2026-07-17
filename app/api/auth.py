"""Authentication and password-management endpoints."""
import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.services.auth import AuthService


router = APIRouter()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=200)
    new_password: str = Field(..., min_length=8, max_length=200)

    @field_validator("new_password")
    @classmethod
    def _check_pwd_strength(cls, value: str) -> str:
        if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
            raise ValueError("密码必须同时包含字母和数字")
        return value


def _validate_login(data: dict) -> LoginRequest:
    """Keep malformed login attempts indistinguishable from bad credentials."""
    try:
        return LoginRequest(**data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=401,
            detail="登录信息格式错误,请检查后重试",
        ) from exc


def _validate_password_change(data: dict) -> ChangePasswordRequest:
    """Return an actionable input error without invalidating the session."""
    try:
        return ChangePasswordRequest(**data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail="新密码至少 8 位，且必须同时包含字母和数字",
        ) from exc


def _auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


@router.post("/v1/auth/login")
def login(body: dict, request: Request):
    """Authenticate credentials and return a bearer token."""
    payload = _validate_login(body or {})
    auth = _auth_service(request)
    user = auth.authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
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
def logout():
    """Acknowledge logout; the client removes the stateless token."""
    return {"message": "已退出登录"}


@router.get("/v1/auth/me")
def me(request: Request):
    """Return the authenticated user."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    user = _auth_service(request).get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not user.get("is_active"):
        raise HTTPException(status_code=401, detail="账户已禁用")
    return user


@router.post("/v1/auth/change-password")
def change_password(body: dict, request: Request):
    """Change the authenticated user's password and rotate the token."""
    payload = _validate_password_change(body or {})
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    auth = _auth_service(request)
    user = auth.get_user(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not user.get("is_active"):
        raise HTTPException(status_code=401, detail="账户已禁用")
    candidate = auth.authenticate(user["username"], payload.old_password)
    if not candidate:
        raise HTTPException(status_code=400, detail="旧密码错误")
    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    if not auth.change_password(user_id, payload.new_password):
        raise HTTPException(status_code=500, detail="改密失败")

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
