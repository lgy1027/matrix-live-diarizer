"""速率限制中间件

简单的内存速率限制实现，适用于单进程部署。
"""
import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import logging

logger = logging.getLogger("Matrix_Core")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件
    
    基于 IP 地址的滑动窗口速率限制。
    """
    
    def __init__(self, app, requests_per_minute: int = 60, requests_per_hour: int = 1000, enabled: bool = True):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.enabled = enabled
        # 存储: {ip: [(timestamp, path), ...]}
        self.requests: Dict[str, List[Tuple[float, str]]] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)
        
        # 获取客户端 IP
        client_ip = self._get_client_ip(request)
        now = time.time()
        
        # 清理过期记录（超过1小时的）
        hour_ago = now - 3600
        self.requests[client_ip] = [
            (t, p) for t, p in self.requests[client_ip] if t > hour_ago
        ]
        
        # 统计请求数
        minute_ago = now - 60
        minute_count = sum(1 for t, _ in self.requests[client_ip] if t > minute_ago)
        hour_count = len(self.requests[client_ip])
        
        # 检查限制
        if minute_count >= self.requests_per_minute:
            logger.warning(f"速率限制: {client_ip} 超过每分钟限制 ({minute_count}/{self.requests_per_minute})")
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后重试"},
                headers={"Retry-After": "60"}
            )
        
        if hour_count >= self.requests_per_hour:
            logger.warning(f"速率限制: {client_ip} 超过每小时限制 ({hour_count}/{self.requests_per_hour})")
            return JSONResponse(
                status_code=429,
                content={"detail": "请求过于频繁，请稍后重试"},
                headers={"Retry-After": "3600"}
            )
        
        # 记录请求
        self.requests[client_ip].append((now, request.url.path))
        
        return await call_next(request)
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP"""
        # 检查代理头
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # 直接连接
        if request.client:
            return request.client.host
        
        return "unknown"