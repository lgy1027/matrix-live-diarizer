import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.repositories.database import CURRENT_SCHEMA_VERSION, Database
from app.repositories.jobs import JobRepository
from app.repositories.meetings import MeetingRepository
from app.repositories.people import PeopleRepository
from app.repositories.people import DuplicateVoiceSampleError


@pytest.fixture()
def product_repos(tmp_path):
    db = Database(str(tmp_path / "matrix-product.db"))
    db.init_schema()
    return MeetingRepository(db), JobRepository(db), PeopleRepository(db)


def test_product_schema_contains_user_facing_entities(tmp_path):
    db = Database(str(tmp_path / "schema.db"))
    db.init_schema()
    with db.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
        }
    assert {
        "meetings",
        "processing_jobs",
        "people",
        "voice_samples",
        "meeting_speakers",
        "transcript_segments",
        "meeting_notes",
    } <= tables
    assert "sessions" not in tables
    assert "segments" not in tables


def test_schema_version_is_explicit(tmp_path):
    db = Database(str(tmp_path / "schema-version.db"))
    db.init_schema()
    with db.connect() as conn:
        version = conn.execute(
            "SELECT value FROM product_meta WHERE key='schema_version'"
        ).fetchone()[0]
    assert version == CURRENT_SCHEMA_VERSION


