"""速率限制中间件

简单的内存速率限制实现，适用于单进程部署。
"""
import ipaddress
import socket
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
    trusted_proxies: 可信代理 IP 列表(默认信任 127.0.0.1/::1)。
                     只有当直连 IP 在 trusted_proxies 时,才会采用 X-Forwarded-For。
                     防止客户端伪造 X-Forwarded-For 绕过限流。
    """

    def __init__(self, app, requests_per_minute: int = 60, requests_per_hour: int = 1000,
                 enabled: bool = True, trusted_proxies: list = None,
                 auth_login_per_minute: int = 5, auth_lock_seconds: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        # Bug-82 (审核 #1): 登录端点更严限流,防暴力破解
        # 同一 IP 每 60s 最多 5 次登录尝试,触发后锁 60s
        self.auth_login_per_minute = auth_login_per_minute
        self.auth_lock_seconds = auth_lock_seconds
        # 记录: {ip: {path: [timestamps]}}
        self._auth_locked: Dict[str, float] = {}  # {ip: lock_until_ts}
        self.enabled = enabled
        # 默认信任本机回环
        self._trusted_networks = []
        for cidr in (trusted_proxies or ["127.0.0.0/8", "::1/128"]):
            try:
                self._trusted_networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                logger.warning(f"[RateLimit] 无效 trusted_proxy CIDR: {cidr}")
        # 存储: {ip: [(timestamp, path), ...]}
        self.requests: Dict[str, List[Tuple[float, str]]] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        # 获取客户端 IP
        client_ip = self._get_client_ip(request)
        path = request.url.path
        now = time.time()

        # Bug-82 (审核 #1): /v1/auth/login 走更严限流
        if path == "/v1/auth/login":
            return await self._check_auth_login(client_ip, request, call_next, now)

        # 通用限流
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
        self.requests[client_ip].append((now, path))

        return await call_next(request)

    async def _check_auth_login(self, client_ip: str, request: Request, call_next, now: float):
        """登录端点特殊限流

        策略:
        - 同一 IP 每 auth_login_per_minute (5) 次/60s 允许
        - 触发后锁定 auth_lock_seconds (60s),期间 429
        - 注意: 记录"尝试"不管成功失败(防探测失败绕过)
        """
        # 锁状态检查
        lock_until = self._auth_locked.get(client_ip, 0)
        if now < lock_until:
            retry_after = int(lock_until - now)
            logger.warning(f"[LoginLock] {client_ip} 登录锁定中, {retry_after}s 后解锁")
            return JSONResponse(
                status_code=429,
                content={"detail": f"登录尝试过多, 请 {retry_after} 秒后重试"},
                headers={"Retry-After": str(retry_after)},
            )

        # 60s 滑动窗口
        minute_ago = now - 60
        recent = [t for t, p in self.requests[client_ip] if t > minute_ago and p == "/v1/auth/login"]
        if len(recent) >= self.auth_login_per_minute:
            # 锁定
            self._auth_locked[client_ip] = now + self.auth_lock_seconds
            logger.warning(f"[LoginLock] {client_ip} 触发锁定, {self.auth_lock_seconds}s")
            return JSONResponse(
                status_code=429,
                content={"detail": f"登录尝试过多, 请 {self.auth_lock_seconds} 秒后重试"},
                headers={"Retry-After": str(self.auth_lock_seconds)},
            )

        # 允许,记录
        self.requests[client_ip].append((now, "/v1/auth/login"))
        return await call_next(request)
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP

        只有当直连 IP 在 trusted_proxies 列表中,才采用 X-Forwarded-For 头。
        防止客户端伪造 header 绕过限流。
        """
        direct_ip = request.client.host if request.client else None

        if direct_ip and self._is_trusted(direct_ip):
            # 直连来自可信代理(如 nginx),允许采纳 X-Forwarded-For
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                return forwarded.split(",")[0].strip()
            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip

        # 直连或不可信,直接用 socket peer
        return direct_ip or "unknown"

    def _is_trusted(self, ip_str: str) -> bool:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        for net in self._trusted_networks:
            if ip in net:
                return True
        return False