"""WebSocket transcribing 占位消息 — 纯函数测试

对应 app/api/websocket.py 抽出的:
- should_push_transcribing: 在 SILENCE→SPEECH 状态切换时返回 True
- SeqCounter: 单调递增 seq 分配
"""
import sys

from app.api.websocket import (
    STATE_SILENCE,
    STATE_SPEECH,
    SeqCounter,
    should_push_transcribing,
)


def test_should_push_transcribing_silence_to_speech_true():
    """SILENCE → SPEECH(首次进入语音)→ 应推 transcribing"""
    assert should_push_transcribing(STATE_SILENCE, STATE_SPEECH) is True


def test_should_push_transcribing_silence_to_silence_false():
    """SILENCE → SILENCE(一直静)→ 不推"""
    assert should_push_transcribing(STATE_SILENCE, STATE_SILENCE) is False


def test_should_push_transcribing_speech_to_speech_false():
    """SPEECH → SPEECH(连续语音)→ 不推(只在第一次进 SPEECH 推)"""
    assert should_push_transcribing(STATE_SPEECH, STATE_SPEECH) is False


def test_should_push_transcribing_speech_to_silence_false():
    """SPEECH → SILENCE(语音结束)→ 不推(等 ASR 结果)"""
    assert should_push_transcribing(STATE_SPEECH, STATE_SILENCE) is False


def test_allocate_seq_starts_at_one():
    """新计数器从 1 开始"""
    c = SeqCounter()
    assert c.next() == 1
    assert c.next() == 2
    assert c.next() == 3


def test_allocate_seq_independent_instances():
    """不同实例独立计数"""
    a = SeqCounter()
    b = SeqCounter()
    assert a.next() == 1
    assert b.next() == 1
    assert a.next() == 2


def test_consume_pending_returns_last_seq():
    """next() 后 consume_pending() 应返回相同的 seq"""
    c = SeqCounter()
    seq = c.next()
    assert c.consume_pending() == seq


def test_consume_pending_clears_after_consume():
    """consume_pending() 之后再次调用应返回 0(sentinel:无配对)"""
    c = SeqCounter()
    c.next()
    first = c.consume_pending()
    assert first == 1
    assert c.consume_pending() == 0
    assert c.consume_pending() == 0  # 多次调用都返 0


def test_consume_pending_returns_zero_when_no_pending():
    """全新 counter 还没 next() 时,consume_pending() 返 0"""
    c = SeqCounter()
    assert c.consume_pending() == 0


def test_pairing_semantics():
    """模拟 transcribing→ASR 配对:next() 后 consume_pending() 必须返回相同 seq

    模拟两次完整语音段:每段都 next() 推占位,ASR 完成时 consume_pending() 拿到配对 seq
    """
    c = SeqCounter()

    # 第一段
    placeholder_seq = c.next()
    assert placeholder_seq == 1
    asr_seq = c.consume_pending()
    assert asr_seq == placeholder_seq  # 配对成功

    # 第二段
    placeholder_seq = c.next()
    assert placeholder_seq == 2
    asr_seq = c.consume_pending()
    assert asr_seq == placeholder_seq  # 配对成功


def test_pending_overwritten_by_next():
    """连续 next() 不 consume:pending 会被最新 next() 覆盖(spec:同一时刻仅 1 个占位段)

    场景:ASR 失败/丢消息时,下一个 transcribing 推出来,旧 pending 被覆盖
    """
    c = SeqCounter()
    c.next()  # seq=1,pending=1
    c.next()  # seq=2,pending=2 (旧的 pending=1 被覆盖)
    assert c.consume_pending() == 2  # 只剩最新的
    assert c.consume_pending() == 0  # 清空了

