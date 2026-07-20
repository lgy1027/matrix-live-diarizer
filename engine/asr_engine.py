"""ASR 语音识别引擎"""
import torch
import numpy as np
import asyncio
import logging
import threading
import time
import os
import scipy.signal as signal
from modelscope import snapshot_download as _ms_snapshot_download
from qwen_asr import Qwen3ASRModel
from engine.asr.contracts import empty_asr_result, make_asr_result
from app.services.model_resolver import resolve_hf, resolve_silero_vad
# ModelScope CDN 限速常见(实测 8MB/s,1.75GB 约 4 分钟),易触发 90s 超时。
# 兜底:ModelScope 失败 → 改用 HF 本地缓存(前提:已下完,~/.cache/huggingface/hub/)
from huggingface_hub import snapshot_download as _hf_snapshot_download
HF_LOCAL_FILES_ONLY = True
QWEN_ASR_REVISION = os.environ.get(
    "QWEN_ASR_REVISION", "4ce9cc728b473a5aedbe7b6e1ea45646316824dc"
)
QWEN_ALIGNER_REVISION = os.environ.get(
    "QWEN_ALIGNER_REVISION", "cf1c50164ea3ac48240d12bef5ead74aee0720cc"
)
SILERO_VAD_REVISION = os.environ.get(
    "SILERO_VAD_REVISION", "76e3dc408eb2a5c655c34e230d2d5459b4439daa"
)
# Qwen3ForcedAligner 是可选依赖(给字级时间戳用),只在 _load_with_fallback 内 lazy import
# 这样测试 mock qwen_asr 简单 module 时(无 __path__)不会在 import 阶段就失败


def snapshot_download(repo_id: str, **kwargs):
    """下载 model,优先 ModelScope,失败 fallback HF 本地缓存"""
    try:
        return _ms_snapshot_download(repo_id, **kwargs)
    except Exception as e:
        logger = __import__('logging').getLogger("ASR_Engine")
        logger.warning(f"[ASR] ModelScope 下载失败 ({type(e).__name__}),fallback HF 本地缓存")
        # HF fallback 必须 local_files_only=True,避免网络问题
        return _hf_snapshot_download(repo_id, local_files_only=HF_LOCAL_FILES_ONLY)

logger = logging.getLogger("ASR_Engine")

# 扩展的幻觉词列表
HALLUCINATIONS = [
    # 常见幻觉词
    "谢谢。", "大家再见。", "字幕由", "感谢收看",
    "谢谢大家。", "谢谢观看。", "再见。", "拜拜。",
    # 无意义输出
    "嗯。", "啊。", "呃。", "这个。",
    # 节目相关幻觉
    "出品人", "制片人", "监制", "导演", "编剧",
    "主演", "特邀演员", "友情出演", "联合出品",
    "本节目由", "本视频由", "本片由",
    # 平台水印
    "西瓜视频", "抖音", "快手", "B站", "哔哩哔哩",
    "YouTube", "优酷", "爱奇艺", "腾讯视频",
    # 重复模式
    "。。", "，，", "、、", "。。。",
]


