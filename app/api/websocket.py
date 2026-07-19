"""WebSocket 实时音频流路由"""
import asyncio
import json
import time
import re
import numpy as np
import logging
import wave
from pathlib import Path
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketState

from app.config import config
from app.constants import SYSTEM_SPEAKER
from app.services import SessionContext
from app.runtime import EngineSnapshot
from app.services.realtime_auth import authenticate_websocket
from engine.speaker.speaker_factory import get_engine_info

logger = logging.getLogger("Matrix_Core")

# Bug-12: 实时字幕里的填充词/语气词,提升可读性
# 规则: 这些词如果独立出现(前后是标点/空格/字符串边界)就删掉
# 避免误伤"这个方案"等正常使用 — 只删独立位置
_FILLER_PATTERNS = [
    # 嗯/呃/啊 等单字语气词(独立位置: 字符串边界 或 前后是标点/空格)
    r"(?:^|(?<=[,，。、\s]))[嗯呃啊唉哦哈嘿哟]{1,2}(?=[,，。、\s]|$)",
    # 独立 "这个" 填充(后跟标点/空格/结束)
    r"(?:^|(?<=[,，。、\s]))这个(?=[,，。、\s]|$)",
    # 独立 "那个" 填充
    r"(?:^|(?<=[,，。、\s]))那个(?=[,，。、\s]|$)",
    # "就是说/讲讲"
    r"(?:^|(?<=[,，。、\s]))就是[说讲]?下?(?=[,，。、\s]|$)",
]

router = APIRouter()

# client_id 验证：只允许字母、数字、下划线，最长 64 字符
CLIENT_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_]{1,64}$')


def validate_client_id(client_id: str) -> str:
    """验证并清理 client_id，防止日志注入"""
    if not client_id:
        return "anonymous"
    # 移除换行符，防止日志注入
    safe_id = client_id.replace('\n', '').replace('\r', '')[:64]
    if not CLIENT_ID_PATTERN.match(safe_id):
        safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', safe_id)[:64] or "anonymous"
    return safe_id


def _runtime_for(websocket: WebSocket):
    return getattr(websocket.app.state, "runtime", None)


def _engine_snapshot(websocket: WebSocket) -> EngineSnapshot:
    snapshot = getattr(websocket, "_engine_snapshot", None)
    if snapshot is not None:
        return snapshot
    runtime = _runtime_for(websocket)
    if runtime is None:
        raise RuntimeError("Application runtime is not initialized")
    snapshot = runtime.snapshot()
    websocket._engine_snapshot = snapshot
    return snapshot


def check_engines(websocket: WebSocket):
    """检查引擎是否已初始化"""
    runtime = _runtime_for(websocket)
    if runtime is None or runtime.asr is None or runtime.speaker is None:
        raise RuntimeError("Application runtime is not initialized")


async def _ensure_live_meeting(
    websocket: WebSocket, client_id: str, *, notify: bool = True
) -> str:
    meeting_id = getattr(websocket, "_meeting_id", None)
    if meeting_id:
        return meeting_id
    default_title = f"实时记录-{time.strftime('%H%M%S')}"
    meeting_id = websocket.app.state.meeting_repo.create(
        source="live", title=default_title, processing_mode="quick", status="processing"
    )
    websocket._meeting_id = meeting_id
    if notify:
        await websocket.send_json(
            {"type": "meeting", "meeting_id": meeting_id, "title": default_title}
        )
    logger.info("[WS] %s 创建实时会议: %s", client_id, meeting_id)
    return meeting_id


async def _append_live_audio(
    websocket: WebSocket, client_id: str, pcm_bytes: bytes
) -> None:
    meeting_id = await _ensure_live_meeting(websocket, client_id)
    writer = getattr(websocket, "_audio_writer", None)
    if writer is None:
        live_dir = Path(config.storage.media_dir).resolve() / "live"
        live_dir.mkdir(parents=True, exist_ok=True)
        audio_path = live_dir / f"{meeting_id}.wav"
        writer = wave.open(str(audio_path), "wb")
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(config.audio.sample_rate)
        websocket._audio_writer = writer
        websocket._audio_path = str(audio_path)
        websocket.app.state.meeting_repo.update(
            meeting_id,
            audio_path=str(audio_path),
        )
    writer.writeframesraw(pcm_bytes)


def _close_live_audio(websocket: WebSocket) -> None:
    writer = getattr(websocket, "_audio_writer", None)
    if writer is not None:
        writer.close()
        websocket._audio_writer = None


def _make_audio_queue_item(websocket: WebSocket, pcm_bytes: bytes) -> tuple[int, bytes]:
    """为音频帧附加完整录音中的绝对 sample offset。

    WebSocket 二进制协议仍然只接收 PCM bytes；offset 仅存在于服务端队列中。
    因此即使有界队列丢弃旧帧，后续帧的时间也不会被压缩。
    """
    current_offset = getattr(websocket, "_received_audio_samples", 0)
    sample_offset = current_offset if isinstance(current_offset, int) else 0
    websocket._received_audio_samples = sample_offset + len(pcm_bytes) // 2
    return sample_offset, pcm_bytes


