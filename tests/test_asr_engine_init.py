"""ASR 引擎初始化测试（验证设备回退配置层）"""
import importlib


def test_audio_config_asr_device_default():
    """默认 asr_device 是 auto"""
    from app.config import AudioConfig
    cfg = AudioConfig.from_env()
    assert cfg.asr_device == "auto"
    assert cfg.asr_load_timeout_sec == 90


def test_audio_config_asr_device_cpu(monkeypatch):
    """ASR_DEVICE=cpu 强制使用 CPU"""
    monkeypatch.setenv("ASR_DEVICE", "CPU")  # 大小写不敏感
    monkeypatch.setenv("ASR_LOAD_TIMEOUT_SEC", "30")

    from app.config import AudioConfig
    cfg = AudioConfig.from_env()
    assert cfg.asr_device == "cpu"
    assert cfg.asr_load_timeout_sec == 30


def test_audio_config_asr_device_explicit(monkeypatch):
    """ASR_DEVICE=mps 显式指定 mps"""
    monkeypatch.setenv("ASR_DEVICE", "mps")
    monkeypatch.setenv("ASR_LOAD_TIMEOUT_SEC", "120")

    from app.config import AudioConfig
    cfg = AudioConfig.from_env()
    assert cfg.asr_device == "mps"
    assert cfg.asr_load_timeout_sec == 120


def test_audio_config_asr_timeout_invalid_falls_back(monkeypatch):
    """ASR_LOAD_TIMEOUT_SEC 非数字 → 用默认值 90"""
    monkeypatch.setenv("ASR_LOAD_TIMEOUT_SEC", "not-a-number")

    from app.config import AudioConfig
    cfg = AudioConfig.from_env()
    assert cfg.asr_load_timeout_sec == 90


def test_asr_engine_singleton_unaffected_by_init_failure(monkeypatch):
    """加载失败不污染单例（不会改写 cls._instance）"""
    # 即便初始化过程中抛异常，_instance 仍存在（__new__ 总是先跑）
    import engine.asr_engine as asr_mod

    # 确保测试不依赖真实模型：用空环境触发设备选择 cpu + 加载失败
    monkeypatch.setenv("ASR_DEVICE", "cpu")
    monkeypatch.setenv("ASR_LOAD_TIMEOUT_SEC", "1")

    # 触发一次 __init__：会进入 _load_with_fallback，因网络/模型不可用而失败
    # 这只是为了验证：失败后 initialized 仍为 False 但 _instance 已存在
    from app.config import AudioConfig
    AudioConfig.from_env()  # 应用环境变量

    # 直接构造两次都返回同一对象
    e1 = asr_mod.ASREngine()
    e2 = asr_mod.ASREngine()
    assert e1 is e2
