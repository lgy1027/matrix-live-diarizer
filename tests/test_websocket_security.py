"""WebSocket 客户端 ID 验证测试

对应 app/api/websocket.py:validate_client_id
- 允许字符: [a-zA-Z0-9_]{1,64}
- 防止日志注入(换行符剥离)
- 非法字符替换为 _
"""
import sys

from app.api.websocket import validate_client_id


def test_normal_id_unchanged():
    assert validate_client_id("alice_42") == "alice_42"


def test_numeric_id_unchanged():
    assert validate_client_id("12345") == "12345"


def test_empty_returns_anonymous():
    assert validate_client_id("") == "anonymous"


def test_none_returns_anonymous():
    # None 走 if not client_id 路径
    assert validate_client_id(None) == "anonymous"


def test_newline_stripped():
    """换行符必须剥离(防日志注入)"""
    assert validate_client_id("alice\n") == "alice"
    assert validate_client_id("bob\r") == "bob"
    assert validate_client_id("eve\r\nattack") == "eveattack"


def test_special_chars_replaced_with_underscore():
    """非法字符 → _"""
    assert validate_client_id("alice@bob") == "alice_bob"
    assert validate_client_id("user.name") == "user_name"
    assert validate_client_id("path/to/x") == "path_to_x"
    assert validate_client_id("a b c") == "a_b_c"
    # 中文字符全部不是 [a-zA-Z0-9_],都变 _ (4 字符)
    assert validate_client_id("中文用户") == "____"


def test_max_length_truncated_to_64():
    """超长 ID 截到 64 字符"""
    long_id = "a" * 100
    out = validate_client_id(long_id)
    assert len(out) == 64
    assert out == "a" * 64


def test_unicode_replaced():
    """非 ASCII 字符(包括中文)都替换"""
    # "用户" 是 2 字符,变 __; 后面 A 保留
    assert validate_client_id("用户A") == "__A"
    assert validate_client_id("🦀") == "_"


def test_only_special_chars_returns_underscores():
    """全是特殊字符 → 全部转 _"""
    out = validate_client_id("@@@")
    assert out == "___"


def test_underscore_kept():
    """下划线是合法字符,保留"""
    assert validate_client_id("user_42_test") == "user_42_test"


def test_log_injection_payload_neutralized():
    """典型日志注入 payload 必须被中和"""
    # 攻击者构造: id="alice\n[ERROR] fake log entry"
    payload = "alice\n[ERROR] fake log entry"
    out = validate_client_id(payload)
    # \n 移除,其他字符替换为 _
    assert "\n" not in out
    # [ ] space 都被替换为 _
    # 预期: "alice_ERROR__fake_log_entry"
    assert out == "alice_ERROR__fake_log_entry"


# ========== L5: WebSocket 连接速率限制 ==========

def test_ws_rate_limit_blocks_after_threshold():
    """L5: 同一 IP 在窗口内连接数超阈值后被限流。"""
    from app.services import realtime_auth
    realtime_auth._ws_connect_log.clear()
    host = "203.0.113.7"
    # 阈值 = _WS_CONNECT_MAX,前 N 次放行,第 N+1 次被限
    for i in range(realtime_auth._WS_CONNECT_MAX):
        assert realtime_auth._ws_rate_limited(host) is False, f"第 {i+1} 次不应限流"
    # 第 MAX+1 次触发
    assert realtime_auth._ws_rate_limited(host) is True
    realtime_auth._ws_connect_log.clear()


def test_ws_rate_limit_empty_host_skipped():
    """L5: 空客户端 host 不限流(不阻塞无 client 信息的情况)。"""
    from app.services import realtime_auth
    realtime_auth._ws_connect_log.clear()
    assert realtime_auth._ws_rate_limited("") is False
    realtime_auth._ws_connect_log.clear()


def test_ws_rate_limit_per_ip_independent():
    """L5: 不同 IP 计数独立,A 被限不影响 B。"""
    from app.services import realtime_auth
    realtime_auth._ws_connect_log.clear()
    a, b = "203.0.113.7", "198.51.100.9"
    for _ in range(realtime_auth._WS_CONNECT_MAX):
        realtime_auth._ws_rate_limited(a)
    assert realtime_auth._ws_rate_limited(a) is True
    assert realtime_auth._ws_rate_limited(b) is False  # B 未超
    realtime_auth._ws_connect_log.clear()


def test_ws_rate_limit_dict_garbage_collects_empty_keys():
    """#6: 队列清空后删除 dict 键,防 IP 扩散(NAT/IPv6 扫描)撑爆内存。"""
    from app.services import realtime_auth
    realtime_auth._ws_connect_log.clear()
    host = "203.0.113.7"
    realtime_auth._ws_rate_limited(host)
    assert host in realtime_auth._ws_connect_log
    # 模拟窗口过期:把时间戳推到窗口外
    import time as _time
    realtime_auth._ws_connect_log[host][0] = _time.time() - realtime_auth._WS_CONNECT_WINDOW - 1
    # 下次调用会 popleft 清空,然后删键
    realtime_auth._ws_rate_limited(host)  # 触发清理 + 重新加入
    # 关键:清理后若再次因新连接 setdefault,键存在但 deque 是新的(不累积)
    assert len(realtime_auth._ws_connect_log[host]) == 1
    realtime_auth._ws_connect_log.clear()


def test_ws_client_ip_uses_xff_from_trusted_proxy():
    """#5: 直连来自可信反代(127.0.0.1)时读 X-Forwarded-For,避免反代后全站共享
    proxy IP 的 20 连接配额(单点 DoS)。"""
    from app.services import realtime_auth
    from unittest.mock import MagicMock

    ws = MagicMock()
    ws.client.host = "127.0.0.1"
    ws.headers = {"X-Forwarded-For": "203.0.113.9"}
    assert realtime_auth._ws_client_ip(ws) == "203.0.113.9"

    # X-Real-IP 兜底
    ws2 = MagicMock()
    ws2.client.host = "127.0.0.1"
    ws2.headers = {"X-Real-IP": "198.51.100.10"}
    assert realtime_auth._ws_client_ip(ws2) == "198.51.100.10"


def test_ws_client_ip_ignores_xff_from_untrusted():
    """#5: 直连不可信时不读 XFF(防客户端伪造绕过限流)。"""
    from app.services import realtime_auth
    from unittest.mock import MagicMock

    ws = MagicMock()
    ws.client.host = "203.0.113.50"  # 非可信反代
    ws.headers = {"X-Forwarded-For": "1.2.3.4"}
    assert realtime_auth._ws_client_ip(ws) == "203.0.113.50"