def _unpack_audio_queue_item(item, fallback_offset: int) -> tuple[int, bytes]:
    """读取带 offset 的新队列条目，并兼容内部测试/旧调用直接传 bytes。"""
    if (
        isinstance(item, tuple)
        and len(item) == 2
        and isinstance(item[0], int)
        and isinstance(item[1], bytes)
    ):
        return item
    return fallback_offset, item


# 状态机常量(模块级,供测试 import)
STATE_SILENCE = 0
STATE_SPEECH = 1
SILENCE_THRESHOLD_FRAMES = 8  # bug-fix: 3 帧 (384ms) 太短,自然换气就切碎。
                                          # 8 帧 ≈ 1024ms 允许 1 秒停顿不切(用户感受:响应延迟略增,但完整)
                                          # 保持模块级常量,便于 WebSocket 状态机测试直接覆盖。
LOUD_RMS_THRESHOLD = 0.005    # bug-fix: 0.015 偏高,某些帧瞬时 RMS 跌到这个值就被判静音 → buffer 不累积。原 0.015。
SILENCE_THRESHOLD_SECONDS = 0.8
PROCESSOR_DRAIN_TIMEOUT_SECONDS = 30.0


def classify_frame(chunk: np.ndarray, asr_engine_obj) -> bool:
    """判断单帧是否为语音

    纯函数化(供测试):两步判定
    1. 能量门: RMS > 阈值 才走 VAD,否则直接判静音
    2. VAD: 用 asr_engine.is_silent 精判

    返回 True = 是语音帧
    """
    if chunk is None or len(chunk) == 0:
        return False
    chunk_rms = float(np.sqrt(np.mean(chunk ** 2)))
    if chunk_rms <= LOUD_RMS_THRESHOLD:
        return False
    # 能量足够才走 VAD(节省 CPU)
    if asr_engine_obj is None:
        # 测试/无引擎情况:仅靠能量
        return True
    # bug-fix: silero-vad 对 2048 samples (128ms) 单帧判定不稳定,经常假阳性判静音
    # → buffer 永远累积不到 0.5s 以上,Qwen3-ASR 收不到长音频 → 转写空
    # 改用纯 RMS 判定(阈值已经过第一道门)
    return not asr_engine_obj.is_silent(chunk, use_vad=False)


def should_emit_segment(
    state: int,
    silence_count: int,
    buffer_len: int,
    sample_rate: int,
    max_segment_seconds: float,
    silence_threshold: int = SILENCE_THRESHOLD_FRAMES,
    *,
    silence_samples: int | None = None,
) -> bool:
    """判断当前帧后是否应该触发 ASR 识别

    触发条件(任一):
    1. STATE_SPEECH + 静音帧数 >= 阈值(语音段自然结束)
    2. STATE_SPEECH + 缓冲长度 >= 上限(强制识别,防 OOM)
    """
    if state != STATE_SPEECH:
        return False
    silence_reached = (
        silence_samples >= int(sample_rate * SILENCE_THRESHOLD_SECONDS)
        if silence_samples is not None
        else silence_count >= silence_threshold
    )
    if silence_reached:
        return True
    max_buffer = int(sample_rate * max_segment_seconds)
    if buffer_len >= max_buffer:
        return True
    return False


class SeqCounter:
    """单调递增 seq 分配器,用于 transcribing/ASR 结果配对

    协议:
    - next() 分配一个新 seq(在 SILENCE→SPEECH 时调用,推 transcribing 占位消息)
    - consume_pending() 取出并清空最近一次 next() 分配的 seq(在 ASR 完成时调用,让 ASR msg 与 transcribing 配对)
    - 两次 next() 之间未 consume_pending() 是允许的:旧 pending 会被覆盖(与 spec "同一时刻仅 1 个占位段" 对齐)
    """

    def __init__(self) -> None:
        self._n = 0
        self._pending: int | None = None

    def next(self) -> int:
        """分配并记住一个新 seq(用于 transcribing 占位)"""
        self._n += 1
        self._pending = self._n
        return self._n

    def consume_pending(self) -> int:
        """返回最近一次 next() 分配的 seq;若没有 pending(老消息/异常路径)返 0

        0 作为 sentinel 表示 "该消息没有 transcribing 配对" (前端可忽略 seq 字段或创建新段)
        """
        if self._pending is None:
            return 0
        v = self._pending
        self._pending = None
        return v


def should_push_transcribing(prev_state: int, new_state: int) -> bool:
    """判断是否应推 transcribing 占位消息

    仅在 SILENCE→SPEECH 状态切换时返回 True,即"用户开始说话"那一帧。
    """
    return prev_state == STATE_SILENCE and new_state == STATE_SPEECH


