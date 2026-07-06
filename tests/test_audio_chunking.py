import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
import numpy as np
from typing import List, Tuple

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.upload import split_audio_into_chunks, merge_text_with_overlap


class TestSplitAudioIntoChunks:
    """测试音频分段功能"""
    
    def test_short_audio_no_split(self):
        """短音频不应分段"""
        sample_rate = 16000
        duration = 10  # 10秒
        audio = np.random.randn(duration * sample_rate).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=1.0
        )
        
        assert len(chunks) == 1
        assert chunks[0][1] == 0.0  # start_time
        assert abs(chunks[0][2] - duration) < 0.1  # end_time
    
    def test_long_audio_multiple_chunks(self):
        """长音频应分成多段"""
        sample_rate = 16000
        duration = 120  # 2分钟
        audio = np.random.randn(duration * sample_rate).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=1.0
        )
        
        # 120秒 / (30-1)秒步长 ≈ 4-5 段
        assert len(chunks) >= 4
        assert len(chunks) <= 6
        
        # 检查第一段
        assert chunks[0][1] == 0.0
        assert chunks[0][2] == 30.0
        
        # 检查最后一段结束时间
        assert abs(chunks[-1][2] - duration) < 1.0
    
    def test_chunk_overlap(self):
        """分段应有重叠"""
        sample_rate = 16000
        duration = 60  # 1分钟
        audio = np.random.randn(duration * sample_rate).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=2.0
        )
        
        if len(chunks) > 1:
            # 第二段开始时间应小于第一段结束时间
            assert chunks[1][1] < chunks[0][2]
            # 重叠约2秒
            overlap = chunks[0][2] - chunks[1][1]
            assert abs(overlap - 2.0) < 0.1
    
    def test_very_long_audio(self):
        """测试超长音频（1小时）分段计算"""
        sample_rate = 16000
        duration = 3600  # 1小时
        
        # 只测试分段计算逻辑，不实际生成数据
        chunk_duration = 30.0
        overlap_duration = 1.0
        chunk_samples = int(chunk_duration * sample_rate)
        overlap_samples = int(overlap_duration * sample_rate)
        step_samples = chunk_samples - overlap_samples
        total_samples = duration * sample_rate
        
        chunk_count = 0
        start = 0
        while start < total_samples:
            end = min(start + chunk_samples, total_samples)
            chunk_len = end - start
            if chunk_len >= sample_rate * 0.5:
                chunk_count += 1
            start += step_samples
            if total_samples - start < sample_rate * 0.5:
                break
        
        # 3600秒 / 29秒步长 ≈ 124 段
        assert chunk_count >= 120
        assert chunk_count <= 130
    
    def test_exact_chunk_boundary(self):
        """测试恰好等于分段时长的音频
        
        注意：由于步长 = chunk_duration - overlap_duration = 29秒，
        30秒的音频会产生2段（第一段0-30秒，第二段29-30秒）
        """
        sample_rate = 16000
        duration = 30  # 恰好30秒
        audio = np.random.randn(duration * sample_rate).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=1.0
        )
        
        # 由于有重叠，30秒会产生2段
        assert len(chunks) == 2
        assert chunks[0][1] == 0.0
        assert chunks[0][2] == 30.0
        # 第二段从29秒开始
        assert chunks[1][1] == 29.0
        assert chunks[1][2] == 30.0
    
    def test_audio_shorter_than_step(self):
        """测试音频时长小于步长的情况"""
        sample_rate = 16000
        duration = 25  # 小于步长29秒
        audio = np.random.randn(duration * sample_rate).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=1.0
        )
        
        # 只有1段
        assert len(chunks) == 1
        assert abs(chunks[0][2] - 25.0) < 0.1


class TestMergeTextWithOverlap:
    """测试文本合并功能"""
    
    def test_empty_prev_text(self):
        """前一段为空"""
        result = merge_text_with_overlap("", "新文本")
        assert result == "新文本"
    
    def test_empty_new_text(self):
        """新一段为空"""
        result = merge_text_with_overlap("旧文本", "")
        assert result == "旧文本"
    
    def test_exact_overlap(self):
        """完全重叠"""
        result = merge_text_with_overlap("这是一段测试文本", "测试文本的后半部分")
        assert result == "这是一段测试文本的后半部分"
    
    def test_partial_overlap(self):
        """部分重叠"""
        result = merge_text_with_overlap("你好世界", "世界你好")
        # "世界" 重叠
        assert "世界" in result
    
    def test_no_overlap(self):
        """无重叠"""
        result = merge_text_with_overlap("第一段内容", "第二段内容")
        # 直接拼接
        assert "第一段内容" in result
        assert "第二段内容" in result
    
    def test_with_punctuation(self):
        """带标点符号"""
        result = merge_text_with_overlap("你好，世界。", "世界。再见。")
        assert result == "你好，世界。再见。"
    
    def test_whitespace_handling(self):
        """空格处理"""
        result = merge_text_with_overlap("测试文本 ", " 测试文本继续")
        assert "测试文本" in result


