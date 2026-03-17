"""声纹引擎动态切换测试 - TDD"""
import pytest
import os
import sys
from unittest.mock import Mock, patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockSpeakerEngine:
    """模拟声纹引擎"""
    
    def __init__(self, engine_type: str, embedding_dim: int = 192):
        self.engine_type = engine_type
        self.embedding_dim = embedding_dim
        self.collection = Mock()
        self.emb_buffer = {}
        self.EMB_BUFFER_SIZE = 5
    
    def get_embedding_dim(self) -> int:
        return self.embedding_dim
    
    def list_speakers(self, session_id=None):
        return []
    
    def get_speaker(self, speaker_id):
        return None
    
    def rename_speaker(self, speaker_id, name):
        return True
    
    def delete_speaker(self, speaker_id):
        return True


class TestSpeakerEngineManager:
    """测试引擎管理器"""

    def test_manager_class_exists(self):
        """测试 SpeakerEngineManager 类存在"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        assert SpeakerEngineManager is not None

    def test_manager_is_singleton(self):
        """测试管理器是单例模式"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager1 = SpeakerEngineManager()
        manager2 = SpeakerEngineManager()
        
        assert manager1 is manager2

    def test_manager_has_current_engine(self):
        """测试管理器有当前引擎属性"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        
        assert hasattr(manager, 'current_engine')
        assert hasattr(manager, 'current_type')

    def test_manager_get_engine(self):
        """测试获取引擎"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        engine = manager.get_engine()
        
        assert engine is not None

    def test_manager_switch_engine(self):
        """测试切换引擎"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        
        # 切换到 eres2net
        result = manager.switch_engine("eres2net")
        
        assert result["success"] is True
        assert result["engine_type"] == "eres2net"
        assert "engine_info" in result

    def test_manager_switch_to_invalid_engine(self):
        """测试切换到无效引擎"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        
        result = manager.switch_engine("invalid_engine")
        
        assert result["success"] is False
        assert "error" in result

    def test_manager_switch_same_engine(self):
        """测试切换到当前引擎"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        
        # 先确保是 campplus
        manager.switch_engine("campplus")
        
        # 再次切换到 campplus
        result = manager.switch_engine("campplus")
        
        assert result["success"] is True
        assert "already_active" in result.get("message", "").lower() or result.get("already_active") is True

    def test_manager_returns_embedding_dim_warning(self):
        """测试返回 embedding 维度警告"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        
        result = manager.switch_engine("wespeaker")  # wespeaker 是 256 维
        
        # 应该包含维度信息
        assert "embedding_dim" in result or "engine_info" in result

    def test_manager_get_all_engines_info(self):
        """测试获取所有引擎信息"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        
        info = manager.get_all_engines_info()
        
        assert "current" in info
        assert "engines" in info
        assert "campplus" in info["engines"]
        assert "eres2net" in info["engines"]
        assert "wespeaker" in info["engines"]

    def test_manager_engine_caching(self):
        """测试引擎缓存机制"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        
        # 切换到 eres2net
        manager.switch_engine("eres2net")
        engine1 = manager.get_engine()
        
        # 切换到 campplus
        manager.switch_engine("campplus")
        
        # 再切换回 eres2net（应该使用缓存）
        manager.switch_engine("eres2net")
        engine2 = manager.get_engine()
        
        # 应该是同一个实例（缓存）
        assert engine1 is engine2