def next_state(state: int, is_speech: bool) -> int:
    """状态机推进: SILENCE ↔ SPEECH

    SILENCE + speech → SPEECH
    SPEECH + speech  → SPEECH(不变)
    SPEECH + silence → SPEECH(还在累积,等 silence_threshold 触发识别)
    SILENCE + silence → SILENCE
    """
    if state == STATE_SILENCE and is_speech:
        return STATE_SPEECH
    return state


def _strip_filler_words(text: str) -> str:
    """Bug-12: 删除独立位置的填充词/语气词,提升实时字幕可读性。

    只删除独立位置的填充词(前后是标点/空格/字符串边界),避免误伤"这个方案"等正常使用。
    例: "嗯,我们今天讨论一下,呃,语音识别" → "我们今天讨论一下,语音识别"
    保留句末句号/问号/感叹号,只清掉由删除造成的孤立尾标(逗号)。
    """
    if not text:
        return text
    out = text
    for pattern in _FILLER_PATTERNS:
        out = re.sub(pattern, "", out)
    # 连续逗号压成单个
    out = re.sub(r"[,，]{2,}", ",", out)
    # 多个空格压成单个
    out = re.sub(r"[ \t]+", " ", out)
    # 清理因删除导致的孤立前导/后置逗号(保留句号/问号/感叹号)
    out = re.sub(r"^\s*[,，]\s*", "", out)
    out = re.sub(r"[,，]\s*$", "", out)
    return out.strip()


def _offset_words(words, offset: float):
    """把 segment 内相对 words 时间戳偏移到会话时间轴."""
    if not words:
        return None
    shifted = []
    for item in words:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        try:
            copied["start"] = float(copied.get("start", 0)) + offset
            copied["end"] = float(copied.get("end", 0)) + offset
        except (TypeError, ValueError):
            pass
        shifted.append(copied)
    return shifted or None


def _words_for_incremental_text(words, full_text: str, incremental_text: str):
    """仅在能精确证明 word 序列对应增量文本时保留时间戳。

    ASR 的重叠窗口通常返回完整文本，而产品只输出新增后缀。若无法在 word
    边界精确切出该后缀，宁可丢弃 words，也不能保存与文本不一致的时间戳。
    """
    if not words or not incremental_text:
        return None
    if incremental_text == full_text:
        return words
    if not full_text.endswith(incremental_text):
        return None

    prefix = full_text[: -len(incremental_text)]
    consumed = ""
    for index, item in enumerate(words):
        if not isinstance(item, dict):
            return None
        token = item.get("text", item.get("word"))
        if not isinstance(token, str):
            return None
        consumed += token
        if consumed == prefix:
            suffix = words[index + 1 :]
            suffix_text = "".join(
                str(word.get("text", word.get("word", "")))
                for word in suffix
                if isinstance(word, dict)
            )
            return suffix if suffix and suffix_text == incremental_text else None
        if not prefix.startswith(consumed):
            return None
    return None


def _engine_device(engine: object) -> str:
    value = getattr(engine, "device", None)
    if value is None:
        value = getattr(engine, "_device", None)
    return str(value or "unknown").lower()


def can_run_engine_pair_in_parallel(asr: object, speaker: object) -> bool:
    """Parallelize only when adapters explicitly declare compatible devices."""
    asr_device = _engine_device(asr)
    speaker_device = _engine_device(speaker)
    if "unknown" in {asr_device, speaker_device}:
        return False
    if "cpu" in {asr_device, speaker_device}:
        return True
    return asr_device != speaker_device


async def _run_live_engines(engines: EngineSnapshot, audio_data: np.ndarray):
    """Run independent ASR and speaker providers without early slot release."""
    async def call_asr():
        try:
            return await engines.asr.run_asr(audio_data, use_preprocessing=True)
        except Exception as exc:
            return exc

    async def call_speaker():
        try:
            return await asyncio.to_thread(engines.speaker.extract_feat, audio_data)
        except Exception as exc:
            return exc

    if can_run_engine_pair_in_parallel(engines.asr, engines.speaker):
        return await asyncio.gather(call_asr(), call_speaker())
    return await call_asr(), await call_speaker()


def _current_asr_type() -> str:
    try:
        from engine.asr import get_asr_engine_info
        return str(get_asr_engine_info().get("type") or config.audio.asr_engine)
    except Exception:
        return config.audio.asr_engine


def _current_speaker_type() -> str:
    try:
        return str(get_engine_info().get("type") or config.speaker.engine_type)
    except Exception:
        return config.speaker.engine_type


