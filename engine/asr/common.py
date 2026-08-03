"""ASR 引擎共享工具."""
from __future__ import annotations

import numpy as np


# ASR 静音段常见幻觉水印。只收"完整句级/带标点"的形态,
# 不收裸品牌词(抖音/B站/YouTube)和裸职衔词(导演/编剧/出品人)——
# 这些在正常会议文本里高频出现,裸子串 replace 会误删真实内容。
# 裸品牌/职衔幻觉若需要按需过滤,改由下游整句匹配处理。
HALLUCINATIONS = [
    "谢谢。", "大家再见。", "字幕由", "感谢收看",
    "谢谢大家。", "谢谢观看。", "再见。", "拜拜。",
    "嗯。", "啊。", "呃。", "这个。",
    "本节目由", "本视频由", "本片由",
    "。。", "，，", "、、", "。。。",
]


def filter_hallucinations(text: str) -> str:
    """过滤常见 ASR 幻觉词和纯标点短结果."""
    if not text:
        return ""
    for item in HALLUCINATIONS:
        text = text.replace(item, "")

    import re
    text = re.sub(r"[。]{2,}", "。", text)
    text = re.sub(r"[，]{2,}", "，", text)
    text = re.sub(r"[、]{2,}", "、", text).strip()
    if len(text) < 2:
        return ""
    if all(c in '，。！？、；：""\'\'（）【】…—' for c in text):
        return ""
    return text


def rms_is_silent(audio_data: np.ndarray, threshold: float = 0.012) -> bool:
    """轻量 RMS 静音判断,供非 Qwen 引擎和状态机使用."""
    if audio_data is None or len(audio_data) == 0:
        return True
    rms = float(np.sqrt(np.mean(audio_data ** 2)))
    return rms < threshold


def evaluate_audio_quality(audio_data: np.ndarray) -> dict:
    """返回与 Qwen 引擎兼容的粗略音频质量评分."""
    if audio_data is None or len(audio_data) == 0:
        return {"quality": "empty", "score": 0}

    rms = float(np.sqrt(np.mean(audio_data ** 2)))
    peak = float(np.max(np.abs(audio_data)))
    score = 100
    if rms < 0.005:
        score -= 40
    elif rms < 0.02:
        score -= 20
    elif rms > 0.5:
        score -= 30
    if peak < 1e-6:
        score = 0
    return {"quality": "ok" if score >= 40 else "poor", "score": score, "rms": rms, "peak": peak}
