"""SessionContext 增量文本提取测试

测核心:
- 4 个 case:新含旧 / 旧含新 / 重叠后缀前缀 / 完全不相关
- 标准化:标点不影响去重
- last_output_text 防重复输出

对应 app/services/session.py
"""
import sys

from app.services.session import SessionContext


def test_first_text_returns_as_is():
    """首次调用:直接返回"""
    ctx = SessionContext("c1")
    out = ctx.get_incremental_text("你好世界")
    assert out == "你好世界"


def test_empty_new_text_returns_empty():
    """空文本不输出"""
    ctx = SessionContext("c1")
    assert ctx.get_incremental_text("") == ""


def test_punctuation_normalized():
    """标点不影响匹配:旧"你好" + 新"你好,世界" → 输出",世界" """
    ctx = SessionContext("c1")
    assert ctx.get_incremental_text("你好") == "你好"
    out = ctx.get_incremental_text("你好,世界")
    # 增量从位置 2 开始(标点保留): ",世界"  或  "，世界"
    assert "世界" in out, f"应包含'世界',实际 {out!r}"


def test_new_contains_old_extracts_tail():
    """新文本含旧文本 → 提取新增尾部"""
    ctx = SessionContext("c1")
    ctx.get_incremental_text("今天天气")
    out = ctx.get_incremental_text("今天天气很好")
    assert "很好" in out
    assert "今天天气" not in out


def test_old_contains_new_returns_empty():
    """旧文本含新文本(ASR 修正) → 不输出"""
    ctx = SessionContext("c1")
    ctx.get_incremental_text("今天天气很好很热")
    out = ctx.get_incremental_text("今天天气很好")
    assert out == ""


def test_overlap_suffix_prefix_extracts_new():
    """旧后缀 = 新前缀(ASR 滚动更新) → 提取新前缀之后"""
    ctx = SessionContext("c1")
    ctx.get_incremental_text("我喜欢苹果")
    # ASR 修正: "喜欢苹果和香蕉" (重叠 = "喜欢苹果")
    out = ctx.get_incremental_text("喜欢苹果和香蕉")
    assert "香蕉" in out
    assert "喜欢苹果" not in out


def test_completely_different_returns_new_text():
    """完全不相关 → 视为新话题,输出新文本"""
    ctx = SessionContext("c1")
    ctx.get_incremental_text("今天天气很好")
    out = ctx.get_incremental_text("明天会下雨")
    assert out == "明天会下雨"


def test_similar_text_without_exact_overlap_is_not_silently_lost():
    """没有精确重叠时不能凭相似度吞掉一条可能的 ASR 修正。"""
    ctx = SessionContext("c1")
    ctx.get_incremental_text("今天天气非常的好")
    # 相似但内容变了: "今天天气非常好"(少一个"的很")
    out = ctx.get_incremental_text("今天天气非常好")
    assert out == "今天天气非常好"


def test_repeat_last_output_returns_empty():
    """重复 last_output_text → 不输出"""
    ctx = SessionContext("c1")
    assert ctx.get_incremental_text("你好") == "你好"
    # 完全重复
    out = ctx.get_incremental_text("你好")
    assert out == ""


def test_no_duplicate_incremental_across_segments():
    """模拟连续 ASR 输出:同一段文本只输出一次"""
    ctx = SessionContext("c1")
    # 第一帧: 完整
    out1 = ctx.get_incremental_text("hello world")
    assert out1 == "hello world"
    # 第二帧: ASR 修正(完全相同)— 不输出
    out2 = ctx.get_incremental_text("hello world")
    assert out2 == ""
    # 第三帧: ASR 补全(新加 "today")
    out3 = ctx.get_incremental_text("hello world today")
    assert "today" in out3
    # 第四帧: 重复第三帧
    out4 = ctx.get_incremental_text("hello world today")
    assert out4 == ""