def compute_skip_count(queue_size: int, threshold: int, keep_recent: int = 25) -> int:
    """队列满时,计算要跳过的旧帧数(保留最近 N 帧)

    跳帧策略:当队列堆积超过阈值,丢弃旧帧防止 OOM
    - queue_size <= threshold: 0 (不跳帧,正常处理)
    - queue_size > threshold: 跳过 queue_size - keep_recent 帧
      默认 keep_recent=25 ≈ 0.5s(50fps 帧率 @ 20ms)

    Bug-02: 之前只保留 1 帧,在极速发送场景下(0.1ms 间隔 1000 帧),
    保留的 1 帧在 20s 音频里占比 0.005%,ASR 无法累积到完整语音段 → 0 识别
    改为保留 0.5s(25 帧),既能防止 OOM,又能给 ASR 足够上下文

    纯函数化(供测试):只依赖入参,不触碰真实队列
    """
    if queue_size <= threshold:
        return 0
    # 至少保留 1 帧(防止 keep_recent=0 时跳过全部)
    keep = max(1, min(keep_recent, queue_size))
    return queue_size - keep


async def queue_monitor(queue: asyncio.Queue, client_id: str, stop_event: asyncio.Event):
    """队列监控：定期打印队列状态"""
    try:
        monitor_interval = config.audio.queue_monitor_interval
    except (AttributeError, TypeError) as e:
        logger.error(f"[QUEUE_MONITOR] 配置加载失败: {e}")
        return
    
    while not stop_event.is_set():
        await asyncio.sleep(monitor_interval)
        if not stop_event.is_set():
            size = queue.qsize()
            if size > 0:
                logger.info(f"[QUEUE] {client_id} size={size}/{queue.maxsize}")


