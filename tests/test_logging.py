"""日志规范化测试 - TDD"""
import pytest
import logging
from unittest.mock import Mock, patch
import io
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class TestLoggingStandard:
    """测试日志规范化"""

    def test_engines_import_logging_module(self):
        """测试引擎导入日志模块"""
        source_path = REPO_ROOT / "engine" / "speaker" / "campplus_engine.py"
        source = source_path.read_text(encoding="utf-8")
        
        # 检查是否导入了 logging 模块
        # 渐进式重构：允许现有 print，但要求有日志基础设施
        has_logging_import = 'import logging' in source or 'from logging' in source
        assert has_logging_import, "引擎应导入 logging 模块"

    def test_logger_instance_exists(self):
        """测试 logger 实例存在"""
        from engine.speaker.base_engine import logger as base_logger
        
        assert base_logger is not None
        assert isinstance(base_logger, logging.Logger)

    def test_logger_name_format(self):
        """测试 logger 名称格式"""
        from engine.speaker.base_engine import logger as base_logger
        
        # logger 名称应该有意义
        assert "Matrix" in base_logger.name or "speaker" in base_logger.name.lower() or "engine" in base_logger.name.lower()

    def test_log_level_can_be_configured(self):
        """测试日志级别可配置"""
        # 创建一个临时 logger 测试
        test_logger = logging.getLogger("test_matrix")
        original_level = test_logger.level
        
        # 设置级别
        test_logger.setLevel(logging.DEBUG)
        assert test_logger.level == logging.DEBUG
        
        # 恢复
        test_logger.setLevel(original_level)


class TestLoggingOutput:
    """测试日志输出"""

    def test_error_logging_includes_context(self):
        """测试错误日志包含上下文"""
        from app.exceptions import AudioProcessingError
        
        # 创建错误
        error = AudioProcessingError("处理失败", audio_duration=10.5, sample_rate=16000)
        
        # 错误信息应该包含上下文
        error_str = str(error)
        assert "处理失败" in error_str

    def test_base_engine_logging_methods(self):
        """测试基类引擎有日志方法"""
        from engine.speaker.base_engine import BaseSpeakerEngine
        
        # 基类应该有 logger 属性
        # 由于是抽象类，我们检查类定义
        import inspect
        source = inspect.getsource(BaseSpeakerEngine)
        
        # 应该使用 logger 而非 print
        assert 'logger.' in source or 'logging' in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
