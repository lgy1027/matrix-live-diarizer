"""Named people and their registered voice samples."""
from __future__ import annotations
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

from engine.speaker.speaker_factory import resolve_embedding_model_id

from .database import Database


class DuplicateVoiceSampleError(ValueError):
    """The same decoded voice content is already enrolled for this person."""


class PeopleRepository:
    def __init__(self, db: Database):
        self.db = db

    def create(self, name: str, notes: str | None = None) -> str:
        person_id = str(uuid.uuid4())
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO people (id, name, notes) VALUES (?, ?, ?)",
                (person_id, name, notes),
            )
            conn.commit()
        return person_id

    def get(self, person_id: str) -> Optional[dict]:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT p.*,
                          (SELECT COUNT(*) FROM voice_samples vs
                           WHERE vs.person_id = p.id) AS sample_count,
                          COALESCE((SELECT SUM(vs.duration_sec) FROM voice_samples vs
                                    WHERE vs.person_id = p.id), 0.0)
                              AS total_sample_duration,
                          (SELECT COUNT(DISTINCT ms.meeting_id) FROM meeting_speakers ms
                           WHERE ms.person_id = p.id) AS meeting_count
                   FROM people p WHERE p.id = ?""",
                (person_id,),
            ).fetchone()
        return dict(row) if row else None

    def list(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT p.*,
                          (SELECT COUNT(*) FROM voice_samples vs
                           WHERE vs.person_id = p.id) AS sample_count,
                          COALESCE((SELECT SUM(vs.duration_sec) FROM voice_samples vs
                                    WHERE vs.person_id = p.id), 0.0)
                              AS total_sample_duration,
                          (SELECT COUNT(DISTINCT ms.meeting_id) FROM meeting_speakers ms
                           WHERE ms.person_id = p.id) AS meeting_count
                   FROM people p ORDER BY p.name COLLATE NOCASE"""
            ).fetchall()
        return [dict(row) for row in rows]

    def update(self, person_id: str, *, name: str, notes: str | None = None) -> bool:
        with self.db.connect() as conn:
            cursor = conn.execute(
                """UPDATE people SET name = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (name, notes, person_id),
            )
            conn.commit()
        return cursor.rowcount > 0

    def delete(self, person_id: str) -> bool:
        with self.db.connect() as conn:
            paths = [
                row[0] for row in conn.execute(
                    "SELECT audio_path FROM voice_samples WHERE person_id = ?",
                    (person_id,),
                ).fetchall()
            ]
            cursor = conn.execute("DELETE FROM people WHERE id = ?", (person_id,))
            conn.commit()
        for path in paths:
            Path(path).unlink(missing_ok=True)
        return cursor.rowcount > 0

    def add_sample(
        self,
        person_id: str,
        *,
        audio_path: str,
        duration_sec: float,
        embedding: bytes | None = None,
        embedding_dim: int | None = None,
        model_name: str | None = None,
        quality_score: float | None = None,
        effective_speech_sec: float = 0.0,
        audio_sha256: str | None = None,
    ) -> str:
        sample_id = str(uuid.uuid4())
        persisted_model_id = resolve_embedding_model_id(model_name, embedding_dim)
        if model_name and persisted_model_id is None:
            raise ValueError("embedding model is incompatible with its vector dimension")
        with self.db.connect() as conn:
            if conn.execute(
                "SELECT 1 FROM people WHERE id = ?", (person_id,)
            ).fetchone() is None:
                raise ValueError("person not found")
            try:
                conn.execute(
                    """INSERT INTO voice_samples
                       (id, person_id, audio_path, embedding, embedding_dim, model_name,
                        duration_sec, effective_speech_sec, quality_score, audio_sha256)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sample_id, person_id, audio_path, embedding, embedding_dim,
                        persisted_model_id, duration_sec, effective_speech_sec,
                        quality_score, audio_sha256,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as exc:
                if (
                    audio_sha256
                    and "voice_samples.person_id, voice_samples.audio_sha256" in str(exc)
                ):
                    raise DuplicateVoiceSampleError(
                        "duplicate voice sample for person"
                    ) from exc
                raise
        return sample_id

    def list_samples(self, person_id: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT id, person_id, embedding_dim, model_name,
                          embedding IS NOT NULL AS has_embedding,
                          duration_sec, effective_speech_sec, quality_score, created_at
                   FROM voice_samples WHERE person_id = ? ORDER BY created_at DESC""",
                (person_id,),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            model_id = resolve_embedding_model_id(
                item.get("model_name"), item.get("embedding_dim")
            )
            item["model_id"] = model_id
            item["embedding_status"] = (
                "ready" if item.pop("has_embedding") and model_id else "stale"
            )
            items.append(item)
        return items

    def get_sample(self, person_id: str, sample_id: str) -> Optional[dict]:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT id, person_id, audio_path, duration_sec,
                          effective_speech_sec, quality_score, embedding_dim,
                          model_name, created_at
                   FROM voice_samples WHERE id = ? AND person_id = ?""",
                (sample_id, person_id),
            ).fetchone()
        return dict(row) if row else None

    def delete_sample(self, person_id: str, sample_id: str) -> bool:
        """Delete one enrolled sample and its managed local audio file."""
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT audio_path FROM voice_samples WHERE id = ? AND person_id = ?",
                (sample_id, person_id),
            ).fetchone()
            if row is None:
                return False
            cursor = conn.execute(
                "DELETE FROM voice_samples WHERE id = ? AND person_id = ?",
                (sample_id, person_id),
            )
            conn.commit()
        Path(row["audio_path"]).unlink(missing_ok=True)
        return cursor.rowcount > 0

    def matching_samples(self, model_name: str, embedding_dim: int) -> list[dict]:
        requested_model_id = resolve_embedding_model_id(model_name, embedding_dim)
        if requested_model_id is None:
            return []
        with self.db.connect() as conn:
            rows = conn.execute(
                """SELECT vs.person_id, p.name, vs.embedding, vs.embedding_dim,
                          vs.model_name, vs.quality_score, vs.duration_sec,
                          vs.effective_speech_sec
                   FROM voice_samples vs JOIN people p ON p.id = vs.person_id
                   WHERE vs.embedding IS NOT NULL AND vs.embedding_dim = ?""",
                (embedding_dim,),
            ).fetchall()
        compatible = []
        for row in rows:
            item = dict(row)
            model_id = resolve_embedding_model_id(
                item.get("model_name"), item.get("embedding_dim")
            )
            if model_id != requested_model_id:
                continue
            item["model_id"] = model_id
            compatible.append(item)
        return compatible

    def has_sample_hash(self, person_id: str, audio_sha256: str) -> bool:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM voice_samples WHERE person_id = ? AND audio_sha256 = ?",
                (person_id, audio_sha256),
            ).fetchone() is not None