async def audio_processor(
    websocket: WebSocket,
    queue: asyncio.Queue,
    client_id: str,
    stop_event: asyncio.Event
):
    """音频处理协程：基于语音活动检测的动态分段
    
    策略：
    - 语音活跃时：持续累积音频
    - 语音结束时（检测到静音）：触发 ASR 识别
    - 缓冲区达到上限：强制识别（保留部分上下文）
    """
    engines = _engine_snapshot(websocket)

    # 检查配置
    try:
        sample_rate = config.audio.sample_rate
        max_buffer_seconds = config.audio.max_buffer_seconds
        skip_frame_threshold = config.audio.skip_frame_threshold
        timeout_seconds = config.audio.timeout_seconds
        # 新增：语音段最大长度（秒）
        max_segment_seconds = getattr(config.audio, 'max_segment_seconds', 5)
    except (AttributeError, TypeError) as e:
        logger.error(f"[PROCESSOR] 配置加载失败: {e}")
        stop_event.set()
        return
    
    ctx = SessionContext(client_id)
    
    # 语音活动状态机
    state = STATE_SILENCE

    # 语音累积缓冲区
    speech_buffer = np.array([], dtype=np.float32)

    # 静音帧计数（用于判断语音结束）
    silence_frame_count = 0
    silence_sample_count = 0

    # 超时追踪
    last_active_time = time.time()
    
    # 统计信息
    total_frames = 0
    skipped_frames = 0
    samples_seen = 0
    speech_start_sample = 0
    last_processed_end_sample = None

    # Once receiving stops, drain every frame the server already accepted.
    while not stop_event.is_set() or not queue.empty():
        # 跳帧策略(纯函数 compute_skip_count 算要跳的帧数)
        queue_size = queue.qsize()
        frames_to_skip = compute_skip_count(queue_size, skip_frame_threshold)
        for _ in range(frames_to_skip):
            try:
                queue.get_nowait()
                skipped_frames += 1
            except asyncio.QueueEmpty:
                break
        
        # 获取数据
        try:
            item = await asyncio.wait_for(queue.get(), timeout=0.1 if stop_event.is_set() else 1.0)
        except asyncio.TimeoutError:
            # 超时且有待处理的语音，强制识别
            if len(speech_buffer) > 0:
                await _process_speech_segment(
                    websocket, ctx, speech_buffer, client_id, sample_rate,
                    segment_start_time=speech_start_sample / sample_rate,
                )
                speech_buffer = np.array([], dtype=np.float32)
                # Bug(M4): 超时只是"队列暂空",状态机仍在 SPEECH、语义上
                # 上下文连续。若在此重置 last_full_text,下一段 ASR 返回的
                # 含旧前缀文本(0.5s 上下文 / 短间隔重复语气词)会因基准清空
                # 被当增量重发 → 前端看到重复字。故超时 flush 后**不重置**
                # last_full_text,也不切 state;静音触发的 reset(见下文
                # STATE_SILENCE 切换)才重置上下文。
                state = STATE_SILENCE
                silence_frame_count = 0
                silence_sample_count = 0
                scope = getattr(websocket, "_speaker_scope", client_id)
                engines.speaker.reset_buffer(scope)
            if stop_event.is_set() and queue.empty():
                break
            continue
        except asyncio.CancelledError:
            break
        
        total_frames += 1

        # 转换音频格式。新队列条目携带完整已保存音频中的绝对 offset；
        # fallback 只用于兼容直接向处理器传 bytes 的内部调用。
        chunk_start_sample, data = _unpack_audio_queue_item(item, samples_seen)
        chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        chunk_end_sample = chunk_start_sample + len(chunk)
        samples_seen = max(samples_seen, chunk_end_sample)

        # 队列降载会造成绝对时间轴上的缺口。不能把缺口两侧的语音拼成连续
        # buffer，否则后续段的开始时间和保存的完整 WAV 会错位。
        if (
            last_processed_end_sample is not None
            and chunk_start_sample > last_processed_end_sample
        ):
            if state == STATE_SPEECH and len(speech_buffer) > sample_rate * 0.1:
                await _process_speech_segment(
                    websocket, ctx, speech_buffer, client_id, sample_rate,
                    segment_start_time=speech_start_sample / sample_rate,
                )
            state = STATE_SILENCE
            speech_buffer = np.array([], dtype=np.float32)
            silence_frame_count = 0
            silence_sample_count = 0
            ctx.last_full_text = ""
            engines.speaker.reset_buffer(getattr(websocket, "_speaker_scope", client_id))
        last_processed_end_sample = chunk_end_sample

        # 调用纯函数 classify_frame(单帧 VAD 判定)
        is_speech_chunk = classify_frame(chunk, engines.asr)

        # 状态机处理
        if state == STATE_SILENCE:
            if is_speech_chunk:
                # 静音 → 语音：开始累积
                state = STATE_SPEECH
                speech_buffer = chunk.copy()
                speech_start_sample = chunk_start_sample
                silence_frame_count = 0
                silence_sample_count = 0
                logger.debug(f"[PROCESSOR] {client_id} 语音开始")
                # 推 transcribing 占位消息(纯函数判定: 仅 SILENCE→SPEECH 触发)
                if should_push_transcribing(STATE_SILENCE, state):
                    if not hasattr(websocket, "_seq_counter"):
                        websocket._seq_counter = SeqCounter()
                    seq = websocket._seq_counter.next()
                    try:
                        await websocket.send_json({"type": "transcribing", "seq": seq})
                    except Exception as e:
                        logger.debug(f"[PROCESSOR] 推 transcribing 失败: {e}")
            else:
                # 持续静音
                silence_frame_count += 1
                silence_sample_count += len(chunk)
                
                # 超时断开
                if time.time() - last_active_time > timeout_seconds:
                    logger.warning(f"[TIMEOUT] {client_id} 超时断开")
                    try:
                        await websocket.send_json({
                            "speaker": SYSTEM_SPEAKER, 
                            "text": "LINK_IDLE_TIMEOUT"
                        })
                    except Exception:
                        pass
                    stop_event.set()
                    break
        
        elif state == STATE_SPEECH:
            if is_speech_chunk:
                # 持续语音：累积
                speech_buffer = np.concatenate([speech_buffer, chunk])
                silence_frame_count = 0
                silence_sample_count = 0
                last_active_time = time.time()

                # 缓冲区达到上限：强制识别
                if should_emit_segment(
                    state, silence_frame_count, len(speech_buffer),
                    sample_rate, max_segment_seconds,
                    silence_samples=silence_sample_count,
                ):
                    logger.debug(f"[PROCESSOR] {client_id} 达到上限，强制识别")
                    await _process_speech_segment(
                        websocket, ctx, speech_buffer, client_id, sample_rate,
                        segment_start_time=speech_start_sample / sample_rate,
                    )
                    # 保留最后 0.5 秒作为上下文
                    keep_samples = int(sample_rate * 0.5)
                    speech_buffer = speech_buffer[-keep_samples:] if len(speech_buffer) > keep_samples else np.array([], dtype=np.float32)
                    speech_start_sample = max(chunk_end_sample - len(speech_buffer), 0)

            else:
                # 语音中检测到静音帧
                # Bug-01: 静音帧只用来计数,不再累积到 speech_buffer
                # 之前把静音帧也加到 buffer,导致 ASR 看到"语音+静音"混合
                # 在短音频(0.5-1s)上经常识别空(text="")
                silence_frame_count += 1
                silence_sample_count += len(chunk)

                # 连续静音帧达到阈值：语音结束
                if should_emit_segment(
                    state, silence_frame_count, len(speech_buffer),
                    sample_rate, max_segment_seconds,
                    silence_samples=silence_sample_count,
                ):
                    logger.debug(f"[PROCESSOR] {client_id} 语音结束，开始识别")
                    
                    # 触发 ASR
                    if len(speech_buffer) > sample_rate * 0.1:  # 至少 0.1 秒
                        await _process_speech_segment(
                            websocket, ctx, speech_buffer, client_id, sample_rate,
                            segment_start_time=speech_start_sample / sample_rate,
                        )
                    
                    # 重置状态
                    state = STATE_SILENCE
                    speech_buffer = np.array([], dtype=np.float32)
                    silence_frame_count = 0
                    silence_sample_count = 0
                    ctx.last_full_text = ""  # 语音段结束，重置上下文
                    engines.speaker.reset_buffer(getattr(websocket, "_speaker_scope", client_id))
                    logger.info(f"[RESET] {client_id} 语义重置（语音段结束）")

    # Bug-01: 退出前 flush 残余 buffer,避免短音频(<1.5s)在 close 时被丢
    # 触发条件: state 是 SPEECH(累积了语音但没等到 silence_threshold) 或 buffer > 0
    if state == STATE_SPEECH and len(speech_buffer) > sample_rate * 0.1:
        logger.debug(f"[PROCESSOR] {client_id} 退出前 flush 残余 buffer ({len(speech_buffer)/sample_rate:.2f}s)")
        try:
            await _process_speech_segment(
                websocket, ctx, speech_buffer, client_id, sample_rate,
                segment_start_time=speech_start_sample / sample_rate,
            )
        except Exception as e:
            logger.warning(f"[PROCESSOR] flush 失败: {e}")

    # 打印统计
    if total_frames > 0:
        skip_rate = skipped_frames / total_frames * 100
        logger.info(f"[STATS] {client_id} frames={total_frames}, skipped={skipped_frames} ({skip_rate:.1f}%)")


