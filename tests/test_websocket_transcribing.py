"""WebSocket transcribing 占位消息 — 纯函数测试

对应 app/api/websocket.py 抽出的:
- should_push_transcribing: 在 SILENCE→SPEECH 状态切换时返回 True
- SeqCounter: 单调递增 seq 分配
"""
import sys

sys.path.insert(0, "/Users/lgy/python/github.com/lgy1027/matrix-live-diarizer")

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

