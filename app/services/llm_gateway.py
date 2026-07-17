"""本地 LLM 网关（可选 + 安全护栏）"""
import ipaddress
import socket
import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.config import LLMConfig

logger = logging.getLogger("Matrix_LLM")


class EndpointSecurityError(ValueError):
    """LLM endpoint 不在允许列表（公网/不可信）"""


class LLMUnavailableError(RuntimeError):
    """LLM 探测失败或调用失败"""


class LLMTimeoutError(LLMUnavailableError):
    pass


class LLMModelMissingError(LLMUnavailableError):
    pass


def _validate_endpoint(endpoint: str, allowed_hosts: tuple, allow_public: bool = False) -> None:
    """解析 endpoint 并校验 host 是私有/本地地址
    allow_public=True 时跳过 IP 校验（用户已显式开公网）。
    """
    parsed = urlparse(endpoint)
    host = parsed.hostname
    if not host:
        raise EndpointSecurityError(f"无法解析 endpoint: {endpoint}")
    if host in allowed_hosts:
        return
    if allow_public:
        return
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except (socket.gaierror, ValueError) as e:
        raise EndpointSecurityError(f"DNS 解析失败: {host} ({e})") from e
    if not ip.is_private and not ip.is_loopback:
        raise EndpointSecurityError(
            f"endpoint {host} ({ip}) 不是私有/本机地址。"
            f"本项目默认不允许调用公网 LLM。"
            f"如确实需要,设置环境变量 LLM_ALLOW_PUBLIC=true 显式开公网,"
            f"并通过 LLM_API_KEY 配置 Bearer token。"
        )