async def _process_speech_segment(
    websocket: WebSocket,
    ctx: SessionContext,
    audio_data: np.ndarray,
    client_id: str,
    sample_rate: int = 16000,
    segment_start_time: float = 0.0,
):
    """处理一个语音段"""
    if len(audio_data) < 1600:  # 至少 0.1 秒
        return
    
    # 计算音频时长
    audio_duration = len(audio_data) / sample_rate
    segment_end_time = segment_start_time + audio_duration
    
    engines = _engine_snapshot(websocket)
    runtime = _runtime_for(websocket)
    inference_slot = runtime.inference.live()

    # Cancellation of asyncio.to_thread does not stop its worker. Shield the
    # pair and wait for it before releasing the inference slot so a subsequent
    # job cannot run over a still-active model call.
    async with inference_slot:
        inference_task = asyncio.create_task(_run_live_engines(engines, audio_data))
        try:
            asr_result, emb_result = await asyncio.shield(inference_task)
        except asyncio.CancelledError:
            await inference_task
            raise

    if isinstance(asr_result, Exception):
        logger.error("[ASR ERROR] %s", asr_result)
        return
    from engine.asr.contracts import normalize_asr_result

    asr_result = normalize_asr_result(asr_result, audio_duration=audio_duration)
    if not asr_result["is_final"]:
        logger.debug("[ASR] 忽略 non-final 结果；当前协议只持久化 finalized utterance")
        return

    # run_asr 现在返回 dict {text, words}
    full_text = asr_result["text"]
    seg_words = asr_result["words"]
    # diag: 打印 ASR 原始输出 + 音频时长,排查"很多话没转录"问题
    logger.info(f"[DIAG-ASR] {client_id} duration={audio_duration:.2f}s full_text={full_text!r}")

    # Bug-fix: Qwen3-ASR 对 < 0.5s 短音频返回空(模型没足够上下文),
    # 用户"一直在说话"但每段 VAD 切到 0.13s 时全返空 → 前端没字幕
    # 改成 < 0.5s 直接跳过 ASR,等累积够长再识别(用户感受延迟略增,但每段都能稳定识别)
    if audio_duration < 0.5 and not (full_text and full_text.strip()):
        logger.info(f"[DIAG-ASR] {client_id} 跳过短段 {audio_duration:.2f}s (< 0.5s, Qwen3-ASR 返空)")
        return

    embedding = None
    if isinstance(emb_result, Exception):
        logger.warning("[SPEAKER ERROR] 声纹不可用，转写降级为匿名: %s", emb_result)
    elif isinstance(emb_result, tuple) and len(emb_result) == 2:
        embedding = emb_result[0]
    else:
        logger.warning("[ENGINE CONTRACT] 声纹返回无效，转写降级为匿名")

    # 处理识别结果
    if full_text and full_text.strip():
        # 调用 compare_and_identify，传递音频时长
        # 整改: 用 client_id 当默认名 (SessionContext 没 session_title 属性, 简化用 client_id)
        meeting_id = await _ensure_live_meeting(websocket, client_id)
        speaker_scope = meeting_id
        websocket._speaker_scope = speaker_scope
        _default_name = "Speaker"
        # compare_and_identify 现在返回 (spk_id, score) — 把置信度也透出给前端做可视化
        spk_id, spk_score = "Spk_unknown", 0.0
        if embedding is not None:
            try:
                spk_id, spk_score = engines.speaker.compare_and_identify(
                    embedding,
                    speaker_scope,
                    audio_duration,
                    default_name=_default_name,
                )
            except Exception as exc:
                logger.warning("[SPEAKER ERROR] 聚类失败，转写降级为匿名: %s", exc)
        incr_text = ctx.get_incremental_text(full_text)
        incremental_words = _words_for_incremental_text(
            seg_words, full_text, incr_text
        )
        absolute_words = (
            incremental_words
            if asr_result["timestamp_origin"] == "stream"
            else _offset_words(incremental_words, segment_start_time)
        )
        result_start = segment_start_time
        result_end = segment_end_time
        if absolute_words:
            result_start = min(float(word["start"]) for word in absolute_words)
            result_end = max(float(word["end"]) for word in absolute_words)
        elif asr_result["segments"]:
            native_start = min(
                float(segment["start"]) for segment in asr_result["segments"]
            )
            native_end = max(
                float(segment["end"]) for segment in asr_result["segments"]
            )
            if asr_result["timestamp_origin"] == "stream":
                result_start, result_end = native_start, native_end
            else:
                result_start = segment_start_time + native_start
                result_end = segment_start_time + native_end
        # diag: 看增量合并把什么过滤掉了
        if not incr_text:
            logger.info(f"[DIAG-ASR] {client_id} 增量合并返回空 (full_text={full_text!r} last={ctx.last_full_text!r})")

        if incr_text:
            try:
                # ASR 结果带 seq,与前面推的 transcribing 占位(seq=N)配对
                seq_counter = getattr(websocket, "_seq_counter", None)
                seq = seq_counter.consume_pending() if seq_counter else 0
                msg = {
                    "speaker": spk_id,
                    "score": round(spk_score, 4),
                    "text": incr_text,
                    "time": time.strftime("%H:%M:%S"),
                    "seq": seq,
                    "start": result_start,
                    "end": result_end,
                    "timebase": "meeting",
                    "is_final": True,
                    "speaker_state": (
                        "unknown" if spk_id == "Spk_unknown" else "provisional"
                    ),
                }
                # 字级时间戳:在 incr_text 上做近似对齐(整体偏移到 segment 起始时间 0)
                # 真实精确对齐需要 segment 累积时间偏移,留作 v0.3.x 增量
                if incremental_words:
                    msg["words"] = absolute_words
                await websocket.send_json(msg)
                logger.info(f"[{client_id} | {spk_id}]: {incr_text}")
            except Exception as e:
                logger.debug(f"[PROCESSOR] 发送结果失败: {e}")

        # 实时结果直接进入产品会议模型，与上传任务共享校正/搜索/导出链路。
        if incr_text:
            try:
                websocket.app.state.meeting_repo.append_live_segment(
                    meeting_id,
                    text=incr_text,
                    start_time=result_start,
                    end_time=result_end,
                    speaker_label=spk_id,
                    confidence=spk_score,
                    words=absolute_words,
                )
            except Exception as e:
                logger.warning(f"[WS] 实时会议存档失败: {e}")