class ASREngine:
    _instance = None

    def __new__(cls):
        if not cls._instance:
            cls._instance = super(ASREngine, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self):
        if self.initialized:
            return

        from app.config import config
        self.config = config.audio

        # 设备选择（auto 优先 mps，失败回退 cpu）
        requested = self.config.asr_device
        if requested == "auto":
            if torch.cuda.is_available():
                preferred = "cuda"
            elif torch.backends.mps.is_available():
                preferred = "mps"
            else:
                preferred = "cpu"
        else:
            preferred = requested
        self.device = preferred
        logger.info(f"[ASR] 初始化中，设备: {self.device} (requested={requested})")

        try:
            success = self._load_with_fallback(preferred)
        except Exception as e:
            logger.error(f"[ASR] 初始化异常: {e}")
            success = False

        if not success:
            logger.error("[ASR] 所有设备尝试失败，引擎不可用")
        else:
            logger.info(f"[ASR] 模型加载成功（VAD 已启用）设备={self.device}")

    def _load_with_fallback(self, preferred: str) -> bool:
        """按首选设备 → CPU 顺序尝试加载，每设备有超时（防 MPS 死锁）。"""
        if preferred == "cpu":
            order = ["cpu"]
        else:
            order = [preferred, "cpu"]

        timeout = self.config.asr_load_timeout_sec

        for device in order:
            logger.info(f"[ASR] 尝试加载到 {device}（超时 {timeout}s）")
            t0 = time.time()
            result: dict = {"ok": False, "err": None, "asr_model": None, "cancelled": False}

            def _worker():
                try:
                    if result["cancelled"]:
                        return
                    # 本地优先:模型物化到 models/asr/Qwen3-ASR-0.6B/(复用 HF 缓存,
                    # 不重新下载),from_pretrained 接受本地目录路径。
                    # 注意:不传 revision — QWEN_ASR_REVISION 是 modelscope 的 hash,
                    # HF 上不存在;HF 走 main 分支,从已缓存物化即可。
                    model_dir = resolve_hf(
                        "Qwen/Qwen3-ASR-0.6B", "asr", "Qwen3-ASR-0.6B",
                    )
                    if result["cancelled"]:
                        return
                    dtype = torch.bfloat16 if device in ("cuda", "mps") else torch.float32
                    # 可选加载 forced aligner (Qwen3-ForcedAligner-0.6B, ~600MB)
                    # forced_aligner 传本地路径字符串(与原 snapshot_download 返回值一致,
                    # from_pretrained 内部按 str 处理),物化到 models/asr/Qwen3-ForcedAligner-0.6B/。
                    forced_aligner_id = None
                    if self.config.asr_word_timestamps:
                        if result["cancelled"]:
                            return
                        logger.info("[ASR] 加载 forced aligner (Qwen3-ForcedAligner-0.6B)")
                        forced_aligner_id = resolve_hf(
                            "Qwen/Qwen3-ForcedAligner-0.6B", "asr",
                            "Qwen3-ForcedAligner-0.6B",
                        )
                    if result["cancelled"]:
                        return
                    result["asr_model"] = Qwen3ASRModel.from_pretrained(
                        model_dir, dtype=dtype, device_map=device,
                        forced_aligner=forced_aligner_id,
                    )
                    if result["cancelled"]:
                        # 已被取消:刚加载的模型无人持有,清引用让 GC 回收
                        result["asr_model"] = None
                        return
                    result["ok"] = True
                except Exception as e:
                    result["err"] = e

            th = threading.Thread(target=_worker, daemon=True)
            th.start()
            th.join(timeout=timeout)
            elapsed = time.time() - t0

            if th.is_alive():
                logger.warning(
                    f"[ASR] {device} 加载超时 ({elapsed:.0f}s > {timeout}s)，放弃此设备"
                )
                # 超时后置 cancel 标志,daemon worker 在下一个阶段边界主动
                # return,减少与下一个设备加载线程并发占显存/内存(daemon 会随
                # 主进程退出,但服务长跑时仍值得尽早收尾)。
                result["cancelled"] = True
                if result.get("asr_model") is not None:
                    result["asr_model"] = None
                continue

            if not result["ok"]:
                # 失败时立即释放已加载的 model 引用,避免后续 fallback 累积
                if result.get("asr_model") is not None:
                    del result["asr_model"]
                    try:
                        import gc; gc.collect()
                    except Exception:
                        pass

            if result["ok"]:
                self.device = device
                self.asr_model = result["asr_model"]
                # 加载 Silero VAD:物化到 models/vad/silero-vad/ 后离线加载。
                # resolve_silero_vad 本地优先,复用 torch hub 缓存 copytree(自动迁移),
                # 避开 torch.hub 的 GitHub API 调用(限流 403 会触发 torch 2.11
                # hub.py 的 _validate_not_a_forked_repo KeyError bug)。
                try:
                    _vad_dir = resolve_silero_vad()
                    self.vad_model, utils = torch.hub.load(
                        repo_or_dir=_vad_dir, model='silero_vad',
                        source='local', trust_repo=True,
                    )
                    self.get_speech_timestamps = utils[0]
                    self.vad_model.eval()
                    self.sample_rate = 16000
                except Exception as e:
                    logger.error(f"[ASR] VAD 加载失败: {e}")
                    return False
                logger.info(f"[ASR] {device} 加载成功 ({elapsed:.1f}s)")
                self.initialized = True
                return True

            logger.warning(f"[ASR] {device} 加载失败: {result['err']}")

        return False

    def is_silent(self, audio_data, threshold=0.012, use_vad=True):
        """智能静音检测：结合 RMS 和 VAD"""
        if len(audio_data) == 0: 
            return True
        
        # 快速 RMS 检测（第一道筛选）
        rms = np.sqrt(np.mean(audio_data**2))
        if rms < 0.001:  # 极低能量直接跳过
            return True
        
        if not use_vad:
            return rms < threshold
        
        # VAD 检测（更准确）
        try:
            audio_tensor = torch.FloatTensor(audio_data)
            speech_timestamps = self.get_speech_timestamps(
                audio_tensor, 
                self.vad_model,
                sampling_rate=self.sample_rate,
                threshold=0.5,
                min_speech_duration_ms=100,
                min_silence_duration_ms=50
            )
            # 如果没有检测到语音段，则认为是静音
            return len(speech_timestamps) == 0
        except Exception as e:
            logger.warning(f"[VAD] 检测异常，回退到 RMS: {e}")
            return rms < threshold

    def preprocess_audio(self, audio_data: np.ndarray) -> np.ndarray:
        """音频预处理：降噪、增益、滤波"""
        if len(audio_data) < 1600:
            return audio_data
        
        # 1. 高通滤波（去除低频噪声，如电源嗡嗡声）
        try:
            sos = signal.butter(4, 80, btype='highpass', fs=self.sample_rate, output='sos')
            audio_data = signal.sosfilt(sos, audio_data)
        except Exception:
            pass
        
        # 2. 自动增益控制 (AGC) - 改进版
        rms = np.sqrt(np.mean(audio_data**2))
        target_rms = 0.08  # 目标 RMS
        
        if rms > 1e-6:
            # 动态增益：保持合理范围
            gain = min(target_rms / rms, 10.0)  # 最大增益 10 倍
            audio_data = audio_data * gain
            
            # 软限幅防止削波
            peak = np.max(np.abs(audio_data))
            if peak > 0.95:
                audio_data = audio_data * (0.95 / peak)
                # 软限幅
                audio_data = np.tanh(audio_data * 1.5) / 1.5
        
        # 3. 软门限降噪（针对稳态噪声）
        # 注意:这是简化的能量门限,不是完整 STFT 谱减。VAD + Silero
        # 负责主要的语音检测,这一步只做粗粒度软门限。
        audio_data = self._spectral_subtraction(audio_data, noise_est_ratio=0.1)

        return audio_data

    def _spectral_subtraction(self, audio: np.ndarray, noise_est_ratio: float = 0.1) -> np.ndarray:
        """软门限降噪（不是完整谱减法）

        仅按能量阈值做软衰减,不依赖 STFT。设计取舍:轻量、无频域失真。
        真正的稳态噪声抑制请用完整 STFT + 谱减或 Wiener 滤波。
        """
        if len(audio) < 1024:
            return audio

        try:
            # 估计噪声（取开头一小段）
            noise_len = min(int(len(audio) * noise_est_ratio), 1600)
            noise = audio[:noise_len]

            noise_power = np.mean(noise**2)
            threshold = noise_power * 3
            sqrt_th = np.sqrt(threshold) + 1e-6

            # 能量低于阈值的部分做软衰减(不是直接置 0,避免引入突变)
            mask = np.abs(audio) > sqrt_th
            reduced = np.where(
                mask,
                audio,
                audio * (np.abs(audio) / sqrt_th)
            )

            return reduced
        except Exception:
            return audio

    def extract_speech_segments(self, audio_data: np.ndarray) -> list:
        """使用 VAD 提取语音片段"""
        try:
            audio_tensor = torch.FloatTensor(audio_data)
            speech_timestamps = self.get_speech_timestamps(
                audio_tensor,
                self.vad_model,
                sampling_rate=self.sample_rate,
                threshold=0.3,
                min_speech_duration_ms=200,
                min_silence_duration_ms=100,
                window_size_samples=512
            )
            
            segments = []
            for ts in speech_timestamps:
                start, end = ts['start'], ts['end']
                segment = audio_data[start:end]
                if len(segment) >= 1600:  # 至少 0.1 秒
                    segments.append(segment)
            
            return segments
        except Exception as e:
            logger.warning(f"[VAD] 分段异常: {e}")
            return [audio_data] if len(audio_data) >= 1600 else []

    def filter_hallucinations(self, text: str) -> str:
        """过滤幻觉词"""
        if not text:
            return ""
        
        # 移除幻觉词
        for h in HALLUCINATIONS:
            text = text.replace(h, "")
        
        # 移除重复标点
        import re
        text = re.sub(r'[。]{2,}', '。', text)
        text = re.sub(r'[，]{2,}', '，', text)
        text = re.sub(r'[、]{2,}', '、', text)
        
        # 过滤过短结果（可能是噪声）
        text = text.strip()
        if len(text) < 2:
            return ""
        
        # 过滤纯标点
        if all(c in '，。！？、；：""''（）【】…—' for c in text):
            return ""
        
        return text

    def evaluate_audio_quality(self, audio_data: np.ndarray) -> dict:
        """评估音频质量"""
        if len(audio_data) == 0:
            return {"quality": "empty", "score": 0}
        
        rms = np.sqrt(np.mean(audio_data**2))
        peak = np.max(np.abs(audio_data))
        
        # 计算动态范围
        if rms > 0:
            dynamic_range = 20 * np.log10(peak / (rms + 1e-10))
        else:
            dynamic_range = 0
        
        # 零交叉率（语音特征）
        zero_crossings = np.sum(np.abs(np.diff(np.sign(audio_data)))) / (2 * len(audio_data))
        
        # 评分
        score = 100
        if rms < 0.005:
            score -= 40  # 音量太低
        elif rms < 0.02:
            score -= 20  # 音量偏低
        elif rms > 0.5:
            score -= 30  # 可能削波
        
        if dynamic_range < 3:
            score -= 20  # 动态范围太小
        
        # 返回评估结果
        if score >= 80:
            quality = "excellent"
        elif score >= 60:
            quality = "good"
        elif score >= 40:
            quality = "fair"
        else:
            quality = "poor"
        
        return {
            "quality": quality,
            "score": score,
            "rms": float(rms),
            "peak": float(peak),
            "dynamic_range": float(dynamic_range),
            "zero_crossing_rate": float(zero_crossings)
        }

    async def run_asr(self, audio_data, use_preprocessing=True):
        """语音转写

        Returns:
            ASRResult-compatible dict. ``text`` and the legacy ``words`` field
            remain available; the shared contract also reports segments,
            timestamp granularity, language, and provider metadata.
        """
        if audio_data is None or len(audio_data) < 1600:
            return empty_asr_result()

        # 音频质量评估
        quality = self.evaluate_audio_quality(audio_data)
        if quality["score"] < 30:
            logger.warning(f"[ASR] 音频质量较差: {quality}")
            return empty_asr_result()

        # 预处理
        if use_preprocessing:
            audio_data = self.preprocess_audio(audio_data)

        # VAD 检测是否有语音
        if self.is_silent(audio_data, use_vad=True):
            logger.debug("[ASR] VAD 检测为静音，跳过")
            return empty_asr_result()

        try:
            loop = asyncio.get_event_loop()
            # 字级时间戳需要 forced aligner 初始化(已在 _load_with_fallback 完成)
            want_words = bool(self.config.asr_word_timestamps and self.asr_model.forced_aligner)
            res = await loop.run_in_executor(
                None,
                lambda: self.asr_model.transcribe(
                    audio=(audio_data, 16000),
                    return_time_stamps=want_words,
                )
            )

            if not res:
                return empty_asr_result()

            text = res[0].text.strip()
            words = None
            if want_words and res[0].time_stamps:
                words = [
                    {"text": it.text, "start": float(it.start_time), "end": float(it.end_time)}
                    for it in res[0].time_stamps
                ]

            return make_asr_result(text, words=words)

        except Exception as e:
            logger.error(f"[ASR] 推理异常: {e}")
            return empty_asr_result()

    def __del__(self):
        if hasattr(self, 'asr_model'):
            del self.asr_model
