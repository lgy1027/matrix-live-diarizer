"""说话人管理功能测试"""
import pytest
import os
import sys
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MockCollection:
    """模拟 ChromaDB Collection"""
    
    def __init__(self):
        self.data = {}
        self.embeddings = {}
        self.metadatas = {}
    
    def add(self, ids, embeddings, metadatas):
        for i, id_ in enumerate(ids):
            self.data[id_] = True
            self.embeddings[id_] = embeddings[i]
            self.metadatas[id_] = metadatas[i]
    
    def get(self, ids=None, where=None, include=None):
        result_ids = []
        result_embeddings = []
        result_metadatas = []
        
        if ids:
            for id_ in ids:
                if id_ in self.data:
                    result_ids.append(id_)
                    if include and 'embeddings' in include:
                        result_embeddings.append(self.embeddings.get(id_))
                    if include and 'metadatas' in include:
                        result_metadatas.append(self.metadatas.get(id_, {}))
        else:
            for id_ in self.data:
                if where is None or self._match_where(id_, where):
                    result_ids.append(id_)
                    if include and 'metadatas' in include:
                        result_metadatas.append(self.metadatas.get(id_, {}))
        
        result = {'ids': result_ids}
        if include and 'embeddings' in include:
            result['embeddings'] = result_embeddings
        if include and 'metadatas' in include:
            result['metadatas'] = result_metadatas
        return result
    
    def _match_where(self, id_, where):
        meta = self.metadatas.get(id_, {})
        for key, value in where.items():
            if meta.get(key) != value:
                return False
        return True
    
    def update(self, ids, embeddings=None, metadatas=None):
        for i, id_ in enumerate(ids):
            if embeddings:
                self.embeddings[id_] = embeddings[i]
            if metadatas:
                self.metadatas[id_] = metadatas[i]
    
    def delete(self, ids):
        for id_ in ids:
            self.data.pop(id_, None)
            self.embeddings.pop(id_, None)
            self.metadatas.pop(id_, None)
    
    def query(self, query_embeddings, n_results=1, where=None):
        return {
            'ids': [[]],
            'distances': [[]],
            'metadatas': [[]]
        }


