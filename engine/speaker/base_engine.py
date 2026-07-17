"""Shared contract for process-local speaker clustering engines."""
import logging
import time
from abc import ABC, abstractmethod
from typing import Tuple

import numpy as np


logger = logging.getLogger("Matrix_Core")


class BaseSpeakerEngine(ABC):
    """Extract embeddings and cluster anonymous speakers within one meeting."""

    @abstractmethod
    def extract_feat(self, audio_data: np.ndarray) -> Tuple[np.ndarray, float]:
        """Return a normalized embedding and audio duration in seconds."""

    @abstractmethod
    def compare_and_identify(
        self,
        current_emb,
        client_id: str,
        audio_duration: float = 0,
        use_buffer: bool = True,
        default_name: str | None = None,
    ) -> tuple[str, float]:
        """Return an anonymous meeting-local speaker label and confidence."""

    @property
    @abstractmethod
    def _model_name(self) -> str:
        """Human-readable model name for logs."""

    @property
    def model_id(self) -> str:
        """Stable embedding-space identity used for persistent voice samples."""
        from .speaker_factory import embedding_model_id

        return embedding_model_id(self)

    def get_smoothed_embedding(self, emb: np.ndarray, client_id: str) -> np.ndarray:
        """Apply a per-client sliding average to an embedding."""
        self.emb_buffer[client_id].append(emb)
        if len(self.emb_buffer[client_id]) > self.EMB_BUFFER_SIZE:
            self.emb_buffer[client_id].pop(0)
        smoothed = np.mean(self.emb_buffer[client_id], axis=0)
        return smoothed / (np.linalg.norm(smoothed) + 1e-6)

    def reset_buffer(self, client_id: str) -> None:
        """Reset the smoothing window after a speech boundary."""
        self.emb_buffer[client_id] = []

    def cleanup_client(self, client_id: str) -> None:
        """Release per-client runtime state after disconnect."""
        if client_id in self.emb_buffer:
            del self.emb_buffer[client_id]
            logger.info("[%s] 已清理客户端 %s 的缓冲区", self._model_name, client_id)
        self.delete_session_clusters(client_id)

    def delete_session_clusters(self, client_id: str) -> None:
        """Delete ephemeral anonymous clusters belonging to one live meeting."""
        collection = getattr(self, "collection", None)
        if collection is None:
            return
        try:
            collection.delete(where={"session_id": client_id})
        except (AttributeError, ValueError, TypeError):
            logger.warning(
                "[%s] 无法清理会话声纹簇 %s", self._model_name, client_id,
                exc_info=True,
            )

    def query_session_candidates(
        self,
        embedding,
        client_id: str,
        n_results: int = 3,
    ) -> dict:
        """Query anonymous clusters belonging to the current meeting only."""
        return self.collection.query(
            query_embeddings=[embedding],
            n_results=n_results,
            where={"session_id": client_id},
        )

    @staticmethod
    def cluster_metadata(metadata: dict | None, client_id: str, count: int) -> dict:
        """Update runtime cluster metadata without changing its meeting scope."""
        updated = dict(metadata or {})
        updated["session_id"] = client_id
        updated["count"] = count
        updated["last_update"] = time.time()
        return updated