class LLMGateway:
    def __init__(self, config: LLMConfig):
        if config.enabled:
            _validate_endpoint(config.endpoint, config.allowed_hosts, config.allow_public)
        self.config = config
        self._available_cache: Optional[bool] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 300.0

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    async def is_available(self) -> bool:
        if not self.config.enabled:
            return False
        if self.config.mock:
            return True
        now = asyncio.get_event_loop().time()
        if self._available_cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._available_cache
        result = await self._probe()
        self._available_cache = result
        self._cache_time = now
        return result

    async def _probe(self) -> bool:
        """用最小 chat completions 调用探活,而不是 /models。
        很多 OpenAI 兼容 endpoint(尤其第三方中转)不开放 /models,只暴露 /chat/completions。
        这里发一个 max_tokens=1 的请求,401/403/404 都判为不可用,200 判为可用。
        """
        url = f"{self.config.endpoint.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
            "stream": False,
        }
        try:
            resp = await self._post_with_dns_guard(
                url, payload=payload, headers=headers, timeout=5.0
            )
            return resp.status_code == 200
        except Exception as e:
            logger.info(f"[LLM] 探测失败: {e}")
            return False

    async def summarize(self, segments: list[dict], max_words: int = 200) -> Optional[str]:
        text, _source = await self._generate("summarize", segments, max_words=max_words)
        return text

    async def extract_action_items(self, segments: list[dict]) -> Optional[list[str]]:
        text, _source = await self._generate("action_items", segments)
        if not text:
            return None
        text = text.strip()
        normalized = text.lstrip("-* ").strip()
        # 检测模型返回"无行动项"等否定词
        if normalized.startswith((
            "无", "没有", "暂无", "未识别到明确行动项", "N/A", "n/a"
        )):
            return []
        items = [line.strip("-* ").strip() for line in text.split("\n") if line.strip()]
        # 兜底:如果整段都不像行动项(>3 个短句可能模型失控),截断到 50
        return items[:50]

    async def generate_minutes(self, segments: list[dict]) -> Optional[str]:
        text, _source = await self._generate("minutes", segments)
        return text

    async def _generate(self, op: str, segments: list[dict], **kwargs) -> tuple[str, str]:
        """LLM 失败时静默降级到 extractive,返回 (text, source) tuple。

        source 取值:
        - "llm" — LLM 真实生成(mock 模式也算)
        - "extractive-fallback" — 降级到本地 TextRank

        触发降级的情况:
        - LLM 未启用 (config.enabled=False)
        - LLM 不可用 (probe 失败)
        - LLM 调用抛 LLMUnavailableError / LLMTimeoutError / LLMModelMissingError
        - LLM mock 模式 (mock_response 走原路径,不在降级范围)
        """
        # 1. 尝试 LLM
        if self.config.enabled:
            try:
                if self.config.mock:
                    return self._mock_response(op, segments, **kwargs), "llm"
                if not await self.is_available():
                    raise LLMUnavailableError(f"LLM 不可用: {self.config.endpoint}")
                from .llm_prompts import PROMPTS
                transcript = self._segments_to_text(segments)
                template = PROMPTS.get(op)
                if not template:
                    raise ValueError(f"未知操作: {op}")
                try:
                    prompt = template.format(transcript=transcript, **kwargs)
                except KeyError:
                    prompt = template.replace("{transcript}", transcript)
                text = await self._call_llm(prompt)
                return text, "llm"
            except (LLMUnavailableError, LLMTimeoutError, LLMModelMissingError) as e:
                logger.warning(f"[LLM] 失败,降级到 extractive: {e}")
            except Exception as e:
                logger.warning(f"[LLM] 未知错误,降级: {e}")

        # 2. Fallback: extractive
        if op == "action_items":
            from .extractive_summary import NO_ACTIONS
            items = self._extractive_fallback_action_items(segments)
            content = "\n".join(f"- {item}" for item in items) if items else f"- {NO_ACTIONS}"
            return content, "extractive-fallback"
        return self._extractive_fallback(op, segments, **kwargs), "extractive-fallback"

    def _extractive_fallback(self, op: str, segments: list[dict], **kwargs) -> str:
        """extractive 兜底 — 返回 str"""
        from .extractive_summary import ExtractiveSummarizer
        summarizer = ExtractiveSummarizer()
        if op == "summarize":
            max_words = kwargs.get("max_words", 200)
            max_sent = max(3, max_words // 30)
            return summarizer.summarize(segments, max_sentences=max_sent)
        if op == "minutes":
            return summarizer.generate_minutes(segments)
        return "[本地摘要不可用]"

    def _extractive_fallback_action_items(self, segments: list[dict]) -> list[str]:
        """行动项降级时返回 list(给 action_items 端点用)"""
        from .extractive_summary import ExtractiveSummarizer
        summarizer = ExtractiveSummarizer()
        return summarizer.extract_action_items(segments)

    def _segments_to_text(self, segments: list[dict]) -> str:
        from .speaker_identity import speaker_display_name

        lines = []
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            spk = speaker_display_name(seg, unknown="?")
            lines.append(f"[{spk}] {text}")
        return "\n".join(lines)

    def _mock_response(self, op: str, segments: list[dict], **kwargs) -> str:
        if op == "summarize":
            return "[MOCK] 会议主要讨论了产品方向与下一步计划。"
        if op == "action_items":
            return "- [MOCK] 行动项 1\n- [MOCK] 行动项 2"
        if op == "minutes":
            return "[MOCK] 会议纪要：议题、决议、行动项"
        return "[MOCK]"

    async def _call_llm(self, prompt: str) -> str:
        # DNS rebinding 防御:URL 保留域名(SSL 证书走 SNI 校验),
        # 但 socket-level 把目标域名强制解析到 __init__ 时校验过的 IP。
        # 这样 URL 用域名不破坏 HTTPS 校验,同时连接目标被锁死。
        url = f"{self.config.endpoint.rstrip('/')}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        # 公网 OpenAI 兼容接口需要 Bearer token;本机 Ollama/vLLM 不需要
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            resp = await self._post_with_dns_guard(
                url,
                payload=payload,
                headers=headers,
                timeout=self.config.timeout_sec,
            )
            if resp.status_code == 404:
                raise LLMModelMissingError(
                    f"模型 {self.config.model} 未加载。"
                    f"请运行: ollama pull {self.config.model}"
                )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"LLM 调用超时: {e}") from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"LLM HTTP 错误: {e}") from e

    async def _post_with_dns_guard(
        self,
        url: str,
        *,
        payload: dict,
        headers: dict,
        timeout: float,
    ):
        """Send one request while DNS pinning is exclusively installed.

        ``socket.getaddrinfo`` is process-global.  The lock acquisition happens
        in a worker thread so concurrent async callers do not block the event
        loop, and the context manager always restores the socket function.
        """
        pinned_ip = self._resolve_pinned_ip(url)
        async with self._dns_pin_guard(url, pinned_ip):
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.post(url, json=payload, headers=headers)

    # ---- DNS pinning(防 DNS rebinding 攻击)----
    # 思路:在 LLM 调用期间,临时把 socket.getaddrinfo 改成对目标域名返回校验过的 IP。
    # URL 仍用域名(SSL SNI 校验用域名),但 socket connect 走固定 IP,
    # 解决 "把 host 换成 IP 后 SSL cert IP mismatch" 的问题。

    _socket_patch_active: bool = False
    _socket_patch_lock = threading.Lock()
    _base_getaddrinfo = socket.getaddrinfo
    _original_getaddrinfo = None
    _pinned_target_host: Optional[str] = None
    _pinned_target_ip: Optional[str] = None

    @classmethod
    @asynccontextmanager
    async def _dns_pin_guard(cls, url: str, pinned_ip: Optional[str]):
        if not pinned_ip:
            yield
            return
        await asyncio.to_thread(cls._socket_patch_lock.acquire)
        try:
            cls._install_socket_patch(url, pinned_ip)
            yield
        finally:
            cls._uninstall_socket_patch()
            cls._socket_patch_lock.release()

    @classmethod
    def _resolve_pinned_ip(cls, url: str) -> Optional[str]:
        """从 URL 解析域名,提前解析成 IP 备用。返回 None 表示跳过 pinning。"""
        try:
            parsed = urlparse(url)
            host = parsed.hostname
            if not host:
                return None
            # IP literal 不需要 pinning
            try:
                ipaddress.ip_address(host)
                return None
            except ValueError:
                pass
            return socket.gethostbyname(host)
        except (socket.gaierror, ValueError):
            return None

    @classmethod
    def _install_socket_patch(cls, url: str, pinned_ip: str) -> None:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host or cls._socket_patch_active:
            return
        # 已是 IP literal 时,patch 没意义(URL 里的 host 就是 IP,getaddrinfo 不会被以 host 调用)
        try:
            ipaddress.ip_address(host)
            return
        except ValueError:
            pass
        cls._pinned_target_host = host
        cls._pinned_target_ip = pinned_ip
        if cls._original_getaddrinfo is None:
            cls._original_getaddrinfo = socket.getaddrinfo

        _pinned_host = host
        _pinned_ip = pinned_ip
        _default_port = parsed.port or 443
        _orig = cls._original_getaddrinfo

        def _patched_getaddrinfo(h, port, *a, **kw):
            if h == _pinned_host:
                try:
                    port_int = int(port) if port is not None else _default_port
                except (TypeError, ValueError):
                    port_int = _default_port
                return _orig(_pinned_ip, port_int, *a, **kw)
            return _orig(h, port, *a, **kw)

        socket.getaddrinfo = _patched_getaddrinfo
        cls._socket_patch_active = True

    @classmethod
    def _uninstall_socket_patch(cls) -> None:
        if cls._original_getaddrinfo is not None:
            socket.getaddrinfo = cls._original_getaddrinfo
        cls._original_getaddrinfo = None
        cls._pinned_target_host = None
        cls._pinned_target_ip = None
        cls._socket_patch_active = False