class TestSpeakerManagementMethods:
    """测试说话人管理方法"""
    
    @pytest.fixture
    def mock_engine(self):
        """创建模拟引擎"""
        from engine.speaker.campplus_engine import CamPlusEngine
        
        engine = object.__new__(CamPlusEngine)
        engine.collection = MockCollection()
        engine.emb_buffer = {}
        engine.match_history = {}
        engine.EMB_BUFFER_SIZE = 5
        engine.HISTORY_SIZE = 3
        
        # 添加测试数据
        engine.collection.add(
            ids=["Spk_001", "Spk_002", "Spk_003"],
            embeddings=[[0.1] * 192, [0.2] * 192, [0.3] * 192],
            metadatas=[
                {"session_id": "session_a", "count": 5, "last_update": 1000},
                {"session_id": "session_a", "count": 3, "last_update": 2000},
                {"session_id": "session_b", "count": 2, "last_update": 1500},
            ]
        )
        return engine
    
    def test_list_speakers_all(self, mock_engine):
        """测试获取所有说话人"""
        speakers = mock_engine.list_speakers()
        
        assert len(speakers) == 3
        # 按更新时间倒序
        assert speakers[0]["id"] == "Spk_002"
        assert speakers[1]["id"] == "Spk_003"
        assert speakers[2]["id"] == "Spk_001"
    
    def test_list_speakers_by_session(self, mock_engine):
        """测试按会话获取说话人"""
        speakers = mock_engine.list_speakers(session_id="session_a")
        
        assert len(speakers) == 2
        for s in speakers:
            assert s["session_id"] == "session_a"
    
    def test_list_speakers_empty_session(self, mock_engine):
        """测试空会话"""
        speakers = mock_engine.list_speakers(session_id="nonexistent")
        assert len(speakers) == 0
    
    def test_get_speaker_exists(self, mock_engine):
        """测试获取存在的说话人"""
        speaker = mock_engine.get_speaker("Spk_001")
        
        assert speaker is not None
        assert speaker["id"] == "Spk_001"
        assert speaker["session_id"] == "session_a"
        assert speaker["sample_count"] == 5
    
    def test_get_speaker_not_exists(self, mock_engine):
        """测试获取不存在的说话人"""
        speaker = mock_engine.get_speaker("Spk_999")
        assert speaker is None
    
    def test_rename_speaker_success(self, mock_engine):
        """测试重命名说话人"""
        result = mock_engine.rename_speaker("Spk_001", "张三")
        assert result is True
        
        speaker = mock_engine.get_speaker("Spk_001")
        assert speaker["name"] == "张三"
    
    def test_rename_speaker_not_exists(self, mock_engine):
        """测试重命名不存在的说话人"""
        result = mock_engine.rename_speaker("Spk_999", "李四")
        assert result is False
    
    def test_rename_speaker_empty_name(self, mock_engine):
        """测试空名称重命名"""
        # 引擎层不验证名称，由API层验证
        result = mock_engine.rename_speaker("Spk_001", "")
        # 仍然成功，只是名称为空
        assert result is True
    
    def test_delete_speaker_success(self, mock_engine):
        """测试删除说话人"""
        result = mock_engine.delete_speaker("Spk_001")
        assert result is True
        
        speaker = mock_engine.get_speaker("Spk_001")
        assert speaker is None
    
    def test_delete_speaker_not_exists(self, mock_engine):
        """测试删除不存在的说话人"""
        result = mock_engine.delete_speaker("Spk_999")
        assert result is False
    
    def test_speaker_response_format(self, mock_engine):
        """测试返回格式"""
        speaker = mock_engine.get_speaker("Spk_001")
        
        assert "id" in speaker
        assert "name" in speaker
        assert "session_id" in speaker
        assert "sample_count" in speaker
        assert "last_update" in speaker


