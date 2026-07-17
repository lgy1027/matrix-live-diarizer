"""配置模块测试"""


def test_storage_config_defaults():
    from app.config import StorageConfig
    cfg = StorageConfig.from_env()
    assert cfg.db_path == "./data/matrix.db"


def test_llm_config_defaults():
    from app.config import LLMConfig
    cfg = LLMConfig.from_env()
    assert cfg.enabled is False
    assert cfg.endpoint == "http://127.0.0.1:11434/v1"
    assert cfg.model == "qwen2.5:1.5b"
    assert cfg.timeout_sec == 60


def test_deployment_config_defaults_to_local():
    from app.config import DeploymentConfig
    cfg = DeploymentConfig.from_env()
    assert cfg.mode == "local"


def test_server_defaults_to_loopback(monkeypatch):
    from app.config import ServerConfig
    monkeypatch.delenv("HOST", raising=False)
    assert ServerConfig.from_env().host == "127.0.0.1"


def test_deployment_config_reads_known_mode(monkeypatch):
    from app.config import DeploymentConfig
    monkeypatch.setenv("DEPLOYMENT_MODE", "LAN")
    cfg = DeploymentConfig.from_env()
    assert cfg.mode == "lan"


def test_llm_config_reads_env(monkeypatch):
    from app.config import LLMConfig
    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setenv("LLM_MODEL", "llama3:8b")
    monkeypatch.setenv("LLM_TIMEOUT_SEC", "120")
    cfg = LLMConfig.from_env()
    assert cfg.enabled is True
    assert cfg.model == "llama3:8b"
    assert cfg.timeout_sec == 120


def test_llm_allowed_hosts_from_env(monkeypatch):
    from app.config import LLMConfig
    monkeypatch.setenv("LLM_ALLOWED_HOSTS", "127.0.0.1,192.168.1.5,::1")
    cfg = LLMConfig.from_env()
    assert cfg.allowed_hosts == ("127.0.0.1", "192.168.1.5", "::1")


def test_appconfig_load_includes_new_blocks():
    from app.config import AppConfig, StorageConfig, LLMConfig, DeploymentConfig
    cfg = AppConfig.load()
    assert isinstance(cfg.storage, StorageConfig)
    assert isinstance(cfg.llm, LLMConfig)
    assert isinstance(cfg.deployment, DeploymentConfig)


def test_invalid_pyannote_device_falls_back_to_auto(monkeypatch):
    from app.config import SpeakerConfig

    monkeypatch.setenv("PYANNOTE_DEVICE", "metal")

    assert SpeakerConfig.from_env().diarization_device == "auto"
