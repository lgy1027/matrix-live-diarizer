"""CamPlus 声纹引擎

模型: damo/speech_campplus_sv_zh-cn_16k-common
EER: 0.65% (VoxCeleb)
"""
import numpy as np
import torch
import chromadb
from chromadb.config import Settings
from modelscope.models import Model
import time
import logging
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

from engine.speaker.base_engine import BaseSpeakerEngine
from engine.speaker.speaker_factory import ENGINE_CONFIG

logger = logging.getLogger("Matrix_Speaker")


class CamPlusEngine(BaseSpeakerEngine):
    """CamPlus 声纹引擎 - 继承基类
    
    优化策略：
    1. 短音频处理：不足2秒的音频标记为"临时说话人"
    2. 延迟注册：需要多个样本确认新说话人
    3. 智能合并：相似度高的临时说话人自动合并
    """
    
    # 短于这个时长的音频跳过声纹匹配,标 Spk_unknown。用户短促回复
    # "嗯/对/好"(0.1-0.3s)cosine 距离波动大、易误合;CamPlus 训练在
    # 4-10s 段,0.3s 以下 embedding 无意义。
    MIN_USABLE_DURATION = 0.3

    # 最小音频长度(秒)用于"可靠"声纹提取(走正常阈值 vs 宽松阈值)
    # 方向 A: 从 1.5 降到 1.0,让更多段参与声纹(但仍要求有起码质量)
    MIN_AUDIO_DURATION = 1.0

    # 短于这个时长的段(<MIN_AUDIO 但 >=MIN_USABLE)走更宽容阈值
    # 让短段能合并到现有 Spk(避免空库期碎片)
    SHORT_SEGMENT_DURATION = 0.5

    @staticmethod
    def _classify_segment_duration(audio_duration: float) -> str:
        """纯函数(供测试):根据 audio_duration 分类声纹匹配策略

        Returns:
            "skip":  audio_duration < MIN_USABLE_DURATION — 直接返 "Spk_unknown"
            "short": MIN_USABLE ≤ audio_duration < SHORT_SEGMENT — 走宽松阈值
            "reliable": audio_duration ≥ SHORT_SEGMENT — 走正常阈值
        """
        if audio_duration < CamPlusEngine.MIN_USABLE_DURATION:
            return "skip"
        if audio_duration < CamPlusEngine.SHORT_SEGMENT_DURATION:
            return "short"
        return "reliable"

    def __init__(self):
        # 本地优先:物化到 models/speaker/camplus/(复用 modelscope 缓存,自动迁移),
        # Model.from_pretrained 接受本地目录路径。无本地则下载迁移。
        from app.services.model_resolver import resolve_modelscope
        model_id = 'damo/speech_campplus_sv_zh-cn_16k-common'
        local = resolve_modelscope(
            model_id, "speaker", "camplus",
            revision=ENGINE_CONFIG["campplus"]["model_revision"],
        )
        logger.info("[CamPlus] 从本地路径加载: %s", local)
        self.device = "cpu"
        self.model = Model.from_pretrained(local, device='cpu')
        self.model.eval()

        self.chroma_client = chromadb.EphemeralClient(
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name="speaker_fingerprints",
            metadata={"hnsw:space": "cosine"}
        )
        self.emb_buffer = defaultdict(list)
        self.EMB_BUFFER_SIZE = 5
        self.pending_speakers = defaultdict(list)
        self.PENDING_THRESHOLD = 3
        self.ENGINE_NAME = "CamPlus"
        logger.info("[CamPlus] 引擎初始化完成")

    @property
    def _model_name(self) -> str:
        return "CamPlus"

    def extract_feat(self, audio_data: np.ndarray) -> Tuple[np.ndarray, float]:
        """提取声纹特征，返回 (embedding, 音频时长)"""
        try:
            audio_duration = len(audio_data) / 16000.0  # 假设16kHz采样率
            
            tensor = torch.FloatTensor(audio_data).unsqueeze(0)
            with torch.no_grad():
                outputs = self.model(tensor)
                emb = outputs['spk_embedding'] if isinstance(outputs, dict) else outputs
                final_emb = emb.cpu().numpy().flatten()
                final_emb = final_emb / (np.linalg.norm(final_emb) + 1e-6)
                return final_emb, audio_duration
        except Exception as e:
            logger.error(f"[CamPlus] 提取异常: {e}")
            return None, 0

    def get_smoothed_embedding(self, emb: np.ndarray, client_id: str) -> np.ndarray:
        """滑动窗口平均声纹（仅实时流使用，文件上传应直接用原 embedding）"""
        self.emb_buffer[client_id].append(emb)
        if len(self.emb_buffer[client_id]) > self.EMB_BUFFER_SIZE:
            self.emb_buffer[client_id].pop(0)

        smoothed = np.mean(self.emb_buffer[client_id], axis=0)
        smoothed = smoothed / (np.linalg.norm(smoothed) + 1e-6)
        return smoothed

    def reset_buffer(self, client_id: str):
        """重置声纹缓存"""
        self.emb_buffer[client_id] = []
        # 不重置 pending_speakers，保留累积信息

    def cleanup_client(self, client_id: str):
        """清理客户端资源（连接断开时调用）"""
        if client_id in self.emb_buffer:
            del self.emb_buffer[client_id]
        if client_id in self.pending_speakers:
            del self.pending_speakers[client_id]
        self.delete_session_clusters(client_id)
        logger.info(f"[CamPlus] 已清理客户端 {client_id} 的缓冲区")

    def _check_pending_speakers(self, emb: np.ndarray, client_id: str) -> Optional[str]:
        """检查临时说话人缓存，看是否匹配已有的临时说话人"""
        if client_id not in self.pending_speakers:
            return None

        pending_list = self.pending_speakers[client_id]

        for i, (pending_emb, _, spk_id, count) in enumerate(pending_list):
            # 计算相似度
            similarity = np.dot(emb, pending_emb)
            distance = 1 - similarity

            if distance < 0.40:  # 相似度 > 60%
                # 更新临时说话人
                new_count = count + 1
                # 更新平均 embedding
                new_emb = (pending_emb * count + emb) / new_count
                new_emb = new_emb / (np.linalg.norm(new_emb) + 1e-6)

                pending_list[i] = (new_emb, 0, spk_id, new_count)

                # 如果累积足够样本，正式注册
                if new_count >= self.PENDING_THRESHOLD:
                    self.collection.add(
                        ids=[spk_id],
                        embeddings=[new_emb.tolist()],
                        metadatas=[{"session_id": client_id, "count": new_count, "last_update": time.time(), "confirmed": True}]
                    )
                    logger.info(f"[CONFIRMED] {spk_id} (samples={new_count})")
                    pending_list.pop(i)
                    return spk_id

                logger.debug(f"[PENDING MATCH] {spk_id} (samples={new_count}/{self.PENDING_THRESHOLD})")
                return spk_id

        return None

    def compare_and_identify(
        self,
        current_emb,
        client_id: str,
        audio_duration: float = 0,
        use_buffer: bool = True,
        default_name: str | None = None,
    ) -> tuple[str, float]:
        """说话人匹配与识别 - 优化版

        Args:
            current_emb: 当前声纹特征
            client_id: 客户端ID
            audio_duration: 音频时长（秒），用于判断可靠性
            use_buffer: 是否使用滑动窗口平滑。
                - True (默认): 实时流场景，同一 client 持续说话，buffer 平滑抖动
                - False: 文件上传场景，每次上传是独立 speaker 查询，buffer 残留会污染

        Returns:
            tuple[str, float]: (说话人ID, 置信度 0.0-1.0)
                - 短段(<MIN_USABLE_DURATION) → ("Spk_unknown", 0.0)
                - embedding=None → ("Spk_unknown", 0.0)
                - 命中已有 Spk(高/边缘阈值) → (spk_id, 1.0 - best_dist)
                - 新建 Spk → (new_id, 1.0 - best_dist)  (新 Spk 通常置信度较低)
        """
        if current_emb is None:
            # 返回 Spk_unknown 而非 "Unknown":符合 ^Spk_ 格式,和下游
            # speaker_id 校验 pattern、默认值保持一致。
            return "Spk_unknown", 0.0

        # 段时长分类用纯函数,便于测试和复用
        segment_class = self._classify_segment_duration(audio_duration)
        if segment_class == "skip":
            return "Spk_unknown", 0.0
        is_short_segment = (segment_class == "short")
        is_reliable = (segment_class == "reliable")

        # 阈值: 距离越小越相似
        # 方向 A: 收紧 LOW(避免误合) + 放宽 HIGH(容错短段) + 加宽 grace
        LOW_THRESHOLD = 0.50      # 高置信度(原 0.40,收紧避免误合)
        HIGH_THRESHOLD = 0.60     # 边缘区域(原 0.50,放宽容错短段)
        # 短段(0.3-0.5s)用更宽松阈值
        if is_short_segment:
            LOW_THRESHOLD = 0.65
            HIGH_THRESHOLD = 0.75
        MIN_SAMPLES_FOR_EDGE = 2  # 降低边缘匹配样本要求

        # 新 Spk grace period:阈值放宽 0.08。空库期短段 cosine 波动
        # 0.05-0.10 是常态,太严会把同一个人的短段误判成新说话人。
        GRACE_PERIOD_SAMPLES = 3
        GRACE_THRESHOLD_BOOST = 0.08
        import time as _time
        current_ts = _time.time()

        # 实时流：用滑动窗口平滑（抖动场景）
        # 文件上传：直接用当前 embedding（避免 buffer 跨文件污染）
        if use_buffer:
            smoothed_emb = self.get_smoothed_embedding(current_emb, client_id)
        else:
            smoothed_emb = current_emb
        emb_list = smoothed_emb.tolist()

        # 先检查临时说话人缓存
        pending_spk = self._check_pending_speakers(smoothed_emb, client_id)
        if pending_spk:
            # pending 命中:置信度尚未"确认"(样本累积中),用 0.5 中性值
            return pending_spk, 0.5

        # 查询已确认的说话人
        results = self.query_session_candidates(
            emb_list,
            client_id,
            n_results=3,
        )

        if results['distances'] and len(results['distances'][0]) > 0:
            # 找最佳匹配
            best_dist = results['distances'][0][0]
            best_id = results['ids'][0][0]
            best_meta = results['metadatas'][0][0]
            best_count = best_meta.get("count", 1)

            # 对于可靠样本，使用更严格的阈值
            # 对于不可靠样本，使用更宽松的阈值（倾向于匹配已有说话人）
            low_thresh = LOW_THRESHOLD if is_reliable else LOW_THRESHOLD + 0.10
            high_thresh = HIGH_THRESHOLD if is_reliable else HIGH_THRESHOLD + 0.10

            # 最佳候选是样本数 < 3 的新 Spk 时,再放宽 high 阈值,给新
            # 声纹一段"软启动"窗口,让后续短段/失真样本能合并进来。
            if best_count < GRACE_PERIOD_SAMPLES:
                high_thresh += GRACE_THRESHOLD_BOOST
                logger.debug(
                    f"[GRACE] {best_id} samples={best_count}, high_thresh 放宽到 {high_thresh:.2f}"
                )

            logger.debug(f"[MATCH] Dist={best_dist:.4f}, Best={best_id}, Count={best_count}, Reliable={is_reliable}")

            # 高置信度匹配
            if best_dist < low_thresh:
                # 防漂移:已积累足够样本(>= 10)后,锁定均值不再更新,
                # 避免长会议中被边缘样本推离早期聚类中心
                if best_count < 10:
                    old_mean = np.array(
                        self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                    )
                    # 自适应权重:样本越多更新越保守
                    weight = min(0.15, 1.5 / (best_count + 1))
                    new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                    new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                    embedding_to_save = new_mean.tolist()
                else:
                    # 锁定,只更新 count/timestamp
                    embedding_to_save = None

                update_kwargs = {
                    "ids": [best_id],
                    "metadatas": [self.cluster_metadata(best_meta, client_id, best_count + 1)],
                }
                if embedding_to_save is not None:
                    update_kwargs["embeddings"] = [embedding_to_save]
                self.collection.update(**update_kwargs)
                logger.info(f"[MATCHED] {best_id} (sim: {1-best_dist:.0%}, samples={best_count+1}, "
                            f"{'updated' if embedding_to_save is not None else 'locked'})")
                return best_id, float(1 - best_dist)
            
            # 边缘匹配：需要已有足够样本
            if best_dist < high_thresh and best_count >= MIN_SAMPLES_FOR_EDGE:
                update_kwargs = {
                    "ids": [best_id],
                    "metadatas": [self.cluster_metadata(best_meta, client_id, best_count + 1)],
                }
                old_mean = np.array(
                    self.collection.get(ids=[best_id], include=['embeddings'])['embeddings'][0]
                )
                weight = min(0.10, 1.0 / (best_count + 1))
                new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                update_kwargs["embeddings"] = [new_mean.tolist()]
                self.collection.update(**update_kwargs)
                logger.info(f"[EDGE OK] {best_id} (sim: {1-best_dist:.0%}, samples={best_count+1})")
                return best_id, float(1 - best_dist)
            
            # 检查第二、第三候选（可能有更好的匹配）
            for i in range(1, min(3, len(results['distances'][0]))):
                dist = results['distances'][0][i]
                spk_id = results['ids'][0][i]
                meta = results['metadatas'][0][i]
                count = meta.get("count", 1)
                
                if dist < high_thresh and count >= MIN_SAMPLES_FOR_EDGE:
                    update_kwargs = {
                        "ids": [spk_id],
                        "metadatas": [self.cluster_metadata(meta, client_id, count + 1)],
                    }
                    old_mean = np.array(
                        self.collection.get(ids=[spk_id], include=['embeddings'])['embeddings'][0]
                    )
                    weight = min(0.10, 1.0 / (count + 1))
                    new_mean = (old_mean * (1 - weight)) + (smoothed_emb * weight)
                    new_mean = new_mean / (np.linalg.norm(new_mean) + 1e-6)
                    update_kwargs["embeddings"] = [new_mean.tolist()]
                    self.collection.update(**update_kwargs)
                    logger.info(f"[ALT MATCH] {spk_id} (sim: {1-dist:.0%}, samples={count+1})")
                    return spk_id, float(1 - dist)
            
            if best_dist < high_thresh:
                logger.debug(f"[EDGE?] Dist={best_dist:.4f} 样本不足({best_count}<{MIN_SAMPLES_FOR_EDGE})")
            else:
                logger.debug(f"[NEW?] Dist={best_dist:.4f}")
        else:
            # 空 DB / 无候选 → 新建 Spk 路径,后续 return 用 best_dist=None 兜底
            best_dist = None

        # 注册新说话人（但可能还在待确认状态）
        # 整改: new_id 改用 uuid hex 8 字符, 短且唯一; 同时支持 default_name (从 filename 或 client_id 推)
        import uuid as _uuid
        new_id = f"Spk_{_uuid.uuid4().hex[:8]}"
        # 默认名: 优先用 default_name, 否则剥 client_id 当 fallback
        display_name = default_name or client_id.replace("test_client_", "").replace("_", " ").strip() or new_id

        if is_reliable:
            # 可靠样本：直接注册
            self.collection.add(
                ids=[new_id],
                embeddings=[emb_list],
                metadatas=[{
                    "session_id": client_id,
                    "count": 1,
                    "last_update": time.time(),
                    "confirmed": True,
                    "name": display_name,  # 整改: 写入默认显示名
                }],
            )
            logger.info(f"[NEW SPEAKER] {new_id} name={display_name!r} (reliable, {audio_duration:.1f}s)")
        else:
            # 不可靠样本：放入待确认缓存
            self.pending_speakers[client_id].append((smoothed_emb, audio_duration, new_id, 1))
            logger.info(f"[PENDING] {new_id} name={display_name!r} (unreliable, {audio_duration:.1f}s, need {self.PENDING_THRESHOLD} samples)")

            # 如果待确认缓存超过限制，强制注册最老的一个
            if len(self.pending_speakers[client_id]) > 5:
                old_emb, _, old_id, old_count = self.pending_speakers[client_id].pop(0)
                self.collection.add(
                    ids=[old_id],
                    embeddings=[old_emb.tolist()],
                    metadatas=[{
                        "session_id": client_id,
                        "count": old_count,
                        "last_update": time.time(),
                        "confirmed": False,
                        "name": display_name,
                    }],
                )
                logger.info(f"[FORCE REGISTER] {old_id} (pending overflow)")

        # 新建 Spk 时的置信度:有候选时返 (1 - best_dist) 反映"与最近候选的相似度"
        # 无候选(空 DB)时返 0.0;前端可据此判断"是否值得展示给用户看"
        new_speaker_score = float(1 - best_dist) if best_dist is not None else 0.0
        return new_id, new_speaker_score
