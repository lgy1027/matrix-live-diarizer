"""统计引擎：纯规则实现，不依赖 jieba。基础分词 = 单字 + 连续 ASCII 词。"""
import re
from collections import Counter


# 中文常见停用词（小集合，可扩展）
_STOP_WORDS = {
    "的", "了", "是", "在", "和", "与", "或", "及", "等", "之",
    "我", "你", "他", "她", "它", "我们", "你们", "他们",
    "这", "那", "这个", "那个", "啊", "嗯", "哦", "哎", "唉",
    "就", "也", "都", "还", "只", "才", "要", "会", "能", "可",
    "把", "被", "对", "向", "从", "到", "给", "以", "为", "于",
}


def _tokenize(text: str) -> list[str]:
    """分词：中文滑动 bigram（2 字窗口） + 英文/数字单词。
    bigram 策略让单字停用词（的/了/是）天然不会成词。
    """
    tokens: list[str] = []
    # 1) 英文/数字单词
    for match in re.finditer(r"[A-Za-z0-9]+", text):
        tok = match.group(0)
        if tok.lower() in {"the", "a", "an", "is", "are", "was", "of", "to", "and", "in"}:
            continue
        tokens.append(tok)
    # 2) 中文 bigram 滑动窗口
    for match in re.finditer(r"[一-鿿]+", text):
        chunk = match.group(0)
        if len(chunk) == 1:
            tok = chunk
            if tok in _STOP_WORDS:
                continue
            tokens.append(tok)
        else:
            for i in range(len(chunk) - 1):
                tokens.append(chunk[i : i + 2])
    return tokens


def _word_count(text: str) -> int:
    """字数统计：中文 bigram 数 + 英文单词数。
    "你好 world" → 1 + 1 = 2
    "今天天气"   → 3 (今,天天,天气)
    """
    count = len(re.findall(r"[A-Za-z0-9]+", text))
    for match in re.finditer(r"[一-鿿]+", text):
        chunk = match.group(0)
        if len(chunk) == 1:
            count += 1
        else:
            count += len(chunk) - 1
    return count


def compute_statistics(
    segments: list[dict],
    total_duration_sec: float,
    speaker_aliases: dict | None = None,
    top_n: int = 20,
) -> dict:
    """计算会话统计信息"""
    speaker_aliases = speaker_aliases or {}
    speech_total = 0.0
    by_speaker: dict[str | None, dict] = {}
    prev_speaker = None
    turn_taking = 0
    all_tokens: list[str] = []

    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        dur = max(0.0, seg["end_time"] - seg["start_time"])
        speech_total += dur
        spk = seg.get("speaker_id")
        if spk not in by_speaker:
            by_speaker[spk] = {
                "speaker_id": spk,
                "display_name": speaker_aliases.get(spk, spk or "未识别"),
                "talk_time_sec": 0.0,
                "segment_count": 0,
                "word_count": 0,
            }
        by_speaker[spk]["talk_time_sec"] += dur
        by_speaker[spk]["segment_count"] += 1
        by_speaker[spk]["word_count"] += _word_count(text)
        all_tokens.extend(_tokenize(text))
        if prev_speaker is not None and spk != prev_speaker:
            turn_taking += 1
        prev_speaker = spk

    speakers_list = list(by_speaker.values())
    for s in speakers_list:
        s["talk_ratio"] = s["talk_time_sec"] / speech_total if speech_total > 0 else 0
        s["avg_segment_sec"] = (
            s["talk_time_sec"] / s["segment_count"] if s["segment_count"] > 0 else 0
        )

    hot = Counter(all_tokens).most_common(top_n)
    silence = max(0.0, total_duration_sec - speech_total)
    return {
        "total_duration_sec": total_duration_sec,
        "speech_duration_sec": round(speech_total, 3),
        "silence_duration_sec": round(silence, 3),
        "silence_ratio": round(silence / total_duration_sec, 3) if total_duration_sec > 0 else 0.0,
        "speakers": speakers_list,
        "hot_words": [{"word": w, "count": c} for w, c in hot],
        "turn_taking_count": turn_taking,
    }
