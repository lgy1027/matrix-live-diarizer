"""K/V 设置存储（用户偏好）"""


class SettingsRepository:
    def __init__(self, db):
        self.db = db

    def get(self, key: str) -> str | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO settings (key, value) VALUES (?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (key, value),
            )
            conn.commit()

    def delete(self, key: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()

    def get_bool(self, key: str, default: bool = False) -> bool:
        v = self.get(key)
        if v is None:
            return default
        return v.lower() in ("true", "1", "yes", "on")

    def all_keys(self) -> list[str]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT key FROM settings").fetchall()
        return [r["key"] for r in rows]
