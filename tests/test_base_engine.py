"""声纹引擎基类测试 - TDD"""
import pytest
import inspect
from abc import ABC, abstractmethod
import numpy as np
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


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

    def test_base_class_has_runtime_cluster_methods_only(self):
        """基类只暴露运行期聚类能力，不承担持久化人物 CRUD。"""
        from engine.speaker.base_engine import BaseSpeakerEngine

        assert hasattr(BaseSpeakerEngine, 'query_session_candidates')
        assert hasattr(BaseSpeakerEngine, 'cleanup_client')
        for removed in ('list_speakers', 'get_speaker', 'rename_speaker',
                        'delete_speaker', 'add_speaker', 'merge_speakers'):
            assert not hasattr(BaseSpeakerEngine, removed)

    def test_campplus_inherits_base(self):
        """测试 CamPlus 引擎继承基类"""
        # 检查源码中是否有继承基类的代码
        source_path = REPO_ROOT / "engine" / "speaker" / "campplus_engine.py"
        source = source_path.read_text(encoding="utf-8")
        # 检查类定义是否继承 BaseSpeakerEngine
        assert 'class CamPlusEngine(BaseSpeakerEngine)' in source, \
            "CamPlusEngine 应继承 BaseSpeakerEngine"

    def test_eres2net_inherits_base(self):
        """测试 ERes2Net 引擎继承基类"""
        source_path = REPO_ROOT / "engine" / "speaker" / "eres2net_engine.py"
        source = source_path.read_text(encoding="utf-8")
        assert 'class ERes2NetEngine(BaseSpeakerEngine)' in source, \
            "ERes2NetEngine 应继承 BaseSpeakerEngine"

    def test_wespeaker_inherits_base(self):
        """测试 Wespeaker 引擎继承基类"""
        source_path = REPO_ROOT / "engine" / "speaker" / "wespeaker_engine.py"
        source = source_path.read_text(encoding="utf-8")
        assert 'class WespeakerEngine(BaseSpeakerEngine)' in source, \
            "WespeakerEngine 应继承 BaseSpeakerEngine"


class TestBaseEngineSharedMethods:
    """测试基类共享方法"""

    def test_query_candidates_is_scoped_to_current_meeting(self):
        """Chroma 查询必须只命中当前会议的匿名聚类。"""
        from unittest.mock import MagicMock
        from engine.speaker.base_engine import BaseSpeakerEngine

        class FakeEngine(BaseSpeakerEngine):
            def extract_feat(self, audio_data):
                return audio_data, 1.0

            def compare_and_identify(
                self, current_emb, client_id, audio_duration=0,
                use_buffer=True, default_name=None,
            ):
                return "Unknown", 0.0

            @property
            def _model_name(self):
                return "Fake"

        engine = FakeEngine()
        engine.collection = MagicMock()

        expected = {
            "ids": [["Spk_session"]],
            "distances": [[0.22]],
            "metadatas": [[{"session_id": "meeting-1", "count": 2}]],
        }
        engine.collection.query.return_value = expected

        result = engine.query_session_candidates([0.1, 0.2], "meeting-1")

        assert result == expected
        engine.collection.query.assert_called_once_with(
            query_embeddings=[[0.1, 0.2]],
            n_results=3,
            where={"session_id": "meeting-1"},
        )

    def test_cleanup_deletes_ephemeral_clusters_for_meeting(self):
        from collections import defaultdict
        from unittest.mock import MagicMock
        from engine.speaker.base_engine import BaseSpeakerEngine

        class FakeEngine(BaseSpeakerEngine):
            def extract_feat(self, audio_data):
                return audio_data, 1.0

            def compare_and_identify(self, current_emb, client_id, audio_duration=0,
                                     use_buffer=True, default_name=None):
                return "Unknown", 0.0

            @property
            def _model_name(self):
                return "Fake"

        engine = FakeEngine()
        engine.collection = MagicMock()
        engine.emb_buffer = defaultdict(list, {"meeting-1": [[0.1]]})

        engine.cleanup_client("meeting-1")

        assert "meeting-1" not in engine.emb_buffer
        engine.collection.delete.assert_called_once_with(
            where={"session_id": "meeting-1"}
        )


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
    engine.pending_speakers = defaultdict(list)
    engine.match_history = defaultdict(list)
    engine.EMB_BUFFER_SIZE = 5
    engine.PENDING_THRESHOLD = 3
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


@pytest.mark.parametrize(
    "engine_cls",
    ["CamPlusEngine", "ERes2NetEngine", "WespeakerEngine"],
)
def test_compare_and_identify_supports_common_contract(engine_cls):
    """所有可热切换引擎必须接受上传路径使用的公共参数。"""
    from engine.speaker.campplus_engine import CamPlusEngine
    from engine.speaker.eres2net_engine import ERes2NetEngine
    from engine.speaker.wespeaker_engine import WespeakerEngine

    target_cls = {
        "CamPlusEngine": CamPlusEngine,
        "ERes2NetEngine": ERes2NetEngine,
        "WespeakerEngine": WespeakerEngine,
    }[engine_cls]
    parameters = inspect.signature(target_cls.compare_and_identify).parameters

    assert "use_buffer" in parameters
    assert parameters["use_buffer"].default is True
    assert "default_name" in parameters
    assert parameters["default_name"].default is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
