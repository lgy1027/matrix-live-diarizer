"""回归测试:app 工厂传给 RateLimitMiddleware 的 requests_per_minute 必须从 config.rate_limit 来

之前 app/__init__.py:38 用 getattr(config.server, 'rate_limit_requests', 100),
config.server 没有该字段,走默认 100 — 忽略 .env 里的 RATE_LIMIT_REQUESTS_PER_MINUTE。
实际限流按 100/min 触发,但用户 .env 配 60,完全失效。

回归测试:改 .env 后,中间件 kwargs 必须反映 .env。
"""
import importlib
import sys


def _reload_clean_app(monkeypatch, env: dict):
    """清掉 app.* sys.modules,设环境变量,重新加载"""
    for mod in list(sys.modules):
        if mod == "app" or mod.startswith("app."):
            del sys.modules[mod]
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cfg_mod = importlib.import_module("app.config")
    importlib.reload(cfg_mod)
    from app import create_app
    return create_app()


def test_rate_limit_uses_config_not_hardcoded_default(monkeypatch):
    """app 工厂必须把 config.rate_limit 传给中间件,不能写死 100"""
    app = _reload_clean_app(monkeypatch, {
        "RATE_LIMIT_REQUESTS_PER_MINUTE": "5",
        "RATE_LIMIT_REQUESTS_PER_HOUR": "50",
    })

    from app.middleware.rate_limit import RateLimitMiddleware
    from app.config import config
    assert config.rate_limit.requests_per_minute == 5
    assert config.rate_limit.requests_per_hour == 50

    mw = None
    for m in app.user_middleware:
        if m.cls is RateLimitMiddleware:
            mw = m
            break
    assert mw is not None, "RateLimitMiddleware 未注册"
    assert mw.kwargs.get("requests_per_minute") == 5, \
        f"app 工厂没把 config.rate_limit.requests_per_minute 传给中间件,实际: {mw.kwargs.get('requests_per_minute')}"
    assert mw.kwargs.get("requests_per_hour") == 50
    assert mw.kwargs.get("enabled") is True


def test_rate_limit_can_be_disabled(monkeypatch):
    """RATE_LIMIT_ENABLED=false 时中间件 enabled=False"""
    app = _reload_clean_app(monkeypatch, {"RATE_LIMIT_ENABLED": "false"})

    from app.middleware.rate_limit import RateLimitMiddleware
    mw = None
    for m in app.user_middleware:
        if m.cls is RateLimitMiddleware:
            mw = m
            break
    assert mw is not None
    assert mw.kwargs.get("enabled") is False

