"""pyannote 离线说话人识别服务

定位: 上传录音文件时的"高准确度"说话人识别模式。
- 准确度: Diarization Error Rate ~18% (业界 SOTA)
- 延迟: 2-5 秒 (需整段音频后处理,不能实时)
- 依赖: pyannote.audio >= 3.1.0 + HF_TOKEN 环境变量
- 模型: pyannote/speaker-diarization-community-1 (MIT 许可证,免费商用)

调研依据:
- pyannote 3.1: 5s 窗口 + 1s 步长 (90% overlap) + spectral clustering
- 离线 SOTA,DER 18% on AMI benchmark
- 实时做不到 (作者官方 README 明确说"not out of the box")

用法:
    diar = PyannoteDiarizer()
    segments = diar.diarize("audio.wav")  # [(start, end, "SPEAKER_00"), ...]
"""
import logging
import os
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger("Matrix_Pyannote")


class PyannoteDiarizer:
    """pyannote 离线说话人识别

    单例懒加载:首次调用 diarize() 时初始化 pipeline(下载模型 ~50MB)。
    失败时不抛异常,返回空列表,让上层 fallback 到 CamPlus。
    """

    _instance = None
    _pipeline = None
    _enabled = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._pipeline is not None:
            return
        # 检查 HF_TOKEN
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            logger.warning(
                "[PYANNOTE] HF_TOKEN 未设置,pyannote 离线模式不可用 — 用户上传文件时将 fallback 到 CamPlus"
            )
            self._enabled = False
            return
        try:
            from pyannote.audio import Pipeline  # noqa: F401
            import torch
        except ImportError as e:
            logger.warning(f"[PYANNOTE] pyannote.audio 未安装: {e}")
            self._enabled = False
            return
        try:
            logger.info("[PYANNOTE] 加载 pyannote/speaker-diarization-community-1 (~50MB,首次需联网)...")
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-community-1",
                token=token,
            )
            # 默认 CPU (MPS 上 pyannote 兼容性未验证)
            self._pipeline.to(torch.device("cpu"))
            self._enabled = True
            logger.info("[PYANNOTE] 加载完成,可用于离线高准确度说话人识别")
        except Exception as e:
            logger.error(f"[PYANNOTE] 加载失败: {e}")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        """是否可用(检查 HF_TOKEN + 模型是否加载成功)"""
        return self._enabled

    def diarize(self, audio_path: str) -> List[Tuple[float, float, str]]:
        """对音频文件做离线说话人识别

        Args:
            audio_path: 音频文件路径 (WAV/MP3/M4A 等,pyannote 通过 ffmpeg 解码)

        Returns:
            List of (start_sec, end_sec, speaker_id) — speaker_id 形如 "SPEAKER_00"
            失败时返回 []
        """
        if not self._enabled:
            return []
        if not Path(audio_path).exists():
            logger.warning(f"[PYANNOTE] 文件不存在: {audio_path}")
            return []
        try:
            output = self._pipeline(audio_path)
            # output.speaker_diarization 是 Annotation,可迭代 (turn, speaker)
            results = []
            for turn, speaker in output.speaker_diarization:
                results.append((float(turn.start), float(turn.end), str(speaker)))
            logger.info(f"[PYANNOTE] {audio_path}: {len(results)} 个说话人段,识别出 {len(set(s[2] for s in results))} 个不同说话人")
            return results
        except Exception as e:
            logger.error(f"[PYANNOTE] diarize 失败: {e}")
            return []


def get_pyannote_diarizer() -> PyannoteDiarizer:
    """获取 pyannote 服务单例"""
    return PyannoteDiarizer()


def align_speakers_to_segments(
    pyannote_segments: List[Tuple[float, float, str]],
    asr_segments: List[dict],
) -> List[dict]:
    """把 pyannote 离线说话人识别结果对齐到 ASR 转写的 segments

    策略: 对每个 ASR segment,找覆盖其中点的 pyannote turn,
    用该 turn 的 speaker_id 替换 ASR segment 的 speaker_id。

    Args:
        pyannote_segments: [(start, end, "SPEAKER_00"), ...] 来自 PyannoteDiarizer.diarize
        asr_segments: [{"start": float, "end": float, "text": str, "speaker": str, ...}, ...]

    Returns:
        asr_segments 的深拷贝,speaker 字段被替换为 pyannote 的 SPEAKER_xx
    """
    if not pyannote_segments:
        return asr_segments

    out = []
    for seg in asr_segments:
        seg_start = float(seg.get("start", 0))
        seg_end = float(seg.get("end", seg_start))
        # 找覆盖 ASR segment 中点的 pyannote turn
        seg_mid = (seg_start + seg_end) / 2
        matched_speaker = None
        for ps, pe, spk in pyannote_segments:
            if ps <= seg_mid < pe:
                matched_speaker = spk
                break
        if matched_speaker is None:
            # 退而求其次: 找最大重叠的 turn
            best_overlap = 0.0
            for ps, pe, spk in pyannote_segments:
                overlap = max(0, min(seg_end, pe) - max(seg_start, ps))
                if overlap > best_overlap:
                    best_overlap = overlap
                    matched_speaker = spk
        new_seg = dict(seg)
        new_seg["speaker"] = matched_speaker or seg.get("speaker", "Unknown")
        new_seg["diarization_source"] = "pyannote" if matched_speaker else "fallback"
        out.append(new_seg)
    return out