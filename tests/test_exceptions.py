"""异常处理测试 - TDD"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException


class TestExceptionHandling:
    """测试细化异常处理"""

    def test_upload_handles_http_exception_correctly(self):
        """测试上传端点正确处理 HTTPException"""
        from fastapi import FastAPI
        from app.api.upload import router
        
        app = FastAPI()
        app.include_router(router)
        
        with patch('app.api.upload.asr_engine', Mock()), \
             patch('app.api.upload.inference_lock', MagicMock()), \
             patch('app.api.upload.current_dir', '/tmp'):
            
            client = TestClient(app)
            
            # 测试上传超大文件应返回 400 而非 500
            large_content = b'x' * 600 * 1024 * 1024  # 600MB
            response = client.post(
                "/v1/upload",
                files={"file": ("large.wav", large_content, "audio/wav")}
            )
            
            # 应该是 400 (客户端错误) 而非 500 (服务器错误)
            assert response.status_code in [400, 413]

    def test_custom_exception_classes_exist(self):
        """测试自定义异常类存在"""
        from app.exceptions import (
            AudioProcessingError,
            EngineNotInitializedError,
            InvalidAudioFormatError,
        )
        
        # 这些异常类应该继承自 Exception
        assert issubclass(AudioProcessingError, Exception)
        assert issubclass(EngineNotInitializedError, Exception)
        assert issubclass(InvalidAudioFormatError, Exception)

    def test_audio_processing_error_with_context(self):
        """测试 AudioProcessingError 包含上下文信息"""
        from app.exceptions import AudioProcessingError
        
        error = AudioProcessingError("处理失败", audio_duration=10.5, sample_rate=16000)
        
        assert "处理失败" in str(error)
        assert error.audio_duration == 10.5
        assert error.sample_rate == 16000

    def test_engine_not_initialized_error(self):
        """测试 EngineNotInitializedError"""
        from app.exceptions import EngineNotInitializedError
        
        error = EngineNotInitializedError("ASR")
        
        assert "ASR" in str(error)
        assert error.engine_name == "ASR"


class TestSpecificExceptionHandling:
    """测试特定异常处理"""

    def test_upload_rejects_invalid_audio_format(self):
        """测试上传端点拒绝无效音频格式"""
        from fastapi import FastAPI
        from app.api.upload import router
        
        app = FastAPI()
        app.include_router(router)
        
        # Mock librosa at module level before import
        import sys
        librosa_mock = MagicMock()
        librosa_mock.load.side_effect = Exception("Invalid audio file")
        
        with patch.dict('sys.modules', {'librosa': librosa_mock}), \
             patch('app.api.upload.asr_engine', Mock()), \
             patch('app.api.upload.inference_lock', MagicMock()), \
             patch('app.api.upload.current_dir', '/tmp'):
            
            client = TestClient(app)
            
            # 创建一个有效的 WAV 头
            wav_header = b'RIFF' + b'\x24\x00\x00\x00' + b'WAVE' + b'fmt ' + \
                         b'\x10\x00\x00\x00' + b'\x01\x00\x01\x00' + \
                         b'\x80\x3e\x00\x00' + b'\x00\x7d\x00\x00' + \
                         b'\x02\x00\x10\x00' + b'data' + b'\x00\x00\x00\x00'
            
            response = client.post(
                "/v1/upload",
                files={"file": ("invalid.wav", wav_header, "audio/wav")}
            )

            # 业务失败应返回 5xx (Round 2 改为 raise HTTPException(500)),
            # 不再返回 200 + status="error"
            assert response.status_code >= 400
            assert "detail" in response.json()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
