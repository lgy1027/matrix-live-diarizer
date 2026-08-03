"""健康检查端点测试。"""
import pytest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """测试健康检查端点"""

    @pytest.fixture
    def mock_app(self):
        """创建测试应用"""
        from fastapi import FastAPI
        
        # 尝试导入 health router，如果不存在则创建空的
        try:
            from app.api.health import router as health_router
        except ImportError:
            # 如果模块不存在，创建一个空的路由
            from fastapi import APIRouter
            health_router = APIRouter()
        
        app = FastAPI()
        app.include_router(health_router)
        return app

    def test_health_endpoint_exists(self, mock_app):
        """测试 /health 端点存在"""
        client = TestClient(mock_app)
        response = client.get("/health")
        
        assert response.status_code == 200

    def test_health_returns_healthy_status(self, mock_app):
        """测试 /health 返回健康状态"""
        client = TestClient(mock_app)
        response = client.get("/health")
        
        data = response.json()
        assert data.get("status") == "healthy"

    def test_health_returns_timestamp(self, mock_app):
        """测试 /health 返回时间戳"""
        client = TestClient(mock_app)
        response = client.get("/health")
        
        data = response.json()
        assert "timestamp" in data
        assert isinstance(data["timestamp"], (int, float))

    def test_ready_endpoint_exists(self, mock_app):
        """测试 /ready 端点存在(无引擎时返 503 就绪探针语义)"""
        client = TestClient(mock_app)
        response = client.get("/ready")

        assert response.status_code in (200, 503)

    def test_ready_returns_engine_status(self, mock_app):
        """测试 /ready 返回引擎状态"""
        client = TestClient(mock_app)
        response = client.get("/ready")
        
        data = response.json()
        assert "status" in data

    def test_ready_checks_asr_engine(self, mock_app):
        """测试 /ready 检查 ASR 引擎状态"""
        mock_app.state.runtime = Mock(asr=Mock(), speaker=Mock())
        client = TestClient(mock_app)
        response = client.get("/ready")
        assert response.json()["asr"] is True

    def test_ready_checks_speaker_engine(self, mock_app):
        """测试 /ready 检查说话人引擎状态"""
        mock_app.state.runtime = Mock(asr=Mock(), speaker=Mock())
        client = TestClient(mock_app)
        response = client.get("/ready")
        assert response.json()["speaker"] is True

    def test_ready_reports_not_ready_when_slot_leaked(self, mock_app):
        """槽泄漏时 /ready 应报 not_ready 且 inference_slot=False。"""
        runtime = Mock(asr=Mock(), speaker=Mock())
        runtime.slot_leaked = True
        mock_app.state.runtime = runtime
        client = TestClient(mock_app)
        response = client.get("/ready")
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["inference_slot"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
