"""ASR 语音识别引擎"""
import torch
import numpy as np
import asyncio
import logging
import scipy.signal as signal
from modelscope import snapshot_download
from qwen_asr import Qwen3ASRModel 

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
        
        # 设备检测：CUDA > MPS > CPU
        if torch.cuda.is_available():
            self.device = "cuda"
        elif torch.backends.mps.is_available():
            self.device = "mps"
        else:
            self.device = "cpu"
        logger.info(f"[ASR] 初始化中，设备: {self.device}")

        try:
            model_dir = snapshot_download("Qwen/Qwen3-ASR-0.6B")
            # CUDA 和 MPS 使用 bfloat16，CPU 使用 float32
            dtype = torch.bfloat16 if self.device in ("cuda", "mps") else torch.float32
            self.asr_model = Qwen3ASRModel.from_pretrained(
                model_dir, 
                dtype=dtype, 
                device_map=self.device
            )
            
            # 加载 Silero VAD
            self.vad_model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad', 
                model='silero_vad',
                trust_repo=True
            )
            self.get_speech_timestamps = utils[0]
            self.vad_model.eval()
            
            self.sample_rate = 16000
            self.initialized = True
            logger.info("[ASR] 模型加载成功（VAD 已启用）")
        except Exception as e:
            logger.error(f"[ASR] 初始化失败: {e}")

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
        
        # 3. 简单谱减降噪（针对稳态噪声）
        audio_data = self._spectral_subtraction(audio_data, noise_est_ratio=0.1)
        
        return audio_data

    def _spectral_subtraction(self, audio: np.ndarray, noise_est_ratio: float = 0.1) -> np.ndarray:
        """简单谱减降噪"""
        if len(audio) < 1024:
            return audio
        
        try:
            # 估计噪声（取开头一小段）
            noise_len = min(int(len(audio) * noise_est_ratio), 1600)
            noise = audio[:noise_len]
            
            # STFT 参数
            n_fft = 512
            hop_length = 256
            
            # 简化的谱减
            # 这里用卷积平滑代替完整 STFT，减少计算量
            noise_power = np.mean(noise**2)
            
            # 门限降噪
            threshold = noise_power * 3
            mask = np.abs(audio) > np.sqrt(threshold)
            
            # 软门限
            reduced = np.where(
                mask,
                audio,
                audio * (np.abs(audio) / (np.sqrt(threshold) + 1e-6))
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
        """语音转写（优化版）"""
        if audio_data is None or len(audio_data) < 1600:
            return ""

        # 音频质量评估
        quality = self.evaluate_audio_quality(audio_data)
        if quality["score"] < 30:
            logger.warning(f"[ASR] 音频质量较差: {quality}")
            return ""

        # 预处理
        if use_preprocessing:
            audio_data = self.preprocess_audio(audio_data)
        
        # VAD 检测是否有语音
        if self.is_silent(audio_data, use_vad=True):
            logger.debug("[ASR] VAD 检测为静音，跳过")
            return ""

        try:
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None, 
                lambda: self.asr_model.transcribe(audio=(audio_data, 16000))
            )
            
            if not res: 
                return ""
            
            text = res[0].text.strip()
            
            # 过滤幻觉词
            text = self.filter_hallucinations(text)
                
            return text

        except Exception as e:
            logger.error(f"[ASR] 推理异常: {e}")
            return ""

    def __del__(self):
        if hasattr(self, 'asr_model'):
            del self.asr_model
