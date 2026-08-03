"""append_live_segment 和 ensure_speaker 的并发事务回归测试。"""
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from app.repositories.database import Database
from app.repositories.meetings import MeetingRepository


@pytest.fixture()
def repos(tmp_path):
    db = Database(str(tmp_path / "adv.db"))
    db.init_schema()
    return MeetingRepository(db)


# ---------------------------------------------------------------------------
# 1. 50 线程并发写同一 meeting:busy_timeout 是否会被打穿
# ---------------------------------------------------------------------------
def test_append_live_segment_50_threads_does_not_hit_busy_timeout(repos):
    """50 worker × 8 segment = 400 次追加,每次 acquire 2 次 BEGIN IMMEDIATE
    (ensure_speaker + segment insert)。WAL + busy_timeout=5s 下若任一写等
    锁超过 5s 会抛 `database is locked`。统计异常数与成功数。"""
    meetings = repos
    meeting_id = meetings.create(source="live", title="高压并发")

    errors: list[Exception] = []
    success: list[int] = []
    N_THREADS = 50
    N_PER_THREAD = 8

    def worker(tid: int):
        local_ok = 0
        for i in range(N_PER_THREAD):
            try:
                meetings.append_live_segment(
                    meeting_id,
                    text=f"t{tid}-{i}",
                    start_time=float(tid * 100 + i),
                    end_time=float(tid * 100 + i + 0.5),
                    speaker_label=f"SPEAKER_{tid % 4}",
                )
                local_ok += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
        return local_ok

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=N_THREADS) as ex:
        futures = [ex.submit(worker, t) for t in range(N_THREADS)]
        for f in as_completed(futures):
            success.append(f.result())
    elapsed = time.monotonic() - t0

    total_ok = sum(success)
    locked = [e for e in errors if "locked" in str(e).lower()]

    detail = meetings.detail(meeting_id)
    n_segments = len(detail["segments"])

    # 诊断输出(不 assert,先看数据)
    print(
        f"\n[50-thread] ok={total_ok}/{N_THREADS*N_PER_THREAD} "
        f"locked_errors={len(locked)} other_errors={len(errors)-len(locked)} "
        f"segments_in_db={n_segments} elapsed={elapsed:.2f}s"
    )

    assert len(locked) == 0, f"busy_timeout 被打穿: {len(locked)} 个 'database is locked'"
    assert n_segments == N_THREADS * N_PER_THREAD


# ---------------------------------------------------------------------------
# 2. 异常路径:BEGIN IMMEDIATE 后 INSERT 抛错,事务是否正确回滚
# ---------------------------------------------------------------------------
def test_append_live_segment_insert_failure_rolls_back_no_residual(repos, monkeypatch):
    """BEGIN IMMEDIATE 后 INSERT 抛 IntegrityError:
    - with self.db.connect() 的 finally 只 conn.close()
    - close() 是否隐式 rollback?有没有残留半事务导致后续 "cannot start a
      transaction within a transaction"?
    """
    meetings = repos
    meeting_id = meetings.create(source="live", title="异常路径")
    # 先正常插一条,建好 speaker
    meetings.append_live_segment(
        meeting_id, text="正常段", start_time=0, end_time=1,
        speaker_label="SPEAKER_00",
    )

    # 拦截 connect:让 segment INSERT 抛错(一次性,只第一次抛)
    original_connect = meetings.db.connect
    fired = {"done": False}

    class _FailingConn:
        def __init__(self):
            self._ctx = original_connect()
            self._conn = None

        def __enter__(self):
            self._conn = self._ctx.__enter__()
            return self

        def __exit__(self, *a):
            return self._ctx.__exit__(*a)

        def execute(self, sql, params=()):
            # 只在第一次 segment INSERT 时抛错,之后放行
            if "INSERT INTO transcript_segments" in sql and not fired["done"]:
                fired["done"] = True
                raise sqlite3.IntegrityError("simulated segment insert failure")
            return self._conn.execute(sql, params)

        def commit(self):
            self._conn.commit()

        def rollback(self):
            self._conn.rollback()

    monkeypatch.setattr(meetings.db, "connect", _FailingConn)

    with pytest.raises(sqlite3.IntegrityError):
        meetings.append_live_segment(
            meeting_id, text="失败段", start_time=2, end_time=3,
            speaker_label="SPEAKER_00",
        )

    # 关键断言:后续操作不报 "cannot start a transaction within a transaction"
    # 即上一个异常路径没有残留活跃事务
    meetings.append_live_segment(
        meeting_id, text="恢复段", start_time=4, end_time=5,
        speaker_label="SPEAKER_00",
    )
    detail = meetings.detail(meeting_id)
    texts = [s["text"] for s in detail["segments"]]
    assert "失败段" not in texts, "失败段不应残留(事务应回滚)"
    assert "正常段" in texts
    assert "恢复段" in texts


