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
        words_json: Optional[str] = None,
    ) -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO segments
                   (session_id, segment_index, speaker_id, text, start_time, end_time, confidence, words_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, segment_index, speaker_id, text, start_time, end_time, confidence, words_json),
            )
            conn.commit()
        return cur.lastrowid

    def list_segments(self, session_id: str) -> list[dict]:
        import json as _json
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM segments WHERE session_id = ? ORDER BY segment_index ASC",
                (session_id,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            # 解析 words_json:DB 存的是 str,前端用 list
            if d.get("words_json"):
                try:
                    d["words"] = _json.loads(d["words_json"])
                except (ValueError, TypeError):
                    d["words"] = None
            else:
                d["words"] = None
            result.append(d)
        return result

    def update_segment_speaker(self, segment_id: int, new_speaker_id: Optional[str]) -> bool:
        """更新单 segment 的 speaker_id (split / 重新指派用)

        new_speaker_id 为 None 时清空(标记为未识别)
        """
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE segments SET speaker_id = ? WHERE id = ?",
                (new_speaker_id, segment_id),
            )
            conn.commit()
        return cur.rowcount > 0

    def reassign_speaker(self, old_speaker_id: str, new_speaker_id: str) -> int:
        """把所有 segments.speaker_id == old 的改成 new (merge 用)

        返回更新的行数
        """
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE segments SET speaker_id = ? WHERE speaker_id = ?",
                (new_speaker_id, old_speaker_id),
            )
            conn.commit()
        return cur.rowcount

    def clear_segments_speaker(self, segment_ids: list[int], speaker_id: Optional[str] = None) -> int:
        """把指定 segments 的 speaker_id 清空(可选:仅清特定 speaker 的)

        用于 split: 用户挑出"这个 segment 不该是 Spk_001" → 改 null
        """
        if not segment_ids:
            return 0
        placeholders = ",".join("?" * len(segment_ids))
        with self.db.connect() as conn:
            if speaker_id is not None:
                cur = conn.execute(
                    f"UPDATE segments SET speaker_id = NULL WHERE id IN ({placeholders}) AND speaker_id = ?",
                    (*segment_ids, speaker_id),
                )
            else:
                cur = conn.execute(
                    f"UPDATE segments SET speaker_id = NULL WHERE id IN ({placeholders})",
                    segment_ids,
                )
            conn.commit()
        return cur.rowcount

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

    def count_sessions_with_speaker(self, speaker_id: str) -> int:
        """统计引用了 speaker_id 的 session 数 (用于删除声纹时展示影响面)

        返回 DISTINCT session_id 计数. 0 表示没文稿引用, 删除是安全的.
        """
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(DISTINCT session_id) FROM segments WHERE speaker_id = ?",
                (speaker_id,),
            ).fetchone()
        return row[0] if row else 0

    def count_segments_with_speaker(self, speaker_id: str) -> int:
        """统计引用了 speaker_id 的 segment 总数 (用于删声纹影响预览)"""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM segments WHERE speaker_id = ?",
                (speaker_id,),
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

    # ---- 全文搜索 (Roadmap #2.2) ----

    @staticmethod
    def _sanitize_fts_query(q: str) -> str:
        """FTS5 MATCH query 清洗: 去除特殊字符 (", *, :, -, .) 避免解析错误

        FTS5 把 - 当 NOT 运算符,4o 会被当 column name 而报错。
        简单方案: 把非 [中文/英文/数字] 字符替换为空格。
        """
        import re
        # 保留中文、英文、数字;其他字符替换为空格
        cleaned = re.sub(r"[^\w一-鿿]+", " ", q, flags=re.UNICODE)
        return cleaned.strip()

    @staticmethod
    def _build_snippet(text: str, q: str, ctx_chars: int = 8) -> str:
        """造 snippet: 找 q 位置 + 前后 ctx_chars 字符 + [match]X[/match]

        q 含特殊字符或 trigram 跨边界时,先尝试完整 q,失败再退化到 q 前缀。
        找不到任何位置时,返回前 32 字符不包 [match] 标记。
        """
        if not text:
            return ""
        match_str = q
        pos = text.find(match_str)
        if pos < 0:
            for sub_len in (min(2, len(q)), 1):
                if sub_len == 0:
                    break
                sub = q[:sub_len]
                p = text.find(sub)
                if p >= 0:
                    pos = p
                    match_str = sub
                    break
        if pos < 0:
            return text[:32] + ("..." if len(text) > 32 else "")
        start = max(0, pos - ctx_chars)
        end = min(len(text), pos + len(match_str) + ctx_chars)
        prefix = ("..." if start > 0 else "")
        suffix = ("..." if end < len(text) else "")
        window = text[start:end]
        mp = pos - start
        return (
            prefix
            + window[:mp]
            + "[match]" + match_str + "[/match]"
            + window[mp + len(match_str):]
            + suffix
        )

    def search_segments(
        self,
        q: str,
        session_id: Optional[str] = None,
        speaker_id: Optional[str] = None,
        limit: int = 50,
    ) -> tuple[int, list[dict]]:
        """全文搜索 segments (Roadmap #2.2)

        Args:
            q: 搜索关键词(3+ 字中文命中率高,英文/数字也支持)
            session_id: 限定会话(可选)
            speaker_id: 限定说话人(可选)
            limit: 返回数量上限

        Returns:
            (total, hits) — hits 含 segment 字段 + session 元数据 + snippet 高亮

        策略: FTS5 trigram 主路径 + LIKE '%q%' 兜底(2 字 / 含特殊字符场景)
        """
        if not q or not q.strip():
            return 0, []

        # 1. FTS5 路径
        fts_q = self._sanitize_fts_query(q)
        fts_results: list[dict] = []
        if fts_q:
            with self.db.connect() as conn:
                # contentless FTS5 不支持 snippet() (因为没存原 text)
                # 用 s.text 自己造 snippet: 找 query 第一次出现位置 + 前后各 N 字符
                sql = """
                    SELECT
                        s.id            AS segment_id,
                        s.session_id    AS session_id,
                        s.speaker_id    AS speaker_id,
                        s.text          AS text,
                        s.start_time    AS start_time,
                        s.end_time      AS end_time,
                        sess.title      AS session_title,
                        sess.original_filename AS session_filename
                    FROM segments_fts
                    JOIN segments s ON s.id = segments_fts.rowid
                    JOIN sessions sess ON sess.id = s.session_id
                    WHERE segments_fts MATCH ?
                """
                params: list = [fts_q + "*"]  # 前缀匹配: 兜底 "语音" 也能命中"语音识别"
                if session_id:
                    sql += " AND s.session_id = ?"
                    params.append(session_id)
                if speaker_id:
                    sql += " AND s.speaker_id = ?"
                    params.append(speaker_id)
                sql += " ORDER BY rank LIMIT ?"
                params.append(limit)
                fts_results = [dict(r) for r in conn.execute(sql, params).fetchall()]
                # 用 helper 造 snippet(支持 FTS5 命中 + LIKE 兜底两种场景)
                for hit in fts_results:
                    hit["snippet"] = self._build_snippet(hit["text"] or "", q)

        # 2. LIKE 兜底路径(对 FTS5 未命中场景: 2 字 / 特殊字符)
        like_q = q.strip()
        like_results: list[dict] = []
        if like_q:
            with self.db.connect() as conn:
                sql = """
                    SELECT
                        s.id            AS segment_id,
                        s.session_id    AS session_id,
                        s.speaker_id    AS speaker_id,
                        s.text          AS text,
                        s.start_time    AS start_time,
                        s.end_time      AS end_time,
                        sess.title      AS session_title,
                        sess.original_filename AS session_filename,
                        s.text          AS snippet
                    FROM segments s
                    JOIN sessions sess ON sess.id = s.session_id
                    WHERE s.text LIKE ?
                """
                params = [f"%{like_q}%"]
                if session_id:
                    sql += " AND s.session_id = ?"
                    params.append(session_id)
                if speaker_id:
                    sql += " AND s.speaker_id = ?"
                    params.append(speaker_id)
                sql += " LIMIT ?"
                params.append(limit)
                like_results = [dict(r) for r in conn.execute(sql, params).fetchall()]

        # 3. UNION 去重 (FTS5 优先,因为有 snippet 高亮)
        seen: set[int] = set()
        merged: list[dict] = []
        for hit in fts_results + like_results:
            sid = hit["segment_id"]
            if sid not in seen:
                seen.add(sid)
                # LIKE 路径的 snippet 是 raw text,补 [match] 标记
                if not hit.get("snippet") or hit["snippet"] == hit.get("text"):
                    hit["snippet"] = self._build_snippet(hit["text"] or "", like_q or q)
                merged.append(hit)
        total = len(merged)
        return total, merged[:limit]