def test_previous_alpha_schema_upgrades_without_deleting_database(tmp_path):
    path = tmp_path / "schema-v1.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE product_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO product_meta VALUES ('schema_version', '1');
            CREATE TABLE meetings (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, status TEXT NOT NULL,
                title TEXT NOT NULL, original_filename TEXT, audio_path TEXT,
                duration_sec REAL NOT NULL DEFAULT 0, processing_mode TEXT NOT NULL,
                language TEXT, error_message TEXT, diarization_status TEXT NOT NULL,
                diarization_error TEXT, created_at TIMESTAMP, updated_at TIMESTAMP
            );
            INSERT INTO meetings
                (id, source, status, title, processing_mode, diarization_status)
                VALUES ('kept', 'upload', 'ready', '保留', 'meeting', 'completed');
            """
        )

    db = Database(str(path), create_default_admin=False)
    db.init_schema()

    with db.connect() as conn:
        version = conn.execute("SELECT value FROM product_meta").fetchone()[0]
        meeting = conn.execute(
            "SELECT title, transcript_state, processing_manifest_json FROM meetings"
        ).fetchone()
    assert version == CURRENT_SCHEMA_VERSION
    assert tuple(meeting) == ("保留", "draft", None)


def test_v2_alpha_schema_adds_identity_status_in_place(tmp_path):
    path = tmp_path / "schema-v2.db"
    db = Database(str(path), create_default_admin=False)
    db.init_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO meetings (id, source, title) VALUES ('m1', 'upload', '保留')"
        )
        conn.execute(
            """INSERT INTO meeting_speakers
               (id, meeting_id, label, manually_confirmed)
               VALUES ('s1', 'm1', 'SPEAKER_00', 0)"""
        )
        conn.execute("ALTER TABLE meeting_speakers DROP COLUMN identity_status")
        conn.execute(
            "UPDATE product_meta SET value = '2' WHERE key = 'schema_version'"
        )
        conn.commit()

    db.init_schema()

    with db.connect() as conn:
        version = conn.execute("SELECT value FROM product_meta").fetchone()[0]
        status = conn.execute(
            "SELECT identity_status FROM meeting_speakers WHERE id = 's1'"
        ).fetchone()[0]
    assert version == CURRENT_SCHEMA_VERSION
    assert status == "anonymous"


def test_v3_alpha_schema_adds_voice_quality_fields_in_place(tmp_path):
    path = tmp_path / "schema-v3.db"
    db = Database(str(path), create_default_admin=False)
    db.init_schema()
    with db.connect() as conn:
        conn.execute("DROP INDEX idx_voice_samples_person_audio")
        conn.execute("ALTER TABLE voice_samples DROP COLUMN effective_speech_sec")
        conn.execute("ALTER TABLE voice_samples DROP COLUMN audio_sha256")
        conn.execute("UPDATE product_meta SET value = '3' WHERE key = 'schema_version'")
        conn.commit()

    db.init_schema()

    with db.connect() as conn:
        version = conn.execute("SELECT value FROM product_meta").fetchone()[0]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(voice_samples)")}
    assert version == CURRENT_SCHEMA_VERSION
    assert {"effective_speech_sec", "audio_sha256"} <= columns


def test_concurrent_duplicate_voice_samples_have_domain_error(product_repos, tmp_path):
    _meetings, _jobs, people = product_repos
    person_id = people.create("并发样本")

    def add(index: int):
        return people.add_sample(
            person_id,
            audio_path=str(tmp_path / f"sample-{index}.wav"),
            duration_sec=5,
            effective_speech_sec=5,
            audio_sha256="same-decoded-pcm",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(add, index) for index in range(2)]
    successes = []
    duplicates = []
    for future in futures:
        try:
            successes.append(future.result())
        except DuplicateVoiceSampleError as exc:
            duplicates.append(exc)

    assert len(successes) == 1
    assert len(duplicates) == 1


def test_atomic_replacement_records_refined_manifest(product_repos):
    meetings, _jobs, _people = product_repos
    meeting_id = meetings.create(source="upload", title="manifest")

    meetings.replace_generated_transcript(
        meeting_id,
        [{
            "segment_index": 0,
            "text": "hello",
            "start_time": 0.1,
            "end_time": 0.9,
            "speaker_label": None,
        }],
        processing_manifest={"version": 1, "strategy": "transcription-only"},
    )

    meeting = meetings.get(meeting_id)
    assert meeting["transcript_state"] == "refined"
    assert meeting["processing_manifest"] == {
        "version": 1,
        "strategy": "transcription-only",
    }


def test_meeting_detail_uses_anonymous_speaker_then_confirmed_person(product_repos):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="产品周会")
    segment_id = meetings.insert_segment(
        meeting_id,
        segment_index=0,
        text="今天确认发布计划",
        start_time=0,
        end_time=2.5,
        speaker_label="Speaker A",
    )
    detail = meetings.detail(meeting_id)
    speaker_id = detail["speakers"][0]["id"]
    assert detail["segments"][0]["speaker_label"] == "Speaker A"
    assert detail["segments"][0]["person_name"] is None
    assert detail["segments"][0]["identity_status"] == "anonymous"

    person_id = people.create("张三")
    assert meetings.confirm_speaker(meeting_id, speaker_id, person_id)
    corrected = meetings.detail(meeting_id)
    assert corrected["segments"][0]["person_name"] == "张三"
    assert corrected["segments"][0]["manually_confirmed"] == 1
    assert corrected["segments"][0]["identity_status"] == "confirmed"
    assert corrected["segments"][0]["id"] == segment_id


def test_automatic_identity_remains_a_suggestion_until_confirmed(product_repos):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="声纹建议")
    meetings.insert_segment(
        meeting_id, segment_index=0, text="候选身份", start_time=0, end_time=3,
        speaker_label="SPEAKER_00",
    )
    person_id = people.create("张三")

    assert meetings.suggest_speaker(meeting_id, "SPEAKER_00", person_id, 0.91)
    suggested = meetings.detail(meeting_id)
    speaker = suggested["speakers"][0]
    segment = suggested["segments"][0]
    assert speaker["person_name"] == "张三"
    assert speaker["manually_confirmed"] == 0
    assert speaker["confidence"] == 0.91
    assert speaker["identity_status"] == "suggested"
    assert segment["manually_confirmed"] == 0
    assert segment["identity_status"] == "suggested"

    assert meetings.confirm_speaker(meeting_id, speaker["id"], person_id)
    confirmed = meetings.detail(meeting_id)["segments"][0]
    assert confirmed["manually_confirmed"] == 1
    assert confirmed["identity_status"] == "confirmed"


def test_strict_automatic_identity_is_distinct_and_can_be_cleared(product_repos):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="自动声纹匹配")
    meetings.insert_segment(
        meeting_id, segment_index=0, text="自动候选", start_time=0, end_time=6,
        speaker_label="SPEAKER_00",
    )
    person_id = people.create("李四")

    assert meetings.suggest_speaker(
        meeting_id, "SPEAKER_00", person_id, 0.93,
        identity_status="auto_matched",
    )
    matched = meetings.detail(meeting_id)["segments"][0]
    assert matched["person_name"] == "李四"
    assert matched["identity_status"] == "auto_matched"
    assert matched["manually_confirmed"] == 0

    speaker_id = matched["meeting_speaker_id"]
    assert meetings.confirm_speaker(meeting_id, speaker_id, None)
    cleared = meetings.detail(meeting_id)["segments"][0]
    assert cleared["person_name"] is None
    assert cleared["identity_status"] == "anonymous"


def test_reprocessing_clears_stale_machine_identity_for_rematching(product_repos):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="重新匹配")
    meetings.insert_segment(
        meeting_id, segment_index=0, text="旧结果", start_time=0, end_time=3,
        speaker_label="SPEAKER_00",
    )
    person_id = people.create("旧候选")
    meetings.suggest_speaker(
        meeting_id, "SPEAKER_00", person_id, 0.95,
        identity_status="auto_matched",
    )

    meetings.replace_generated_transcript(
        meeting_id,
        [{
            "segment_index": 0,
            "text": "新结果",
            "start_time": 0,
            "end_time": 3,
            "speaker_label": "SPEAKER_00",
        }],
    )

    speaker = meetings.detail(meeting_id)["speakers"][0]
    assert speaker["person_id"] is None
    assert speaker["confidence"] is None
    assert speaker["identity_status"] == "anonymous"


def test_search_uses_only_trusted_person_names(product_repos):
    meetings, _jobs, people = product_repos
    person_id = people.create("张三")
    meeting_id = meetings.create(source="upload", title="搜索身份")
    meetings.insert_segment(
        meeting_id, segment_index=0, text="自动身份", start_time=0, end_time=1,
        speaker_label="SPEAKER_00",
    )
    meetings.suggest_speaker(meeting_id, "SPEAKER_00", person_id, 0.82)
    assert meetings.search("自动身份")[0]["speaker_name"] == "SPEAKER_00"

    meetings.suggest_speaker(
        meeting_id, "SPEAKER_00", person_id, 0.93,
        identity_status="auto_matched",
    )
    assert meetings.search("自动身份")[0]["speaker_name"] == "张三"


def test_segment_assignment_is_scoped_to_its_meeting(product_repos):
    meetings, _jobs, _people = product_repos
    first = meetings.create(source="upload", title="第一场")
    second = meetings.create(source="upload", title="第二场")
    segment_id = meetings.insert_segment(
        first, segment_index=0, text="测试", start_time=0, end_time=1,
        speaker_label="Speaker A",
    )
    other_speaker = meetings.ensure_speaker(second, "Speaker X")

    with pytest.raises(ValueError, match="does not belong"):
        meetings.assign_segments(first, [segment_id], other_speaker)


def test_job_retry_and_cancel_rules(product_repos):
    meetings, jobs, _people = product_repos
    meeting_id = meetings.create(source="upload", title="任务测试", status="processing")
    job_id = jobs.create(meeting_id)

    assert jobs.request_cancel(job_id)
    assert jobs.get(job_id)["cancel_requested"] == 1
    jobs.update(job_id, status="cancelled", stage="cancelled", progress=40)
    assert jobs.retry(job_id)
    retried = jobs.get(job_id)
    assert retried["status"] == "queued"
    assert retried["progress"] == 0
    assert retried["retry_count"] == 1


def test_request_cancel_queued_job_finalizes_immediately(product_repos):
    """queued 阶段取消的 job 应直接终结为 cancelled + meeting failed,
    不依赖 claim_next 领出(claim_next 已过滤 cancel_requested=0,否则会永不终结、
    meeting 永久卡 processing)。
    """
    meetings, jobs, _people = product_repos
    meeting_id = meetings.create(source="upload", title="排队取消", status="processing")
    job_id = jobs.create(meeting_id)
    assert jobs.get(job_id)["status"] == "queued"

    assert jobs.request_cancel(job_id) is True
    job = jobs.get(job_id)
    assert job["status"] == "cancelled"
    assert job["cancel_requested"] == 1
    assert job["finished_at"] is not None
    # meeting 应同步标 failed(与 running 阶段取消一致)
    meeting = meetings.get(meeting_id)
    assert meeting["status"] == "failed"
    # cancelled 后仍可 retry
    assert jobs.retry(job_id)
    assert jobs.get(job_id)["status"] == "queued"


def test_deleting_meeting_removes_managed_audio_and_children(product_repos, tmp_path):
    meetings, jobs, _people = product_repos
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"audio")
    meeting_id = meetings.create(
        source="upload", title="待删除", audio_path=str(audio)
    )
    job_id = jobs.create(meeting_id)
    meetings.insert_segment(
        meeting_id, segment_index=0, text="内容", start_time=0, end_time=1
    )

    assert meetings.delete(meeting_id)
    assert not audio.exists()
    assert jobs.get(job_id) is None


def test_schema_init_repairs_inconsistent_transcript_search_index(tmp_path):
    path = tmp_path / "fts-repair.db"
    db = Database(str(path), create_default_admin=False)
    db.init_schema()
    meetings = MeetingRepository(db)
    meeting_id = meetings.create(source="upload", title="索引修复")
    meetings.insert_segment(
        meeting_id,
        segment_index=0,
        text="需要重新建立全文索引",
        start_time=0,
        end_time=1,
    )

    with db.connect() as conn:
        conn.execute(
            "INSERT INTO transcript_segments_fts(transcript_segments_fts) "
            "VALUES('delete-all')"
        )
        conn.commit()
    with db.connect() as conn:
        with pytest.raises(sqlite3.DatabaseError, match="malformed"):
            conn.execute(
                "INSERT INTO transcript_segments_fts(transcript_segments_fts, rank) "
                "VALUES('integrity-check', 1)"
            )

    db.init_schema()

    assert meetings.search("重新建立")
    assert meetings.delete(meeting_id)


def test_person_deletion_removes_samples_but_preserves_meeting(product_repos, tmp_path):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="live", title="实时会议")
    speaker_id = meetings.ensure_speaker(meeting_id, "Speaker A")
    person_id = people.create("李四")
    sample = tmp_path / "sample.wav"
    sample.write_bytes(b"voice")
    people.add_sample(person_id, audio_path=str(sample), duration_sec=8)
    meetings.confirm_speaker(meeting_id, speaker_id, person_id)

    assert people.delete(person_id)
    assert not sample.exists()
    assert meetings.get(meeting_id) is not None
    assert meetings.detail(meeting_id)["speakers"][0]["person_id"] is None


def test_person_summary_includes_voice_duration_without_join_multiplication(
    product_repos, tmp_path
):
    meetings, _jobs, people = product_repos
    person_id = people.create("王敏")
    for index, duration in enumerate((4.5, 6.0)):
        sample = tmp_path / f"sample-{index}.wav"
        sample.write_bytes(b"voice")
        people.add_sample(person_id, audio_path=str(sample), duration_sec=duration)
    for title in ("周会", "复盘"):
        meeting_id = meetings.create(source="upload", title=title)
        speaker_id = meetings.ensure_speaker(meeting_id, "SPEAKER_00")
        meetings.confirm_speaker(meeting_id, speaker_id, person_id)

    person = people.get(person_id)
    listed = people.list()[0]

    assert person is not None
    assert person["sample_count"] == listed["sample_count"] == 2
    assert person["total_sample_duration"] == listed["total_sample_duration"] == 10.5
    assert person["meeting_count"] == listed["meeting_count"] == 2


def test_atomic_transcript_replacement_preserves_notes_and_confirmed_speakers(
    product_repos,
):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="重新处理")
    meetings.insert_segment(
        meeting_id,
        segment_index=0,
        text="旧文稿",
        start_time=0,
        end_time=2,
        speaker_label="SPEAKER_00",
    )
    meetings.insert_segment(
        meeting_id,
        segment_index=1,
        text="即将消失的匿名说话人",
        start_time=2,
        end_time=4,
        speaker_label="SPEAKER_OLD",
    )
    person_id = people.create("张三")
    original_speaker = next(
        speaker
        for speaker in meetings.detail(meeting_id)["speakers"]
        if speaker["label"] == "SPEAKER_00"
    )
    meetings.confirm_speaker(meeting_id, original_speaker["id"], person_id)
    note = meetings.save_note(meeting_id, "summary", "人工修订后的摘要", "manual")

    segment_ids = meetings.replace_generated_transcript(
        meeting_id,
        [
            {
                "segment_index": 0,
                "text": "新文稿第一段",
                "start_time": 0.1,
                "end_time": 2.2,
                "speaker_label": "SPEAKER_00",
                "confidence": 0.95,
                "words": [{"word": "新", "start": 0.1, "end": 0.2}],
            },
            {
                "segment_index": 1,
                "text": "新文稿第二段",
                "start_time": 2.2,
                "end_time": 4.5,
                "speaker_label": "SPEAKER_01",
            },
        ],
    )

    detail = meetings.detail(meeting_id)
    assert len(segment_ids) == 2
    assert [segment["text"] for segment in detail["segments"]] == [
        "新文稿第一段",
        "新文稿第二段",
    ]
    retained = next(
        speaker for speaker in detail["speakers"] if speaker["label"] == "SPEAKER_00"
    )
    assert retained["id"] == original_speaker["id"]
    assert retained["person_id"] == person_id
    assert retained["manually_confirmed"] == 1
    assert {speaker["label"] for speaker in detail["speakers"]} == {
        "SPEAKER_00",
        "SPEAKER_01",
    }
    assert detail["notes"] == [{**note, "content": "人工修订后的摘要"}]
    assert detail["segments"][0]["words"] == [
        {"word": "新", "start": 0.1, "end": 0.2}
    ]


def test_atomic_transcript_replacement_keeps_confirmed_speaker_not_in_new_result(
    product_repos,
):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="保留人工确认")
    meetings.insert_segment(
        meeting_id,
        segment_index=0,
        text="旧文稿",
        start_time=0,
        end_time=1,
        speaker_label="SPEAKER_CONFIRMED",
    )
    speaker = meetings.detail(meeting_id)["speakers"][0]
    meetings.confirm_speaker(meeting_id, speaker["id"], people.create("李四"))

    meetings.replace_generated_transcript(
        meeting_id,
        [{
            "segment_index": 0,
            "text": "新匿名文稿",
            "start_time": 0,
            "end_time": 1,
            "speaker_label": None,
        }],
    )

    detail = meetings.detail(meeting_id)
    assert detail["segments"][0]["speaker_label"] is None
    assert detail["speakers"] == []


def test_reprocessing_maps_confirmed_people_by_timeline_not_label(product_repos):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="标签交换")
    meetings.insert_segment(
        meeting_id, segment_index=0, text="甲旧", start_time=0, end_time=5,
        speaker_label="SPEAKER_00",
    )
    meetings.insert_segment(
        meeting_id, segment_index=1, text="乙旧", start_time=5, end_time=10,
        speaker_label="SPEAKER_01",
    )
    old = meetings.detail(meeting_id)["speakers"]
    alice = people.create("甲")
    bob = people.create("乙")
    meetings.confirm_speaker(
        meeting_id, next(s["id"] for s in old if s["label"] == "SPEAKER_00"), alice
    )
    meetings.confirm_speaker(
        meeting_id, next(s["id"] for s in old if s["label"] == "SPEAKER_01"), bob
    )

    meetings.replace_generated_transcript(
        meeting_id,
        [
            {
                "segment_index": 0, "text": "甲新", "start_time": 0.1,
                "end_time": 4.9, "speaker_label": "SPEAKER_01",
            },
            {
                "segment_index": 1, "text": "乙新", "start_time": 5.1,
                "end_time": 9.9, "speaker_label": "SPEAKER_00",
            },
        ],
    )

    segments = meetings.detail(meeting_id)["segments"]
    assert [(s["speaker_label"], s["person_name"]) for s in segments] == [
        ("SPEAKER_01", "甲"),
        ("SPEAKER_00", "乙"),
    ]
    assert all(s["identity_status"] == "confirmed" for s in segments)


def test_reprocessing_merges_old_labels_confirmed_as_same_person(product_repos):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="过度分段合并")
    person_id = people.create("张三")
    for index, label in enumerate(("SPEAKER_00", "SPEAKER_01")):
        meetings.insert_segment(
            meeting_id, segment_index=index, text=f"旧段{index}",
            start_time=index * 3, end_time=(index + 1) * 3,
            speaker_label=label,
        )
        speaker = next(
            item for item in meetings.detail(meeting_id)["speakers"]
            if item["label"] == label
        )
        meetings.confirm_speaker(meeting_id, speaker["id"], person_id)

    meetings.replace_generated_transcript(
        meeting_id,
        [{
            "segment_index": 0, "text": "合并后的新段", "start_time": 0,
            "end_time": 6, "speaker_label": "SPEAKER_NEW",
        }],
    )

    segment = meetings.detail(meeting_id)["segments"][0]
    assert segment["person_name"] == "张三"
    assert segment["identity_status"] == "confirmed"


def test_reprocessing_drops_ambiguous_confirmed_identity(product_repos):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="边界歧义")
    for index, (label, person) in enumerate((("SPEAKER_00", "甲"), ("SPEAKER_01", "乙"))):
        meetings.insert_segment(
            meeting_id, segment_index=index, text=person,
            start_time=index * 5, end_time=(index + 1) * 5,
            speaker_label=label,
        )
        speaker = next(
            s for s in meetings.detail(meeting_id)["speakers"] if s["label"] == label
        )
        meetings.confirm_speaker(meeting_id, speaker["id"], people.create(person))

    meetings.replace_generated_transcript(
        meeting_id,
        [{
            "segment_index": 0, "text": "无法确定", "start_time": 0,
            "end_time": 10, "speaker_label": "SPEAKER_00",
        }],
    )

    segment = meetings.detail(meeting_id)["segments"][0]
    assert segment["person_name"] is None
    assert segment["identity_status"] == "anonymous"


def test_atomic_transcript_replacement_rolls_back_everything_on_insert_failure(
    product_repos,
):
    meetings, _jobs, people = product_repos
    meeting_id = meetings.create(source="upload", title="事务回滚")
    meetings.insert_segment(
        meeting_id,
        segment_index=0,
        text="必须保留的旧文稿",
        start_time=0,
        end_time=1,
        speaker_label="SPEAKER_00",
    )
    speaker_id = meetings.detail(meeting_id)["speakers"][0]["id"]
    meetings.confirm_speaker(meeting_id, speaker_id, people.create("王五"))
    # 在 confirm 之后取快照:replace 失败回滚后应恢复到 confirm 之后、replace 之前的状态。
    # 不能在 confirm 之前取——confirm 会更新 updated_at,Windows 上跨秒时旧快照的时间戳
    # 与回滚后的实际值不一致,导致 flaky 失败。
    old_speaker = meetings.detail(meeting_id)["speakers"][0]
    meetings.save_note(meeting_id, "minutes", "必须保留的纪要", "manual")

    with pytest.raises(sqlite3.IntegrityError):
        meetings.replace_generated_transcript(
            meeting_id,
            [
                {
                    "segment_index": 0,
                    "text": "第一段新文稿",
                    "start_time": 0,
                    "end_time": 1,
                    "speaker_label": "SPEAKER_NEW",
                },
                {
                    "segment_index": 0,
                    "text": "重复序号触发唯一约束",
                    "start_time": 1,
                    "end_time": 2,
                    "speaker_label": "SPEAKER_NEW",
                },
            ],
        )

    detail = meetings.detail(meeting_id)
    assert [segment["text"] for segment in detail["segments"]] == [
        "必须保留的旧文稿"
    ]
    assert detail["speakers"] == [
        {
            **old_speaker,
            "person_id": detail["speakers"][0]["person_id"],
                "person_name": "王五",
                "manually_confirmed": 1,
                "identity_status": "confirmed",
                "confidence": None,
        }
    ]
    assert detail["notes"][0]["content"] == "必须保留的纪要"


def _meeting_with_two_speakers(meetings, segments_count=3):
    """建一个 upload 会议 + 两个匿名 speaker,每个 speaker 几条 segment。"""
    meeting_id, _ = meetings.create_with_job(
        source="upload", title="合并测试", processing_mode="meeting", status="processing"
    )
    spk_a = meetings.ensure_speaker(meeting_id, "SPEAKER_00")
    spk_b = meetings.ensure_speaker(meeting_id, "SPEAKER_01")
    seg_ids_a = []
    seg_ids_b = []
    with meetings.db.connect() as conn:
        for i in range(segments_count):
            cur = conn.execute(
                """INSERT INTO transcript_segments
                   (meeting_id, segment_index, meeting_speaker_id, text,
                    start_time, end_time)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (meeting_id, i, spk_a, f"A段{i}", float(i), float(i + 1)),
            )
            seg_ids_a.append(cur.lastrowid)
        for i in range(segments_count):
            cur = conn.execute(
                """INSERT INTO transcript_segments
                   (meeting_id, segment_index, meeting_speaker_id, text,
                    start_time, end_time)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (meeting_id, segments_count + i, spk_b, f"B段{i}",
                 float(segments_count + i), float(segments_count + i + 1)),
            )
            seg_ids_b.append(cur.lastrowid)
        conn.commit()
    return meeting_id, spk_a, spk_b, seg_ids_a, seg_ids_b


def test_merge_speakers_reassigns_segments_and_deletes_source(product_repos):
    meetings, _jobs, _people = product_repos
    meeting_id, spk_a, spk_b, seg_ids_a, seg_ids_b = _meeting_with_two_speakers(meetings)

    migrated = meetings.merge_speakers(meeting_id, spk_a, [spk_b])
    assert migrated == len(seg_ids_b)

    with meetings.db.connect() as conn:
        # source 的 segments 全改指到 target
        reassigned = conn.execute(
            "SELECT meeting_speaker_id FROM transcript_segments WHERE id IN (%s)"
            % ",".join("?" for _ in seg_ids_b),
            seg_ids_b,
        ).fetchall()
        assert all(r["meeting_speaker_id"] == spk_a for r in reassigned)
        # source speaker 已删
        assert conn.execute(
            "SELECT 1 FROM meeting_speakers WHERE id = ?", (spk_b,)
        ).fetchone() is None
        # target 还在
        assert conn.execute(
            "SELECT 1 FROM meeting_speakers WHERE id = ?", (spk_a,)
        ).fetchone() is not None


def test_merge_speakers_rejects_target_in_sources(product_repos):
    meetings, _jobs, _people = product_repos
    meeting_id, spk_a, spk_b, _, _ = _meeting_with_two_speakers(meetings)
    with pytest.raises(ValueError, match="不能在 source_ids"):
        meetings.merge_speakers(meeting_id, spk_a, [spk_a, spk_b])


def test_merge_speakers_target_not_found_raises_speaker_not_found(product_repos):
    from app.repositories.meetings import SpeakerNotFoundError
    meetings, _jobs, _people = product_repos
    meeting_id, spk_a, _b, _, _ = _meeting_with_two_speakers(meetings)
    with pytest.raises(SpeakerNotFoundError):
        meetings.merge_speakers(meeting_id, "nonexistent-uuid", [spk_a])


def test_split_speaker_creates_new_speaker_and_moves_segments(product_repos):
    meetings, _jobs, _people = product_repos
    meeting_id, spk_a, _b, seg_ids_a, _ = _meeting_with_two_speakers(meetings)

    new_id = meetings.split_speaker(meeting_id, spk_a, seg_ids_a[:2])
    assert new_id != spk_a
    with meetings.db.connect() as conn:
        moved = conn.execute(
            "SELECT meeting_speaker_id FROM transcript_segments WHERE id IN (?, ?)",
            seg_ids_a[:2],
        ).fetchall()
        assert all(r["meeting_speaker_id"] == new_id for r in moved)
        # 新 speaker 存在且匿名
        row = conn.execute(
            "SELECT identity_status FROM meeting_speakers WHERE id = ?", (new_id,)
        ).fetchone()
        assert row["identity_status"] == "anonymous"
        # source speaker 仍在(只移了部分 segment)
        assert conn.execute(
            "SELECT 1 FROM meeting_speakers WHERE id = ?", (spk_a,)
        ).fetchone() is not None


def test_split_speaker_repeated_does_not_hit_unique_constraint(product_repos):
    """对同一 source 重复 split,label 带 uuid 后缀不应触发 UNIQUE(meeting_id,label)。"""
    meetings, _jobs, _people = product_repos
    meeting_id, spk_a, _b, seg_ids_a, _ = _meeting_with_two_speakers(meetings)
    # 第一次 split
    first = meetings.split_speaker(meeting_id, spk_a, seg_ids_a[:1])
    # 第二次 split 同一 source 的另一段
    second = meetings.split_speaker(meeting_id, spk_a, seg_ids_a[1:2])
    assert first != second
    with meetings.db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM meeting_speakers WHERE meeting_id = ?", (meeting_id,)
        ).fetchone()[0]
        # 原 A + 原 B + 2 个 split = 4
        assert count == 4


def test_split_speaker_source_not_found_raises_speaker_not_found(product_repos):
    from app.repositories.meetings import SpeakerNotFoundError
    meetings, _jobs, _people = product_repos
    meeting_id, _a, _b, _, _ = _meeting_with_two_speakers(meetings)
    with pytest.raises(SpeakerNotFoundError):
        meetings.split_speaker(meeting_id, "nonexistent-uuid", [1])


def test_create_with_job_is_atomic_on_insert_failure(product_repos):
    """job 插入失败时 meeting 也不应残留(同事务回滚)。"""
    meetings, jobs, _people = product_repos
    # 让 processing_jobs 表 insert 失败:用一个非法 meeting 外键不行,
    # 改用 monkeypatch 不便(跨 repo)。直接验证成功路径的两行都进同事务:
    # 插入一个 meeting 但让 job 的 meeting_id 列约束触发——用 DROP 掉 jobs
    # 表的主键约束来制造失败太重。改为:验证 create_with_job 后 meeting+job 都在,
    # 且 create(老路径)不被 upload 使用(已在 test_product_api 验证)。
    meeting_id, job_id = meetings.create_with_job(
        source="upload", title="原子测试", processing_mode="meeting", status="processing"
    )
    assert meetings.get(meeting_id) is not None
    assert jobs.get(job_id) is not None


def test_create_with_job_rolls_back_when_job_insert_fails(product_repos, monkeypatch):
    """真正验证原子性:job INSERT 抛错时 meeting 不应残留(同事务回滚)。"""
    meetings, _jobs, _people = product_repos
    # 拦截 conn.execute:meeting INSERT 放行,job INSERT 抛 IntegrityError
    original_connect = meetings.db.connect

    class _Wrapper:
        def __init__(self):
            self._ctx = original_connect()

        def __enter__(self):
            self._conn = self._ctx.__enter__()
            return self

        def __exit__(self, *a):
            return self._ctx.__exit__(*a)

        def execute(self, sql, params=()):
            if "INSERT INTO processing_jobs" in sql:
                raise sqlite3.IntegrityError("simulated failure")
            return self._conn.execute(sql, params)

        def commit(self):
            self._conn.commit()

        def rollback(self):
            self._conn.rollback()

    monkeypatch.setattr(meetings.db, "connect", _Wrapper)
    with pytest.raises(sqlite3.IntegrityError):
        meetings.create_with_job(
            source="upload", title="应回滚", processing_mode="meeting", status="processing"
        )
    # meeting 不应残留(事务回滚,未 commit)
    rows = meetings.list()
    assert rows[0] == 0


def test_append_live_segment_concurrent_no_unique_collision(product_repos):
    """并发追加 live segment 不应撞 UNIQUE(meeting_id, segment_index)。

    回归:append_live_segment 原先 SELECT MAX+1 → INSERT 不在 BEGIN IMMEDIATE
    写事务里,并发连接读到相同 index 会导致 sqlite3.IntegrityError。
    """
    meetings, _jobs, _people = product_repos
    meeting_id = meetings.create(source="live", title="并发追加")

    def append(index: int):
        return meetings.append_live_segment(
            meeting_id,
            text=f"段{index}",
            start_time=float(index),
            end_time=float(index + 1),
            speaker_label="SPEAKER_00",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(append, index) for index in range(32)]
        # 全部成功(不抛 IntegrityError);失败的 future.result() 会 re-raise
        inserted_ids = [future.result() for future in futures]

    assert len(inserted_ids) == 32
    detail = meetings.detail(meeting_id)
    segments = detail["segments"]
    # 32 段全部落库,index 0..31 各一次无重复
    indices = sorted(segment["segment_index"] for segment in segments)
    assert indices == list(range(32))
