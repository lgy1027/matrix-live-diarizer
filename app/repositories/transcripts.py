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

    # 允许通过 update_session 修改的列(防越权改 client_id/is_archived 等)
    _SESSION_UPDATABLE_COLS = frozenset({"title", "is_archived"})

    def update_session(self, sid: str, **fields) -> None:
        if not fields:
            return
        # 白名单过滤:只接受预定义列,其它(尤其是 client_id/created_at)丢弃
        safe_fields = {k: v for k, v in fields.items()
                       if k in self._SESSION_UPDATABLE_COLS}
        if not safe_fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in safe_fields)
        params = list(safe_fields.values())
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

    def get_enriched_sessions(self, source=None, q=None, limit=50, offset=0) -> tuple[int, list[dict]]:
        """返回 (total, items)，items 中每个 session 含
        - duration: 时长（秒）— 前端用
        - segments_count: 段数
        - speakers: distinct speaker_id 列表（不含 None）
        - size_mb: 文件大小（仅 upload，本地计算文件 size）
        - size 字段在 sessions 表里没有；可由 frontend 按需计算
        """
        # 1. 主查询
        sql = "SELECT * FROM sessions WHERE is_archived = 0"
        params: list = []
        if source:
            sql += " AND source = ?"
            params.append(source)
        if q:
            sql += " AND (title LIKE ? OR original_filename LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like])
        sql += " ORDER BY created_at DESC"
        items_sql = sql + " LIMIT ? OFFSET ?"
        count_sql = "SELECT COUNT(*) FROM (" + sql + ")"
        items_params = params + [limit, offset]

        with self.db.connect() as conn:
            total = conn.execute(count_sql, params).fetchone()[0]
            rows = conn.execute(items_sql, items_params).fetchall()
            if not rows:
                return total, []
            # 2. 批量聚合 segments（一次查询所有 session）
            ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(ids))
            agg_rows = conn.execute(
                f"""SELECT session_id,
                          COUNT(*) AS segments_count,
                          COUNT(DISTINCT speaker_id) AS unique_speakers,
                          GROUP_CONCAT(DISTINCT speaker_id) AS speaker_ids
                   FROM segments
                   WHERE session_id IN ({placeholders})
                   GROUP BY session_id""",
                ids,
            ).fetchall()
            agg_by_sid = {r["session_id"]: dict(r) for r in agg_rows}

        # 3. enrich
        items = []
        for r in rows:
            s = dict(r)
            # 字段重命名：duration_sec → duration（前端用）
            s["duration"] = s.get("duration_sec") or 0
            # 聚合
            agg = agg_by_sid.get(s["id"], {})
            s["segments_count"] = agg.get("segments_count", 0)
            speaker_ids_str = agg.get("speaker_ids") or ""
            s["speakers"] = [x for x in speaker_ids_str.split(",") if x]
            items.append(s)
        return total, items

    def get_speaker_count(self, session_id: str) -> int:
        """返回 distinct speaker_id 数（不含 NULL）"""
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT COUNT(DISTINCT speaker_id) FROM segments
                   WHERE session_id = ? AND speaker_id IS NOT NULL""",
                (session_id,),
            ).fetchone()
        return row[0] if row else 0

    def get_segment_count(self, session_id: str) -> int:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM segments WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return row[0] if row else 0

    def clear_speaker_id_from_segments(self, speaker_id: str) -> int:
        """把 segments 表里所有 speaker_id == X 的清空成 NULL

        用于 cascade 删除声纹前清空引用，避免 segments 出现孤立 Spk_xxx 引用。
        返回被清的段数（无匹配返回 0）。
        """
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE segments SET speaker_id = NULL WHERE speaker_id = ?",
                (speaker_id,),
            )
            conn.commit()
        return cur.rowcount