async def _finalize_live_session(websocket: WebSocket, client_id: str) -> None:
    """Finalize persistence and speaker state after the processor owns no work."""
    meeting_id = getattr(websocket, "_meeting_id", None)
    if meeting_id:
        notification = {
            "type": "meeting_finalized",
            "meeting_id": meeting_id,
            "refinement_status": "ready",
        }
        try:
            meeting = websocket.app.state.meeting_repo.get(meeting_id)
            audio_path = Path(meeting.get("audio_path") or "") if meeting else None
            if audio_path is not None and audio_path.is_file():
                job_id, created = websocket.app.state.job_repo.enqueue_refinement(meeting_id)
                if created:
                    websocket.app.state.job_runner.notify()
                notification.update(job_id=job_id, refinement_status="queued")
            else:
                websocket.app.state.meeting_repo.finalize_live(meeting_id)
        except Exception as exc:
            logger.warning("[WS] 实时会议精修排队失败，保留实时文稿: %s", exc)
            websocket.app.state.meeting_repo.finalize_live(meeting_id)
            notification["refinement_status"] = "unavailable"
        try:
            await websocket.send_json(notification)
        except Exception:
            pass
    speaker_scope = getattr(websocket, "_speaker_scope", None)
    if speaker_scope:
        _engine_snapshot(websocket).speaker.cleanup_client(speaker_scope)
    logger.info("[WS] 用户 %s 连接已释放", client_id)


async def _finish_deferred_processor(
    websocket: WebSocket, client_id: str, processor_task: asyncio.Task
) -> None:
    """Keep ownership of an uninterruptible model call without blocking WS close."""
    try:
        await asyncio.shield(processor_task)
    except Exception:
        logger.warning("[WS] %s 后台 processor 异常", client_id, exc_info=True)
    finally:
        await _finalize_live_session(websocket, client_id)


