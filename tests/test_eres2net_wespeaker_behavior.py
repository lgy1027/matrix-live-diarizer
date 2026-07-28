"""ERes2Net / Wespeaker 行为级回归测试

目的:为引擎合并到 base_engine 的重构锁定当前行为基线。
合并前跑这套测试必须全绿(锁基线);合并后再跑同一套测试,全绿即证明行为不变。

不加载真模型(modelscope/torch 太重),用 `__new__` 跳过 __init__,
手动挂载最小 mock 属性,跟 test_speaker_threshold.py 同套路。
覆盖 compare_and_identify 的四条核心分支 + _get_dynamic_threshold 阈值锁值 +
extract_feat 归一化契约。
"""
import os
import sys
from collections import defaultdict
from unittest.mock import MagicMock

import numpy as np
import pytest

# conftest 在 collection 阶段可能把 fake 写进 sys.modules,清掉让 import 走真实代码
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _fake in (
    "engine",
    "engine.speaker",
    "engine.speaker.base_engine",
    "engine.speaker.speaker_factory",
    "engine.speaker.eres2net_engine",
    "engine.speaker.wespeaker_engine",
):
    sys.modules.pop(_fake, None)

from engine.speaker.eres2net_engine import ERes2NetEngine
from engine.speaker.wespeaker_engine import WespeakerEngine


# 两个引擎的阈值 profile(锁值,合并后抽成 THRESHOLD_PROFILE 也要保持这些数)
# (reliable_low, reliable_high, unreliable_low, unreliable_high)
THRESHOLD_PROFILES = {
    "ERes2NetEngine": (0.38, 0.48, 0.48, 0.58),
    "WespeakerEngine": (0.44, 0.54, 0.54, 0.64),
}
EMB_DIM = {
    "ERes2NetEngine": 192,
    "WespeakerEngine": 256,
}


def _make_engine_mock(engine_cls):
    """构造不加载模型、但运行期状态完整的引擎实例。"""
    eng = engine_cls.__new__(engine_cls)
    eng.model = MagicMock()
    eng.collection = MagicMock()
    eng.chroma_client = MagicMock()
    eng.emb_buffer = defaultdict(list)
    eng.match_history = defaultdict(list)
    eng.EMB_BUFFER_SIZE = 5
    eng.HISTORY_SIZE = 3
    return eng


@pytest.mark.parametrize("engine_cls", [ERes2NetEngine, WespeakerEngine], ids=lambda c: c.__name__)
class TestGetDynamicThreshold:
    """_get_dynamic_threshold 阈值锁值 — 合并后读 THRESHOLD_PROFILE 也要保持。"""

    def test_reliable_base_values(self, engine_cls):
        """可靠段(count=0,无 adjustment)的 low/high 基值。"""
        eng = _make_engine_mock(engine_cls)
        low, high = eng._get_dynamic_threshold(count=0, is_reliable=True)
        exp_low, exp_high, _, _ = THRESHOLD_PROFILES[engine_cls.__name__]
        assert low == pytest.approx(exp_low)
        assert high == pytest.approx(exp_high)

    def test_unreliable_base_values(self, engine_cls):
        """非可靠段用更宽松阈值。"""
        eng = _make_engine_mock(engine_cls)
        low, high = eng._get_dynamic_threshold(count=0, is_reliable=False)
        _, _, exp_low, exp_high = THRESHOLD_PROFILES[engine_cls.__name__]
        assert low == pytest.approx(exp_low)
        assert high == pytest.approx(exp_high)

    def test_adjustment_grows_with_count_capped(self, engine_cls):
        """adjustment = min(0.05, count*0.005),count=100 封顶 0.05。"""
        eng = _make_engine_mock(engine_cls)
        exp_low, _, _, _ = THRESHOLD_PROFILES[engine_cls.__name__]
        low_small = eng._get_dynamic_threshold(count=1, is_reliable=True)[0]
        low_big = eng._get_dynamic_threshold(count=100, is_reliable=True)[0]
        assert low_small == pytest.approx(exp_low + 0.005)
        assert low_big == pytest.approx(exp_low + 0.05)  # 封顶


