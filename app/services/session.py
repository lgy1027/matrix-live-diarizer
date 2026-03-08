"""会话上下文管理器"""
import numpy as np
from app.constants import PUNCTUATION_CHARS


class SessionContext:
    """会话上下文管理器"""
    
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.audio_buffer = np.array([], dtype=np.float32)
        self.last_full_text = ""

    def get_incremental_text(self, new_text: str) -> str:
        """提取增量文本，避免重复输出"""
        if not new_text:
            return ""
        
        def normalize(t: str) -> str:
            return "".join(c for c in t if c not in PUNCTUATION_CHARS)

        norm_new = normalize(new_text)
        norm_old = normalize(self.last_full_text)

        # 包含性检查
        if norm_new in norm_old and len(norm_new) <= len(norm_old):
            return ""

        # 滑动窗口匹配
        max_overlap = min(len(self.last_full_text), len(new_text))
        overlap_len = 0
        for i in range(max_overlap, 0, -1):
            if self.last_full_text.endswith(new_text[:i]):
                overlap_len = i
                break
        
        incremental = new_text[overlap_len:]
        
        norm_incr = normalize(incremental)
        if not norm_incr:
            return ""
        
        # 过滤重复片段
        if norm_old and norm_incr:
            for pattern_len in range(1, min(len(norm_old) + 1, 10)):
                pattern = norm_old[:pattern_len]
                if norm_incr == pattern:
                    return ""
                if len(norm_incr) > len(pattern) and len(norm_incr) % len(pattern) == 0:
                    if norm_incr == pattern * (len(norm_incr) // len(pattern)):
                        return ""

        self.last_full_text = (self.last_full_text + incremental)[-100:]
        return incremental