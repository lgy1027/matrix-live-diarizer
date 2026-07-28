"""SQLite 数据库连接与 schema 初始化"""
import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger("Matrix_DB")
CURRENT_SCHEMA_VERSION = "4"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS product_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
INSERT OR IGNORE INTO product_meta(key, value) VALUES ('schema_version', '4');

CREATE TABLE IF NOT EXISTS meetings (
    id                TEXT PRIMARY KEY,
    source            TEXT NOT NULL CHECK(source IN ('live', 'upload')),
    status            TEXT NOT NULL DEFAULT 'draft'
                      CHECK(status IN ('draft', 'processing', 'ready', 'failed')),
    title             TEXT NOT NULL,
    original_filename TEXT,
    audio_path        TEXT,
    duration_sec      REAL NOT NULL DEFAULT 0,
    processing_mode   TEXT NOT NULL DEFAULT 'meeting'
                      CHECK(processing_mode IN ('quick', 'meeting')),
    language          TEXT,
    error_message     TEXT,
    diarization_status TEXT NOT NULL DEFAULT 'not_requested'
                       CHECK(diarization_status IN ('not_requested', 'pending', 'completed', 'unavailable')),
    diarization_error TEXT,
    transcript_state  TEXT NOT NULL DEFAULT 'draft'
                      CHECK(transcript_state IN ('draft', 'refined')),
    processing_manifest_json TEXT,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_meetings_status_created
    ON meetings(status, created_at DESC);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id               TEXT PRIMARY KEY,
    meeting_id       TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    status           TEXT NOT NULL DEFAULT 'queued'
                     CHECK(status IN ('queued', 'running', 'completed', 'failed', 'cancelled')),
    stage            TEXT NOT NULL DEFAULT 'queued',
    progress         INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
    error_message    TEXT,
    retry_count      INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at       TIMESTAMP,
    finished_at      TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created
    ON processing_jobs(status, created_at ASC);

CREATE TABLE IF NOT EXISTS people (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    notes      TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_people_name ON people(name);

CREATE TABLE IF NOT EXISTS voice_samples (
    id            TEXT PRIMARY KEY,
    person_id     TEXT NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    audio_path    TEXT NOT NULL,
    embedding     BLOB,
    embedding_dim INTEGER,
    model_name    TEXT,
    duration_sec  REAL NOT NULL,
    effective_speech_sec REAL NOT NULL DEFAULT 0,
    quality_score REAL,
    audio_sha256  TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_voice_samples_person ON voice_samples(person_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_voice_samples_person_audio
    ON voice_samples(person_id, audio_sha256) WHERE audio_sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS meeting_speakers (
    id               TEXT PRIMARY KEY,
    meeting_id       TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    label            TEXT NOT NULL,
    person_id        TEXT REFERENCES people(id) ON DELETE SET NULL,
    confidence       REAL,
    manually_confirmed INTEGER NOT NULL DEFAULT 0,
    identity_status  TEXT NOT NULL DEFAULT 'anonymous'
                     CHECK(identity_status IN ('anonymous', 'suggested', 'auto_matched', 'confirmed')),
    color            TEXT,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(meeting_id, label)
);
CREATE INDEX IF NOT EXISTS idx_meeting_speakers_meeting
    ON meeting_speakers(meeting_id);

CREATE TABLE IF NOT EXISTS transcript_segments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id         TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    segment_index      INTEGER NOT NULL,
    meeting_speaker_id TEXT REFERENCES meeting_speakers(id) ON DELETE SET NULL,
    text               TEXT NOT NULL,
    start_time         REAL NOT NULL,
    end_time           REAL NOT NULL,
    confidence         REAL,
    words_json         TEXT,
    manually_edited    INTEGER NOT NULL DEFAULT 0,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(meeting_id, segment_index)
);
CREATE INDEX IF NOT EXISTS idx_transcript_segments_meeting
    ON transcript_segments(meeting_id, segment_index);

-- FTS5 trigram 全文搜索(contentless,外链 transcript_segments)
CREATE VIRTUAL TABLE IF NOT EXISTS transcript_segments_fts
    USING fts5(text, content='transcript_segments', content_rowid='id', tokenize='trigram');

CREATE TRIGGER IF NOT EXISTS ts_fts_ai AFTER INSERT ON transcript_segments BEGIN
    INSERT INTO transcript_segments_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS ts_fts_ad AFTER DELETE ON transcript_segments BEGIN
    INSERT INTO transcript_segments_fts(transcript_segments_fts, rowid, text)
        VALUES('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS ts_fts_au AFTER UPDATE ON transcript_segments BEGIN
    INSERT INTO transcript_segments_fts(transcript_segments_fts, rowid, text)
        VALUES('delete', old.id, old.text);
    INSERT INTO transcript_segments_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS meeting_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    note_type  TEXT NOT NULL CHECK(note_type IN ('summary', 'minutes', 'actions')),
    content    TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'local',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(meeting_id, note_type)
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 用户表 (Roadmap 安全项: admin/admin 默认账户 + 强制改密)
CREATE TABLE IF NOT EXISTS users (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    username              TEXT UNIQUE NOT NULL,
    password_hash         TEXT NOT NULL,                -- werkzeug pbkdf2:sha256 哈希
    must_change_password  INTEGER DEFAULT 0,           -- 1 = 下次登录强制改密
    is_active             INTEGER DEFAULT 1,
    created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login_at         TIMESTAMP,
    password_changed_at   REAL DEFAULT 0                -- 改密时间戳,用于校验 token 里的 pwd_iat
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""


class Database:
    """SQLite 包装：自动建目录、WAL 模式、Row 工厂"""

    def __init__(self, db_path: str, *, create_default_admin: bool = True):
        self.db_path = db_path
        self.create_default_admin = create_default_admin
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        """创建当前产品 schema、索引、默认账户并启用 WAL。"""
        with self.connect() as conn:
            # PRAGMA 必须在任何 INSERT/executescript 之前(不能在事务中)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._upgrade_alpha_schema(conn)
            conn.executescript(SCHEMA_SQL)
            self._validate_schema_version(conn)
            self._validate_required_columns(conn)
            self._repair_transcript_search_index(conn)
            # 默认 admin 账户初始化(空表时插入)
            if self.create_default_admin:
                self._ensure_default_admin(conn)
            conn.commit()

    def _upgrade_alpha_schema(self, conn: sqlite3.Connection) -> None:
        """Apply the one supported pre-release schema upgrade in place.

        Version 1 is the immediately preceding alpha schema. Requiring users to
        delete their database for two additive meeting metadata columns makes
        local development needlessly fragile, so this upgrade is deliberately
        small and idempotent. Unknown versions still fail closed below.
        """
        meta_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_meta'"
        ).fetchone()
        if meta_exists is None:
            return
        row = conn.execute(
            "SELECT value FROM product_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None or row[0] not in {"1", "2", "3"}:
            return
        meeting_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meetings'"
        ).fetchone()
        previous_version = row[0]
        if previous_version == "1" and meeting_exists is not None:
            columns = {
                item[1] for item in conn.execute("PRAGMA table_info(meetings)").fetchall()
            }
            if "transcript_state" not in columns:
                conn.execute(
                    """ALTER TABLE meetings ADD COLUMN transcript_state TEXT NOT NULL
                       DEFAULT 'draft' CHECK(transcript_state IN ('draft', 'refined'))"""
                )
            if "processing_manifest_json" not in columns:
                conn.execute(
                    "ALTER TABLE meetings ADD COLUMN processing_manifest_json TEXT"
                )
        speaker_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meeting_speakers'"
        ).fetchone()
        if speaker_exists is not None:
            speaker_columns = {
                item[1]
                for item in conn.execute("PRAGMA table_info(meeting_speakers)").fetchall()
            }
            if "identity_status" not in speaker_columns:
                conn.execute(
                    """ALTER TABLE meeting_speakers ADD COLUMN identity_status TEXT NOT NULL
                       DEFAULT 'anonymous' CHECK(identity_status IN
                       ('anonymous', 'suggested', 'auto_matched', 'confirmed'))"""
                )
                # 回填已存在 speaker 的身份状态(基于 manually_confirmed/person_id)。
                # 必须与补列同分支:旧库可能已有 audio_sha256(下面 voice_samples
                # 分支不会进入 audio_sha256 补列路径),但缺 identity_status 列 —
                # 此时只补列不回填会导致已确认人物静默降级为 anonymous。
                conn.execute(
                    """UPDATE meeting_speakers
                       SET identity_status = CASE
                           WHEN manually_confirmed = 1 THEN 'confirmed'
                           WHEN person_id IS NOT NULL THEN 'suggested'
                           ELSE 'anonymous' END"""
                )
        voice_sample_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='voice_samples'"
        ).fetchone()
        if voice_sample_exists is not None:
            sample_columns = {
                item[1]
                for item in conn.execute("PRAGMA table_info(voice_samples)").fetchall()
            }
            if "effective_speech_sec" not in sample_columns:
                conn.execute(
                    "ALTER TABLE voice_samples ADD COLUMN effective_speech_sec "
                    "REAL NOT NULL DEFAULT 0"
                )
            if "audio_sha256" not in sample_columns:
                conn.execute("ALTER TABLE voice_samples ADD COLUMN audio_sha256 TEXT")
        conn.execute(
            "UPDATE product_meta SET value = ? WHERE key = 'schema_version'",
            (CURRENT_SCHEMA_VERSION,),
        )
        logger.info(
            "[DB] alpha schema 已从 v%s 原地升级到 v%s",
            previous_version,
            CURRENT_SCHEMA_VERSION,
        )

    def _ensure_default_admin(self, conn: sqlite3.Connection) -> None:
        """确保默认 admin 账户存在

        首次启动: 自动创建 admin/admin, 设 must_change_password=1
        已存在: 跳过(不覆盖)
        """
        cur = conn.execute("SELECT COUNT(*) FROM users")
        if cur.fetchone()[0] > 0:
            return
        # 用 werkzeug 生成 pbkdf2 哈希(项目已有依赖)
        from werkzeug.security import generate_password_hash
        pwd_hash = generate_password_hash("admin", method="pbkdf2:sha256", salt_length=16)
        conn.execute(
            "INSERT INTO users (username, password_hash, must_change_password) VALUES (?, ?, 1)",
            ("admin", pwd_hash),
        )
        logger.info("[DB] 已创建默认 admin 账户(密码: admin, 首次登录需修改)")

    def _validate_schema_version(self, conn: sqlite3.Connection) -> None:
        row = conn.execute(
            "SELECT value FROM product_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None or row[0] != CURRENT_SCHEMA_VERSION:
            raise RuntimeError(
                f"不支持的数据库版本: {row[0] if row else 'missing'}; "
                f"当前全新项目需要 schema {CURRENT_SCHEMA_VERSION}"
            )

    def _validate_required_columns(self, conn: sqlite3.Connection) -> None:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(meetings)").fetchall()
        }
        required = {
            "diarization_status", "diarization_error", "transcript_state",
            "processing_manifest_json",
        }
        if not required <= columns:
            raise RuntimeError(
                "数据库结构与 schema_version 不一致；"
                "请重置 STORAGE_DB_PATH 指向的 alpha 数据库。"
            )
        speaker_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(meeting_speakers)").fetchall()
        }
        if "identity_status" not in speaker_columns:
            raise RuntimeError(
                "数据库结构缺少人物身份状态；请重启以完成 alpha schema 升级。"
            )
        sample_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(voice_samples)").fetchall()
        }
        if not {"effective_speech_sec", "audio_sha256"} <= sample_columns:
            raise RuntimeError(
                "数据库结构缺少声音样本质量字段；请重启以完成 alpha schema 升级。"
            )

    @staticmethod
    def _transcript_search_index_is_valid(conn: sqlite3.Connection) -> bool:
        """Check that the external-content FTS index matches transcript rows."""
        conn.execute("SAVEPOINT transcript_fts_check")
        try:
            conn.execute(
                "INSERT INTO transcript_segments_fts(transcript_segments_fts, rank) "
                "VALUES('integrity-check', 1)"
            )
        except sqlite3.DatabaseError as exc:
            conn.execute("ROLLBACK TO transcript_fts_check")
            conn.execute("RELEASE transcript_fts_check")
            if "malformed" not in str(exc).lower():
                raise
            return False
        conn.execute("RELEASE transcript_fts_check")
        return True

    def _repair_transcript_search_index(self, conn: sqlite3.Connection) -> None:
        """Rebuild only the derived FTS index when legacy data is inconsistent."""
        if self._transcript_search_index_is_valid(conn):
            return

        quick_check = [row[0] for row in conn.execute("PRAGMA quick_check").fetchall()]
        if quick_check != ["ok"]:
            raise sqlite3.DatabaseError(
                "SQLite 主数据库完整性检查失败: " + "; ".join(quick_check)
            )

        logger.warning("[DB] 文稿全文索引不一致，正在从原始文稿安全重建")
        conn.execute(
            "INSERT INTO transcript_segments_fts(transcript_segments_fts) "
            "VALUES('rebuild')"
        )
        if not self._transcript_search_index_is_valid(conn):
            raise sqlite3.DatabaseError("文稿全文索引重建后仍未通过完整性检查")
        logger.info("[DB] 文稿全文索引重建完成")

    def _init_schema_on_conn(self, conn: sqlite3.Connection) -> None:
        """在已开启的连接上建表(兜底用)"""
        conn.executescript(SCHEMA_SQL)
        self._validate_schema_version(conn)
        self._validate_required_columns(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.commit()

    @contextmanager
    def connect(self):
        """获取连接,启用 Row 工厂 + busy_timeout

        busy_timeout 5s: SQLite 在"database is locked"时会自动等
        5 秒重试,而不是立即抛错。配合 WAL 模式对并发 WebSocket
        + upload 同时写库友好。

        自动初始化:空数据库第一次连接时创建产品 schema。
        """
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        # 兜底:检查产品根表是否存在,没有就建。
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='product_meta'"
        )
        if cur.fetchone() is None:
            self._init_schema_on_conn(conn)
        try:
            yield conn
        finally:
            conn.close()
