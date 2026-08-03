"""速率限制中间件

简单的内存速率限制实现，适用于单进程部署。
"""
import ipaddress
import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import Request
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
        # 登录端点单独的更严限流,防暴力破解:每 60s 最多 5 次,触发后锁 60s
        self.auth_login_per_minute = auth_login_per_minute
        self.auth_lock_seconds = auth_lock_seconds
        # 记录: {ip: {path: [timestamps]}}
        self._auth_locked: Dict[str, float] = {}  # {ip: lock_until_ts}
        # Requests already admitted but not yet authenticated.  Updating this
        # counter before the first await closes the concurrent-burst window in
        # which many bad-password requests could all observe zero failures.
        self._auth_in_flight: Dict[str, int] = {}
        self.enabled = enabled
        # 默认信任本机回环
        self._trusted_networks = []
        for cidr in (trusted_proxies or ["127.0.0.0/8", "::1/128"]):
            try:
                self._trusted_networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                logger.warning(f"[RateLimit] 无效 trusted_proxy CIDR: {cidr}")
        # 存储: {ip: [(timestamp, path), ...]}。容量上限防 IP 扩散(公网扫描/IPv6 轮换)
        # 撑爆内存:超 MAX_TRACKED_IPS 时按 LRU 丢弃最久未访问的 key。
        self.requests: Dict[str, List[Tuple[float, str]]] = defaultdict(list)
        self._max_tracked_ips = 50_000
        # 登录锁字典容量上限:攻击者轮换源 IP 触发锁,每 IP 留一条,长期累积撑大。
        self._max_auth_locked = 50_000

    def _sweep_tracked(self) -> None:
        """惰性清理 + 容量上限淘汰,防 never-again 的 IP 永驻字典。"""
        if len(self.requests) <= self._max_tracked_ips:
            return
        # 优先丢弃空列表 key;仍超限按最近访问时间 LRU 淘汰
        empty = [ip for ip, lst in self.requests.items() if not lst]
        for ip in empty:
            del self.requests[ip]
        if len(self.requests) <= self._max_tracked_ips:
            return
        # 按 list 最后一个时间戳(最近访问)排序,淘汰最旧的
        ranked = sorted(
            self.requests.items(),
            key=lambda kv: kv[1][-1][0] if kv[1] else 0.0,
        )
        for ip, _ in ranked[: len(self.requests) - self._max_tracked_ips]:
            del self.requests[ip]

    def _sweep_auth_locked(self) -> None:
        """登录锁字典容量上限淘汰 + 过期清理,防轮换源 IP 撑大 _auth_locked。"""
        if not self._auth_locked:
            return
        now = time.time()
        # 先惰性清过期锁
        expired = [ip for ip, until in self._auth_locked.items() if until <= now]
        for ip in expired:
            del self._auth_locked[ip]
        if len(self._auth_locked) <= self._max_auth_locked:
            return
        # 超限:按 lock_until 升序淘汰最早解锁的
        ranked = sorted(self._auth_locked.items(), key=lambda kv: kv[1])
        for ip, _ in ranked[: len(self._auth_locked) - self._max_auth_locked]:
            del self._auth_locked[ip]
    
    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        # 获取客户端 IP
        client_ip = self._get_client_ip(request)
        path = request.url.path
        now = time.time()

        # 健康探针不计数(避免 LB 每 5s 探活挤占业务配额)
        if path in ("/health", "/ready"):
            return await call_next(request)

        # 登录端点走更严的限流分支
        if path == "/v1/auth/login":
            return await self._check_auth_login(client_ip, request, call_next, now)

        # 通用限流
        # 清理过期记录(超过1小时的)
        hour_ago = now - 3600
        self.requests[client_ip] = [
            (t, p) for t, p in self.requests[client_ip] if t > hour_ago
        ]
        # 清空则删 key(防空 list 永驻),并触发全局容量上限淘汰
        if not self.requests[client_ip]:
            del self.requests[client_ip]
            self._sweep_tracked()
        else:
            self._sweep_tracked()

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
        - 同一 IP 每 auth_login_per_minute (5) 次失败/60s 允许;成功登录不占配额
        - 触发后锁定 auth_lock_seconds (60s),期间 429
        - 只计失败(401),防合法用户反复登录被误锁;失败仍计数防探测绕过
        """
        # 锁状态检查(过期锁主动清理,防 key 永驻)
        self._sweep_auth_locked()
        lock_until = self._auth_locked.get(client_ip, 0)
        if lock_until and now >= lock_until:
            del self._auth_locked[client_ip]
            lock_until = 0
        if now < lock_until:
            retry_after = int(lock_until - now)
            logger.warning(f"[LoginLock] {client_ip} 登录锁定中, {retry_after}s 后解锁")
            return JSONResponse(
                status_code=429,
                content={"detail": f"登录尝试过多, 请 {retry_after} 秒后重试"},
                headers={"Retry-After": str(retry_after)},
            )

        # 此路径早返回不走 dispatch 的通用清理段;原地清理该 IP 过期条目,
        # 防同一 IP 长期低频失败登录(恰好不触发锁)累积撑大列表(数月数十万条)。
        hour_ago = now - 3600
        self.requests[client_ip] = [
            (t, p) for t, p in self.requests[client_ip] if t > hour_ago
        ]

        # 60s 滑动窗口:只统计失败的登录尝试
        minute_ago = now - 60
        recent = [t for t, p in self.requests[client_ip] if t > minute_ago and p == "/v1/auth/login"]
        in_flight = self._auth_in_flight.get(client_ip, 0)
        if len(recent) >= self.auth_login_per_minute:
            # 已确认的失败达到阈值才锁定。仅有并发中的请求时不能判断
            # 密码是否错误，否则合法用户的成功登录突发也会被误锁。
            self._auth_locked[client_ip] = now + self.auth_lock_seconds
            logger.warning(f"[LoginLock] {client_ip} 触发锁定, {self.auth_lock_seconds}s")
            return JSONResponse(
                status_code=429,
                content={"detail": f"登录尝试过多, 请 {self.auth_lock_seconds} 秒后重试"},
                headers={"Retry-After": str(self.auth_lock_seconds)},
            )
        if len(recent) + in_flight >= self.auth_login_per_minute:
            return JSONResponse(
                status_code=429,
                content={"detail": "并发登录请求过多, 请稍后重试"},
                headers={"Retry-After": "1"},
            )

        self._auth_in_flight[client_ip] = in_flight + 1
        try:
            response = await call_next(request)
        finally:
            remaining = self._auth_in_flight.get(client_ip, 1) - 1
            if remaining > 0:
                self._auth_in_flight[client_ip] = remaining
            else:
                self._auth_in_flight.pop(client_ip, None)
        if response.status_code == 401:
            # 失败计数(用于触发锁定)
            self.requests[client_ip].append((now, "/v1/auth/login"))
            self._sweep_tracked()
        elif response.status_code == 200:
            # 成功登录后清理该 IP 的历史失败记录,避免合法用户后续输错 1 次
            # 就因旧失败累积触发锁定(误锁)。
            self.requests[client_ip] = [
                (t, p) for t, p in self.requests[client_ip]
                if t > now - 60 and p != "/v1/auth/login"
            ]
            if not self.requests[client_ip]:
                del self.requests[client_ip]
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP

        只有当直连 IP 在 trusted_proxies 列表中,才采用 X-Forwarded-For 头。
        防止客户端伪造 header 绕过限流。

        local 模式直连恒为 loopback(命中默认 trusted_proxies),此时也采纳 XFF,
        以支持"本机起反代再回连"的部署形态。local 威胁模型假定本机可信;若担心
        本机进程伪造 XFF 绕限流,应切 lan/public 模式 + 显式配 TRUSTED_PROXIES。
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