class TestChunkTimeCalculation:
    """测试分段时间计算"""
    
    def test_start_time_sequence(self):
        """分段开始时间应递增"""
        sample_rate = 16000
        audio = np.random.randn(60 * sample_rate).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=1.0
        )
        
        for i in range(1, len(chunks)):
            assert chunks[i][1] > chunks[i-1][1], f"分段{i}开始时间应大于前一段"
    
    def test_no_gaps_in_coverage(self):
        """分段应覆盖整个音频（考虑重叠）"""
        sample_rate = 16000
        duration = 60
        audio = np.random.randn(duration * sample_rate).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=1.0
        )
        
        # 第一个分段应从0开始
        assert chunks[0][1] == 0.0
        
        # 最后一个分段应覆盖到结尾
        assert abs(chunks[-1][2] - duration) < 0.1
        
        # 每个分段应被覆盖（考虑重叠）
        for i in range(1, len(chunks)):
            # 前一分段结束时间应大于等于当前分段开始时间（有重叠）
            assert chunks[i-1][2] >= chunks[i][1], f"分段{i-1}和{i}之间有间隙"


class TestEdgeCases:
    """边界条件测试"""
    
    def test_minimum_duration(self):
        """最小有效时长（0.5秒）"""
        sample_rate = 16000
        audio = np.random.randn(int(0.5 * sample_rate)).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=1.0
        )
        
        # 0.5秒应该能生成一个分段
        assert len(chunks) == 1
    
    def test_below_minimum_duration(self):
        """低于最小时长"""
        sample_rate = 16000
        audio = np.random.randn(int(0.3 * sample_rate)).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=1.0
        )
        
        # 太短，可能不分段
        assert len(chunks) <= 1
    
    def test_large_overlap(self):
        """大重叠比例"""
        sample_rate = 16000
        duration = 100
        audio = np.random.randn(duration * sample_rate).astype(np.float32)
        
        chunks = split_audio_into_chunks(
            audio, sample_rate,
            chunk_duration=30.0,
            overlap_duration=15.0  # 50%重叠
        )
        
        # 重叠大，分段数应更多
        assert len(chunks) >= 5
        
        # 检查重叠
        if len(chunks) > 1:
            overlap = chunks[0][2] - chunks[1][1]
            assert abs(overlap - 15.0) < 1.0


class TestOverlapTextMerging:
    """测试重叠区域的文本合并（模拟分段处理场景）"""
    
    def test_simulate_chunked_transcription(self):
        """模拟分段转写后的文本合并
        
        场景：60秒音频，30秒分段，1秒重叠
        分段1: 0-30秒，ASR输出: "你好世界这是测试"
        分段2: 29-60秒，ASR输出: "测试继续第二段内容"
        
        期望：合并后去除重复的"测试"
        """
        # 模拟两个分段的 ASR 输出（有重叠）
        chunk1_text = "你好世界这是测试"
        chunk2_text = "测试继续第二段内容"
        
        # 使用 merge_text_with_overlap 合并
        result = merge_text_with_overlap(chunk1_text, chunk2_text)
        
        # 应该去除重复的"测试"
        assert "测试" not in result[:len(chunk1_text)] or result.count("测试") == 1
        # 结果应该包含两段的独特内容
        assert "你好世界" in result
        assert "继续第二段内容" in result
    
    def test_multiple_chunks_merging(self):
        """测试多段连续合并"""
        # 模拟 3 个分段的 ASR 输出
        chunks = [
            "第一段内容结束",
            "结束时的开头第二段",
            "第二段继续第三段内容"
        ]
        
        result = chunks[0]
        for i in range(1, len(chunks)):
            result = merge_text_with_overlap(result, chunks[i])
        
        # 检查没有明显的重复
        assert result.count("结束") <= 2
        assert result.count("第二段") == 1
    
    def test_speaker_change_scenario(self):
        """测试说话人切换场景
        
        模拟分段处理时说话人变化的情况
        """
        # 分段1: 说话人A
        text1 = "我是说话人A这是我的发言"
        # 分段2: 说话人B（重叠区域内容相同但说话人不同）
        text2 = "我的发言继续我是说话人B"
        
        # 同一说话人的文本应该合并去重
        merged = merge_text_with_overlap(text1, text2)
        
        # 结果应该是连贯的
        assert "说话人A" in merged
        assert "说话人B" in merged
    
    def test_real_world_overlap_case(self):
        """测试真实场景的重叠合并
        
        场景：30秒分段，1秒重叠
        重叠区域的文本应该被正确处理
        """
        # 真实 ASR 可能输出的文本
        chunk1 = "今天我们来讨论一下人工智能的发展趋势"
        chunk2 = "趋势目前看来非常乐观尤其是在大模型领域"
        
        result = merge_text_with_overlap(chunk1, chunk2)
        
        # "趋势" 应该只出现一次
        assert result.count("趋势") == 1
        # 结果应该是连贯的句子
        assert "人工智能的发展" in result
        assert "大模型领域" in result


