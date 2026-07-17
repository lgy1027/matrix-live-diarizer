"""会话上下文管理器"""
import numpy as np
from app.constants import PUNCTUATION_CHARS


class SessionContext:
    """会话上下文管理器"""
    
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.audio_buffer = np.array([], dtype=np.float32)
        self.last_full_text = ""
        self.last_output_text = ""  # 上次实际输出的文本

    def get_incremental_text(self, new_text: str) -> str:
        """提取增量文本，避免重复输出
        
        策略：
        1. 如果新文本以旧文本开头，返回新增部分
        2. 如果新旧文本有重叠后缀/前缀，提取非重叠部分
        3. 如果完全不相关，可能是新的话题，返回新文本
        """
        if not new_text:
            return ""
        
        # 标准化（去除标点）用于比较
        def normalize(t: str) -> str:
            return "".join(c for c in t if c not in PUNCTUATION_CHARS)
        
        norm_new = normalize(new_text)
        norm_old = normalize(self.last_full_text)
        
        # 空旧文本，直接返回新文本
        if not norm_old:
            self.last_full_text = new_text
            self.last_output_text = new_text
            return new_text
        
        # 情况1：新文本包含旧文本（ASR 补全了之前的内容）
        if norm_old in norm_new:
            # 找到旧文本在新文本中的位置
            start_idx = norm_new.find(norm_old)
            # 计算新增部分的起始位置（在标准化文本中）
            new_start_in_norm = start_idx + len(norm_old)
            # 在原始文本中找到对应位置
            incremental = self._extract_after_position(new_text, new_start_in_norm)
            if incremental and normalize(incremental):
                self.last_full_text = new_text
                self.last_output_text = incremental
                return incremental
            return ""
        
        # 情况2：旧文本包含新文本（可能是 ASR 修正或重复）
        if norm_new in norm_old:
            return ""  # 不输出
        
        # 情况3：查找最大重叠（旧文本后缀 = 新文本前缀）
        max_overlap = 0
        
        # 从长到短查找重叠
        for overlap_len in range(min(len(norm_old), len(norm_new)), 0, -1):
            if norm_old[-overlap_len:] == norm_new[:overlap_len]:
                max_overlap = overlap_len
                break
        
        if max_overlap > 0:
            # 有重叠，提取非重叠部分
            incremental = self._extract_after_position(new_text, max_overlap)
            if incremental and normalize(incremental):
                self.last_full_text = new_text
                self.last_output_text = incremental
                return incremental
            return ""
        
        # 没有可证明的精确重叠时，宁可输出一个新段，也不能因为“看起来
        # 相似”就吞掉 ASR 修正。真正的 partial revision 需要独立协议。
        # 检查是否是上一次输出的重复
        if normalize(new_text) == normalize(self.last_output_text):
            return ""
        
        self.last_full_text = new_text
        self.last_output_text = new_text
        return new_text
    
    def _extract_after_position(self, text: str, norm_position: int) -> str:
        """在标准化文本的第 norm_position 个字符后提取内容（保留标点）"""
        if norm_position <= 0:
            return text
        if norm_position >= len("".join(c for c in text if c not in PUNCTUATION_CHARS)):
            return ""
        
        # 遍历原始文本，找到标准化位置对应的实际位置
        char_count = 0
        for i, c in enumerate(text):
            if c not in PUNCTUATION_CHARS:
                char_count += 1
                if char_count == norm_position:
                    # 返回该位置之后的内容（包含当前位置之后可能紧跟的标点）
                    return text[i + 1:]
        
        return ""
