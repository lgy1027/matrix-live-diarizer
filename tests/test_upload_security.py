"""文件上传安全验证测试 - TDD"""
import pytest
import io
from unittest.mock import Mock, patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient


class TestFileUploadSecurity:
    """测试文件上传安全验证"""

    @pytest.fixture
    def mock_app(self):
        """创建测试应用"""
        from fastapi import FastAPI
        from app.api.upload import router
        
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def mock_engines(self):
        """模拟引擎"""
        asr_mock = Mock()
        asr_mock.run_asr = Mock(return_value="测试文本")
        
        spk_mock = Mock()
        spk_mock.extract_feat = Mock(return_value=[0.1] * 192)
        spk_mock.compare_and_identify = Mock(return_value="Spk_001")
        
        import asyncio
        lock = asyncio.Lock()
        
        return asr_mock, spk_mock, lock

    def test_reject_invalid_file_extension_exe(self, mock_app, mock_engines):
        """测试拒绝 .exe 文件"""
        asr, spk, lock = mock_engines
        
        with patch('app.api.upload.asr_engine', asr), \
             patch('app.api.upload.spk_engine', spk), \
             patch('app.api.upload.inference_lock', lock), \
             patch('app.api.upload.current_dir', '/tmp'):
            
            client = TestClient(mock_app)
            
            response = client.post(
                "/v1/upload",
                files={"file": ("virus.exe", b"fake content", "application/octet-stream")}
            )
            
            assert response.status_code == 400
            assert "不支持的文件类型" in response.json()["detail"]

    def test_reject_invalid_extension_txt(self, mock_app, mock_engines):
        """测试拒绝 .txt 文件"""
        asr, spk, lock = mock_engines
        
        with patch('app.api.upload.asr_engine', asr), \
             patch('app.api.upload.spk_engine', spk), \
             patch('app.api.upload.inference_lock', lock), \
             patch('app.api.upload.current_dir', '/tmp'):
            
            client = TestClient(mock_app)
            
            response = client.post(
                "/v1/upload",
                files={"file": ("document.txt", b"text content", "text/plain")}
            )
            
            assert response.status_code == 400
            assert "不支持的文件类型" in response.json()["detail"]

    def test_reject_oversized_file(self, mock_app, mock_engines):
        """测试拒绝超大文件"""
        asr, spk, lock = mock_engines
        
        with patch('app.api.upload.asr_engine', asr), \
             patch('app.api.upload.spk_engine', spk), \
             patch('app.api.upload.inference_lock', lock), \
             patch('app.api.upload.current_dir', '/tmp'), \
             patch('app.api.upload.MAX_FILE_SIZE', 100):  # 限制 100 bytes
            
            client = TestClient(mock_app)
            
            # 上传超过限制的文件
            large_content = b'x' * 200
            response = client.post(
                "/v1/upload",
                files={"file": ("large.wav", large_content, "audio/wav")}
            )
            
            assert response.status_code == 400
            assert "文件大小" in response.json()["detail"]

    def test_valid_extensions_list(self):
        """测试允许的文件扩展名列表"""
        from app.api.upload import ALLOWED_EXTENSIONS
        
        # 应包含常见音频格式
        assert '.wav' in ALLOWED_EXTENSIONS
        assert '.mp3' in ALLOWED_EXTENSIONS
        assert '.m4a' in ALLOWED_EXTENSIONS
        assert '.flac' in ALLOWED_EXTENSIONS
        assert '.ogg' in ALLOWED_EXTENSIONS
        
        # 不应包含危险格式
        assert '.exe' not in ALLOWED_EXTENSIONS
        assert '.bat' not in ALLOWED_EXTENSIONS
        assert '.sh' not in ALLOWED_EXTENSIONS
        assert '.txt' not in ALLOWED_EXTENSIONS

    def test_max_file_size_constant(self):
        """测试最大文件大小常量"""
        from app.api.upload import MAX_FILE_SIZE
        
        # 应该是合理的限制 (100MB - 1GB)
        assert MAX_FILE_SIZE >= 100 * 1024 * 1024
        assert MAX_FILE_SIZE <= 1024 * 1024 * 1024


if __name__ == "__main__":
    pytest.main([__file__, "-v"])