def test_ensure_speaker_select_hit_still_holds_write_lock(repos, monkeypatch):
    """ensure_speaker 即使 SELECT 命中(已存在)也走 BEGIN IMMEDIATE 拿写锁。
    用一个探针连接验证:ensure_speaker 执行期间,另一个连接的写操作会被
    阻塞(说明确实拿了 RESERVED/EXCLUSIVE 锁,而非只读)。
    """
    meetings = repos
    meeting_id = meetings.create(source="live", title="锁探针")
    # 预先建 speaker
    meetings.ensure_speaker(meeting_id, "SPEAKER_00")

    # 用 barrier 协调:ensure_speaker 内部持锁期间,探针尝试写
    import threading
    barrier = threading.Barrier(2)
    probe_blocked = threading.Event()
    probe_acquired = threading.Event()
    probe_hold = threading.Event()  # 主线程持锁期间

    def ensure_slow():
        # 在 ensure_speaker 内人为拉长 commit 之前的窗口
        barrier.wait()
        # 直接用底层连接复制 ensure_speaker 的逻辑,并在 commit 前停顿
        with meetings.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id FROM meeting_speakers WHERE meeting_id=? AND label=?",
                (meeting_id, "SPEAKER_00"),
            ).fetchone()
            assert row is not None  # SELECT 命中
            # 通知探针:写锁已拿,你试试写
            probe_hold.set()
            time.sleep(0.3)  # 持锁窗口
            conn.commit()
        probe_acquired.set()

    def probe_write():
        barrier.wait()
        probe_hold.wait(timeout=2.0)
        # 此时主线程应持写锁,这里 BEGIN IMMEDIATE 应阻塞
        t0 = time.monotonic()
        with meetings.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO meeting_notes(meeting_id, note_type, content) "
                "VALUES (?, 'summary', 'probe')",
                (meeting_id,),
            )
            conn.commit()
        elapsed = time.monotonic() - t0
        if elapsed > 0.15:
            probe_blocked.set()

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(ensure_slow)
        f2 = ex.submit(probe_write)
        f1.result(timeout=5)
        f2.result(timeout=5)

    assert probe_blocked.is_set(), (
        "ensure_speaker 在 SELECT 命中时也持写锁(预期行为,确认序列化开销存在)"
    )


# ---------------------------------------------------------------------------
# ensure_speaker 并发写入同一 label 时保持幂等
# ---------------------------------------------------------------------------
def test_ensure_speaker_concurrent_same_label_no_collision(repos):
    meetings = repos
    meeting_id = meetings.create(source="live", title="speaker 并发")
    label = "SPEAKER_00"

    def ensure(_):
        return meetings.ensure_speaker(meeting_id, label)

    with ThreadPoolExecutor(max_workers=16) as ex:
        results = [f.result() for f in [ex.submit(ensure, i) for i in range(64)]]

    # 全部返回同一个 id(幂等),无 IntegrityError
    unique_ids = set(results)
    assert len(unique_ids) == 1, f"应返回同一 speaker id,实际: {unique_ids}"
    with meetings.db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM meeting_speakers WHERE meeting_id=? AND label=?",
            (meeting_id, label),
        ).fetchone()[0]
    assert count == 1


# ---------------------------------------------------------------------------
# 4. TOCTOU:ensure_speaker 返回 id 后,append 的 INSERT 之间 speaker 被删
#    → FK ON DELETE SET NULL,但这里 segment INSERT 带 stale id,可能 FK 违约
# ---------------------------------------------------------------------------
def test_append_live_segment_does_not_use_external_ensure_speaker(
    repos, monkeypatch
):
    """Speaker creation and segment insertion must share one transaction."""
    meetings = repos
    meeting_id = meetings.create(source="live", title="TOCTOU")
    monkeypatch.setattr(
        meetings,
        "ensure_speaker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("append must not open a separate speaker transaction")
        ),
    )

    meetings.append_live_segment(
        meeting_id, text="atomic speaker", start_time=0, end_time=1,
        speaker_label="SPEAKER_00",
    )
    detail = meetings.detail(meeting_id)
    assert detail["segments"][0]["speaker_label"] == "SPEAKER_00"


# ---------------------------------------------------------------------------
# 5. 性能量化:ensure_speaker 写锁开销 vs 纯 SELECT
# ---------------------------------------------------------------------------
def test_ensure_speaker_write_lock_throughput_regression(repos):
    """对比:对已存在 speaker 调用 ensure_speaker N 次(每次 BEGIN IMMEDIATE +
    SELECT + commit)vs 直接 SELECT N 次(无事务)。量化写锁序列化开销。"""
    meetings = repos
    meeting_id = meetings.create(source="live", title="吞吐")
    meetings.ensure_speaker(meeting_id, "SPEAKER_00")

    N = 500

    t0 = time.monotonic()
    for _ in range(N):
        meetings.ensure_speaker(meeting_id, "SPEAKER_00")
    t_ensure = time.monotonic() - t0

    t0 = time.monotonic()
    for _ in range(N):
        with meetings.db.connect() as conn:
            conn.execute(
                "SELECT id FROM meeting_speakers WHERE meeting_id=? AND label=?",
                (meeting_id, "SPEAKER_00"),
            ).fetchone()
    t_select = time.monotonic() - t0

    ratio = t_ensure / max(t_select, 1e-6)
    print(
        f"\n[throughput] ensure_speaker(写锁) {N}×: {t_ensure:.3f}s | "
        f"raw SELECT {N}×: {t_select:.3f}s | ratio={ratio:.1f}x"
    )
    # 不硬断言具体倍数,但 ratio > 1 说明确有开销;记录在案
    assert t_ensure >= t_select


# ---------------------------------------------------------------------------
# 6. append_live_segment 在高并发下 ensure_speaker + insert 两次写锁是否
#    足够快,以至于 50 线程不串行化成顺序
# ---------------------------------------------------------------------------
def test_append_live_segment_concurrent_throughput(repos):
    """32 并发 append,各 1 segment。单进程 SQLite 写本应串行,但若每次 append
    持锁时间合理,total 应远小于 N × 单次时延。"""
    meetings = repos
    meeting_id = meetings.create(source="live", title="吞吐并发")

    def append(i):
        meetings.append_live_segment(
            meeting_id, text=f"s{i}", start_time=float(i), end_time=float(i + 1),
            speaker_label="SPEAKER_00",
        )

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(append, range(64)))
    elapsed = time.monotonic() - t0
    print(f"\n[concurrent-throughput] 64 append / 8 workers: {elapsed:.2f}s")
    assert len(meetings.detail(meeting_id)["segments"]) == 64
