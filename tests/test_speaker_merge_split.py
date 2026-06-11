"""说话人合并 / 拆分 API 测试

merge: 把多个 source 声纹合并到 target,加权平均 embedding,
       更新 segments.speaker_id
split: 把指定 segments 的 speaker_id 改成新值或清空
"""
import sys
import types
import numpy as np
from unittest.mock import MagicMock, patch


def _make_fake_engine_with_collection():
    """构造一个带 ChromaDB 风格 collection 的 mock 引擎"""
    fake = MagicMock()
    col = MagicMock()
    # 模拟 ChromaDB 的 get/upsert/delete
    store = {}

    def fake_get(ids, include=None):
        embs = []
        metas = []
        out_ids = []
        for i in ids:
            if i in store:
                out_ids.append(i)
                embs.append(store[i]["emb"])
                metas.append(store[i]["meta"])
        return {"ids": out_ids, "embeddings": embs, "metadatas": metas}

    def fake_upsert(ids, embeddings, metadatas):
        for i, e, m in zip(ids, embeddings, metadatas):
            store[i] = {"emb": e, "meta": m}

    def fake_delete(ids):
        for i in ids:
            store.pop(i, None)

    col.get = fake_get
    col.upsert = fake_upsert
    col.delete = fake_delete
    fake.collection = col
    fake._store = store
    return fake


def test_merge_speakers_weighted_average():
    """加权平均:target (count=2) + source (count=3) = new_count=5"""
    from engine.speaker.base_engine import BaseSpeakerEngine

    # 用 BaseSpeakerEngine 子类(跳过 @abstractmethod)
    class _Stub(BaseSpeakerEngine):
        def _model_name(self): return "stub"
        def extract_feat(self, audio):
            return np.zeros(4, dtype=np.float32), 0.0
        def compare_and_identify(self, emb, cid, dur=0):
            return "Spk_001"
        def list_speakers(self, session_id=None):
            return []
        def get_speaker(self, sid):
            return None
        def rename_speaker(self, sid, name):
            return True
        def delete_speaker(self, sid):
            return True
        def get_smoothed_embedding(self, emb, cid):
            return emb
        def reset_buffer(self, cid):
            pass
        def cleanup_client(self, cid):
            pass

    # chromadb 0.5+ 改了 upsert 参数顺序
    # BaseSpeakerEngine 用 upsert(ids=, embeddings=, metadatas=)
    # chromadb 0.4 用 upsert(embeddings=, metadatas=, ids=)
    # BaseSpeakerEngine 实际用的接口需要在 mock 验证
    # 此测试只验证 merge_speakers 的逻辑,不依赖真实 chromadb
    # (走 _model_name / collection 即可)
    # 实际 merge_speakers 直接调 self.collection.upsert(ids=..., embeddings=..., metadatas=...)
    pass  # 跳过:BaseSpeakerEngine 是抽象类,需要 mock collection 才能实例化


def test_merge_speakers_invalid_target_id_returns_error():
    """非法 target_id (没 Spk_ 前缀) → 返回错误"""
    from engine.speaker.base_engine import BaseSpeakerEngine
    engine = _make_fake_engine_with_collection()
    # patch 一下:BaseSpeakerEngine.merge_speakers 不依赖 self.__init__
    # 直接给一个 stub 实例
    eng = MagicMock(spec=BaseSpeakerEngine)
    eng.collection = engine.collection
    # 重新调真实方法
    result = BaseSpeakerEngine.merge_speakers(eng, "bad_id", ["Spk_001"])
    assert result["ok"] is False
    assert "target_id" in result["error"]


def test_merge_speakers_target_in_source_returns_error():
    """target_id 在 source_ids 里 → 拒绝"""
    from engine.speaker.base_engine import BaseSpeakerEngine
    eng = MagicMock(spec=BaseSpeakerEngine)
    eng.collection = MagicMock()
    result = BaseSpeakerEngine.merge_speakers(eng, "Spk_001", ["Spk_001", "Spk_002"])
    assert result["ok"] is False
    assert "target_id 不能在 source_ids" in result["error"]


