"""WebSocket 状态机纯函数测试

对应 app/api/websocket.py 重构后抽出的:
- classify_frame: 单帧 VAD 判定(纯函数)
- should_emit_segment: 触发 ASR 识别的条件(纯函数)
- next_state: 状态机推进(纯函数)
- compute_skip_count: 队列跳帧策略(纯函数)

这次重构后:
- audio_processor 内部不再有硬编码 STATE_SILENCE / SILENCE_THRESHOLD_FRAMES
- 状态机逻辑可单测,不再依赖完整 WebSocket 流程
"""
import sys
import numpy as np
from unittest.mock import MagicMock

sys.path.insert(0, "/Users/lgy/python/github.com/lgy1027/matrix-live-diarizer")

from app.api.websocket import (
    STATE_SILENCE,
    STATE_SPEECH,
    SILENCE_THRESHOLD_FRAMES,
    LOUD_RMS_THRESHOLD,
    classify_frame,
    should_emit_segment,
    next_state,
    compute_skip_count,
)


# ========== classify_frame ==========

def test_classify_frame_empty_returns_false():
    """空帧 → False(不是语音)"""
    assert classify_frame(np.array([]), None) is False
    assert classify_frame(None, None) is False


def test_classify_frame_quiet_audio_silence():
    """安静音频(RMS < 0.015)→ False(不走 VAD)"""
    quiet = np.zeros(320, dtype=np.float32)  # 静音帧
    assert classify_frame(quiet, None) is False
    # 0.01 振幅的 sine, RMS ≈ 0.007
    t = np.arange(320) / 16000
    quiet_sine = (0.01 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    assert classify_frame(quiet_sine, None) is False


def test_classify_frame_loud_audio_no_vad_engine_returns_true():
    """大声 + 无 VAD 引擎 → True(仅靠能量)"""
    t = np.arange(320) / 16000
    loud = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    assert classify_frame(loud, asr_engine_obj=None) is True


def test_classify_frame_loud_audio_vad_says_speech():
    """大声 + VAD 说不是静音 → True"""
    t = np.arange(320) / 16000
    loud = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    fake_asr = MagicMock()
    fake_asr.is_silent.return_value = False  # VAD: 不是静音
    assert classify_frame(loud, fake_asr) is True
    fake_asr.is_silent.assert_called_once_with(loud, use_vad=True)


def test_classify_frame_loud_audio_vad_says_silence():
    """大声(机器噪声)但 VAD 判静音 → False(音乐/风扇被过滤)"""
    t = np.arange(320) / 16000
    loud = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    fake_asr = MagicMock()
    fake_asr.is_silent.return_value = True  # VAD: 是静音(机器噪声)
    assert classify_frame(loud, fake_asr) is False


def test_classify_frame_loud_threshold_boundary():
    """边界值 RMS = 0.015 时:不算大声(<=,不严格大于)→ False"""
    # 构造一个 RMS 接近阈值的帧(float32 精度可能略低,验证功能即可)
    chunk = np.full(320, LOUD_RMS_THRESHOLD, dtype=np.float32)
    rms = float(np.sqrt(np.mean(chunk ** 2)))
    # RMS 在阈值附近(< 0.016)
    assert abs(rms - LOUD_RMS_THRESHOLD) < 0.001
    # 实际代码用 <=,所以这一帧被判静音
    assert classify_frame(chunk, None) is False


# ========== should_emit_segment ==========

def test_should_emit_silence_state_never_emits():
    """STATE_SILENCE 时永远不触发"""
    for cnt in [0, 1, 3, 100, 9999]:
        assert should_emit_segment(STATE_SILENCE, cnt, 99999, 16000, 5.0) is False


def test_should_emit_speech_state_silence_count_below_threshold():
    """STATE_SPEECH + silence_count < 阈值 → 不触发"""
    for cnt in [0, 1, 2]:  # 默认阈值 3
        assert should_emit_segment(STATE_SPEECH, cnt, 100, 16000, 5.0) is False


def test_should_emit_speech_state_silence_count_at_threshold():
    """STATE_SPEECH + silence_count == 阈值 → 触发"""
    assert should_emit_segment(STATE_SPEECH, SILENCE_THRESHOLD_FRAMES, 100, 16000, 5.0) is True


def test_should_emit_speech_state_buffer_too_long():
    """STATE_SPEECH + 缓冲超 max_segment_seconds → 强制触发"""
    # max_segment_seconds=5, sample_rate=16000 → 阈值 80000 samples
    over = 80000
    assert should_emit_segment(STATE_SPEECH, 0, over, 16000, 5.0) is True
    # 边界:刚好到
    assert should_emit_segment(STATE_SPEECH, 0, 80000, 16000, 5.0) is True
    # 差一个
    assert should_emit_segment(STATE_SPEECH, 0, 79999, 16000, 5.0) is False


def test_should_emit_custom_threshold():
    """自定义 silence_threshold 可覆盖默认值"""
    # threshold=5,count=4 → 不触发
    assert should_emit_segment(STATE_SPEECH, 4, 100, 16000, 5.0, silence_threshold=5) is False
    # threshold=5,count=5 → 触发
    assert should_emit_segment(STATE_SPEECH, 5, 100, 16000, 5.0, silence_threshold=5) is True


# ========== next_state ==========

def test_next_state_silence_to_speech():
    """SILENCE + speech → SPEECH"""
    assert next_state(STATE_SILENCE, True) == STATE_SPEECH


def test_next_state_silence_to_silence():
    """SILENCE + silence → SILENCE(不变)"""
    assert next_state(STATE_SILENCE, False) == STATE_SILENCE


def test_next_state_speech_stays_speech_on_speech():
    """SPEECH + speech → SPEECH(继续累积)"""
    assert next_state(STATE_SPEECH, True) == STATE_SPEECH


def test_next_state_speech_stays_speech_on_silence():
    """SPEECH + silence → SPEECH(等 silence_threshold 触发,state 不变)"""
    # 注意:state 切换由 should_emit_segment 决策,不是 next_state
    # next_state 只决定"立即"是否进 SPEECH 累积
    assert next_state(STATE_SPEECH, False) == STATE_SPEECH


# ========== 集成场景测试 ==========

def test_state_machine_full_speech_burst():
    """完整流程:静音 → 语音 × 5 帧 → 静音 × 3 帧 → 触发识别"""
    # 模拟: SILENCE → 5 帧 speech → 3 帧 silence → 触发
    # 这里用 next_state + should_emit_segment 组合模拟
    state = STATE_SILENCE
    silence_count = 0
    emit_events = []

    # 5 帧语音
    for _ in range(5):
        state = next_state(state, is_speech=True)
        silence_count = 0
        emit = should_emit_segment(state, silence_count, 100, 16000, 5.0)
        emit_events.append(emit)

    # 3 帧静音(从第 1 帧起 silence_count +1,到第 3 帧触发)
    for i in range(3):
        # 实际:asr 拿到 silence 帧,会先累积到 speech_buffer,再 silence_count += 1
        silence_count += 1
        emit = should_emit_segment(state, silence_count, 100, 16000, 5.0)
        emit_events.append(emit)

    # 5 帧语音中:不触发
    assert all(e is False for e in emit_events[:5]), "语音中不应触发"
    # 第 6 帧(静音 #1):不触发
    assert emit_events[5] is False
    # 第 7 帧(静音 #2):不触发
    assert emit_events[6] is False
    # 第 8 帧(静音 #3):触发
    assert emit_events[7] is True, f"第 3 帧静音应触发,实际 emit={emit_events[7]}"


def test_state_machine_force_emit_on_long_speech():
    """长语音:缓冲超限 → 强制触发(不等静音)"""
    state = STATE_SPEECH
    silence_count = 0
    # 模拟缓冲累积 80000 samples(5 秒)
    for chunk_size in [320, 320, 320, 79340]:  # 累计 80300
        if should_emit_segment(state, silence_count, 80000, 16000, 5.0):
            # 触发
            break
        # 继续累积
    # buffer 达 80000 → 触发
    assert should_emit_segment(state, 0, 80000, 16000, 5.0) is True
    # 1000 samples (1 帧) 不会触发
    assert should_emit_segment(state, 0, 1000, 16000, 5.0) is False


# ========== compute_skip_count ==========

def test_compute_skip_count_below_threshold_no_skip():
    """队列未满 → 跳 0 帧"""
    assert compute_skip_count(0, 50) == 0
    assert compute_skip_count(1, 50) == 0
    assert compute_skip_count(49, 50) == 0
    assert compute_skip_count(50, 50) == 0  # 等于阈值也不跳


def test_compute_skip_count_at_threshold_boundary():
    """刚超阈值 1 帧 → 跳 queue_size-1 帧(保留最新 1 帧)"""
    # queue_size=51, threshold=50: 51 > 50 → 跳 51-1=50 帧(留 1 帧最新)
    assert compute_skip_count(51, 50) == 50


def test_compute_skip_count_above_threshold_skip_all_but_one():
    """队列堆积 → 保留最新 1 帧,跳过其余"""
    # queue_size=100, threshold=50: 保留 1 帧,跳 99 帧
    assert compute_skip_count(100, 50) == 99
    # queue_size=60, threshold=50: 保留 1 帧,跳 59 帧
    assert compute_skip_count(60, 50) == 59


def test_compute_skip_count_custom_threshold():
    """自定义阈值"""
    # threshold=10, queue_size=20 → 跳 19
    assert compute_skip_count(20, 10) == 19
    # threshold=10, queue_size=10 → 跳 0
    assert compute_skip_count(10, 10) == 0
    # threshold=0, queue_size=1 → 跳 0(任何 queue_size>0 都跳,只保留 1 帧)
    assert compute_skip_count(1, 0) == 0
    # threshold=0, queue_size=5 → 跳 4
    assert compute_skip_count(5, 0) == 4


def test_compute_skip_count_empty_queue():
    """空队列 → 跳 0 帧"""
    assert compute_skip_count(0, 0) == 0
    assert compute_skip_count(0, 100) == 0


def test_compute_skip_count_total_consistency():
    """跳帧数 + 保留 1 帧 = queue_size(可证伪)"""
    for q, t in [(10, 5), (20, 10), (100, 50), (51, 50), (1, 0)]:
        if q > t:
            assert compute_skip_count(q, t) == q - 1, f"q={q} t={t}"
        else:
            assert compute_skip_count(q, t) == 0, f"q={q} t={t}"


def test_compute_skip_count_idempotent_at_maxsize():
    """极端情况:阈值=0 时,任何非空队列都跳完只留 1 帧"""
    for q in [1, 2, 10, 100]:
        # threshold=0 → 任何 queue_size>0 都跳
        # q=1 → 跳 0(因为 1-1=0,只留 1 帧就是这 1 帧)
        # q=2 → 跳 1
        expected = q - 1
        assert compute_skip_count(q, 0) == expected, f"q={q}"
