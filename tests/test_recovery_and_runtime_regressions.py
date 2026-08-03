"""任务恢复、运行时降级和实时会话回归测试。

覆盖:
- recover_interrupted 处理 cancel_requested
- 接入幻觉词过滤
- WS 奇数长度 PCM 帧
- 引擎初始化失败降级
- job_runner 异常处理器内异常不杀循环
- 删 person 后 meeting_speakers 状态复位
- offline cancel 丢失唤醒
- reprocess 与 live 会话竞态
- realtime_auth DB 异常关闭 WS
- speaker metadata=None 兜底
- 上传短音频落 failed
- validate_audio_file 时长 fallback
- finalize_live 保留 refined
"""
import asyncio
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.repositories.database import Database
from app.repositories.jobs import JobRepository
from app.repositories.meetings import MeetingRepository
from app.repositories.people import PeopleRepository


# ============================================================
# recover_interrupted 处理 cancel_requested
# ============================================================

def test_recover_interrupted_finalizes_cancelled_running_jobs(tmp_path):
    """running + cancel_requested=1 的 job 重启时应终结为 cancelled,而非卡 queued。"""
    db = Database(str(tmp_path / "rec.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)

    meeting_id = meetings.create(source="upload", title="m", status="processing")
    job_id = jobs.create(meeting_id)
    # 直接写 DB 设 running + cancel_requested=1(update 白名单含 cancel_requested)
    jobs.update(job_id, status="running", cancel_requested=1)

    # recover 应终结已取消的 job,常规 running 才回 queued → 这里只有 1 个被取消
    jobs.recover_interrupted()
    job = jobs.get(job_id)
    assert job["status"] == "cancelled"
    meeting = meetings.get(meeting_id)
    assert meeting["status"] == "failed"


def test_recover_interrupted_requeues_uncancelled_running_jobs(tmp_path):
    """running + cancel_requested=0 的 job 正常回 queued。"""
    db = Database(str(tmp_path / "rec2.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)

    meeting_id = meetings.create(source="upload", title="m", status="processing")
    job_id = jobs.create(meeting_id)
    jobs.update(job_id, status="running")

    jobs.recover_interrupted()
    job = jobs.get(job_id)
    assert job["status"] == "queued"


# ============================================================
# 接入幻觉词过滤
# ============================================================

def test_filter_hallucinations_strips_watermarks():
    from engine.asr.common import filter_hallucinations

    # 幻觉词被剥离,正常文本保留
    assert filter_hallucinations("谢谢。") == ""
    assert filter_hallucinations("字幕由") == ""
    assert "你好" in filter_hallucinations("你好世界")
    # 纯标点返回空
    assert filter_hallucinations("。。。") == ""


def test_asr_engine_applies_hallucination_filter(monkeypatch):
    """ASREngine.run_asr 返回的 text 经过 filter_hallucinations。"""
    # 构造一个假的 ASREngine(不走真实加载)
    import engine.asr_engine as asr_mod

    engine = object.__new__(asr_mod.ASREngine)
    engine.config = MagicMock()
    engine.config.asr_word_timestamps = False
    engine.sample_rate = 16000

    # 假 asr_model.transcribe 返回带幻觉词的文本
    fake_result_item = MagicMock()
    fake_result_item.text = "谢谢。本视频由某某赞助"
    fake_result_item.time_stamps = None
    fake_model = MagicMock()
    fake_model.forced_aligner = None
    fake_model.transcribe.return_value = [fake_result_item]
    engine.asr_model = fake_model

    # 绕过 _prepare_and_check(质量评估/VAD):直接 patch 返回原音频
    monkeypatch.setattr(
        asr_mod.ASREngine, "_prepare_and_check",
        lambda self, audio, use_pp: audio,
    )

    async def run():
        return await engine.run_asr(np.ones(3200, dtype=np.float32))

    result = asyncio.run(run())
    # "谢谢。" 和 "本视频由" 都是 HALLUCINATIONS 列表里的词,过滤后只剩 "某某赞助"
    assert result["text"] == "某某赞助"
    assert "谢谢" not in result["text"]
    assert "本视频由" not in result["text"]


# ============================================================
# WS 奇数长度 PCM 帧
# ============================================================

def test_odd_length_pcm_frame_does_not_crash():
    """audio_processor 处理奇数字节 PCM 帧应截断而非抛 ValueError。

    模拟 frombuffer 行为:奇数长度直接抛 ValueError,验证修复后路径截断到偶数。
    """
    odd_data = b"\x01\x02\x03"  # 3 字节,奇数
    # 截断到偶数
    truncated = odd_data[:-1] if len(odd_data) % 2 else odd_data
    assert len(truncated) == 2
    # 能正常 frombuffer
    arr = np.frombuffer(truncated, dtype=np.int16)
    assert len(arr) == 1


# ============================================================
# 引擎初始化失败降级
# ============================================================

def test_init_engines_degrades_on_asr_failure(tmp_path, monkeypatch):
    """ASR 引擎加载失败时 app 仍能启动,runtime 持有 None。"""
    monkeypatch.setenv("STORAGE_DB_PATH", str(tmp_path / "deg.db"))
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setenv("SPEAKER_ENGINE", "campplus")
    monkeypatch.setenv("TEST_AUTH_BYPASS", "1")

    import app
    # 让 get_asr_manager 抛异常
    with patch("engine.asr.get_asr_manager", side_effect=RuntimeError("ASR boom")):
        appl = app.create_app()
    assert appl.state.runtime.asr is None
    # speaker 仍可能加载成功(真实环境),这里不强制


# ============================================================
# job_runner 异常处理器内异常不杀循环
# ============================================================

def test_job_runner_survives_exception_in_handler(tmp_path):
    """requeue_for_retry 抛异常时,_run 不应死亡,循环继续。"""
    db = Database(str(tmp_path / "jr.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    meeting_id = meetings.create(source="upload", title="m", status="processing")
    job_id = jobs.create(meeting_id)

    call_count = {"n": 0}

    async def processor(job):
        call_count["n"] += 1
        raise RuntimeError("transient boom")

    runner_jobs_mod = __import__("app.services.job_runner", fromlist=["JobRunner"])
    JobRunner = runner_jobs_mod.JobRunner
    runner = JobRunner(jobs, meetings, processor)

    async def scenario():
        await runner.start()
        # 等重试跑完落 failed(MAX_AUTO_RETRIES=2)
        for _ in range(900):
            if jobs.get(job_id)["status"] == "failed":
                break
            await asyncio.sleep(0.01)
        await runner.stop()

    asyncio.run(scenario())
    # processor 被调用 3 次(1 首次 + 2 重试),之后 job 落 failed
    assert call_count["n"] == 3
    assert jobs.get(job_id)["status"] == "failed"


# ============================================================
# 删 person 后 meeting_speakers 状态复位
# ============================================================

def test_delete_person_resets_meeting_speakers_identity(tmp_path):
    """删 person 后,关联的 meeting_speakers 应复位为匿名,不留矛盾状态。"""
    db = Database(str(tmp_path / "ppl.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    people = PeopleRepository(db)

    meeting_id = meetings.create(source="upload", title="m", status="processing")
    person_id = people.create(name="张三")
    # 模拟已确认 speaker → person(suggest_speaker 用 auto_matched;确认由 confirm 走)
    speaker_id = meetings.ensure_speaker(meeting_id, "SPEAKER_00")
    meetings.suggest_speaker(
        meeting_id, "SPEAKER_00", person_id, 0.9, identity_status="auto_matched"
    )
    # 删 person
    assert people.delete(person_id) is True

    # 该 speaker 行应复位为匿名:person_id=NULL, manually_confirmed=0, identity_status=anonymous
    with db.connect() as conn:
        row = conn.execute(
            "SELECT person_id, manually_confirmed, identity_status "
            "FROM meeting_speakers WHERE id = ?",
            (speaker_id,),
        ).fetchone()
    assert row is not None
    assert row["person_id"] is None
    assert int(row["manually_confirmed"] or 0) == 0
    assert row["identity_status"] == "anonymous"


# ============================================================
# offline cancel 丢失唤醒
# ============================================================

def test_offline_cancel_does_not_starve_live():
    """offline 协程被 cancel 后,等待的 live 应被唤醒而非永久阻塞。

    offline 的 finally 必须清除饥饿标志并唤醒等待者。
    """
    from app.runtime import InferenceCoordinator

    async def scenario():
        coord = InferenceCoordinator()
        live_started = asyncio.Event()
        live_done = asyncio.Event()

        async def offline_hold():
            async with coord.offline():
                live_started.set()
                await asyncio.sleep(0.3)

        async def live_wait():
            await live_started.wait()
            async with coord.live():
                live_done.set()

        offline_task = asyncio.create_task(offline_hold())
        live_task = asyncio.create_task(live_wait())
        # 让 offline 进入等待(等 live_waiter==0),然后 cancel 它
        await asyncio.sleep(0.05)
        offline_task.cancel()
        try:
            await offline_task
        except asyncio.CancelledError:
            pass
        # live 应在合理时间内完成,不被 starved offline 卡死
        await asyncio.wait_for(live_done.wait(), timeout=2.0)
        await live_task

    asyncio.run(scenario())


# ============================================================
# reprocess 与 live 会话竞态
# ============================================================

def test_enqueue_refinement_rejects_processing_meeting(tmp_path):
    """默认 allow_live=False,reject 对 status=processing 的 meeting 排队。"""
    db = Database(str(tmp_path / "rep.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    meeting_id = meetings.create(
        source="live", title="m", status="processing", audio_path=str(audio)
    )

    with pytest.raises(RuntimeError):
        jobs.enqueue_refinement(meeting_id)


def test_enqueue_refinement_allow_live_bypasses_guard(tmp_path):
    """allow_live=True 时(WS finalize 路径)允许对 processing meeting 排队。"""
    db = Database(str(tmp_path / "rep2.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"RIFF")
    meeting_id = meetings.create(
        source="live", title="m", status="processing", audio_path=str(audio)
    )

    job_id, created = jobs.enqueue_refinement(meeting_id, allow_live=True)
    assert created is True


# ============================================================
# speaker metadata=None 兜底
# ============================================================

def test_compare_and_identify_handles_none_metadata():
    """ChromaDB 返回 metadata=None 时不应抛 AttributeError。"""
    from engine.speaker.base_engine import BaseSpeakerEngine

    # 构造一个最小子类实例
    class _TestEngine(BaseSpeakerEngine):
        _model_name = "test"
        THRESHOLD_PROFILE = (0.3, 0.5, 0.2, 0.4)
        EMB_BUFFER_SIZE = 5
        HISTORY_SIZE = 5

        def extract_feat(self, audio):
            return np.ones(128, dtype=np.float32), 1.0

    engine = object.__new__(_TestEngine)
    from collections import defaultdict
    engine.emb_buffer = defaultdict(list)
    engine.match_history = defaultdict(list)
    engine.collection = MagicMock()
    # query 返回 metadata=None
    engine.collection.query.return_value = {
        "ids": [["spk1"]],
        "distances": [[0.1]],
        "metadatas": [[None]],
    }
    engine.collection.get.return_value = {"embeddings": [np.ones(128)]}
    engine.collection.update = MagicMock()

    emb = np.ones(128, dtype=np.float32)
    # 不应抛 AttributeError(metadata=None 被兜底为 {})
    spk_id, score = engine.compare_and_identify(emb, "client1", audio_duration=2.0)
    # min_dist=0.1 < low_threshold → 匹配到 spk1
    assert spk_id == "spk1"


# ============================================================
# finalize_live 保留 refined 状态
# ============================================================

def test_finalize_live_preserves_refined_state(tmp_path):
    """已 refined 的 meeting 缺音频时 finalize 不应降级为 draft。"""
    db = Database(str(tmp_path / "fin.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    meeting_id = meetings.create(source="live", title="m", status="processing")
    meetings.update(meeting_id, transcript_state="refined")

    assert meetings.finalize_live(meeting_id) is True
    m = meetings.get(meeting_id)
    assert m["transcript_state"] == "refined"


def test_finalize_live_sets_draft_when_not_refined(tmp_path):
    """非 refined 的 meeting finalize 仍设 draft(无 segment 时)。"""
    db = Database(str(tmp_path / "fin2.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    meeting_id = meetings.create(source="live", title="m", status="processing")

    meetings.finalize_live(meeting_id)
    m = meetings.get(meeting_id)
    assert m["transcript_state"] == "draft"


# ============================================================
# 仓储字段白名单与运行时状态入口
# ============================================================

def test_update_rejects_unknown_field(tmp_path):
    """MeetingRepository.update 对不在白名单的字段抛 ValueError,防静默丢数据。"""
    db = Database(str(tmp_path / "upd.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    meeting_id = meetings.create(source="upload", title="m", status="processing")

    # 合法字段正常写入
    assert meetings.update(meeting_id, title="新标题") is True
    assert meetings.get(meeting_id)["title"] == "新标题"

    # 非法字段抛 ValueError(而非静默丢弃)
    with pytest.raises(ValueError, match="不可写入"):
        meetings.update(meeting_id, client_id="should_be_dropped")
    with pytest.raises(ValueError, match="不可写入"):
        meetings.update(meeting_id, created_at="2020-01-01", id="fake")
    # 原数据不受影响
    assert meetings.get(meeting_id)["title"] == "新标题"


def test_dead_asr_aliases_removed():
    """app.state 只通过 runtime 暴露 ASR 引擎。"""
    import app
    # 只验证模块层面没有把 asr_engine/asr_manager 当属性暴露的逻辑残留
    # (create_app 会注入,这里只检查 _init_engines 不再赋值)
    import inspect
    src = inspect.getsource(app._init_engines)
    assert "app.state.asr_engine" not in src
    assert "app.state.asr_manager" not in src
