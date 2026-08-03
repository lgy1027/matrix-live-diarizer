"""ExtractiveSummarizer 测试 — TextRank 兜底摘要 / 行动项 / 纪要生成器"""
import pytest
from app.services.extractive_summary import ExtractiveSummarizer


def test_summarize_short_text_returns_first_sentences():
    """短文本(< 3 段)走兜底:取前 N 段"""
    summarizer = ExtractiveSummarizer()
    segs = [{"text": "第一段。张三说。"}, {"text": "第二段。李四说。"}]
    result = summarizer.summarize(segs, max_sentences=3)
    assert "第一段" in result
    assert "第二段" in result


def test_summarize_chinese_works():
    """中文转写可以抽摘要"""
    summarizer = ExtractiveSummarizer(language="chinese")
    segs = [
        {"text": "今天讨论产品方向。张三说要做 A 方案。"},
        {"text": "李四认为 B 方案更好。需要更多数据支持。"},
        {"text": "张三同意下周做用户调研。李四负责分析数据。"},
    ]
    result = summarizer.summarize(segs, max_sentences=2)
    assert len(result) > 0
    assert isinstance(result, str)


def test_action_items_finds_keywords_zh():
    """中文行动项关键词识别"""
    summarizer = ExtractiveSummarizer()
    segs = [
        {"text": "张三需要在下周完成报告。"},
        {"text": "李四应该跟进客户反馈。"},
        {"text": "今天天气很好。"},
    ]
    items = summarizer.extract_action_items(segs)
    assert len(items) >= 2
    assert any("下周" in i for i in items)


def test_action_items_finds_keywords_en():
    """英文行动项关键词识别"""
    summarizer = ExtractiveSummarizer()
    segs = [
        {"text": "We need to ship this by Friday."},
        {"text": "The weather is nice today."},
        {"text": "TODO: update documentation."},
    ]
    items = summarizer.extract_action_items(segs)
    assert len(items) >= 2


def test_minutes_contains_three_sections():
    """纪要包含议题/决议/行动项三节"""
    summarizer = ExtractiveSummarizer()
    segs = [
        {"text": "今天讨论产品方向。"},
        {"text": "张三需要做用户调研。"},
    ]
    minutes = summarizer.generate_minutes(segs)
    assert "议题" in minutes
    assert "决议" in minutes
    assert "行动项" in minutes


def test_handles_empty_segments():
    """空段落不挂"""
    summarizer = ExtractiveSummarizer()
    assert summarizer.summarize([]) != ""
    assert summarizer.extract_action_items([]) == []
    assert "议题" in summarizer.generate_minutes([])


def test_short_transcript_returns_honest_nonempty_summary():
    summarizer = ExtractiveSummarizer()

    summary = summarizer.summarize([{"text": "请登录控制面板，输入。"}])

    assert "本地摘要不可用" not in summary
    assert "请登录控制面板" in summary
    assert "文稿内容较少" in summary


def test_minutes_do_not_repeat_topic_as_an_invented_decision():
    summarizer = ExtractiveSummarizer()

    minutes = summarizer.generate_minutes([{"text": "请登录控制面板，输入。"}])

    assert minutes.count("请登录控制面板") == 1
    assert "未识别到明确决议" in minutes
    assert "未识别到明确行动项" in minutes


def test_minutes_extract_explicit_decision_only():
    summarizer = ExtractiveSummarizer()
    segments = [
        {"text": "今天讨论发布计划。"},
        {"text": "会议决定周五发布。"},
        {"text": "小王负责准备发布说明。"},
    ]

    minutes = summarizer.generate_minutes(segments)

    assert "会议决定周五发布" in minutes
    assert "小王负责准备发布说明" in minutes


# ========== summa 1.2.0 API 兼容 ==========

def test_summarize_works_with_summa_words_api(monkeypatch):
    """summa 1.2.0 API 是 words/ratio 不是 sentences,代码必须用新 API"""
    from app.services import extractive_summary as es_mod

    called = {}

    def fake_summarize(text, words=None, language=None, **_):
        called["words"] = words
        called["language"] = language
        return "fake summary text"

    fake_summarizer = type("FakeSumma", (), {"summarize": staticmethod(fake_summarize)})
    monkeypatch.setitem(__import__("sys").modules, "summa", type("FakeSummaMod", (), {"summarizer": fake_summarizer}))
    # 也 patch 内部 from summa import summarizer as textrank
    monkeypatch.setattr(es_mod.textrank if hasattr(es_mod, "textrank") else es_mod, "textrank", fake_summarizer, raising=False)

    # 简单构造
    summarizer = es_mod.ExtractiveSummarizer()
    segs = [
        {"text": "第一段。张三说。"},
        {"text": "第二段。李四说。"},
        {"text": "第三段。王五说。"},
        {"text": "第四段。赵六说。"},
    ]
    result = summarizer.summarize(segs, max_sentences=3)
    assert "fake summary" in result


def test_summarize_uses_english_fallback_for_unsupported_language():
    """chinese 等 summa 不支持的语言应映射到 english,不抛错"""
    from app.services import extractive_summary as es_mod
    summarizer = es_mod.ExtractiveSummarizer(language="chinese")
    assert summarizer._summa_language == "english"
    # 也测日文、韩文
    for lang in ["japanese", "korean", "chinese_traditional"]:
        s = es_mod.ExtractiveSummarizer(language=lang)
        assert s._summa_language == "english"


def test_summarize_does_not_raise_on_unsupported_language_long_text():
    """长文本 + chinese language 不应抛错(走前 N 句兜底)"""
    summarizer = ExtractiveSummarizer(language="chinese")
    segs = [
        {"text": "今天讨论 A。张三说 A 好。"},
        {"text": "李四说 A 不行。"},
        {"text": "王五认为要改 B 方案。"},
        {"text": "整体决议:先用 A,B 留作下个版本。"},
    ]
    # 不应抛 ValueError("Valid languages are: ...")
    result = summarizer.summarize(segs, max_sentences=2)
    assert len(result) > 0
