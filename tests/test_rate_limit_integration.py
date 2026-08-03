"""速率限制集成测试。"""
import pytest
from unittest.mock import Mock, patch
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestRateLimitIntegration:
    """测试速率限制集成"""

    def test_rate_limit_middleware_registered(self):
        """测试速率限制中间件已注册"""
        # 检查 app/__init__.py（中间件在这里注册）
        source_path = REPO_ROOT / "app" / "__init__.py"
        source = source_path.read_text(encoding="utf-8")
        
        # 检查是否导入了 RateLimitMiddleware
        assert 'RateLimitMiddleware' in source, "app/__init__.py 应导入 RateLimitMiddleware"

    def test_rate_limit_config_used(self):
        """测试速率限制配置被使用"""
        # 检查 app/__init__.py（中间件在这里注册）
        source_path = REPO_ROOT / "app" / "__init__.py"
        source = source_path.read_text(encoding="utf-8")
        
        # 检查是否使用了速率限制配置
        assert 'rate_limit' in source.lower() or 'requests_per_minute' in source, \
            "app/__init__.py 应使用速率限制配置"


class TestRateLimitMiddlewareFunctional:
    """测试速率限制中间件功能"""

    def test_middleware_blocks_excessive_requests(self):
        """测试中间件阻止过多请求"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from app.middleware.rate_limit import RateLimitMiddleware
        
        app = FastAPI()
        
        @app.get("/test")
        async def test_endpoint():
            return {"status": "ok"}
        
        # 添加速率限制中间件
        app.add_middleware(RateLimitMiddleware, requests_per_minute=5)
        
        client = TestClient(app)
        
        # 前 5 个请求应该成功
        for i in range(5):
            response = client.get("/test")
            assert response.status_code == 200
        
        # 第 6 个请求应该被限制
        response = client.get("/test")
        assert response.status_code == 429


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
