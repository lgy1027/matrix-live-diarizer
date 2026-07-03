"""SQLite 数据库连接与 schema 初始化"""
import os
import sqlite3
import logging
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger("Matrix_DB")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    title         TEXT,
    client_id     TEXT,
    original_filename TEXT,
    duration_sec  REAL,
    speaker_count INTEGER DEFAULT 0,
    is_archived   INTEGER DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_source  ON sessions(source);

CREATE TABLE IF NOT EXISTS segments (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    speaker_id    TEXT,
    text          TEXT NOT NULL,
    start_time    REAL NOT NULL,
    end_time      REAL NOT NULL,
    confidence    REAL,
    is_final      INTEGER DEFAULT 1,
    words_json    TEXT,                          -- 字级时间戳 JSON, ASR_WORD_TIMESTAMPS=true 时填充
    UNIQUE(session_id, segment_index)
);
-- 兼容老库:老 segments 表无 words_json 列,补上(忽略"重复列"错误)
CREATE INDEX IF NOT EXISTS idx_segments_session ON segments(session_id, segment_index);

-- Roadmap #2.2: FTS5 全文搜索虚表(trigram 分词, contentless 模式)
-- trigram 把每 3 字符切为 token,中文 substring 搜 3+ 字命中率高
-- content='' (contentless) 模式: 索引存但 content 仍由 segments.text 提供
--   优势: 支持 'delete' / 'delete-all' 命令(否则 cascade DELETE 报 SQL logic error)
--   限制: SQLite FTS5 无 jieba,2 字以下中文搜不到(建议输入 ≥3 字)
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text,
    session_id UNINDEXED,
    speaker_id UNINDEXED,
    content='',
    tokenize='trigram'
);

-- 触发器: 同步 segments ↔ segments_fts
-- 注意: FTS5 列不接受 NULL,speaker_id / session_id 为 NULL 时用空串兜底
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text, session_id, speaker_id)
    VALUES (new.id, new.text, COALESCE(new.session_id, ''), COALESCE(new.speaker_id, ''));
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text, session_id, speaker_id)
    VALUES ('delete', old.id, old.text, COALESCE(old.session_id, ''), COALESCE(old.speaker_id, ''));
END;
CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text, session_id, speaker_id)
    VALUES ('delete', old.id, old.text, COALESCE(old.session_id, ''), COALESCE(old.speaker_id, ''));
    INSERT INTO segments_fts(rowid, text, session_id, speaker_id)
    VALUES (new.id, new.text, COALESCE(new.session_id, ''), COALESCE(new.speaker_id, ''));
END;

CREATE TABLE IF NOT EXISTS speaker_aliases (
    speaker_id    TEXT PRIMARY KEY,
    display_name  TEXT NOT NULL,
    color         TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
    password_changed_at   REAL DEFAULT 0                -- Bug-88: 改密时间戳(token pwd_iat 校验)
);
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
-- 老库兼容: ALTER TABLE 不能在 executescript(隐式事务)里, 单独跑 (Bug-91 审核)
"""


# 老库升级: 把已有 segments 一次性回填到 segments_fts
# 用 IF NOT EXISTS 模式 — 第一次运行回填,后续幂等
FTS_BACKFILL_SQL = """
INSERT OR IGNORE INTO segments_fts(rowid, text, session_id, speaker_id)
SELECT id, text, session_id, speaker_id FROM segments
WHERE id NOT IN (SELECT rowid FROM segments_fts WHERE rowid IS NOT NULL);
"""


class Database:
    """SQLite 包装：自动建目录、WAL 模式、Row 工厂"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        """创建表 + 索引 + FTS5 虚表 + 触发器 + 回填老数据 + 启用 WAL"""
        with self.connect() as conn:
            # PRAGMA 必须在任何 INSERT/executescript 之前(不能在事务中)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA_SQL)
            # 兼容老库:加 v0.3 新列(已存在则忽略)
            try:
                conn.execute("ALTER TABLE segments ADD COLUMN words_json TEXT")
            except Exception:
                pass  # 重复列错误,新库已含
            # 兼容老库:加 v0.4 新列 password_changed_at (Bug-91 审核)
            try:
                conn.execute("ALTER TABLE users ADD COLUMN password_changed_at REAL DEFAULT 0")
            except Exception:
                pass  # 重复列错误,新库已含
            # 回填老 segments 到 FTS5(对已有库,触发器不会追溯历史 insert)
            conn.executescript(FTS_BACKFILL_SQL)
            # 默认 admin 账户初始化(空表时插入)
            self._ensure_default_admin(conn)
            conn.commit()

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

    def _init_schema_on_conn(self, conn: sqlite3.Connection) -> None:
        """在已开启的连接上建表(兜底用)"""
        conn.executescript(SCHEMA_SQL)
        # 老库兼容 ALTER (Bug-91 审核)
        try:
            conn.execute("ALTER TABLE users ADD COLUMN password_changed_at REAL DEFAULT 0")
        except Exception:
            pass
        conn.executescript(FTS_BACKFILL_SQL)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.commit()

    @contextmanager
    def connect(self):
        """获取连接,启用 Row 工厂 + busy_timeout

        busy_timeout 5s: SQLite 在"database is locked"时会自动等
        5 秒重试,而不是立即抛错。配合 WAL 模式对并发 WebSocket
        + upload 同时写库友好。

        自动初始化: 如果 db 文件存在但 schema 没建(被外部删除后再访问),
        第一次 connect 时 ensure_schema() 兜底建表,避免
        "no such table: sessions" 错误。
        """
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        # 兜底: 检查 sessions 表是否存在,没有就建
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        )
        if cur.fetchone() is None:
            self._init_schema_on_conn(conn)
        try:
            yield conn
        finally:
            conn.close()
