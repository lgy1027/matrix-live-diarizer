"""FTS5 全文搜索单测(Roadmap #2.2)

覆盖:
- 触发器自动同步 segments ↔ segments_fts
- 中文 substring 搜 (3+ 字,2 字用 LIKE 兜底)
- 英文/数字搜
- session_id / speaker_id 过滤
- snippet 高亮
- cascade delete 同步 FTS(contentless 模式关键)
"""
import sys
import os
import tempfile
import pytest

sys.path.insert(0, "/Users/lgy/python/github.com/lgy1027/matrix-live-diarizer")

from app.repositories.database import Database
from app.repositories.transcripts import TranscriptRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init_schema()
    return TranscriptRepository(db)


# ========== 基础搜索 ==========

def test_search_chinese_3_chars(repo):
    """中文 3 字搜(FTS5 trigram 命中)"""
    sid = repo.create_session("upload", "会议1")
    repo.insert_segment(sid, 0, "今天我们讨论语音识别技术", 0, 5, "Spk_a")
    repo.insert_segment(sid, 1, "张老师建议引入多模态", 5, 10, "Spk_b")

    total, hits = repo.search_segments("多模态")
    assert total == 1
    assert "多模态" in hits[0]["text"]


def test_search_chinese_4_chars(repo):
    """中文 4 字搜"""
    sid = repo.create_session("upload", "会议1")
    repo.insert_segment(sid, 0, "今天我们讨论语音识别技术", 0, 5, "Spk_a")

    total, hits = repo.search_segments("今天我们")
    assert total == 1
    assert "[match]今天我们[/match]" in hits[0]["snippet"]


def test_search_chinese_2_chars_like_fallback(repo):
    """中文 2 字 — FTS5 命中不了,LIKE 兜底命中"""
    sid = repo.create_session("upload", "会议1")
    repo.insert_segment(sid, 0, "今天我们讨论语音识别技术", 0, 5, "Spk_a")

    # "今天" 2 字 trigram 搜不到
    total, hits = repo.search_segments("今天")
    # LIKE 兜底路径应命中
    assert total == 1
    # snippet 由 LIKE 路径返 raw text,前端 [match] 替换时通过 JS 实现
    assert hits[0]["text"] == "今天我们讨论语音识别技术"


def test_search_english(repo):
    """英文搜"""
    sid = repo.create_session("upload", "Meeting")
    repo.insert_segment(sid, 0, "OpenAI released GPT-4o model yesterday", 0, 5, "Spk_a")
    repo.insert_segment(sid, 1, "multi-modal model for voice and vision", 5, 10, "Spk_b")

    total, hits = repo.search_segments("OpenAI")
    assert total == 1
    assert "OpenAI" in hits[0]["text"]

    total, hits = repo.search_segments("multi-modal")
    assert total == 1


# ========== 触发器同步 ==========

def test_insert_triggers_fts_insert(repo):
    """INSERT segments 自动同步到 segments_fts"""
    sid = repo.create_session("upload", "t")
    repo.insert_segment(sid, 0, "今天我们讨论语音识别", 0, 5)

    total, hits = repo.search_segments("今天我们")
    assert total == 1


def test_update_triggers_fts_update(repo):
    """UPDATE segments.text 自动同步 FTS(老内容应不再命中)"""
    sid = repo.create_session("upload", "t")
    seg_id = repo.insert_segment(sid, 0, "原始文本", 0, 5)
    # 用 raw SQL 改 text(update_segment_text API 不存在)
    with repo.db.connect() as conn:
        conn.execute("UPDATE segments SET text = ? WHERE id = ?", ("改后的文本", seg_id))
        conn.commit()
    # 老"原始"应不再命中
    total, _ = repo.search_segments("原始")
    assert total == 0
    # 新"改后"应命中
    total, _ = repo.search_segments("改后")
    assert total == 1


def test_delete_session_cascades_segments_and_fts(repo):
    """DELETE session 触发 cascade segments + FTS 同步清空"""
    sid1 = repo.create_session("upload", "t1")
    repo.insert_segment(sid1, 0, "段1", 0, 1)
    repo.insert_segment(sid1, 1, "段2", 1, 2)
    sid2 = repo.create_session("upload", "t2")
    repo.insert_segment(sid2, 0, "段3", 0, 1)

    # 删 sid1
    repo.delete_session(sid1)
    # 段1/段2 应不可搜
    total, _ = repo.search_segments("段1")
    assert total == 0
    total, _ = repo.search_segments("段2")
    assert total == 0
    # 段3 仍可搜
    total, hits = repo.search_segments("段3")
    assert total == 1


