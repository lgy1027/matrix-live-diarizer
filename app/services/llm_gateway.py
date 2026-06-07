"""本地 LLM 网关（可选 + 安全护栏）"""
import ipaddress
import socket
import asyncio
import logging
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
        now = asyncio.get_event_loop().time()
        if self._available_cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._available_cache
        result = await self._probe()
        self._available_cache = result
        self._cache_time = now
        return result

    async def _probe(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.config.endpoint.rstrip('/')}/models")
                return resp.status_code == 200
        except Exception as e:
            logger.info(f"[LLM] 探测失败: {e}")
            return False

    async def summarize(self, segments: list[dict], max_words: int = 200) -> Optional[str]:
        return await self._generate("summarize", segments, max_words=max_words)

    async def extract_action_items(self, segments: list[dict]) -> Optional[list[str]]:
        text = await self._generate("action_items", segments)
        if not text:
            return None
        return [line.strip("-* ").strip() for line in text.split("\n") if line.strip()]

    async def generate_minutes(self, segments: list[dict]) -> Optional[str]:
        return await self._generate("minutes", segments)

    async def _generate(self, op: str, segments: list[dict], **kwargs) -> Optional[str]:
        if not self.config.enabled:
            return None
        if self.config.mock:
            return self._mock_response(op, segments, **kwargs)
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
        return await self._call_llm(prompt)

    def _segments_to_text(self, segments: list[dict]) -> str:
        lines = []
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            spk = seg.get("speaker_id") or "?"
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
            async with httpx.AsyncClient(timeout=self.config.timeout_sec) as client:
                resp = await client.post(url, json=payload, headers=headers)
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
