"""统一错误响应模型"""
from pydantic import BaseModel
from typing import Optional


class ErrorResponse(BaseModel):
    """统一错误响应 schema

    用于所有 API 端点的错误返回，确保前端有统一的错误格式。
    """
    code: str
    message: str
    detail: Optional[str] = None
    retry_after: Optional[int] = None


def error_response(code: str, message: str, **kwargs) -> dict:
    """辅助函数：构造错误响应 dict"""
    return {"code": code, "message": message, **kwargs}
