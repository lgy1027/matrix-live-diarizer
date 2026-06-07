import os
import tempfile
from app.repositories.database import Database


def test_init_creates_tables(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.init_schema()

    with db.connect() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    table_names = {t[0] for t in tables}
    assert "sessions" in table_names
    assert "segments" in table_names
    assert "speaker_aliases" in table_names
    assert "settings" in table_names


def test_wal_mode_enabled(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.init_schema()
    with db.connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_connect_returns_connection_with_row_factory(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    db.init_schema()
    with db.connect() as conn:
        conn.execute("INSERT INTO sessions (id, source) VALUES (?, ?)", ("s1", "websocket"))
        row = conn.execute("SELECT id FROM sessions").fetchone()
    assert row["id"] == "s1"