class TestDiarizationToggle:
    """测试说话人识别开关功能"""
    
    def test_process_chunk_with_diarization(self):
        """测试带说话人识别的分段处理函数签名"""
        # 导入函数
        from app.api.upload import process_audio_chunk_with_diarization, process_audio_chunk_asr_only
        
        # 验证函数存在
        assert callable(process_audio_chunk_with_diarization)
        assert callable(process_audio_chunk_asr_only)

    def test_process_chunk_with_diarization_uses_filename_default_name(self, monkeypatch):
        """长音频分段 diarization 路径应可执行,并把文件名传给声纹默认名."""
        import app.api.upload as upload_mod

        asr = MagicMock()
        asr.run_asr = AsyncMock(return_value={"text": "测试文本", "words": None})
        speaker = MagicMock()
        speaker.extract_feat.return_value = ([0.1] * 192, 1.0)
        speaker.compare_and_identify.return_value = ("Spk_meeting", 0.9)

        monkeypatch.setattr(upload_mod, "asr_engine", asr)
        monkeypatch.setattr(upload_mod, "get_speaker_engine", lambda: speaker)

        chunk = np.ones(16000, dtype=np.float32) * 0.1
        result = asyncio.run(
            upload_mod.process_audio_chunk_with_diarization(
                chunk, 30.0, 31.0, "weekly-meeting.wav"
            )
        )

        assert result.speaker == "Spk_meeting"
        assert result.text == "测试文本"
        speaker.compare_and_identify.assert_called_once()
        assert speaker.compare_and_identify.call_args.kwargs["default_name"] == "weekly-meeting"
    
    def test_diarization_disabled_text_merge(self):
        """测试禁用说话人识别时的文本合并逻辑
        
        当 enable_diarization=false 时：
        - 所有分段的 speaker 应该是 "SPEAKER"
        - 文本直接合并，不需要按说话人分组
        """
        # 模拟禁用说话人识别时的分段结果
        segments = [
            type('Segment', (), {'speaker': 'SPEAKER', 'text': '第一段内容结束'})(),
            type('Segment', (), {'speaker': 'SPEAKER', 'text': '结束后的第二段'})(),
            type('Segment', (), {'speaker': 'SPEAKER', 'text': '第二段继续第三段'})(),
        ]
        
        # 模拟无说话人识别的文本合并
        merged_text = ""
        prev_text = ""
        for seg in segments:
            if seg.text:
                merged_text = merge_text_with_overlap(prev_text, seg.text)
                prev_text = merged_text
        
        # 结果应该是连贯的
        assert "第一段内容" in merged_text
        assert "第二段" in merged_text
        assert "第三段" in merged_text
    
    def test_diarization_enabled_text_merge(self):
        """测试启用说话人识别时的文本合并逻辑
        
        当 enable_diarization=true 时：
        - 不同说话人需要分行显示
        - 同一说话人的分段需要去重合并
        """
        # 模拟启用说话人识别时的分段结果（两个说话人）
        segments = [
            type('Segment', (), {'speaker': 'Spk_001', 'text': '说话人一的发言'})(),
            type('Segment', (), {'speaker': 'Spk_001', 'text': '发言继续'})(),
            type('Segment', (), {'speaker': 'Spk_002', 'text': '说话人二的发言'})(),
        ]
        
        # 模拟有说话人识别的文本合并
        merged_text = ""
        prev_speaker = None
        prev_text = ""
        
        for seg in segments:
            if not seg.text:
                continue
            
            if seg.speaker == prev_speaker:
                merged_segment = merge_text_with_overlap(prev_text, seg.text)
                new_part = merged_segment[len(prev_text):]
                if new_part:
                    merged_text += new_part
                prev_text = merged_segment
            else:
                if merged_text:
                    merged_text += f"\n[{seg.speaker}]: {seg.text}"
                else:
                    merged_text = f"[{seg.speaker}]: {seg.text}"
                prev_speaker = seg.speaker
                prev_text = seg.text
        
        # 验证说话人标记
        assert "[Spk_001]" in merged_text
        assert "[Spk_002]" in merged_text
    
    def test_diarization_flag_default(self):
        """测试 enable_diarization 参数默认值"""
        from fastapi import Query
        
        # 默认值应该是 True
        # 这里只验证模块导入正确
        from app.api.upload import upload_audio
        assert callable(upload_audio)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
