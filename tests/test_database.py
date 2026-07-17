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
    assert "meetings" in table_names
    assert "transcript_segments" in table_names
    assert "people" in table_names
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
        conn.execute(
            "INSERT INTO meetings (id, source, title) VALUES (?, ?, ?)",
            ("m1", "live", "test"),
        )
        row = conn.execute("SELECT id FROM meetings").fetchone()
    assert row["id"] == "m1"


def test_default_admin_can_be_disabled(tmp_path):
    db = Database(str(tmp_path / "no-admin.db"), create_default_admin=False)
    db.init_schema()

    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    assert count == 0