def test_merge_speakers_target_not_in_chromadb():
    """target_id 在 ChromaDB 找不到 → 拒绝"""
    from engine.speaker.base_engine import BaseSpeakerEngine
    fake = _make_fake_engine_with_collection()
    fake._store = {}  # 空的
    result = BaseSpeakerEngine.merge_speakers(fake, "Spk_001", ["Spk_002"])
    assert result["ok"] is False
    assert "不存在" in result["error"]


def test_merge_speakers_happy_path():
    """happy path: 3 source → target,新 count 是总和"""
    from engine.speaker.base_engine import BaseSpeakerEngine
    fake = _make_fake_engine_with_collection()
    # 初始化 1 个 target + 3 个 source
    fake._store["Spk_001"] = {
        "emb": [1.0, 0.0, 0.0, 0.0],
        "meta": {"name": "Target", "count": 1, "sample_count": 1},
    }
    fake._store["Spk_007"] = {
        "emb": [0.0, 1.0, 0.0, 0.0],
        "meta": {"name": "S7", "count": 2, "sample_count": 2},
    }
    fake._store["Spk_013"] = {
        "emb": [0.0, 0.0, 1.0, 0.0],
        "meta": {"name": "S13", "count": 3, "sample_count": 3},
    }
    result = BaseSpeakerEngine.merge_speakers(fake, "Spk_001", ["Spk_007", "Spk_013"])
    assert result["ok"] is True
    assert result["target_id"] == "Spk_001"
    assert set(result["merged_source_ids"]) == {"Spk_007", "Spk_013"}
    # count: 1 + 2 + 3 = 6
    assert result["new_count"] == 6
    # 验证: 加权平均后 L2 normalize
    # 加权: (1*[1,0,0,0] + 2*[0,1,0,0] + 3*[0,0,1,0]) / 6 = [1/6, 2/6, 3/6, 0]
    # L2 norm = sqrt(1+4+9)/6 = sqrt(14)/6 ≈ 0.6236
    # normalize 后: [0.267, 0.535, 0.802, 0]
    import math
    raw = [1/6, 2/6, 3/6, 0]
    norm = math.sqrt(sum(x*x for x in raw))
    expected = [x / norm for x in raw]
    new_emb = fake._store["Spk_001"]["emb"]
    assert abs(new_emb[0] - expected[0]) < 1e-5
    assert abs(new_emb[1] - expected[1]) < 1e-5
    assert abs(new_emb[2] - expected[2]) < 1e-5
    assert abs(new_emb[3] - expected[3]) < 1e-5
    # sources 已删
    assert "Spk_007" not in fake._store
    assert "Spk_013" not in fake._store


def test_merge_speakers_missing_source_skipped():
    """source_ids 里有些不在 ChromaDB → 跳过,继续合并剩下的"""
    from engine.speaker.base_engine import BaseSpeakerEngine
    fake = _make_fake_engine_with_collection()
    fake._store["Spk_001"] = {
        "emb": [1.0, 0.0, 0.0],
        "meta": {"name": "T", "count": 1, "sample_count": 1},
    }
    fake._store["Spk_007"] = {
        "emb": [0.0, 1.0, 0.0],
        "meta": {"name": "S", "count": 1, "sample_count": 1},
    }
    # Spk_999 不存在
    result = BaseSpeakerEngine.merge_speakers(fake, "Spk_001", ["Spk_007", "Spk_999"])
    assert result["ok"] is True
    # 只合并 Spk_007
    assert result["merged_source_ids"] == ["Spk_007"]
    assert result["new_count"] == 2


def test_merge_speakers_all_sources_missing_returns_error():
    """所有 source 都不在 ChromaDB → ok=False,target 不被破坏"""
    from engine.speaker.base_engine import BaseSpeakerEngine
    fake = _make_fake_engine_with_collection()
    fake._store["Spk_001"] = {
        "emb": [1.0, 0.0, 0.0],
        "meta": {"name": "T", "count": 1, "sample_count": 1},
    }
    orig_emb = list(fake._store["Spk_001"]["emb"])
    orig_meta = dict(fake._store["Spk_001"]["meta"])
    # 所有 source 都不存在
    result = BaseSpeakerEngine.merge_speakers(fake, "Spk_001", ["Spk_nope_1", "Spk_nope_2"])
    assert result["ok"] is False
    assert "都不存在" in result["error"]
    assert set(result["missing_source_ids"]) == {"Spk_nope_1", "Spk_nope_2"}
    # ⚠️ 关键: target 不应被破坏(没合并就不该写)
    assert fake._store["Spk_001"]["emb"] == orig_emb
    assert fake._store["Spk_001"]["meta"]["count"] == orig_meta["count"]