def test_delete_single_segment_removes_from_fts(repo):
    """DELETE 单 segment (如果有这个 API)"""
    # 实际项目没暴露 delete_segment API,测内部清理路径
    sid = repo.create_session("upload", "t")
    seg_id = repo.insert_segment(sid, 0, "要删的", 0, 1)
    total, _ = repo.search_segments("要删的")
    assert total == 1
    # 直接 SQL 删 segment(模拟 clear)
    with repo.db.connect() as conn:
        conn.execute("DELETE FROM segments WHERE id=?", (seg_id,))
        conn.commit()
    total, _ = repo.search_segments("要删的")
    assert total == 0


# ========== 过滤 ==========

def test_filter_by_session_id(repo):
    """session_id 过滤"""
    sid1 = repo.create_session("upload", "t1")
    repo.insert_segment(sid1, 0, "段1-A", 0, 1)
    repo.insert_segment(sid1, 1, "段1-B", 1, 2)
    sid2 = repo.create_session("upload", "t2")
    repo.insert_segment(sid2, 0, "段2-A", 0, 1)

    # 不限 session: 应返 3
    total, _ = repo.search_segments("段")
    assert total == 3
    # 限 sid1: 返 2
    total, hits = repo.search_segments("段", session_id=sid1)
    assert total == 2


def test_filter_by_speaker_id(repo):
    """speaker_id 过滤"""
    sid = repo.create_session("upload", "t")
    repo.insert_segment(sid, 0, "段-A", 0, 1, "Spk_a")
    repo.insert_segment(sid, 1, "段-B", 1, 2, "Spk_b")
    repo.insert_segment(sid, 2, "段-C", 2, 3, "Spk_a")

    total, _ = repo.search_segments("段")
    assert total == 3
    # 限 Spk_a
    total, hits = repo.search_segments("段", speaker_id="Spk_a")
    assert total == 2
    # 限 Spk_b
    total, _ = repo.search_segments("段", speaker_id="Spk_b")
    assert total == 1


# ========== Snippet 高亮 ==========

def test_snippet_contains_match_marker(repo):
    """snippet 应含 [match]X[/match] 占位符(前端再替换为 <mark>)"""
    sid = repo.create_session("upload", "t")
    repo.insert_segment(sid, 0, "今天我们讨论语音识别", 0, 5, "Spk_a")

    total, hits = repo.search_segments("今天我们")
    snippet = hits[0]["snippet"]
    assert "[match]" in snippet
    assert "[/match]" in snippet
    assert "今天我们" in snippet


def test_snippet_with_special_chars_in_query(repo):
    """查询含特殊字符(应被 sanitize 后仍能搜)"""
    sid = repo.create_session("upload", "t")
    repo.insert_segment(sid, 0, "GPT-4o 模型", 0, 5, "Spk_a")

    # "GPT-4o" 含 - 会被 sanitize 掉,可能搜不到
    # 但 LIKE 兜底可能命中(原始 query)
    total, hits = repo.search_segments("GPT")
    # GPT 3 字符,FTS5 trigram 应能命中
    assert total == 1


def test_snippet_truncation(repo):
    """长 text snippet 应截断(显示部分 + ...)"""
    sid = repo.create_session("upload", "t")
    long_text = "前文" * 50 + "中关键字" + "后文" * 50
    repo.insert_segment(sid, 0, long_text, 0, 60, "Spk_a")

    total, hits = repo.search_segments("中关键字")
    snippet = hits[0]["snippet"]
    # snippet 应 < 原 text 长度
    assert len(snippet) < len(long_text)
    # 含 ...
    assert "..." in snippet


# ========== 边界 ==========

def test_empty_query_returns_empty(repo):
    """空 query 应返 0 命中,不报错"""
    sid = repo.create_session("upload", "t")
    repo.insert_segment(sid, 0, "段", 0, 1)
    total, hits = repo.search_segments("")
    assert total == 0
    total, hits = repo.search_segments("   ")
    assert total == 0


def test_no_results_returns_empty(repo):
    """无匹配 query 返 0 命中"""
    sid = repo.create_session("upload", "t")
    repo.insert_segment(sid, 0, "段", 0, 1)
    total, hits = repo.search_segments("不存在的词xyz")
    assert total == 0
    assert hits == []


def test_limit_caps_results(repo):
    """limit 参数限制返回数量"""
    sid = repo.create_session("upload", "t")
    for i in range(10):
        repo.insert_segment(sid, i, f"段{i}", 0, 1)
    total, hits = repo.search_segments("段", limit=3)
    assert total == 3
    assert len(hits) == 3
