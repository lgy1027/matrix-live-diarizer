"""纯本地、零 LLM 依赖的摘要 / 行动项 / 纪要生成器 (TextRank)

LLM 不可用时作为兜底,保证响应里始终有内容。
"""
import re
import logging
from typing import List, Dict

logger = logging.getLogger("Matrix_Extractive")

# 中英文行动项关键词
ACTION_KEYWORDS_ZH = [
    "需要", "应该", "必须", "责任", "负责", "跟进", "待办", "TODO", "todo",
    "要求", "完成", "提交", "安排", "处理", "联系", "准备", "交付", "截止",
]
ACTION_KEYWORDS_EN = [
    "need to", "should", "must", "TODO", "todo", "deadline", "owner",
    "responsible", "action item", "follow up", "complete", "submit", "prepare",
]
DECISION_KEYWORDS_ZH = [
    "决定", "决议", "确定", "确认", "结论", "同意", "通过", "采用", "最终", "暂定",
]
DECISION_KEYWORDS_EN = [
    "decided", "decision", "agreed", "approved", "confirmed", "conclusion",
]

MIN_SENTENCES_FOR_TEXTRANK = 3
EMPTY_PLACEHOLDER = "(无内容)"
NO_ACTIONS = "未识别到明确行动项。"
NO_DECISIONS = "未识别到明确决议。"


class ExtractiveSummarizer:
    """基于 TextRank 的本地摘要器(LLM 不可用时兜底)"""

    # summa 1.2.0 仅支持 15 种欧洲语言,中文/日文/韩文不支持
    # 不支持时,summa 会抛 "Valid languages are: ..." 错误
    # 我们在调用时把不支持的语言映射到 english(中文 stopwords 不完美,胜过抛错)
    SUMMA_SUPPORTED_LANGUAGES = {
        "arabic", "danish", "dutch", "english", "finnish", "french", "german",
        "hungarian", "italian", "norwegian", "polish", "portuguese", "romanian",
        "russian", "spanish", "swedish",
    }

    def __init__(self, language: str = "chinese"):
        self.language = language
        # 实际调 summa 时,如果 language 不在白名单,降级到 english
        self._summa_language = language if language in self.SUMMA_SUPPORTED_LANGUAGES else "english"

    def summarize(self, segments: List[Dict], max_sentences: int = 5) -> str:
        text = self._segments_to_paragraph(segments)
        sentences = self._split_sentences(text)

        if not sentences:
            return "当前文稿为空，无法生成摘要。"

        if len(sentences) < MIN_SENTENCES_FOR_TEXTRANK:
            bullets = "\n".join(f"- {sentence}" for sentence in sentences)
            return f"文稿内容较少，以下为原文要点：\n{bullets}"

        # 长文本走 TextRank(summa 1.2.0 API: ratio / words / language,不是 sentences)
        # max_sentences 不直接对应,改用 words 估计:中文 1 句 ≈ 30 字
        try:
            from summa import summarizer as textrank
            target_words = max(30, max_sentences * 30)
            result = textrank.summarize(text, words=target_words, language=self._summa_language)
            cleaned = result.strip()
            if cleaned:
                return cleaned
        except Exception as e:
            logger.warning(f"[Extractive] TextRank 失败,降级: {e}")

        # 兜底:取前 max_sentences 句
        return "。".join(sentences[:max_sentences]) + "。"

    def extract_action_items(self, segments: List[Dict]) -> List[str]:
        text = self._segments_to_paragraph(segments)
        sentences = self._split_sentences(text)
        keywords = ACTION_KEYWORDS_ZH + ACTION_KEYWORDS_EN

        items = []
        for sent in sentences:
            if any(kw in sent for kw in keywords):
                # 清理前缀标签(形如 [Spk_xxx])
                clean = re.sub(r"^\[[\w_]+\]\s*", "", sent).strip()
                if clean and clean not in items:
                    items.append(clean)
        return items[:20]

    def extract_decisions(self, segments: List[Dict]) -> List[str]:
        text = self._segments_to_paragraph(segments)
        sentences = self._split_sentences(text)
        keywords = DECISION_KEYWORDS_ZH + DECISION_KEYWORDS_EN
        decisions = []
        for sentence in sentences:
            if any(keyword.lower() in sentence.lower() for keyword in keywords):
                clean = re.sub(r"^\[[\w_]+\]\s*", "", sentence).strip()
                if clean and clean not in decisions:
                    decisions.append(clean)
        return decisions[:20]

    def generate_minutes(self, segments: List[Dict]) -> str:
        topic = self.summarize(segments, max_sentences=3)
        decisions = self.extract_decisions(segments)
        actions = self.extract_action_items(segments)

        decision_text = "\n".join(f"- {item}" for item in decisions) if decisions else f"- {NO_DECISIONS}"
        action_text = "\n".join(f"- {a}" for a in actions) if actions else f"- {NO_ACTIONS}"

        return (
            f"## 议题\n{topic or '(无内容)'}\n\n"
            f"## 决议\n{decision_text}\n\n"
            f"## 行动项\n{action_text}"
        )

    @staticmethod
    def _segments_to_paragraph(segments: List[Dict]) -> str:
        parts = []
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            # 去掉末尾的句末标点,避免 join 后出现双标点
            text = text.rstrip("。!?.")
            if text:
                parts.append(text)
        if not parts:
            return ""
        return "。".join(parts) + "。"

    @staticmethod
    def _split_sentences(text: str) -> List[str]:
        """中英文混合句子分割 — 用占位符避免空字符串

        不用零宽正则切分(re.split + 零宽会在连续标点处产生空串)
        改用占位符 | 显式分隔,简单稳定。
        """
        text = re.sub(r"\s+", " ", text)
        # 把所有句末标点(中英文)替换成 "标点|",这样 split 不会产生空串
        marked = re.sub(r"([。!?\.])", r"\1|", text)
        raw = marked.split("|")
        return [s.strip() for s in raw if s.strip()]