@pytest.mark.parametrize("engine_cls", [ERes2NetEngine, WespeakerEngine], ids=lambda c: c.__name__)
class TestCompareAndIdentify:
    """compare_and_identify 四条核心分支。use_buffer=False 跳过平滑,直接用传入 emb。"""

    def _query_result(self, dist, spk_id="Spk_existing", count=1):
        return {
            "distances": [[dist]],
            "ids": [[spk_id]],
            "metadatas": [[{"session_id": "c1", "count": count}]],
        }

    def _get_result(self, emb):
        return {"ids": ["Spk_existing"], "embeddings": [emb.tolist()]}

    def test_none_embedding_returns_unknown(self, engine_cls):
        """embedding=None 第一行返回 ('Spk_unknown', 0.0),不触 DB。"""
        eng = _make_engine_mock(engine_cls)
        spk, score = eng.compare_and_identify(None, "c1", audio_duration=5.0)
        assert spk == "Spk_unknown"
        assert score == 0.0
        eng.collection.query.assert_not_called()

    def test_high_confidence_match_returns_best_id(self, engine_cls):
        """min_dist < low_threshold → 返回 best_id,score=1-dist,update mean(weight=0.12 路径)。"""
        eng = _make_engine_mock(engine_cls)
        dim = EMB_DIM[engine_cls.__name__]
        emb = np.random.rand(dim).astype(np.float32)
        eng.collection.query.return_value = self._query_result(dist=0.20)
        eng.collection.get.return_value = self._get_result(emb)

        spk, score = eng.compare_and_identify(
            emb, "c1", audio_duration=2.0, use_buffer=False
        )
        assert spk == "Spk_existing"
        assert score == pytest.approx(0.80)  # 1 - 0.20
        # 高置信度走 update(更新质心),不走 add
        eng.collection.update.assert_called_once()
        eng.collection.add.assert_not_called()

    def test_edge_match_confirmed_by_count_returns_best_id(self, engine_cls):
        """min_dist 在 [low, high) 且 count>=2 → 边缘确认返回 best_id(weight=0.08 路径)。

        count=2 触发 MIN_SAMPLES_FOR_EDGE=2 的确认分支,无需历史连续。
        """
        eng = _make_engine_mock(engine_cls)
        dim = EMB_DIM[engine_cls.__name__]
        emb = np.random.rand(dim).astype(np.float32)
        # count=2 → adjustment=0.01 → reliable low=base+0.01,high=base+0.01
        # 取一个明显在 [low, high) 区间的距离
        exp_low, exp_high, _, _ = THRESHOLD_PROFILES[engine_cls.__name__]
        mid = (exp_low + 0.01 + exp_high + 0.01) / 2  # 落在调整后区间中点
        eng.collection.query.return_value = self._query_result(dist=mid, count=2)
        eng.collection.get.return_value = self._get_result(emb)

        spk, score = eng.compare_and_identify(
            emb, "c1", audio_duration=2.0, use_buffer=False
        )
        assert spk == "Spk_existing"
        assert score == pytest.approx(1 - mid)
        eng.collection.update.assert_called_once()
        eng.collection.add.assert_not_called()

    def test_edge_match_pending_no_confirmation_creates_new(self, engine_cls):
        """min_dist 在 [low, high) 但 count<2 且无连续历史 → 不确认,落到新建。"""
        eng = _make_engine_mock(engine_cls)
        dim = EMB_DIM[engine_cls.__name__]
        emb = np.random.rand(dim).astype(np.float32)
        exp_low, exp_high, _, _ = THRESHOLD_PROFILES[engine_cls.__name__]
        mid = (exp_low + exp_high) / 2  # count=0 区间中点
        eng.collection.query.return_value = self._query_result(dist=mid, count=1)
        eng.collection.get.return_value = self._get_result(emb)

        spk, score = eng.compare_and_identify(
            emb, "c1", audio_duration=2.0, use_buffer=False
        )
        # 未确认 → 新建 Spk_*,score=1-mid
        assert spk.startswith("Spk_")
        assert spk != "Spk_existing"
        assert score == pytest.approx(1 - mid)
        eng.collection.add.assert_called_once()

    def test_no_match_creates_new_speaker(self, engine_cls):
        """min_dist >= high_threshold → 不匹配,新建,score=1-dist。"""
        eng = _make_engine_mock(engine_cls)
        dim = EMB_DIM[engine_cls.__name__]
        emb = np.random.rand(dim).astype(np.float32)
        eng.collection.query.return_value = self._query_result(dist=0.90, count=1)
        eng.collection.get.return_value = self._get_result(emb)

        spk, score = eng.compare_and_identify(
            emb, "c1", audio_duration=2.0, use_buffer=False
        )
        assert spk.startswith("Spk_")
        assert spk != "Spk_existing"
        assert score == pytest.approx(0.10)  # 1 - 0.90
        eng.collection.add.assert_called_once()
        eng.collection.update.assert_not_called()

    def test_negative_score_clamped_to_zero(self, engine_cls):
        """cosine distance 可 >1(差异大说话人),score=1-dist 会为负,clamp 到 0.0。

        回归:docstring 契约 score ∈ [0,1],负数会持久化到 transcript_segments.confidence。
        """
        eng = _make_engine_mock(engine_cls)
        dim = EMB_DIM[engine_cls.__name__]
        emb = np.random.rand(dim).astype(np.float32)
        # dist=1.3 → 1-1.3 = -0.3,clamp 后应为 0.0(走不匹配新建路径)
        eng.collection.query.return_value = self._query_result(dist=1.30, count=1)
        eng.collection.get.return_value = self._get_result(emb)

        spk, score = eng.compare_and_identify(
            emb, "c1", audio_duration=2.0, use_buffer=False
        )
        assert spk.startswith("Spk_")
        assert score == 0.0  # clamp,不出现 -0.3

    def test_high_confidence_score_not_clamped(self, engine_cls):
        """dist 在正常范围(0.2)时 clamp 不影响 score=0.8。"""
        eng = _make_engine_mock(engine_cls)
        dim = EMB_DIM[engine_cls.__name__]
        emb = np.random.rand(dim).astype(np.float32)
        eng.collection.query.return_value = self._query_result(dist=0.20, count=1)
        eng.collection.get.return_value = self._get_result(emb)
        _, score = eng.compare_and_identify(
            emb, "c1", audio_duration=2.0, use_buffer=False
        )
        assert score == pytest.approx(0.80)

    def test_empty_db_creates_new_speaker_zero_score(self, engine_cls):
        """空 DB(distances 空)→ 新建,score=0.0(无候选时 min_dist=None)。"""
        eng = _make_engine_mock(engine_cls)
        dim = EMB_DIM[engine_cls.__name__]
        emb = np.random.rand(dim).astype(np.float32)
        eng.collection.query.return_value = {
            "distances": [[]],
            "ids": [[]],
            "metadatas": [[]],
        }

        spk, score = eng.compare_and_identify(
            emb, "c1", audio_duration=2.0, use_buffer=False
        )
        assert spk.startswith("Spk_")
        assert score == 0.0
        eng.collection.add.assert_called_once()


@pytest.mark.parametrize("engine_cls", [ERes2NetEngine, WespeakerEngine], ids=lambda c: c.__name__)
class TestExtractFeat:
    """extract_feat 异常契约 — 任何内部异常返回 (None, 0) 不向上抛。

    正常路径依赖真 torch(modelscope 太重,CI 用 fake),不在此测;
    其逻辑逐字相同且极简(构造张量→model→归一化),合并时靠逐行对照保证。
    """

    def test_extract_exception_returns_none_zero(self, engine_cls):
        """模型/torch 路径抛异常 → 返回 (None, 0),不向上抛。"""
        eng = _make_engine_mock(engine_cls)
        eng.model.side_effect = RuntimeError("boom")
        emb, dur = eng.extract_feat(np.zeros(16000, dtype=np.float32))
        assert emb is None
        assert dur == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