def _track_background_task(websocket: WebSocket, task: asyncio.Task) -> None:
    tasks = getattr(websocket.app.state, "ws_background_tasks", None)
    if tasks is None:
        tasks = set()
        websocket.app.state.ws_background_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def _wait_for_processor(task: asyncio.Task, timeout: float) -> bool:
    """Return on deadline without cancelling an uninterruptible model owner."""
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False


@router.websocket("/ws/v1/stream/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """实时音频流 WebSocket 入口（队列优化版）
    
    简化版：不使用手动心跳，依赖 receive 超时检测连接状态
    """
    # 验证 client_id
    client_id = validate_client_id(client_id)
    
    # 检查引擎是否初始化
    try:
        check_engines(websocket)
    except RuntimeError as e:
        logger.error(f"[WS] {e}")
        await websocket.close(code=1011, reason=str(e))
        return
    
    _engine_snapshot(websocket)
    await websocket.accept()

    if not await authenticate_websocket(websocket, client_id):
        return

    # 创建有界队列
    try:
        queue = asyncio.Queue(maxsize=config.audio.queue_size)
    except (AttributeError, TypeError) as e:
        logger.error(f"[WS] 队列创建失败: {e}")
        await websocket.close(code=1011, reason="Config error")
        return

    # 停止信号
    stop_event = asyncio.Event()

    # 超时配置
    try:
        receive_timeout = config.audio.heartbeat_timeout + 5
    except (AttributeError, TypeError):
        receive_timeout = 35  # 默认值

    logger.info(f"[WS] 用户 {client_id} 已接入")

    # 创建协程任务
    processor_task = asyncio.create_task(
        audio_processor(websocket, queue, client_id, stop_event)
    )
    monitor_task = asyncio.create_task(
        queue_monitor(queue, client_id, stop_event)
    )

    try:
        # 接收循环（主协程）
        while not stop_event.is_set():
            try:
                message = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=receive_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"[RECEIVER] {client_id} 接收超时，断开连接")
                stop_event.set()
                break

            msg_type = message.get("type")

            if msg_type == "websocket.receive":
                if "text" in message:
                    # 文本命令：{"action": "rename", "title": "..."}
                    try:
                        cmd = json.loads(message["text"])
                        if isinstance(cmd, dict) and cmd.get("action") == "rename":
                            new_title = str(cmd.get("title") or "").strip()
                            meeting_id = await _ensure_live_meeting(
                                websocket, client_id, notify=False
                            )
                            if new_title:
                                websocket.app.state.meeting_repo.update(
                                    meeting_id, title=new_title[:200]
                                )
                            else:
                                new_title = websocket.app.state.meeting_repo.get(
                                    meeting_id
                                )["title"]
                            await websocket.send_json({
                                "type": "renamed", "title": new_title[:200],
                                "meeting_id": meeting_id,
                            })
                    except (json.JSONDecodeError, KeyError, AttributeError) as e:
                        logger.debug(f"[WS] 文本命令解析失败: {e}")
                    continue  # 跳过后续 bytes 处理

                if "bytes" in message:
                    data = message["bytes"]
                    try:
                        await _append_live_audio(websocket, client_id, data)
                    except Exception as exc:
                        logger.warning("[WS] 实时音频保存失败: %s", exc)
                else:
                    continue

                # 尝试放入队列
                queue_item = _make_audio_queue_item(websocket, data)
                try:
                    queue.put_nowait(queue_item)
                except asyncio.QueueFull:
                    # 队列满，丢弃最旧的数据
                    try:
                        queue.get_nowait()
                        queue.put_nowait(queue_item)
                        logger.debug("[RECEIVER] 队列满，丢弃旧数据")
                    except asyncio.QueueEmpty:
                        pass
            
            elif msg_type == "websocket.disconnect":
                logger.info(f"[RECEIVER] {client_id} 客户端主动断开")
                stop_event.set()
                break
            
            elif msg_type == "websocket.close":
                logger.info(f"[RECEIVER] {client_id} 收到关闭消息")
                stop_event.set()
                break
    
    except Exception as e:
        logger.error(f"[WS ERROR] {client_id} {e}")
    
    finally:
        # 设置停止信号
        stop_event.set()

        # ASR can legitimately take longer than two seconds. A bounded graceful
        # drain is safer than cancelling a worker thread that keeps running.
        deferred = False
        try:
            deferred = not await _wait_for_processor(
                processor_task, PROCESSOR_DRAIN_TIMEOUT_SECONDS
            )
            if deferred:
                logger.warning(
                    "[WS] %s processor 30s 内未退出；转为后台持有推理槽并延后 finalize",
                    client_id,
                )
        except Exception as e:
            logger.warning(f"[WS] {client_id} processor 异常: {e}")

        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        # The WAV writer is independent of model inference and can close now.
        _close_live_audio(websocket)
        if deferred:
            task = asyncio.create_task(
                _finish_deferred_processor(websocket, client_id, processor_task)
            )
            _track_background_task(websocket, task)
        else:
            await _finalize_live_session(websocket, client_id)