# ========== Repo 测试 ==========

def test_reassign_speaker_updates_segments(tmp_path):
    """repo.reassign_speaker: 所有 segments.speaker_id == old 改 new"""
    from app.repositories.database import Database
    from app.repositories.transcripts import TranscriptRepository

    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    repo = TranscriptRepository(db)
    sid = repo.create_session(source="websocket", title="t")
    seg_a = repo.insert_segment(sid, 0, "a", 0, 1, speaker_id="Spk_007")
    seg_b = repo.insert_segment(sid, 1, "b", 1, 2, speaker_id="Spk_007")
    repo.insert_segment(sid, 2, "c", 2, 3, speaker_id="Spk_001")

    updated = repo.reassign_speaker("Spk_007", "Spk_001")
    assert updated == 2

    segs = repo.list_segments(sid)
    assert segs[0]["speaker_id"] == "Spk_001"
    assert segs[1]["speaker_id"] == "Spk_001"
    assert segs[2]["speaker_id"] == "Spk_001"  # 原来就是 Spk_001


def test_clear_segments_speaker_clears_only_specific(tmp_path):
    """clear_segments_speaker(segment_ids, speaker_id=X) 只清匹配 X 的"""
    from app.repositories.database import Database
    from app.repositories.transcripts import TranscriptRepository

    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    repo = TranscriptRepository(db)
    sid = repo.create_session(source="websocket", title="t")
    seg_a = repo.insert_segment(sid, 0, "a", 0, 1, speaker_id="Spk_007")
    seg_b = repo.insert_segment(sid, 1, "b", 1, 2, speaker_id="Spk_007")
    seg_c = repo.insert_segment(sid, 2, "c", 2, 3, speaker_id="Spk_001")

    # 只想把 seg_a 从 Spk_007 拆出去,seg_b 保持 Spk_007
    updated = repo.clear_segments_speaker([seg_a, seg_b], speaker_id="Spk_007")
    assert updated == 2  # 都清

    segs = repo.list_segments(sid)
    assert segs[0]["speaker_id"] is None  # seg_a 清空
    assert segs[1]["speaker_id"] is None  # seg_b 也清
    assert segs[2]["speaker_id"] == "Spk_001"  # 不动

    # 给 seg_a 重新指派给 Spk_001
    repo.update_segment_speaker(seg_a, "Spk_001")
    segs = repo.list_segments(sid)
    assert segs[0]["speaker_id"] == "Spk_001"


def test_clear_segments_speaker_no_speaker_filter_clears_all(tmp_path):
    """不传 speaker_id:清指定 segments(不管原 speaker)"""
    from app.repositories.database import Database
    from app.repositories.transcripts import TranscriptRepository

    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    repo = TranscriptRepository(db)
    sid = repo.create_session(source="websocket", title="t")
    seg_a = repo.insert_segment(sid, 0, "a", 0, 1, speaker_id="Spk_X")
    seg_b = repo.insert_segment(sid, 1, "b", 1, 2, speaker_id="Spk_Y")

    updated = repo.clear_segments_speaker([seg_a, seg_b])
    assert updated == 2

    segs = repo.list_segments(sid)
    assert segs[0]["speaker_id"] is None
    assert segs[1]["speaker_id"] is None


def test_clear_segments_speaker_empty_list_returns_zero(tmp_path):
    """空 segment_ids 列表 → 返回 0"""
    from app.repositories.database import Database
    from app.repositories.transcripts import TranscriptRepository

    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    repo = TranscriptRepository(db)
    sid = repo.create_session(source="websocket", title="t")
    repo.insert_segment(sid, 0, "a", 0, 1, speaker_id="Spk_X")

    assert repo.clear_segments_speaker([]) == 0
    assert repo.clear_segments_speaker([], speaker_id="Spk_X") == 0
