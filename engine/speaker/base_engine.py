"""声纹引擎基类

提供说话人管理功能的共享实现，子类只需实现核心的声纹提取方法。
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger("Matrix_Core")


class BaseSpeakerEngine(ABC):
    """声纹引擎基类
    
    子类需要实现:
        - extract_feat: 提取声纹特征，返回 (embedding, audio_duration)
        - compare_and_identify: 说话人匹配与识别
        - _model_name: 返回模型名称用于日志
    
    注意: 子类使用 __new__ 单例模式时，所有属性初始化应在 __new__ 中完成
    """
    
    @abstractmethod
    def extract_feat(self, audio_data: np.ndarray) -> Tuple[np.ndarray, float]:
        """提取声纹特征 - 子类必须实现
        
        Returns:
            Tuple[np.ndarray, float]: (embedding, audio_duration)
        """
        pass
    
    @abstractmethod
    def compare_and_identify(self, current_emb, client_id: str, audio_duration: float = 0) -> str:
        """说话人匹配与识别 - 子类必须实现
        
        Args:
            current_emb: 当前声纹特征
            client_id: 客户端ID
            audio_duration: 音频时长（秒），用于判断可靠性
            
        Returns:
            str: 说话人ID
        """
        pass
    
    @property
    @abstractmethod
    def _model_name(self) -> str:
        """模型名称 - 用于日志"""
        pass
    
    def list_speakers(self, session_id: Optional[str] = None) -> List[Dict]:
        """获取说话人列表"""
        try:
            if session_id:
                results = self.collection.get(
                    where={"session_id": session_id},
                    include=["metadatas"]
                )
            else:
                results = self.collection.get(include=["metadatas"])
            
            speakers = []
            for i, speaker_id in enumerate(results['ids']):
                meta = results['metadatas'][i] if results['metadatas'] else {}
                speakers.append({
                    "id": speaker_id,
                    "name": meta.get("name", speaker_id),
                    "session_id": meta.get("session_id", ""),
                    "sample_count": meta.get("count", 1),
                    "last_update": meta.get("last_update", 0)
                })
            
            # 按更新时间倒序
            speakers.sort(key=lambda x: x["last_update"], reverse=True)
            return speakers
        except Exception as e:
            logger.error(f"[{self._model_name}] 获取说话人列表失败: {e}")
            return []
    
    def get_speaker(self, speaker_id: str) -> Optional[Dict]:
        """获取单个说话人信息"""
        try:
            results = self.collection.get(ids=[speaker_id], include=["metadatas"])
            if not results['ids']:
                return None
            
            meta = results['metadatas'][0]
            return {
                "id": speaker_id,
                "name": meta.get("name", speaker_id),
                "session_id": meta.get("session_id", ""),
                "sample_count": meta.get("count", 1),
                "last_update": meta.get("last_update", 0)
            }
        except Exception as e:
            logger.error(f"[{self._model_name}] 获取说话人失败: {e}")
            return None
    
    def rename_speaker(self, speaker_id: str, name: str) -> bool:
        """重命名说话人"""
        try:
            results = self.collection.get(ids=[speaker_id], include=["metadatas", "embeddings"])
            if not results['ids']:
                logger.warning(f"[{self._model_name}] 说话人 {speaker_id} 不存在")
                return False
            
            meta = results['metadatas'][0]
            meta["name"] = name
            
            self.collection.update(
                ids=[speaker_id],
                embeddings=results['embeddings'],
                metadatas=[meta]
            )
            logger.info(f"[{self._model_name}] 已重命名 {speaker_id} -> {name}")
            return True
        except Exception as e:
            logger.error(f"[{self._model_name}] 重命名失败: {e}")
            return False
    
    def delete_speaker(self, speaker_id: str) -> bool:
        """删除说话人"""
        try:
            results = self.collection.get(ids=[speaker_id])
            if not results['ids']:
                logger.warning(f"[{self._model_name}] 说话人 {speaker_id} 不存在")
                return False

            self.collection.delete(ids=[speaker_id])
            logger.info(f"[{self._model_name}] 已删除说话人 {speaker_id}")
            return True
        except Exception as e:
            logger.error(f"[{self._model_name}] 删除失败: {e}")
            return False

    def add_speaker(
        self,
        speaker_id: str,
        embedding,
        name: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """主动注册声纹(API enroll 用)

        之前声纹只能靠 compare_and_identify 被动累积 — 没有公开 add 接口。
        加此方法让前端可"上传示例音频 + 命名 → 立即入库"。

        Args:
            speaker_id: 声纹 ID(必须匹配 Spk_[a-zA-Z0-9_]+ 格式)
            embedding: 一维 np.ndarray 声纹向量
            name: 显示名(可选,自动剥除控制字符)
            session_id: 关联会话 ID(可选)

        Returns:
            bool: 成功入库
        """
        import re
        import time
        if not re.match(r"^Spk_[a-zA-Z0-9_]{1,50}$", speaker_id):
            logger.error(f"[{self._model_name}] 非法 speaker_id 格式: {speaker_id}")
            return False
        if embedding is None or len(embedding) == 0:
            logger.error(f"[{self._model_name}] 空 embedding")
            return False
        # 净化 name:剥除控制字符,防止日志/响应注入
        if name is not None:
            clean_name = "".join(c for c in str(name) if c.isprintable() or c == " ")[:100]
            name = clean_name.strip() or speaker_id
        try:
            emb_list = embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)
            self.collection.upsert(
                ids=[speaker_id],
                embeddings=[emb_list],
                metadatas=[{
                    "name": name or speaker_id,
                    "session_id": session_id or "",
                    "count": 1,
                    "last_update": time.time(),
                    "confirmed": True,
                }],
            )
            logger.info(f"[{self._model_name}] 已注册声纹 {speaker_id} (主动 enroll)")
            return True
        except Exception as e:
            logger.error(f"[{self._model_name}] 注册声纹失败: {e}")
            return False

    def merge_speakers(
        self,
        target_id: str,
        source_ids: list,
    ) -> dict:
        """合并多个 source 声纹到 target (修正"同一人被识别成多 ID"问题)

        步骤:
        1. 拉取 target 和所有 source 的 embedding + metadata
        2. 加权平均 (按 count 权重) → 新 embedding
        3. target.upsert 新 embedding,合并 metadata.count / sample_count
        4. 删 source 在 ChromaDB 里的记录
        5. 返回新 metadata (供 API 层更新 segments.speaker_id)

        注意: 引擎只管 ChromaDB,segments 表更新由 API 层处理
        """
        import re
        import time
        import numpy as np
        if not re.match(r"^Spk_[a-zA-Z0-9_]{1,50}$", target_id):
            return {"ok": False, "error": f"非法 target_id 格式: {target_id}"}
        for sid in source_ids:
            if not re.match(r"^Spk_[a-zA-Z0-9_]{1,50}$", sid):
                return {"ok": False, "error": f"非法 source_id 格式: {sid}"}
        if target_id in source_ids:
            return {"ok": False, "error": "target_id 不能在 source_ids 里"}

        try:
            # 1. 拉取 target + 所有 source
            all_ids = [target_id] + list(source_ids)
            results = self.collection.get(ids=all_ids, include=["embeddings", "metadatas"])
            fetched = dict(zip(results['ids'], zip(results['embeddings'], results['metadatas'])))

            if target_id not in fetched:
                return {"ok": False, "error": f"target_id {target_id} 不存在"}

            # 2. 加权平均 (权重 = count)
            target_emb = np.array(fetched[target_id][0], dtype=np.float32)
            target_count = int(fetched[target_id][1].get("count", 1))
            target_sample_count = int(fetched[target_id][1].get("sample_count", target_count))
            merged_count = target_count
            merged_sample_count = target_sample_count

            for sid in source_ids:
                if sid not in fetched:
                    logger.warning(f"[MERGE] source {sid} 不在 ChromaDB,跳过")
                    continue
                emb = np.array(fetched[sid][0], dtype=np.float32)
                cnt = int(fetched[sid][1].get("count", 1))
                sc = int(fetched[sid][1].get("sample_count", cnt))
                # 加权: target_emb * target_count + emb * cnt
                # 然后除以总权重
                new_emb = (target_emb * target_count + emb * cnt) / (target_count + cnt)
                target_emb = new_emb
                target_count += cnt
                merged_count += cnt
                merged_sample_count += sc

            # 3. 重新 L2 normalize (ChromaDB 用 cosine 距离)
            norm = np.linalg.norm(target_emb)
            if norm > 1e-9:
                target_emb = target_emb / norm

            # 4. upsert target
            target_meta = dict(fetched[target_id][1])
            target_meta["count"] = merged_count
            target_meta["sample_count"] = merged_sample_count
            target_meta["last_update"] = time.time()
            self.collection.upsert(
                ids=[target_id],
                embeddings=[target_emb.tolist()],
                metadatas=[target_meta],
            )

            # 5. 删 source (只删实际存在的)
            existing_sources = [sid for sid in source_ids if sid in fetched]
            if existing_sources:
                self.collection.delete(ids=existing_sources)

            logger.info(f"[MERGE] {len(existing_sources)} 个 source → {target_id} (合并后 count={merged_count})")
            return {
                "ok": True,
                "target_id": target_id,
                "merged_source_ids": existing_sources,
                "new_count": merged_count,
            }
        except Exception as e:
            logger.error(f"[MERGE] 合并失败: {e}")
            return {"ok": False, "error": str(e)}

    def unassign_segments_speaker(self, speaker_id: str, segment_ids: list[int]) -> int:
        """把一组 segments 的 speaker_id 清成 NULL (拆分用)

        引擎层不直接做(segments 在 SQLite),由 API 层处理。
        这个方法保留接口,目前仅占位 — 真实更新在 API 层做。
        """
        # 不在这里实现,API 层用 repo.update_segment_speaker() 替代
        raise NotImplementedError("see app/api/speakers.py split_speaker endpoint")

    def get_smoothed_embedding(self, emb: np.ndarray, client_id: str) -> np.ndarray:
        """滑动窗口平均声纹"""
        if client_id not in self.emb_buffer:
            self.emb_buffer[client_id] = []
        
        self.emb_buffer[client_id].append(emb)
        if len(self.emb_buffer[client_id]) > self.EMB_BUFFER_SIZE:
            self.emb_buffer[client_id].pop(0)
        
        smoothed = np.mean(self.emb_buffer[client_id], axis=0)
        smoothed = smoothed / (np.linalg.norm(smoothed) + 1e-6)
        return smoothed
    
    def reset_buffer(self, client_id: str):
        """重置声纹缓存"""
        self.emb_buffer[client_id] = []
    
    def cleanup_client(self, client_id: str):
        """清理客户端资源（连接断开时调用）"""
        if client_id in self.emb_buffer:
            del self.emb_buffer[client_id]
            logger.info(f"[{self._model_name}] 已清理客户端 {client_id} 的缓冲区")