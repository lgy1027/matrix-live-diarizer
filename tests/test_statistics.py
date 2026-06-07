from app.services.statistics import compute_statistics


def test_basic_speaker_talk_time():
    segs = [
        {"speaker_id": "A", "text": "x", "start_time": 0.0, "end_time": 10.0},
        {"speaker_id": "B", "text": "y", "start_time": 12.0, "end_time": 15.0},
    ]
    stats = compute_statistics(segs, total_duration_sec=20.0)
    assert stats["speech_duration_sec"] == 13.0
    assert stats["silence_duration_sec"] == 7.0
    assert abs(stats["silence_ratio"] - 0.35) < 0.001

    speakers_by_id = {s["speaker_id"]: s for s in stats["speakers"]}
    assert speakers_by_id["A"]["talk_time_sec"] == 10.0
    assert speakers_by_id["B"]["talk_time_sec"] == 3.0
    assert speakers_by_id["A"]["segment_count"] == 1


def test_turn_taking_count():
    segs = [
        {"speaker_id": "A", "text": "1", "start_time": 0.0, "end_time": 1.0},
        {"speaker_id": "A", "text": "2", "start_time": 1.0, "end_time": 2.0},
        {"speaker_id": "B", "text": "3", "start_time": 2.0, "end_time": 3.0},
        {"speaker_id": "A", "text": "4", "start_time": 3.0, "end_time": 4.0},
    ]
    stats = compute_statistics(segs, total_duration_sec=4.0)
    # A→A 不算，A→B 算 1 次，B→A 算 1 次 = 2
    assert stats["turn_taking_count"] == 2


def test_word_count_per_speaker_chinese_and_english():
    segs = [
        {"speaker_id": "A", "text": "你好 world", "start_time": 0.0, "end_time": 1.0},
        {"speaker_id": "A", "text": "今天天气", "start_time": 1.0, "end_time": 2.0},
    ]
    stats = compute_statistics(segs, total_duration_sec=2.0)
    speakers_by_id = {s["speaker_id"]: s for s in stats["speakers"]}
    # 中文字符 + 英文单词 = 2 + 1 + 2 = 5
    assert speakers_by_id["A"]["word_count"] == 5


def test_hot_words_chinese():
    segs = [
        {"speaker_id": "A", "text": "项目 项目 项目", "start_time": 0.0, "end_time": 1.0},
        {"speaker_id": "A", "text": "会议", "start_time": 1.0, "end_time": 2.0},
    ]
    stats = compute_statistics(segs, total_duration_sec=2.0)
    words = {w["word"]: w["count"] for w in stats["hot_words"]}
    assert words.get("项目") == 3
    assert words.get("会议") == 1


def test_hot_words_excludes_stop_words():
    segs = [
        {"speaker_id": "A", "text": "的 了 是", "start_time": 0.0, "end_time": 1.0},
        {"speaker_id": "A", "text": "项目", "start_time": 1.0, "end_time": 2.0},
    ]
    stats = compute_statistics(segs, total_duration_sec=2.0)
    words = {w["word"] for w in stats["hot_words"]}
    assert "的" not in words
    assert "了" not in words
    assert "项目" in words


def test_empty_segments():
    stats = compute_statistics([], total_duration_sec=0.0)
    assert stats["speech_duration_sec"] == 0.0
    assert stats["silence_ratio"] == 0.0
    assert stats["speakers"] == []
    assert stats["hot_words"] == []


def test_speaker_display_name_lookup():
    segs = [{"speaker_id": "Spk_001", "text": "x", "start_time": 0.0, "end_time": 1.0}]
    stats = compute_statistics(
        segs, total_duration_sec=1.0, speaker_aliases={"Spk_001": "张三"}
    )
    assert stats["speakers"][0]["display_name"] == "张三"
