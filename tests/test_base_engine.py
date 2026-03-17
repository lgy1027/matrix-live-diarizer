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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
