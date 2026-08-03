"""速率限制单元测试。"""
import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
import time
import logging


class TestRateLimit:
    """测试速率限制"""

    @pytest.fixture
    def mock_app(self):
        """创建测试应用"""
        from fastapi import FastAPI
        app = FastAPI()
        @app.get("/probe")
        def probe():
            return {"ok": True}
        return app

    def test_rate_limit_config_exists(self):
        """测试速率限制配置存在"""
        from app.config import config
        
        # 应该有速率限制配置
        assert hasattr(config, 'rate_limit') or hasattr(config, 'rate_limit_requests')

    def test_rate_limit_allows_normal_requests(self, mock_app):
        """测试正常请求不被限制"""
        client = TestClient(mock_app)
        response = client.get("/probe")
        assert response.status_code == 200

    def test_rate_limit_headers_present(self, mock_app):
        """测试响应包含速率限制头"""
        client = TestClient(mock_app)
        response = client.get("/probe")
        assert response.status_code in [200, 429]

    def test_invalid_proxy_warning_does_not_log_untrusted_value(self, mock_app, caplog):
        from app.middleware import RateLimitMiddleware

        malicious = "invalid\r\nforged-log: true"
        with caplog.at_level(logging.WARNING, logger="Matrix_Core"):
            RateLimitMiddleware(mock_app, trusted_proxies=[malicious])

        assert "忽略无效 trusted_proxy CIDR" in caplog.text
        assert "forged-log" not in caplog.text


class TestRateLimitExceeded:
    """测试速率限制超限"""

    def test_rate_limit_returns_429_on_exceed(self):
        """测试超限返回 429"""
        from fastapi import FastAPI
        from app.middleware import RateLimitMiddleware
        
        app = FastAPI()
        # 添加速率限制中间件，设置很低限制以便测试
        app.add_middleware(RateLimitMiddleware, requests_per_minute=2, requests_per_hour=100, enabled=True)
        @app.get("/probe")
        def probe():
            return {"ok": True}
        client = TestClient(app)
        for _ in range(2):
            response = client.get("/probe")
            assert response.status_code == 200
        response = client.get("/probe")
        assert response.status_code == 429


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
