"""安全、资源、数据一致性和输入契约回归测试。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.repositories.database import Database
from app.repositories.jobs import JobRepository
from app.repositories.meetings import MeetingRepository


# ============================================================
# /ready not_ready 返 503
# ============================================================

def test_ready_returns_503_without_engines():
    """无引擎时 /ready 应返 503(就绪探针按状态码分流)。"""
    app = FastAPI()
    from app.api.health import router as health_router
    app.include_router(health_router)
    client = TestClient(app)
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"


# ============================================================
# LLM endpoint 校验:拒绝 link-local / CGNAT
# ============================================================

def test_validate_endpoint_rejects_link_local():
    from app.services.llm_gateway import _validate_endpoint, EndpointSecurityError
    with pytest.raises(EndpointSecurityError):
        _validate_endpoint("http://169.254.169.254/latest/", ())


def test_validate_endpoint_rejects_cgcnat():
    from app.services.llm_gateway import _validate_endpoint, EndpointSecurityError
    with pytest.raises(EndpointSecurityError):
        _validate_endpoint("http://100.64.0.5/v1", ())


def test_validate_endpoint_allows_private_lan():
    from app.services.llm_gateway import _validate_endpoint
    # 10/8 私网允许,返回解析到的 IP(供 DNS pinning)
    ip = _validate_endpoint("http://10.0.0.5/v1", ())
    assert ip == "10.0.0.5"


def test_validate_endpoint_allows_whitelisted_host():
    from app.services.llm_gateway import _validate_endpoint
    # allowed_hosts 命中 → 不做 IP 校验,返 None
    assert _validate_endpoint("http://localhost/v1", ("localhost",)) is None


# ============================================================
# finalize_live 缺音频标 failed
# ============================================================

def test_finalize_live_marks_failed_when_audio_missing(tmp_path):
    db = Database(str(tmp_path / "fin.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    meeting_id = meetings.create(
        source="live", title="m", status="processing",
        audio_path=str(tmp_path / "missing.wav"),
    )
    # 写一段转写,但有段无音频文件 → failed 而非 ready
    meetings.insert_segment(
        meeting_id, segment_index=0, text="hi",
        start_time=0.0, end_time=1.0, speaker_label="SPEAKER_00",
    )
    assert meetings.finalize_live(meeting_id) is True
    m = meetings.get(meeting_id)
    assert m["status"] == "failed"
    assert "缺失" in (m["error_message"] or "")


# ============================================================
# recover_interrupted 恢复无 job 的 live 孤儿会议
# ============================================================

def test_recover_interrupted_finalizes_orphan_live_meeting(tmp_path):
    db = Database(str(tmp_path / "orphan.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    # 崩溃残留:live 会议卡 processing,无 job
    meeting_id = meetings.create(source="live", title="m", status="processing")

    jobs.recover_interrupted()
    m = meetings.get(meeting_id)
    assert m["status"] == "failed"


# ============================================================
# mark_completed 同事务标记 meeting ready + job completed
# ============================================================

def test_mark_completed_sets_meeting_ready_and_job_completed(tmp_path):
    db = Database(str(tmp_path / "mc.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    meeting_id = meetings.create(source="upload", title="m", status="processing")
    job_id = jobs.create(meeting_id)
    jobs.update(job_id, status="running")

    meetings.mark_completed(meeting_id, job_id, "2026-07-31T00:00:00+00:00")

    assert meetings.get(meeting_id)["status"] == "ready"
    assert jobs.get(job_id)["status"] == "completed"


# ============================================================
# split_speaker 只移动属于 source 的 segment
# ============================================================

def test_split_speaker_only_moves_owned_segments(tmp_path):
    db = Database(str(tmp_path / "split.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    meeting_id = meetings.create(source="upload", title="m", status="ready")
    spk_a = meetings.ensure_speaker(meeting_id, "A")
    spk_b = meetings.ensure_speaker(meeting_id, "B")
    seg_a = meetings.insert_segment(
        meeting_id, segment_index=0, text="a",
        start_time=0.0, end_time=1.0, speaker_label="A",
    )
    # 用 B 作 source 拆 A 的 segment:WHERE 过滤后不应移动
    new_id = meetings.split_speaker(meeting_id, spk_b, [seg_a])
    with db.connect() as conn:
        row = conn.execute(
            "SELECT meeting_speaker_id FROM transcript_segments WHERE id = ?",
            (seg_a,),
        ).fetchone()
        new_count = conn.execute(
            "SELECT COUNT(*) FROM transcript_segments WHERE meeting_speaker_id = ?",
            (new_id,),
        ).fetchone()[0]
    assert row["meeting_speaker_id"] == spk_a  # 仍属 A,未被移动
    assert new_count == 0  # 新 speaker 无 segment


# ============================================================
# LIKE 通配符转义
# ============================================================

def test_search_escapes_like_wildcards(tmp_path):
    db = Database(str(tmp_path / "like.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    meetings.create(source="upload", title="普通标题", status="ready")
    meetings.create(source="upload", title="100%off", status="ready")
    # q="%" 应只匹配标题含字面 % 的,而非返回全部
    total, rows = meetings.list(q="%")
    assert total == 1
    assert rows[0]["title"] == "100%off"
    # q="_" 同理:无标题含字面 _ → 0
    total2, _ = meetings.list(q="_")
    assert total2 == 0


def test_search_like_fallback_escapes_wildcards(tmp_path):
    """search() 的 LIKE 兜底分支也应转义通配符,与 list() 一致。

    search 基于 transcript_segments JOIN meetings,故给两个会议各插一段,
    只有一段文本含字面 %。
    """
    db = Database(str(tmp_path / "search-like.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    mid_a = meetings.create(source="upload", title="a", status="ready")
    mid_b = meetings.create(source="upload", title="b", status="ready")
    meetings.insert_segment(
        mid_a, segment_index=0, text="折扣100%off", start_time=0.0, end_time=1.0,
        speaker_label="A",
    )
    meetings.insert_segment(
        mid_b, segment_index=0, text="普通文本", start_time=0.0, end_time=1.0,
        speaker_label="A",
    )
    # q="%" 转义后应只匹配含字面 % 的 segment,而非返回全部
    hits = meetings.search(q="%")
    texts = {h["text"] for h in hits}
    assert "折扣100%off" in texts
    assert "普通文本" not in texts, f"LIKE 兜底未转义通配符: {texts}"


def test_search_fts_malformed_operator_does_not_500(tmp_path):
    """裸 FTS5 操作符 NOT 不应触发 OperationalError,降级到 LIKE 兜底。"""
    db = Database(str(tmp_path / "search-fts.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    meetings.create(source="upload", title="会议", status="ready")
    meetings.insert_segment(
        meetings.create(source="upload", title="m2", status="ready"),
        segment_index=0, text="NOT 操作符测试 hello",
        start_time=0.0, end_time=1.0, speaker_label="A",
    )
    # 不应抛 OperationalError
    results = meetings.search(q="NOT")
    assert isinstance(results, list)


def test_filter_hallucinations_preserves_brand_and_role_words():
    """裸品牌词/职衔词不应被幻觉过滤误删(会议正常文本高频出现)。"""
    from engine.asr.common import filter_hallucinations
    # 含导演/YouTube/B站 的正常会议文本应保留
    assert "导演" in filter_hallucinations("谢谢导演在 YouTube 分享")
    assert "YouTube" in filter_hallucinations("感谢导演在 YouTube 分享")
    # 水印句级短语仍被过滤
    assert filter_hallucinations("谢谢。") == ""
    assert filter_hallucinations("字幕由") == ""


def test_meetings_delete_does_not_raise_nameerror(tmp_path):
    """delete() 在音频文件不可访问时不应因 logger 未定义抛 NameError。"""
    db = Database(str(tmp_path / "del.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    # audio_path 指向一个不可删除的路径(权限场景):应吞掉异常返 True
    meeting_id = meetings.create(
        source="upload", title="m", status="ready",
        audio_path=str(tmp_path / "nope" / "missing.wav"),
    )
    # 不应抛 NameError;会议行已删 → True
    assert meetings.delete(meeting_id) is True
    assert meetings.get(meeting_id) is None


# ============================================================
# 限流字典上界淘汰
# ============================================================

def test_rate_limit_sweep_evicts_when_over_capacity():
    from app.middleware.rate_limit import RateLimitMiddleware
    mw = RateLimitMiddleware.__new__(RateLimitMiddleware)
    mw.requests = {}
    mw._max_tracked_ips = 3
    # 填 5 个 IP,触发淘汰到 3
    import time
    base = time.time()
    for i in range(5):
        mw.requests[f"10.0.0.{i}"] = [(base + i, "/v1/x")]
    mw._sweep_tracked()
    assert len(mw.requests) <= 3
    # 最近访问的应保留(i=4,3,2)
    assert "10.0.0.4" in mw.requests
    assert "10.0.0.0" not in mw.requests


# ============================================================
# MeetingUpdate 空标题拒收
# ============================================================

def test_meeting_update_rejects_blank_title():
    from app.api.meetings import MeetingUpdate
    with pytest.raises(Exception):
        MeetingUpdate(title="   ")


# ============================================================
# logout 注销 token(进程内 revoked 集合)
# ============================================================

def test_revoke_token_makes_it_invalid(tmp_path):
    db = Database(str(tmp_path / "auth.db"))
    db.init_schema()
    from app.services.auth import AuthService
    auth = AuthService(db)
    token = auth.create_token(1, "admin", pwd_iat=0)
    assert auth.decode_token(token) is not None
    assert not auth.is_revoked(token)
    auth.revoke_token(token)
    assert auth.is_revoked(token) is True


# ============================================================
# jobs prune:每 meeting 保留最近 N 个已完成
# ============================================================

def test_prune_finished_keeps_recent_per_meeting(tmp_path):
    db = Database(str(tmp_path / "prune.db"))
    db.init_schema()
    meetings = MeetingRepository(db)
    jobs = JobRepository(db)
    mid = meetings.create(source="upload", title="m", status="processing")
    for _ in range(7):
        jid = jobs.create(mid)
        jobs.update(jid, status="completed")
    deleted = jobs.prune_finished(keep_per_meeting=5)
    assert deleted == 2
    with db.connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM processing_jobs WHERE meeting_id = ?", (mid,)
        ).fetchone()[0]
    assert n == 5


# ============================================================
# revoke_token:只接受合法 JWT + 过期清理
# ============================================================

def test_revoke_token_rejects_arbitrary_strings(tmp_path):
    """logout 端点在鉴权白名单内,revoke 必须先 decode 校验,防任意串投毒撑爆内存。"""
    db = Database(str(tmp_path / "auth2.db"))
    db.init_schema()
    from app.services.auth import AuthService
    auth = AuthService(db)
    # 任意非 JWT 字符串不应入集合
    auth.revoke_token("not-a-jwt-arbitrary-string-8KB" * 100)
    assert len(auth._revoked_tokens) == 0
    # 合法 token 入集合
    token = auth.create_token(1, "admin", pwd_iat=0)
    auth.revoke_token(token)
    assert auth.is_revoked(token)


# ============================================================
# LLMSettingsRequest:provider/model 空白被拒
# ============================================================

def test_llm_settings_rejects_blank_provider_model():
    from app.api.llm import LLMSettingsRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        LLMSettingsRequest(provider="   ", endpoint="http://x/v1", model="m")
    with pytest.raises(ValidationError):
        LLMSettingsRequest(provider="ollama", endpoint="http://x/v1", model="   ")


# ============================================================
# 实时 WAV 上限:超限停止写盘
# ============================================================

def test_append_live_audio_caps_at_max_duration(monkeypatch, tmp_path):
    """实时录音超过 upload_max_duration 上限后,_append_live_audio 停止写盘。"""
    import app.api.websocket as ws_mod

    class _FakeWriter:
        def __init__(self):
            self.written = b""
        def writeframesraw(self, b):
            self.written += b
        def close(self):
            pass

    writer = _FakeWriter()
    websocket = type("W", (), {})()
    websocket._audio_writer = writer
    websocket._received_audio_samples = 10 * 16000 * 2 + 1  # 超 10s(假设 max=10s)
    websocket._meeting_id = "m1"
    # 不触发 _ensure_live_meeting(应因上限提前 return)
    websocket.app = None

    monkeypatch.setattr(ws_mod.config.audio, "upload_max_duration", 10)
    monkeypatch.setattr(ws_mod.config.audio, "sample_rate", 16000)

    import asyncio
    asyncio.run(ws_mod._append_live_audio(websocket, "c1", b"\x00" * 320))
    # 超限后 writer 未被写入
    assert writer.written == b""
    assert getattr(websocket, "_live_audio_capped", False) is True