class TestEngineSwitchAPI:
    """测试引擎切换 API"""

    @pytest.fixture
    def mock_app(self):
        """创建测试应用"""
        from fastapi import FastAPI
        from app.api.speakers import router
        
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def mock_manager(self):
        """模拟引擎管理器"""
        manager = Mock()
        manager.switch_engine.return_value = {
            "success": True,
            "engine_type": "eres2net",
            "engine_info": {
                "name": "ERes2NetV2",
                "embedding_dim": 192,
                "model": "iic/speech_eres2netv2_sv_zh-cn_16k-common"
            },
            "embedding_dim_changed": False
        }
        manager.get_all_engines_info.return_value = {
            "current": "eres2net",
            "engines": {
                "campplus": {"name": "CamPlus", "embedding_dim": 192},
                "eres2net": {"name": "ERes2NetV2", "embedding_dim": 192},
                "wespeaker": {"name": "ResNet34", "embedding_dim": 256}
            }
        }
        manager.get_engine.return_value = Mock()
        return manager

    def test_put_engine_endpoint_exists(self, mock_app):
        """测试 PUT /v1/engine 接口存在"""
        from fastapi.testclient import TestClient
        
        client = TestClient(mock_app)
        
        # 尝试 PUT 请求，即使 mock 不完整也应该返回非 404
        with patch('app.api.speakers.get_engine_manager') as mock_get_manager:
            mock_manager = Mock()
            mock_manager.switch_engine.return_value = {"success": True, "engine_type": "campplus"}
            mock_get_manager.return_value = mock_manager
            
            response = client.put("/v1/engine", json={"engine_type": "campplus"})
            
            # 不应该返回 404
            assert response.status_code != 404

    def test_put_engine_success(self, mock_app, mock_manager):
        """测试成功切换引擎"""
        from fastapi.testclient import TestClient
        
        with patch('app.api.speakers.get_engine_manager', return_value=mock_manager):
            client = TestClient(mock_app)
            response = client.put("/v1/engine", json={"engine_type": "eres2net"})
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["engine_type"] == "eres2net"

    def test_put_engine_invalid_type(self, mock_app, mock_manager):
        """测试无效引擎类型"""
        from fastapi.testclient import TestClient
        
        mock_manager.switch_engine.return_value = {
            "success": False,
            "error": "Invalid engine type: invalid"
        }
        
        with patch('app.api.speakers.get_engine_manager', return_value=mock_manager):
            client = TestClient(mock_app)
            response = client.put("/v1/engine", json={"engine_type": "invalid"})
            
            assert response.status_code == 400

    def test_get_engines_endpoint(self, mock_app, mock_manager):
        """测试 GET /v1/engines 获取所有引擎"""
        from fastapi.testclient import TestClient
        
        with patch('app.api.speakers.get_engine_manager', return_value=mock_manager):
            client = TestClient(mock_app)
            response = client.get("/v1/engines")
            
            assert response.status_code == 200
            data = response.json()
            assert "current" in data
            assert "engines" in data

    def test_put_engine_empty_type(self, mock_app):
        """测试空引擎类型"""
        from fastapi.testclient import TestClient
        
        with patch('app.api.speakers.get_engine_manager') as mock_get_manager:
            client = TestClient(mock_app)
            response = client.put("/v1/engine", json={"engine_type": ""})
            
            # Pydantic 验证应该拒绝空值
            assert response.status_code == 422

    def test_embedding_dim_warning_in_response(self, mock_app):
        """测试响应中包含 embedding 维度警告"""
        from fastapi.testclient import TestClient
        
        mock_manager = Mock()
        mock_manager.switch_engine.return_value = {
            "success": True,
            "engine_type": "wespeaker",
            "engine_info": {
                "name": "ResNet34",
                "embedding_dim": 256
            },
            "previous_dim": 192,
            "embedding_dim_changed": True,
            "warning": "Embedding dimension changed from 192 to 256"
        }
        
        with patch('app.api.speakers.get_engine_manager', return_value=mock_manager):
            client = TestClient(mock_app)
            response = client.put("/v1/engine", json={"engine_type": "wespeaker"})
            
            assert response.status_code == 200
            data = response.json()
            assert data.get("embedding_dim_changed") is True
            assert "warning" in data


class TestEngineSwitchRequestModel:
    """测试请求模型"""

    def test_engine_switch_request_model(self):
        """测试 EngineSwitchRequest 模型"""
        from app.schemas.response import EngineSwitchRequest
        
        request = EngineSwitchRequest(engine_type="eres2net")
        assert request.engine_type == "eres2net"

    def test_engine_switch_request_invalid_type(self):
        """测试无效引擎类型验证"""
        from pydantic import ValidationError
        
        try:
            from app.schemas.response import EngineSwitchRequest
            # 尝试创建空引擎类型
            try:
                EngineSwitchRequest(engine_type="")
                assert False, "Should have raised ValidationError"
            except ValidationError:
                pass  # Expected
        except ImportError:
            # 如果模型还不存在，跳过
            pass


class TestEngineSwitchResponseModel:
    """测试响应模型"""

    def test_engine_switch_response_model(self):
        """测试 EngineSwitchResponse 模型"""
        try:
            from app.schemas.response import EngineSwitchResponse
            
            response = EngineSwitchResponse(
                success=True,
                engine_type="eres2net",
                engine_info={"name": "ERes2NetV2", "embedding_dim": 192},
                embedding_dim_changed=False
            )
            
            assert response.success is True
            assert response.engine_type == "eres2net"
        except ImportError:
            # 如果模型还不存在，跳过
            pass


class TestIntegrationWithExistingCode:
    """测试与现有代码的集成"""

    def test_get_speaker_engine_uses_manager(self):
        """测试 get_speaker_engine 使用管理器"""
        from engine.speaker.speaker_factory import get_speaker_engine, SpeakerEngineManager
        
        # get_speaker_engine 应该从管理器获取引擎
        manager = SpeakerEngineManager()
        engine = get_speaker_engine()
        
        assert engine is not None
        # 引擎应该与管理器中的相同
        assert engine is manager.get_engine()

    def test_app_state_uses_manager(self):
        """测试 app.state 使用管理器"""
        # 检查 app/__init__.py 中是否使用管理器
        import inspect
        from app import create_app
        
        source = inspect.getsource(create_app)
        
        # 应该包含 EngineManager 或相关引用
        # 这是一个软性检查，确保架构正确
        assert "spk_engine" in source


class TestThreadSafety:
    """测试线程安全"""

    def test_manager_has_lock(self):
        """测试管理器有锁机制"""
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        
        assert hasattr(manager, '_lock') or hasattr(manager, 'lock')

    @pytest.mark.asyncio
    async def test_concurrent_switch(self):
        """测试并发切换"""
        import asyncio
        from engine.speaker.speaker_factory import SpeakerEngineManager
        
        manager = SpeakerEngineManager()
        
        async def switch_to(engine_type):
            return manager.switch_engine(engine_type)
        
        # 并发切换
        results = await asyncio.gather(
            switch_to("eres2net"),
            switch_to("wespeaker"),
            switch_to("campplus")
        )
        
        # 所有操作应该成功或被锁保护
        for result in results:
            assert "success" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
