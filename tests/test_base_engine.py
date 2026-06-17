"""声纹引擎基类测试 - TDD"""
import pytest
from abc import ABC, abstractmethod
import numpy as np
import os


class TestSpeakerEngineBaseClass:
    """测试声纹引擎基类"""

    def test_base_class_exists(self):
        """测试基类存在"""
        from engine.speaker.base_engine import BaseSpeakerEngine
        
        # 应该是抽象类
        assert issubclass(BaseSpeakerEngine, ABC)

    def test_base_class_has_abstract_methods(self):
        """测试基类定义了抽象方法"""
        from engine.speaker.base_engine import BaseSpeakerEngine
        
        # 应该有这些抽象方法
        abstract_methods = BaseSpeakerEngine.__abstractmethods__
        assert 'extract_feat' in abstract_methods

    def test_base_class_has_shared_methods(self):
        """测试基类有共享方法"""
        from engine.speaker.base_engine import BaseSpeakerEngine
        
        # 这些方法应该有默认实现
        assert hasattr(BaseSpeakerEngine, 'list_speakers')
        assert hasattr(BaseSpeakerEngine, 'get_speaker')
        assert hasattr(BaseSpeakerEngine, 'rename_speaker')
        assert hasattr(BaseSpeakerEngine, 'delete_speaker')

    def test_campplus_inherits_base(self):
        """测试 CamPlus 引擎继承基类"""
        # 检查源码中是否有继承基类的代码
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "speaker", "campplus_engine.py"
        )
        with open(source_path, 'r') as f:
            source = f.read()
        # 检查类定义是否继承 BaseSpeakerEngine
        assert 'class CamPlusEngine(BaseSpeakerEngine)' in source, \
            "CamPlusEngine 应继承 BaseSpeakerEngine"

    def test_eres2net_inherits_base(self):
        """测试 ERes2Net 引擎继承基类"""
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "speaker", "eres2net_engine.py"
        )
        with open(source_path, 'r') as f:
            source = f.read()
        assert 'class ERes2NetEngine(BaseSpeakerEngine)' in source, \
            "ERes2NetEngine 应继承 BaseSpeakerEngine"

    def test_wespeaker_inherits_base(self):
        """测试 Wespeaker 引擎继承基类"""
        source_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "engine", "speaker", "wespeaker_engine.py"
        )
        with open(source_path, 'r') as f:
            source = f.read()
        assert 'class WespeakerEngine(BaseSpeakerEngine)' in source, \
            "WespeakerEngine 应继承 BaseSpeakerEngine"


class TestBaseEngineSharedMethods:
    """测试基类共享方法"""

    def test_list_speakers_signature(self):
        """测试 list_speakers 方法签名"""
        from engine.speaker.base_engine import BaseSpeakerEngine
        import inspect
        
        sig = inspect.signature(BaseSpeakerEngine.list_speakers)
        params = list(sig.parameters.keys())
        
        assert 'self' in params
        assert 'session_id' in params

    def test_get_speaker_signature(self):
        """测试 get_speaker 方法签名"""
        from engine.speaker.base_engine import BaseSpeakerEngine
        import inspect
        
        sig = inspect.signature(BaseSpeakerEngine.get_speaker)
        params = list(sig.parameters.keys())
        
        assert 'self' in params
        assert 'speaker_id' in params


@pytest.mark.parametrize(
    "engine_cls",
    [
        "CamPlusEngine",
        "ERes2NetEngine",
        "WespeakerEngine",
    ],
)
def test_compare_and_identify_returns_tuple_with_score(engine_cls):
    """回归测试:compare_and_identify 必须返回 (spk_id, score) tuple

    3 个引擎都要覆盖 — 抽象签名非运行时强制,缺一个就有回归风险。
    """
    from unittest.mock import MagicMock
    import numpy as np
    from engine.speaker.campplus_engine import CamPlusEngine
    from engine.speaker.eres2net_engine import ERes2NetEngine
    from engine.speaker.wespeaker_engine import WespeakerEngine

    cls_map = {
        "CamPlusEngine": CamPlusEngine,
        "ERes2NetEngine": ERes2NetEngine,
        "WespeakerEngine": WespeakerEngine,
    }
    target_cls = cls_map[engine_cls]

    # 用 __new__ 跳过 __init__(避免真模型加载),手动挂载最小化 mock attrs
    engine = target_cls.__new__(target_cls)
    engine.collection = MagicMock()
    # 模拟空 DB:query 返空 distances → 走"新建 Spk"路径(避免 deref best_meta MagicMock)
    engine.collection.query.return_value = {"distances": [[]], "ids": [[]], "metadatas": [[]]}
    engine.model = MagicMock()
    engine.chroma_client = MagicMock()
    engine._initialized = True
    # campplus / eres2net / wespeaker 共享这些 buffer 属性 — defaultdict 让新 client_id 自动建空 list
    from collections import defaultdict
    engine.emb_buffer = defaultdict(list)
    engine.match_history = defaultdict(list)
    engine.EMB_BUFFER_SIZE = 5
    engine.HISTORY_SIZE = 3
    emb = np.zeros(192, dtype=np.float32)
    client_id = f"test_client_returns_tuple_{engine_cls}"
    try:
        result = engine.compare_and_identify(emb, client_id, audio_duration=1.0)
        assert isinstance(result, tuple), f"{engine_cls}: 应返回 tuple,实际 {type(result)}"
        assert len(result) == 2, f"{engine_cls}: 应 2 元素,实际 {len(result)}"
        spk_id, score = result
        assert isinstance(spk_id, str), f"{engine_cls}: spk_id 应为 str,实际 {type(spk_id)}"
        assert isinstance(score, float), f"{engine_cls}: score 应为 float,实际 {type(score)}"
        assert 0.0 <= score <= 1.0, f"{engine_cls}: score 应在 [0,1],实际 {score}"
    finally:
        if hasattr(engine, "cleanup_client"):
            engine.cleanup_client(client_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
