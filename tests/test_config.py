"""配置模块测试"""
import pytest


def test_storage_config_defaults():
    from app.config import StorageConfig
    cfg = StorageConfig.from_env()
    assert cfg.db_path == "./data/matrix.db"
    assert cfg.history_enabled is True


def test_llm_config_defaults():
    from app.config import LLMConfig
    cfg = LLMConfig.from_env()
    assert cfg.enabled is False
    assert cfg.endpoint == "http://127.0.0.1:11434/v1"
    assert cfg.model == "qwen2.5:1.5b"
    assert cfg.timeout_sec == 60


def test_history_config_defaults():
    from app.config import HistoryConfig
    cfg = HistoryConfig.from_env()
    assert cfg.retention_days == 0  # 0 = 永久保留
    assert cfg.auto_archive is False
