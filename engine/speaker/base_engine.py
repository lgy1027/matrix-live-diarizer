"""Shared contract for process-local speaker clustering engines."""
import logging
import time
from abc import ABC, abstractmethod
from typing import Tuple

import numpy as np


logger = logging.getLogger("Matrix_Core")


class BaseSpeakerEngine(ABC):
    """Extract embeddings and cluster anonymous speakers within one meeting."""

    # 声纹匹配/聚类逻辑的日志走 Matrix_Speaker,与子类模块 logger 一致;
    # 重构前 compare_and_identify 在子类里用各自的 Matrix_Speaker logger,
    # 上提到基类后统一用此属性,避免日志改挂到 Matrix_Core 造成分桶丢失。
    _logger = logging.getLogger("Matrix_Speaker")

    @abstractmethod
    def extract_feat(self, audio_data: np.ndarray) -> Tuple[np.ndarray, float]:
        """Return a normalized embedding and audio duration in seconds."""

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
        except Exception:
            # chroma 内部可能抛 IndexError/sqlite3.OperationalError/自定义错误,
            # 只记日志不向上抛 — finalize 路径不能因清理失败中断,否则该 meeting
            # 的匿名簇永久泄漏且后续 WS 流程崩在 finalize。
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

    # 子类覆盖: (reliable_low, reliable_high, unreliable_low, unreliable_high)
    # 决定 compare_and_identify 的动态阈值基线。CamPlus 走自己的 compare_and_identify,
    # 不读此项;ERes2Net / Wespeaker 共享本类实现,必须设。
    THRESHOLD_PROFILE: tuple | None = None

    def _get_dynamic_threshold(self, count: int, is_reliable: bool = True) -> tuple:
        """动态阈值 — 可靠样本用更严格阈值,count 越高略微收紧(封顶 0.05)。"""
        if self.THRESHOLD_PROFILE is None:
            # 基类 compare_and_identify 非抽象方法,新引擎若未设 THRESHOLD_PROFILE
            # 又未重写 compare_and_identify,会在有候选时解包 None 抛 TypeError。
            # 此处提前抛明确错误,便于定位。
            raise NotImplementedError(
                f"{type(self).__name__} 使用基类 compare_and_identify 但未设置 "
                "THRESHOLD_PROFILE;请设 (reliable_low, reliable_high, "
                "unreliable_low, unreliable_high),或重写 compare_and_identify。"
            )
        r_low, r_high, u_low, u_high = self.THRESHOLD_PROFILE
        base_low = r_low if is_reliable else u_low
        base_high = r_high if is_reliable else u_high
        adjustment = min(0.05, count * 0.005)
        return base_low + adjustment, base_high + adjustment

    def compare_and_identify(
        self,
        current_emb,
        client_id: str,
        audio_duration: float = 0,
        use_buffer: bool = True,
        default_name: str | None = None,
    ) -> tuple[str, float]:
        """说话人匹配与识别

        Args:
            current_emb: 当前声纹特征
            client_id: 客户端ID
            audio_duration: 音频时长（秒）
            use_buffer: 实时流启用平滑；独立文件识别应关闭
            default_name: 新说话人的默认显示名

        Returns:
            tuple[str, float]: (说话人ID, 置信度 0.0-1.0)
        """
        if current_emb is None:
            # Spk_unknown 符合 ^Spk_ 格式,与下游默认值一致
            return "Spk_unknown", 0.0

        # 判断是否为可靠样本
        is_reliable = audio_duration >= 1.5
        MIN_SAMPLES_FOR_EDGE = 2

        smoothed_emb = (
            self.get_smoothed_embedding(current_emb, client_id)
            if use_buffer
            else current_emb
        )
        emb_list = smoothed_emb.tolist()

        results = self.query_session_candidates(
            emb_list,
            client_id,
            n_results=3,
        )

        if results['distances'] and len(results['distances'][0]) > 0:
            min_dist = results['distances'][0][0]
            best_id = results['ids'][0][0]
            metadata = results['metadatas'][0][0]
            count = metadata.get("count", 1)

            low_threshold, high_threshold = self._get_dynamic_threshold(count, is_reliable)

            self._logger.debug(f"[MATCH] Dist={min_dist:.4f}, Low={low_threshold:.2f}, High={high_threshold:.2f}, Best={best_id}, Count={count}")

            # 高置信度匹配
            if min_dist < low_threshold:
                update_kwargs = {
                    "ids": [best_id],
                    "metadatas": [self.cluster_metadata(metadata, client_id, count + 1)],
                }
                old_mean = np.array(
                    self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                )
                weight = min(0.12, 0.8 / (count + 1))
                new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                update_kwargs["embeddings"] = [new_mean.tolist()]
                self.collection.update(**update_kwargs)
                self._logger.info(f"[MATCHED] {best_id} (sim: {1-min_dist:.0%})")
                return best_id, float(max(0.0, min(1.0, 1 - min_dist)))

            # 边缘匹配
            if min_dist < high_threshold:
                self.match_history[client_id].append((best_id, min_dist))
                if len(self.match_history[client_id]) > self.HISTORY_SIZE:
                    self.match_history[client_id].pop(0)

                recent_matches = [m[0] for m in self.match_history[client_id]]
                same_speaker_count = recent_matches.count(best_id)

                if same_speaker_count >= 2 or count >= MIN_SAMPLES_FOR_EDGE:
                    update_kwargs = {
                        "ids": [best_id],
                        "metadatas": [self.cluster_metadata(metadata, client_id, count + 1)],
                    }
                    old_mean = np.array(
                        self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                    )
                    weight = min(0.08, 0.5 / (count + 1))
                    new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                    new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                    update_kwargs["embeddings"] = [new_mean.tolist()]
                    self.collection.update(**update_kwargs)
                    self._logger.info(f"[EDGE MATCH] {best_id} (连续确认 {same_speaker_count} 次)")
                    return best_id, float(max(0.0, min(1.0, 1 - min_dist)))

                self._logger.debug(f"[EDGE] Dist={min_dist:.4f} 待确认 (连续匹配 {same_speaker_count} 次)")
        else:
            # 空 DB / 无候选 → 新建 Spk 路径,后续 return 用 min_dist=None 兜底
            min_dist = None

        # 注册新说话人
        new_id = f"Spk_{int(time.time_ns() % (1 << 31))}"
        self.collection.add(
            ids=[new_id],
            embeddings=[emb_list],
            metadatas=[{
                "session_id": client_id,
                "count": 1,
                "last_update": time.time(),
                "name": default_name or new_id,
            }]
        )
        self._logger.info(f"[NEW SPEAKER] {new_id} ({audio_duration:.1f}s)")
        # 新建 Spk 时如果有 best_dist,返 1-best_dist;无候选(空 DB)返 0.0
        new_speaker_score = float(max(0.0, min(1.0, 1 - min_dist))) if min_dist is not None else 0.0
        return new_id, new_speaker_score