class TestSpeakerAPIRoutes:
    """测试说话人管理 API 路由"""
    
    @pytest.fixture
    def mock_app(self):
        """创建测试应用"""
        from fastapi import FastAPI
        from app.api.speakers import router
        
        app = FastAPI()
        app.include_router(router)
        return app
    
    @pytest.fixture
    def mock_speaker_engine(self):
        """模拟说话人引擎"""
        engine = Mock()
        engine.list_speakers.return_value = [
            {"id": "Spk_001", "name": "Spk_001", "session_id": "sess_a", "sample_count": 5, "last_update": 1000},
            {"id": "Spk_002", "name": "Spk_002", "session_id": "sess_a", "sample_count": 3, "last_update": 2000},
        ]
        engine.get_speaker.return_value = {"id": "Spk_001", "name": "Spk_001", "session_id": "sess_a", "sample_count": 5, "last_update": 1000}
        engine.rename_speaker.return_value = True
        engine.delete_speaker.return_value = True
        return engine
    
    def test_list_speakers_endpoint(self, mock_app, mock_speaker_engine):
        """测试 GET /v1/speakers"""
        from fastapi.testclient import TestClient
        
        with patch('app.api.speakers.get_speaker_engine', return_value=mock_speaker_engine):
            client = TestClient(mock_app)
            response = client.get("/v1/speakers")
            
            assert response.status_code == 200
            data = response.json()
            assert "speakers" in data
            assert "total" in data
            assert data["total"] == 2
    
    def test_list_speakers_with_session(self, mock_app, mock_speaker_engine):
        """测试 GET /v1/speakers?session_id=xxx"""
        from fastapi.testclient import TestClient
        
        with patch('app.api.speakers.get_speaker_engine', return_value=mock_speaker_engine):
            client = TestClient(mock_app)
            response = client.get("/v1/speakers?session_id=sess_a")
            
            assert response.status_code == 200
            mock_speaker_engine.list_speakers.assert_called_with("sess_a")
    
    def test_get_speaker_endpoint(self, mock_app, mock_speaker_engine):
        """测试 GET /v1/speakers/{speaker_id}"""
        from fastapi.testclient import TestClient
        
        with patch('app.api.speakers.get_speaker_engine', return_value=mock_speaker_engine):
            client = TestClient(mock_app)
            response = client.get("/v1/speakers/Spk_001")
            
            assert response.status_code == 200
            data = response.json()
            assert data["speaker"]["id"] == "Spk_001"
    
    def test_get_speaker_not_found(self, mock_app, mock_speaker_engine):
        """测试获取不存在的说话人"""
        from fastapi.testclient import TestClient
        
        mock_speaker_engine.get_speaker.return_value = None
        
        with patch('app.api.speakers.get_speaker_engine', return_value=mock_speaker_engine):
            client = TestClient(mock_app)
            response = client.get("/v1/speakers/Spk_999")
            
            assert response.status_code == 404
    
    def test_rename_speaker_endpoint(self, mock_app, mock_speaker_engine):
        """测试 PATCH /v1/speakers/{speaker_id}"""
        from fastapi.testclient import TestClient
        
        with patch('app.api.speakers.get_speaker_engine', return_value=mock_speaker_engine):
            client = TestClient(mock_app)
            response = client.patch("/v1/speakers/Spk_001", json={"name": "张三"})
            
            assert response.status_code == 200
            mock_speaker_engine.rename_speaker.assert_called_with("Spk_001", "张三")
    
    def test_rename_speaker_empty_name(self, mock_app, mock_speaker_engine):
        """测试空名称重命名"""
        from fastapi.testclient import TestClient
        
        with patch('app.api.speakers.get_speaker_engine', return_value=mock_speaker_engine):
            client = TestClient(mock_app)
            response = client.patch("/v1/speakers/Spk_001", json={"name": ""})
            
            assert response.status_code == 400
    
    def test_delete_speaker_endpoint(self, mock_app, mock_speaker_engine):
        """测试 DELETE /v1/speakers/{speaker_id}"""
        from fastapi.testclient import TestClient
        
        with patch('app.api.speakers.get_speaker_engine', return_value=mock_speaker_engine):
            client = TestClient(mock_app)
            response = client.delete("/v1/speakers/Spk_001")
            
            assert response.status_code == 200
            mock_speaker_engine.delete_speaker.assert_called_with("Spk_001")
    
    def test_delete_speaker_not_found(self, mock_app, mock_speaker_engine):
        """测试删除不存在的说话人"""
        from fastapi.testclient import TestClient
        
        mock_speaker_engine.get_speaker.return_value = None
        
        with patch('app.api.speakers.get_speaker_engine', return_value=mock_speaker_engine):
            client = TestClient(mock_app)
            response = client.delete("/v1/speakers/Spk_999")
            
            assert response.status_code == 404


class TestSpeakerResponseModels:
    """测试响应模型"""
    
    def test_speaker_info_model(self):
        """测试 SpeakerInfo 模型"""
        from app.schemas.response import SpeakerInfo
        
        info = SpeakerInfo(
            id="Spk_001",
            name="张三",
            session_id="sess_a",
            sample_count=5,
            last_update=1000.0
        )
        
        assert info.id == "Spk_001"
        assert info.name == "张三"
        assert info.session_id == "sess_a"
        assert info.sample_count == 5
        assert info.last_update == 1000.0
    
    def test_speaker_response_model(self):
        """测试 SpeakerResponse 模型"""
        from app.schemas.response import SpeakerResponse, SpeakerInfo
        
        info = SpeakerInfo(
            id="Spk_001",
            name="Spk_001",
            session_id="sess_a",
            sample_count=5,
            last_update=1000.0
        )
        
        response = SpeakerResponse(speaker=info)
        assert response.speaker.id == "Spk_001"
    
    def test_speaker_list_response_model(self):
        """测试 SpeakerListResponse 模型"""
        from app.schemas.response import SpeakerListResponse, SpeakerInfo
        
        speakers = [
            SpeakerInfo(id="Spk_001", name="Spk_001", session_id="sess_a", sample_count=5, last_update=1000.0),
            SpeakerInfo(id="Spk_002", name="Spk_002", session_id="sess_b", sample_count=3, last_update=2000.0),
        ]
        
        response = SpeakerListResponse(speakers=speakers, total=2)
        assert response.total == 2
        assert len(response.speakers) == 2
    
    def test_speaker_update_request_model(self):
        """测试 SpeakerUpdateRequest 模型"""
        from app.schemas.response import SpeakerUpdateRequest
        
        request = SpeakerUpdateRequest(name="新名称")
        assert request.name == "新名称"


