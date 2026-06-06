"""会话与片段的 CRUD"""
import uuid
from typing import Optional
from .database import Database


class TranscriptRepository:
    def __init__(self, db: Database):
        self.db = db

    # ---- sessions ----

    def create_session(
        self,
        source: str,
        title: Optional[str] = None,
        client_id: Optional[str] = None,
        original_filename: Optional[str] = None,
        duration_sec: Optional[float] = None,
    ) -> str:
        sid = str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO sessions
                   (id, source, title, client_id, original_filename, duration_sec)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (sid, source, title, client_id, original_filename, duration_sec),
            )
            conn.commit()
        return sid

    def get_session(self, sid: str) -> Optional[dict]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (sid,)
            ).fetchone()
        return dict(row) if row else None

    def list_sessions(
        self,
        source: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        sql = "SELECT * FROM sessions WHERE is_archived = 0"
        params: list = []
        if source:
            sql += " AND source = ?"
            params.append(source)
        if q:
            sql += " AND (title LIKE ? OR original_filename LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like])
        # id DESC 作为第二排序键，避免 created_at 同一秒时排序不稳定
        sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self.db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def update_session(self, sid: str, **fields) -> None:
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields if k != "updated_at")
        params = [v for k, v in fields.items() if k != "updated_at"]
        params.append(sid)
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE sessions SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                params,
            )
            conn.commit()

    def delete_session(self, sid: str) -> None:
        with self.db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            conn.commit()

    # ---- segments ----

    def insert_segment(
        self,
        session_id: str,
        segment_index: int,
        text: str,
        start_time: float,
        end_time: float,
        speaker_id: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO segments
                   (session_id, segment_index, speaker_id, text, start_time, end_time, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, segment_index, speaker_id, text, start_time, end_time, confidence),
            )
            conn.commit()
        return cur.lastrowid

    def list_segments(self, session_id: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM segments WHERE session_id = ? ORDER BY segment_index ASC",
                (session_id,),
            ).fetchall()
        return [dict(r) for r in rows]
