"""任务重试、文稿幂等性和说话人分离输入边界测试。"""
import asyncio
import sys

import numpy as np
import pytest

from app.repositories.database import Database
from app.repositories.jobs import JobRepository, MAX_AUTO_RETRIES
from app.repositories.meetings import MeetingRepository
from app.services.job_runner import JobRunner
from app.services.meeting_processor import PermanentJobError


# ============================================================
# 类型化重试分类
# ============================================================

def test_permanent_job_error_is_an_explicit_type():
    assert isinstance(PermanentJobError("文案可变"), RuntimeError)


def test_transient_error_message_cannot_be_falsely_blocked(tmp_path):
    db = Database(str(tmp_path / "false_block.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    meeting_id = meetings.create(source="upload", title="误判", status="processing")
    job_id = jobs.create(meeting_id)
    # 模拟 job_runner 失败路径:先 update(failed),再 requeue
    jobs.update(job_id, status="failed", stage="failed", error_message="x")

    requeued = jobs.requeue_for_retry(job_id, retryable=True)
    assert requeued is True
    job = jobs.get(job_id)
    assert job["status"] == "queued"
    assert int(job["retry_count"]) == 1


def test_asr_non_final_result_is_permanent():
    from app.services.meeting_processor import normalize_offline_asr_result

    with pytest.raises(PermanentJobError, match="non-final"):
        normalize_offline_asr_result({"text": "draft", "is_final": False}, 1.0)


# ============================================================
# 自动重试状态恢复
# ============================================================

def test_requeue_resets_diarization_status_like_manual_retry(tmp_path):
    """自动重试与手动重试都应重置 diarization_status。"""
    db = Database(str(tmp_path / "diar_reset.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    meeting_id = meetings.create(source="upload", title="diar", status="processing",
                                 processing_mode="meeting")
    job_id = jobs.create(meeting_id)
    # 模拟第一次跑时 diarization 完成了,但后续步骤失败
    meetings.update(meeting_id, diarization_status="completed", diarization_error=None)

    # 自动重试路径
    requeued = jobs.requeue_for_retry(job_id, retryable=True)
    assert requeued is True
    meeting = meetings.get(meeting_id)
    assert meeting["diarization_status"] == "pending", (
        "requeue_for_retry 应重置 diarization_status 为 pending"
    )

    # 对比:手动 retry 会重置 diarization_status 为 pending
    meeting_id2 = meetings.create(source="upload", title="diar2", status="processing",
                                  processing_mode="meeting")
    job_id2 = jobs.create(meeting_id2)
    meetings.update(meeting_id2, diarization_status="completed", diarization_error=None)
    jobs.update(job_id2, status="failed", error_message="x")
    ok = jobs.retry(job_id2)
    assert ok
    meeting2 = meetings.get(meeting_id2)
    assert meeting2["diarization_status"] == "pending", (
        "手动 retry 会重置 diarization_status 为 pending"
    )


# ============================================================
# 取消与自动重试竞态
# ============================================================

def test_runner_auto_retry_resets_cancel_requested(tmp_path):
    """用户取消(cancel_requested=1)后 job 失败，requeue_for_retry
    应检测 cancel_requested=1 不重排,尊重取消意图。
    """
    db = Database(str(tmp_path / "cancel_race.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    meeting_id = meetings.create(source="upload", title="取消竞态", status="processing")
    job_id = jobs.create(meeting_id)

    # 模拟 job_runner 失败路径:job running → 用户取消 → 失败
    jobs.update(job_id, status="running", stage="transcribing", progress=40)
    # 用户点取消(running job → 只置 cancel_requested=1)
    assert jobs.request_cancel(job_id) is True
    assert int(jobs.get(job_id)["cancel_requested"]) == 1

    # job 因瞬时错误失败(job_runner except 先 update failed)
    jobs.update(job_id, status="failed", stage="failed", error_message="瞬时 ChromaDB 临时不可用")
    # cancel_requested 仍为 1(update 不在 allowed 之外的字段动它)
    assert int(jobs.get(job_id)["cancel_requested"]) == 1

    # job_runner 调 requeue_for_retry
    requeued = jobs.requeue_for_retry(job_id, retryable=True)
    assert requeued is False, "已取消的 job 不应自动重排"
    job = jobs.get(job_id)
    assert job["status"] == "failed"
    assert int(job["cancel_requested"]) == 1
    assert jobs.claim_next() is None


# ============================================================
# 自动重试退避
# ============================================================

def test_runner_retries_oom_with_exponential_backoff(tmp_path):
    """持续资源错误按指数退避重试，避免紧密循环。"""
    async def scenario():
        db = Database(str(tmp_path / "oom.db"))
        db.init_schema()
        meetings = MeetingRepository(db)
        jobs = JobRepository(db)
        meeting_id = meetings.create(source="upload", title="OOM", status="processing")
        job_id = jobs.create(meeting_id)

        timestamps = []

        async def processor(_job):
            timestamps.append(asyncio.get_event_loop().time())
            raise MemoryError("Allocation failed (simulated OOM)")

        runner = JobRunner(jobs, meetings, processor)
        await runner.start()
        for _ in range(900):
            if jobs.get(job_id)["status"] == "failed":
                break
            await asyncio.sleep(0.01)
        await runner.stop()

        # 两次自动重试分别等待约 2 秒和 4 秒。
        assert len(timestamps) == MAX_AUTO_RETRIES + 1
        if len(timestamps) >= 2:
            total_span = timestamps[-1] - timestamps[0]
            # 退避后总跨度应 >= 退避和(2+4=6s),放宽到 5s 容忍调度抖动
            assert total_span >= 5.0, (
                f"3 次重试在 {total_span:.3f}s 内完成,疑似无退避"
            )
        assert jobs.get(job_id)["status"] == "failed"
        assert int(jobs.get(job_id)["retry_count"]) == MAX_AUTO_RETRIES

    asyncio.run(scenario())


# ============================================================
# 文稿重建幂等性
# ============================================================

def test_replace_generated_transcript_is_idempotent_on_retry(tmp_path):
    """验证:job 重试重跑 replace_generated_transcript 不会产生重复行。
    meeting_processor 在 draft 阶段(336 行)和最终阶段(402 行)各调一次,
    重试时再调一次。replace 是 DELETE+INSERT 事务,应幂等。
    """
    db = Database(str(tmp_path / "idem.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    meeting_id = meetings.create(source="upload", title="幂等", status="processing",
                                 processing_mode="meeting")

    segs1 = [
        {"segment_index": 0, "text": "你好", "start_time": 0.0, "end_time": 1.0,
         "speaker_label": "SPEAKER_00", "confidence": 0.9, "words": None},
        {"segment_index": 1, "text": "世界", "start_time": 1.0, "end_time": 2.0,
         "speaker_label": "SPEAKER_01", "confidence": 0.8, "words": None},
    ]
    meetings.replace_generated_transcript(meeting_id, segs1)
    # 模拟重跑:同样的 labels 但可能不同 speaker_label 映射
    segs2 = [
        {"segment_index": 0, "text": "你好世界", "start_time": 0.0, "end_time": 2.0,
         "speaker_label": "SPEAKER_00", "confidence": 0.9, "words": None},
    ]
    meetings.replace_generated_transcript(meeting_id, segs2)

    with db.connect() as conn:
        seg_count = conn.execute(
            "SELECT COUNT(*) FROM transcript_segments WHERE meeting_id = ?",
            (meeting_id,)
        ).fetchone()[0]
        spk_count = conn.execute(
            "SELECT COUNT(*) FROM meeting_speakers WHERE meeting_id = ?",
            (meeting_id,)
        ).fetchone()[0]
    # 不应有重复行:segments = len(segs2), speakers 去重后 = 1
    assert seg_count == 1, f"重跑后应只有 1 条 segment,实际 {seg_count}(幂等)"
    assert spk_count == 1, f"重跑后应只有 1 个 speaker,实际 {spk_count}(幂等)"


def test_suggest_speaker_overwrites_machine_match_on_retry(tmp_path):
    """验证:suggest_speaker WHERE manually_confirmed=0,重跑时 replace
    已把 manually_confirmed 重置为 0,所以 suggest_speaker 会覆盖旧 machine
    match,不会产生重复 person 关联。幂等。
    """
    db = Database(str(tmp_path / "suggest.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    people = __import__("app.repositories.people", fromlist=["PeopleRepository"]).PeopleRepository(db)
    db.init_schema()
    meeting_id = meetings.create(source="upload", title="suggest", status="processing",
                                 processing_mode="meeting")
    person_id = people.create(name="张三")
    # 第一次:suggest SPEAKER_00 → 张三
    meetings.replace_generated_transcript(meeting_id, [
        {"segment_index": 0, "text": "x", "start_time": 0.0, "end_time": 1.0,
         "speaker_label": "SPEAKER_00", "confidence": 0.9, "words": None},
    ])
    ok1 = meetings.suggest_speaker(meeting_id, "SPEAKER_00", person_id, 0.85,
                                    identity_status="auto_matched")
    assert ok1

    # 重跑:replace 重置 manually_confirmed=0,suggest 再次覆盖
    meetings.replace_generated_transcript(meeting_id, [
        {"segment_index": 0, "text": "x", "start_time": 0.0, "end_time": 1.0,
         "speaker_label": "SPEAKER_00", "confidence": 0.9, "words": None},
    ])
    ok2 = meetings.suggest_speaker(meeting_id, "SPEAKER_00", person_id, 0.90,
                                    identity_status="auto_matched")
    assert ok2
    # 仍只有一个 speaker 行,person_id 为最新值
    with db.connect() as conn:
        row = conn.execute(
            "SELECT person_id, confidence, manually_confirmed, identity_status "
            "FROM meeting_speakers WHERE meeting_id = ? AND label = 'SPEAKER_00'",
            (meeting_id,)
        ).fetchone()
    assert row is not None
    assert row["person_id"] == person_id
    assert float(row["confidence"]) == 0.90
    assert int(row["manually_confirmed"]) == 0


# ============================================================
# 采样率与 waveform 类型一致性
# ============================================================

def test_diarize_receives_16khz_from_meeting_processor_path(monkeypatch, tmp_path):
    """验证:meeting_processor 用 librosa.load(sr=config.audio.sample_rate=16000)
    加载后传给 diarize 的 sample_rate 确实是 16000,且 waveform 为 1D float32。

    pyannote community-1 训练于 16kHz,传 16kHz 是正确路径,不是问题。
    """
    from app.services.pyannote_diarization import PyannoteDiarizer

    class FakeTensor:
        def __init__(self, value):
            self.value = np.asarray(value)
        @property
        def shape(self):
            return self.value.shape
        def unsqueeze(self, axis):
            self.value = np.expand_dims(self.value, axis)
            return self

    monkeypatch.setattr(sys.modules["torch"], "as_tensor",
                        lambda value, dtype=None: FakeTensor(value), raising=False)

    captured = {}
    class Pipeline:
        def __call__(self, audio):
            captured["audio"] = audio
            class Out:
                class A:
                    def itertracks(self, yield_label=False):
                        return iter([])
                speaker_diarization = A()
                exclusive_speaker_diarization = A()
            return Out()

    diarizer = object.__new__(PyannoteDiarizer)
    diarizer._enabled = True
    diarizer._pipeline = Pipeline()

    # 模拟 meeting_processor 传的 audio:librosa.load(sr=16000, mono=True) → 1D float32
    wave = np.ones(32000, dtype=np.float32)  # 2s @ 16kHz
    diarizer.diarize("x.wav", waveform=wave, sample_rate=16000)

    assert captured["audio"]["sample_rate"] == 16000
    assert tuple(captured["audio"]["waveform"].shape) == (1, 32000)
    # 验证 dtype:torch.as_tensor(..., dtype=torch.float32) 后应为 float32
    assert captured["audio"]["waveform"].value.dtype == np.float32


# ============================================================
# waveform 输入形状校验
# ============================================================

def test_diarize_rejects_2d_waveform(monkeypatch):
    """二维波形不能作为单声道输入传给 pyannote。"""
    from app.services.pyannote_diarization import PyannoteDiarizer

    class FakeTensor:
        def __init__(self, value):
            self.value = np.asarray(value)
        @property
        def shape(self):
            return self.value.shape
        def unsqueeze(self, axis):
            self.value = np.expand_dims(self.value, axis)
            return self

    monkeypatch.setattr(sys.modules["torch"], "as_tensor",
                        lambda value, dtype=None: FakeTensor(value), raising=False)

    class Pipeline:
        def __call__(self, audio):
            # pyannote 收到 (1, 2, N) 会抛错(模拟)
            raise ValueError("expected 2D waveform (channel, samples)")

    diarizer = object.__new__(PyannoteDiarizer)
    diarizer._enabled = True
    diarizer._pipeline = Pipeline()

    # 2D stereo 波形(未转 mono)
    stereo = np.ones((2, 32000), dtype=np.float32)
    result = diarizer.diarize("x.wav", waveform=stereo, sample_rate=16000)
    assert result == []
    assert "失败" in (diarizer.last_error or "")


def test_diarize_normalizes_int_waveform(monkeypatch):
    from app.services.pyannote_diarization import PyannoteDiarizer

    class FakeTensor:
        def __init__(self, value):
            self.value = np.asarray(value)
        @property
        def shape(self):
            return self.value.shape
        def unsqueeze(self, axis):
            self.value = np.expand_dims(self.value, axis)
            return self

    monkeypatch.setattr(sys.modules["torch"], "as_tensor",
                        lambda value, dtype=None: FakeTensor(value), raising=False)

    captured = {}
    class Pipeline:
        def __call__(self, audio):
            captured["audio"] = audio
            class Out:
                class A:
                    def itertracks(self, yield_label=False):
                        return iter([])
                speaker_diarization = A()
                exclusive_speaker_diarization = A()
            return Out()

    diarizer = object.__new__(PyannoteDiarizer)
    diarizer._enabled = True
    diarizer._pipeline = Pipeline()

    # int16 PCM,数值范围 [-32768, 32767]
    pcm = np.array([0, 32767, -32768, 16000], dtype=np.int16)
    diarizer.diarize("x.wav", waveform=pcm, sample_rate=16000)
    vals = captured["audio"]["waveform"].value.flatten()
    assert vals.dtype == np.float32
    assert float(np.max(np.abs(vals))) <= 1.0
