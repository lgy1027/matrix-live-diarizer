"""本地 LLM 网关（可选 + 安全护栏）"""
import ipaddress
import socket
import asyncio
import logging
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


def _validate_endpoint(
    endpoint: str, allowed_hosts: tuple, allow_public: bool = False
) -> Optional[str]:
    """解析 endpoint 并校验 host 是私有/本地地址。

    返回 init 时刻解析到的 IP(供 DNS pinning 缓存,防 init→request 之间的
    DNS rebinding)。返回 None 表示:命中 allowed_hosts / allow_public=True /
    host 是 IP literal — 这些情况不需要缓存 IP 做 pinning 基准。

    allow_public=True 时跳过 IP 校验(用户已显式开公网)。
    """
    parsed = urlparse(endpoint)
    host = parsed.hostname
    if not host:
        raise EndpointSecurityError(f"无法解析 endpoint: {endpoint}")
    if host in allowed_hosts:
        return None
    if allow_public:
        return None
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
    return str(ip)


class LLMGateway:
    def __init__(self, config: LLMConfig, prompts: Optional[dict] = None):
        # prompts: 用户在 settings 页改过的 prompt(从 settings_repo 加载)。
        # None 时用 DEFAULT_PROMPTS。探活等不涉及 prompt 的调用可不传。
        self._prompts = dict(prompts) if prompts else None  # 延迟加载默认
        self._pinned_host: Optional[str] = None
        self._pinned_ip: Optional[str] = None
        if config.enabled:
            validated_ip = _validate_endpoint(
                config.endpoint, config.allowed_hosts, config.allow_public
            )
            parsed = urlparse(config.endpoint)
            host = parsed.hostname
            self._pinned_host = host
            if validated_ip is not None:
                # strict 私网模式:init 已解析出私网 IP,缓存作为 pinning 基准。
                self._pinned_ip = validated_ip
            elif not config.allow_public and host is not None:
                # allowed_hosts 里的域名(如 "localhost"):validate 没解析,
                # 这里补一次解析用于 pinning。IP literal 不需要 pin。
                try:
                    ipaddress.ip_address(host)
                except ValueError:
                    try:
                        self._pinned_ip = socket.gethostbyname(host)
                    except socket.gaierror:
                        self._pinned_ip = None
                # allow_public=True 不缓存 → 请求时跟随 DNS 轮询,无 rebinding 威胁
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
        - "llm-mapreduce" — 超长转写分块摘要再合并(N+1 次 LLM 调用)
        - "extractive-fallback" — 降级到本地 TextRank

        触发降级的情况:
        - LLM 未启用 (config.enabled=False)
        - LLM 不可用 (probe 失败)
        - LLM 调用抛 LLMUnavailableError / LLMTimeoutError / LLMModelMissingError
        - LLM mock 模式 (mock_response 走原路径,不在降级范围)

        超长处理:transcript token 估算 > max_input_tokens*0.95 时走 map-reduce
        (分块按 segment 边界不切断 turn,各块单独摘要,合并阶段再生成总摘要)。
        1 小时会议(~1万字,估算 ~7300 token)在默认 max_input_tokens=8000 下
        7300 < 7600 不触发单次调用;十几万字超长才分块。
        注:token 估算用 len/1.5 偏保守乐观(实际中文可能更多 token),
        若模型 context 真装不下会由 LLM 报错降级 extractive 兜底。
        """
        # 1. 尝试 LLM
        if self.config.enabled:
            try:
                if self.config.mock:
                    return self._mock_response(op, segments, **kwargs), "llm"
                if not await self.is_available():
                    raise LLMUnavailableError(f"LLM 不可用: {self.config.endpoint}")
                transcript = self._segments_to_text(segments)
                # summarize:按会议总时长自适应摘要篇幅(调用方未显式传 max_words 时)。
                # 见 _adaptive_max_words:短~120/中~200/长~300/超长~400 字。
                if op == "summarize" and "max_words" not in kwargs:
                    kwargs["max_words"] = self._adaptive_max_words(segments)
                # 短文本直接发;超长走 map-reduce(按 segment 边界分块)。
                # 阈值用 0.95 而非 0.8:1 小时会议(~1万字含前缀≈7300 token)
                # 在默认 max_input_tokens=8000 下应落回单次,只在真正超长(>7600)
                # 才分块。0.8 会让 1 小时会议误触发(用户明确不希望日常多调用)。
                if self._est_tokens(transcript) <= self.config.max_input_tokens * 0.95:
                    text = await self._llm_single_call(op, transcript, kwargs)
                    return text, "llm"
                chunks = self._split_segments(segments, self.config.max_input_tokens * 0.7)
                if len(chunks) <= 1:
                    # 估算偏保守导致单块(分不出多块),直接发
                    text = await self._llm_single_call(op, transcript, kwargs)
                    return text, "llm"
                logger.info(f"[LLM] 转写超长({self._est_tokens(transcript):.0f} token),"
                            f"map-reduce 分 {len(chunks)} 块")
                chunk_texts = []
                for i, chunk in enumerate(chunks):
                    chunk_transcript = self._segments_to_text(chunk)
                    # 块摘要:压缩 max_words 避免块摘要总和过长
                    chunk_kwargs = dict(kwargs)
                    if "max_words" in chunk_kwargs:
                        chunk_kwargs["max_words"] = max(100, chunk_kwargs["max_words"] // 2)
                    chunk_texts.append(await self._llm_single_call(op, chunk_transcript, chunk_kwargs))
                # 合并阶段:各块摘要拼接再生成总摘要
                merged = "\n\n".join(f"[分块{i+1}]\n{t}" for i, t in enumerate(chunk_texts))
                text = await self._llm_single_call(op, merged, kwargs)
                return text, "llm-mapreduce"
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

    async def _llm_single_call(self, op: str, transcript: str, kwargs: dict) -> str:
        """渲染 prompt(用 str.replace 防转写花括号触发 KeyError)+ 单次 _call_llm。"""
        from .llm_prompts import DEFAULT_PROMPTS
        prompts = self._prompts if self._prompts is not None else DEFAULT_PROMPTS
        template = prompts.get(op)
        if not template:
            raise ValueError(f"未知操作: {op}")
        prompt = self._render_prompt(template, transcript, kwargs)
        return await self._call_llm(prompt)

    @staticmethod
    def _render_prompt(template: str, transcript: str, kwargs: dict) -> str:
        """用 str.replace 逐占位符替换,不解析转写里的花括号。

        str.format 会把转写文本里的 {xxx} 当占位符解析,触发 KeyError → 旧兜底
        只替 {transcript},留下 {max_words} 字面发给 LLM("数值未填写"提示)。
        str.replace 不解析,转写花括号安全。
        """
        prompt = template.replace("{transcript}", transcript)
        if "max_words" in kwargs:
            prompt = prompt.replace("{max_words}", str(kwargs["max_words"]))
        return prompt

    @staticmethod
    def _est_tokens(text: str) -> float:
        """token 估算:中文 ~1.5 字/token,英文 ~4 字/token。用 /1.5 偏保守
        (多估 token),保证不超 max_input_tokens。"""
        return len(text) / 1.5

    @staticmethod
    def _estimate_meeting_duration(segments: list[dict]) -> float:
        """从 segment 的 start_time/end_time(秒)估算会议总时长(秒)。

        取所有 segment 的最大 end - 最小 start。segment 时间戳缺失或全 0
        (实时流早期)时回退为 0,由 _adaptive_max_words 兜底用中位数篇幅。
        """
        ends = [float(s.get("end_time") or 0) for s in segments if s.get("end_time") is not None]
        starts = [float(s.get("start_time") or 0) for s in segments if s.get("start_time") is not None]
        if not ends or not starts:
            return 0.0
        return max(0.0, max(ends) - min(starts))

    @staticmethod
    def _adaptive_max_words(segments: list[dict]) -> int:
        """按会议总时长自适应摘要目标字数。

        <10min→120, 10–30min→200, 30–60min→300, >60min→400。
        时长估算不出来(0)时用中位数 200(等同旧默认)。
        """
        dur = LLMGateway._estimate_meeting_duration(segments)
        if dur <= 0:
            return 200
        minutes = dur / 60.0
        if minutes < 10:
            return 120
        if minutes < 30:
            return 200
        if minutes < 60:
            return 300
        return 400

    @staticmethod
    def _split_segments(segments: list[dict], max_chars_per_chunk: int) -> list[list[dict]]:
        """按 segment 整块累加分块,不切断单个说话人 turn。

        max_chars_per_chunk 是字符上限(已从 token 换算)。单个 segment 超长
        (罕见)单独成块,不切。
        """
        chunks: list[list[dict]] = []
        current: list[dict] = []
        current_chars = 0
        for seg in segments:
            seg_text = (seg.get("text") or "")
            seg_len = len(seg_text) + 8  # [spk] 前缀开销
            if current and current_chars + seg_len > max_chars_per_chunk:
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(seg)
            current_chars += seg_len
        if current:
            chunks.append(current)
        return chunks

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
            if 300 <= resp.status_code < 400:
                # follow_redirects=False 时重定向不会自动跟随;本地 LLM 不应重定向,
                # 出现 3xx 视为可疑(可能被劫持的 endpoint 试图外发),直接拒绝。
                raise EndpointSecurityError(
                    f"LLM endpoint 返回重定向 {resp.status_code},已拒绝(follow_redirects=False)。"
                )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.TimeoutException as e:
            raise LLMTimeoutError(f"LLM 调用超时: {e}") from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"LLM HTTP 错误: {e}") from e

    def _assert_no_dns_rebind(self) -> None:
        """请求前再校验一次:当前 DNS 解析结果与 init 缓存的 IP 是否一致。

        仅 strict 私网模式(有缓存 IP 且未开 allow_public)生效。allow_public
        用户已显式接受公网,无 rebinding 威胁,跟随 DNS 轮询即可。
        不一致 → 抛 EndpointSecurityError,调用方降级到 extractive 兜底,
        绝不把连接重定向到攻击者 rebind 出的公网 IP。
        """
        if self.config.allow_public:
            return
        if not self._pinned_host or not self._pinned_ip:
            return
        try:
            fresh = socket.gethostbyname(self._pinned_host)
        except socket.gaierror:
            # DNS 暂时不可用:pinning 仍用缓存 IP(安全默认),不阻断
            return
        if fresh != self._pinned_ip:
            raise EndpointSecurityError(
                f"DNS rebinding 检测: {self._pinned_host} 启动时解析为 "
                f"{self._pinned_ip},当前解析为 {fresh}。"
                f"拒绝 LLM 调用,降级到本地摘要。"
            )

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
        # 先做 rebinding 校验(可能抛 EndpointSecurityError → 调用方降级)
        self._assert_no_dns_rebind()
        pinned_ip = self._resolve_pinned_ip(url)
        async with self._dns_pin_guard(url, pinned_ip):
            # follow_redirects=False:被劫持的 LLM endpoint 若 302 到外部 host,
            # httpx 默认跟随且 DNS pinning 只 pin 原始 host,不校验重定向目标 →
            # 可借机 SSRF 外发会议文本。本地 LLM(Ollama/vLLM)不应重定向,
            # 遇重定向直接当错误返回,杜绝绕过 pinning 的外发路径。
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                return await client.post(url, json=payload, headers=headers)

    # ---- DNS pinning(防 DNS rebinding 攻击)----
    # 思路:在 LLM 调用期间,临时把 socket.getaddrinfo 改成对目标域名返回校验过的 IP。
    # URL 仍用域名(SSL SNI 校验用域名),但 socket connect 走固定 IP,
    # 解决 "把 host 换成 IP 后 SSL cert IP mismatch" 的问题。

    _socket_patch_active: bool = False
    _socket_patch_lock = asyncio.Lock()
    _base_getaddrinfo = socket.getaddrinfo
    _original_getaddrinfo = None
    # 多 host pin 映射 host -> (ip, default_port)。早期是单 host 字段,
    # 在并发/重入下会丢 pin:第二个 host 的 pin 被跳过(标志位已置位),
    # 或卸载时把第一个 host 的 pin 一并清掉(无条件还原 getaddrinfo)。
    _pinned_map: dict = {}

    @classmethod
    @asynccontextmanager
    async def _dns_pin_guard(cls, url: str, pinned_ip: Optional[str]):
        if not pinned_ip:
            yield
            return
        # 锁跨整个请求持有,串行化所有 LLM 调用。这是有意的:socket.getaddrinfo
        # 是进程全局 patch,并发 install/remove 会让一个请求的 pin 被另一个
        # 请求的 remove 失效,破坏 DNS rebinding 防御。并发退化换正确性。
        # 用 asyncio.Lock 而非 threading.Lock:协程在获取锁前被取消时,
        # asyncio.Lock.acquire 直接抛 CancelledError 且不持锁,try/finally
        # 安全释放;threading.Lock 经 to_thread(acquire) 在取消时 worker 线程
        # 仍会拿到锁而协程已取消,release 永不执行 → 锁永久孤立、后续全死锁。
        async with cls._socket_patch_lock:
            cls._install_socket_patch(url, pinned_ip)
            try:
                yield
            finally:
                # 正常退出与 yield 期间被取消都走这里:先移除本 host 的 pin,
                # 再由 async with 释放锁。pin 不移除会污染后续 getaddrinfo。
                cls._remove_socket_pin(url)

    def _resolve_pinned_ip(self, url: str) -> Optional[str]:
        """返回用于 socket pinning 的 IP。None 表示跳过 pinning。

        - IP literal host:不需要 pin(URL 里的 host 就是 IP)
        - allow_public=True:跟随当前 DNS(用户显式开公网,无 rebinding 威胁,
          且公网 endpoint 常做 DNS 轮询/CDN,固定 IP 反而会连不上)
        - strict 私网模式:返回 init 时缓存的 IP,不再重新解析 —— 这是防
          DNS rebinding 的关键:连接目标锁死到 init 校验过的私网 IP,
          请求时刻即使 DNS 被 rebind 到公网也不受影响(_assert_no_dns_rebind
          还会再校验一次并拒绝)。
        """
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
            if self.config.allow_public:
                try:
                    return socket.gethostbyname(host)
                except socket.gaierror:
                    return None
            # strict 模式:用 init 缓存的 IP,绝不重新解析作为连接目标
            if host == self._pinned_host:
                return self._pinned_ip
            return None
        except (socket.gaierror, ValueError):
            return None

    @classmethod
    def _install_socket_patch(cls, url: str, pinned_ip: str) -> None:
        """把 (host -> ip, default_port) 加入 _pinned_map,并按需安装 patched getaddrinfo。

        多 host 累积:已安装 patched fn 时不重复安装(读 map 即可),否则第二个
        host 会因标志位已置位被跳过而没有 pin。
        """
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return
        # 已是 IP literal 时,patch 没意义(URL 里的 host 就是 IP,getaddrinfo 不会被以 host 调用)
        try:
            ipaddress.ip_address(host)
            return
        except ValueError:
            pass
        default_port = parsed.port or 443
        cls._pinned_map[host] = (pinned_ip, default_port)
        if cls._original_getaddrinfo is None:
            cls._original_getaddrinfo = socket.getaddrinfo
        if cls._socket_patch_active:
            return  # patched fn 已装,新 host 进 map 即生效
        _orig = cls._original_getaddrinfo

        def _patched_getaddrinfo(h, port, *a, **kw):
            entry = cls._pinned_map.get(h)
            if entry is not None:
                pin_ip, default_port = entry
                try:
                    port_int = int(port) if port is not None else default_port
                except (TypeError, ValueError):
                    port_int = default_port
                return _orig(pin_ip, port_int, *a, **kw)
            return _orig(h, port, *a, **kw)

        socket.getaddrinfo = _patched_getaddrinfo
        cls._socket_patch_active = True

    @classmethod
    def _remove_socket_pin(cls, url: str) -> None:
        """只移除本 context 注册的 host;map 空了才还原 getaddrinfo。"""
        parsed = urlparse(url)
        host = parsed.hostname
        if host:
            cls._pinned_map.pop(host, None)
        if not cls._pinned_map and cls._original_getaddrinfo is not None:
            socket.getaddrinfo = cls._original_getaddrinfo
            cls._original_getaddrinfo = None
            cls._socket_patch_active = False

    @classmethod
    def _uninstall_socket_patch(cls) -> None:
        """全量重置(测试与兜底用):清空 map 并还原 getaddrinfo。"""
        if cls._original_getaddrinfo is not None:
            socket.getaddrinfo = cls._original_getaddrinfo
        cls._original_getaddrinfo = None
        cls._pinned_map.clear()
        cls._socket_patch_active = False
