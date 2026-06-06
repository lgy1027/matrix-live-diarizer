"""SQLite 数据库连接与 schema 初始化"""
import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager


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
    is_final      INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_segments_session ON segments(session_id, segment_index);

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
"""


class Database:
    """SQLite 包装：自动建目录、WAL 模式、Row 工厂"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        """创建表 + 索引 + 启用 WAL"""
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            # WAL 模式是持久化的，单独设置
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.commit()

    @contextmanager
    def connect(self):
        """获取连接，启用 Row 工厂"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()