class TestAllEnginesHaveManagementMethods:
    """测试所有引擎都有管理方法"""
    
    def test_campplus_has_management_methods(self):
        """CamPlus 引擎有管理方法"""
        from engine.speaker.campplus_engine import CamPlusEngine
        
        assert hasattr(CamPlusEngine, 'list_speakers')
        assert hasattr(CamPlusEngine, 'get_speaker')
        assert hasattr(CamPlusEngine, 'rename_speaker')
        assert hasattr(CamPlusEngine, 'delete_speaker')
    
    def test_eres2net_has_management_methods(self):
        """ERes2Net 引擎有管理方法"""
        from engine.speaker.eres2net_engine import ERes2NetEngine
        
        assert hasattr(ERes2NetEngine, 'list_speakers')
        assert hasattr(ERes2NetEngine, 'get_speaker')
        assert hasattr(ERes2NetEngine, 'rename_speaker')
        assert hasattr(ERes2NetEngine, 'delete_speaker')
    
    def test_wespeaker_has_management_methods(self):
        """Wespeaker 引擎有管理方法"""
        from engine.speaker.wespeaker_engine import WespeakerEngine
        
        assert hasattr(WespeakerEngine, 'list_speakers')
        assert hasattr(WespeakerEngine, 'get_speaker')
        assert hasattr(WespeakerEngine, 'rename_speaker')
        assert hasattr(WespeakerEngine, 'delete_speaker')


class TestErrorHandling:
    """测试错误处理"""
    
    @pytest.fixture
    def mock_engine_with_error(self):
        """模拟会抛出异常的引擎"""
        from engine.speaker.campplus_engine import CamPlusEngine
        
        engine = object.__new__(CamPlusEngine)
        engine.collection = Mock()
        engine.collection.get.side_effect = Exception("数据库错误")
        engine.collection.delete.side_effect = Exception("删除失败")
        engine.collection.update.side_effect = Exception("更新失败")
        
        return engine
    
    def test_list_speakers_on_error(self, mock_engine_with_error):
        """错误时返回空列表"""
        result = mock_engine_with_error.list_speakers()
        assert result == []
    
    def test_get_speaker_on_error(self, mock_engine_with_error):
        """错误时返回 None"""
        result = mock_engine_with_error.get_speaker("Spk_001")
        assert result is None
    
    def test_rename_speaker_on_error(self, mock_engine_with_error):
        """错误时返回 False"""
        mock_engine_with_error.collection.get.side_effect = None
        mock_engine_with_error.collection.get.return_value = {
            'ids': ['Spk_001'],
            'metadatas': [{}],
            'embeddings': [[0.1] * 192]
        }
        
        result = mock_engine_with_error.rename_speaker("Spk_001", "张三")
        assert result is False
    
    def test_delete_speaker_on_error(self, mock_engine_with_error):
        """错误时返回 False"""
        mock_engine_with_error.collection.get.side_effect = None
        mock_engine_with_error.collection.get.return_value = {'ids': ['Spk_001']}
        
        result = mock_engine_with_error.delete_speaker("Spk_001")
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
