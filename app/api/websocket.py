"""WebSocket 实时音频流路由"""
import asyncio
import json
import time
import re
import numpy as np
import logging
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketState

from app.config import config
from app.constants import SYSTEM_SPEAKER
from app.services import SessionContext
from engine.speaker.speaker_factory import get_speaker_engine

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

asr_engine = None
inference_lock = None

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


def check_engines():
    """检查引擎是否已初始化"""
    if asr_engine is None or inference_lock is None:
        raise RuntimeError("Engines not initialized. Call init_engines() first.")


def init_engines(asr, spk, lock):
    """初始化引擎实例"""
    global asr_engine, inference_lock
    asr_engine = asr
    inference_lock = lock


# 状态机常量(模块级,供测试 import)
STATE_SILENCE = 0
STATE_SPEECH = 1
SILENCE_THRESHOLD_FRAMES = 8  # bug-fix: 3 帧 (384ms) 太短,自然换气就切碎。
                                          # 8 帧 ≈ 1024ms 允许 1 秒停顿不切(用户感受:响应延迟略增,但完整)
                                          # CLAUDE.md 说 .env 有 VAD_MIN_SILENCE_DURATION 但代码硬编码 3,配置漂移。
LOUD_RMS_THRESHOLD = 0.005    # bug-fix: 0.015 偏高,某些帧瞬时 RMS 跌到这个值就被判静音 → buffer 不累积。原 0.015。


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
) -> bool:
    """判断当前帧后是否应该触发 ASR 识别

    触发条件(任一):
    1. STATE_SPEECH + 静音帧数 >= 阈值(语音段自然结束)
    2. STATE_SPEECH + 缓冲长度 >= 上限(强制识别,防 OOM)
    """
    if state != STATE_SPEECH:
        return False
    if silence_count >= silence_threshold:
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

    # 超时追踪
    last_active_time = time.time()
    
    # 统计信息
    total_frames = 0
    skipped_frames = 0

    while not stop_event.is_set():
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
            data = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            # 超时且有待处理的语音，强制识别
            if len(speech_buffer) > 0:
                await _process_speech_segment(
                    websocket, ctx, speech_buffer, client_id, sample_rate
                )
                speech_buffer = np.array([], dtype=np.float32)
                ctx.last_full_text = ""  # 超时后重置上下文
            continue
        except asyncio.CancelledError:
            break
        
        total_frames += 1

        # 转换音频格式
        chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

        # 调用纯函数 classify_frame(单帧 VAD 判定)
        is_speech_chunk = classify_frame(chunk, asr_engine)

        # 状态机处理
        if state == STATE_SILENCE:
            if is_speech_chunk:
                # 静音 → 语音：开始累积
                state = STATE_SPEECH
                speech_buffer = chunk.copy()
                silence_frame_count = 0
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
                last_active_time = time.time()

                # 缓冲区达到上限：强制识别
                if should_emit_segment(
                    state, silence_frame_count, len(speech_buffer),
                    sample_rate, max_segment_seconds,
                ):
                    logger.debug(f"[PROCESSOR] {client_id} 达到上限，强制识别")
                    await _process_speech_segment(
                        websocket, ctx, speech_buffer, client_id, sample_rate
                    )
                    # 保留最后 0.5 秒作为上下文
                    keep_samples = int(sample_rate * 0.5)
                    speech_buffer = speech_buffer[-keep_samples:] if len(speech_buffer) > keep_samples else np.array([], dtype=np.float32)

            else:
                # 语音中检测到静音帧
                # Bug-01: 静音帧只用来计数,不再累积到 speech_buffer
                # 之前把静音帧也加到 buffer,导致 ASR 看到"语音+静音"混合
                # 在短音频(0.5-1s)上经常识别空(text="")
                silence_frame_count += 1

                # 连续静音帧达到阈值：语音结束
                if should_emit_segment(
                    state, silence_frame_count, len(speech_buffer),
                    sample_rate, max_segment_seconds,
                ):
                    logger.debug(f"[PROCESSOR] {client_id} 语音结束，开始识别")
                    
                    # 触发 ASR
                    if len(speech_buffer) > sample_rate * 0.1:  # 至少 0.1 秒
                        await _process_speech_segment(
                            websocket, ctx, speech_buffer, client_id, sample_rate
                        )
                    
                    # 重置状态
                    state = STATE_SILENCE
                    speech_buffer = np.array([], dtype=np.float32)
                    silence_frame_count = 0
                    ctx.last_full_text = ""  # 语音段结束，重置上下文
                    get_speaker_engine().reset_buffer(client_id)
                    logger.info(f"[RESET] {client_id} 语义重置（语音段结束）")

    # Bug-01: 退出前 flush 残余 buffer,避免短音频(<1.5s)在 close 时被丢
    # 触发条件: state 是 SPEECH(累积了语音但没等到 silence_threshold) 或 buffer > 0
    if state == STATE_SPEECH and len(speech_buffer) > sample_rate * 0.1:
        logger.debug(f"[PROCESSOR] {client_id} 退出前 flush 残余 buffer ({len(speech_buffer)/sample_rate:.2f}s)")
        try:
            await _process_speech_segment(
                websocket, ctx, speech_buffer, client_id, sample_rate
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
    sample_rate: int = 16000
):
    """处理一个语音段"""
    if len(audio_data) < 1600:  # 至少 0.1 秒
        return
    
    # 计算音频时长
    audio_duration = len(audio_data) / sample_rate
    
    # 并行执行 ASR 和声纹提取
    async with inference_lock:
        try:
            asr_task = asr_engine.run_asr(audio_data, use_preprocessing=True)
            spk_task = asyncio.to_thread(get_speaker_engine().extract_feat, audio_data)
            asr_result, emb_result = await asyncio.gather(asr_task, spk_task)
        except Exception as e:
            logger.error(f"[ENGINE ERROR] {e}")
            return

    # run_asr 现在返回 dict {text, words}
    full_text = asr_result.get("text", "") if isinstance(asr_result, dict) else (asr_result or "")
    seg_words = asr_result.get("words") if isinstance(asr_result, dict) else None
    # diag: 打印 ASR 原始输出 + 音频时长,排查"很多话没转录"问题
    logger.info(f"[DIAG-ASR] {client_id} duration={audio_duration:.2f}s full_text={full_text!r}")

    # Bug-fix: Qwen3-ASR 对 < 0.5s 短音频返回空(模型没足够上下文),
    # 用户"一直在说话"但每段 VAD 切到 0.13s 时全返空 → 前端没字幕
    # 改成 < 0.5s 直接跳过 ASR,等累积够长再识别(用户感受延迟略增,但每段都能稳定识别)
    if audio_duration < 0.5 and not (full_text and full_text.strip()):
        logger.info(f"[DIAG-ASR] {client_id} 跳过短段 {audio_duration:.2f}s (< 0.5s, Qwen3-ASR 返空)")
        return

    # 处理声纹提取结果（extract_feat 现在返回 tuple）
    if isinstance(emb_result, tuple):
        embedding, _ = emb_result  # 忽略返回的时长，使用我们计算的
    else:
        embedding = emb_result  # 兼容旧版引擎

    # 处理识别结果
    if full_text and full_text.strip():
        # Bug-12: 过滤常见填充词/语气词,避免实时字幕被噪音淹没
        full_text = _strip_filler_words(full_text)
        if not full_text or not full_text.strip():
            logger.info(f"[DIAG-ASR] {client_id} 全是填充词,过滤后空")
            return  # 过滤后空,不发

        # 调用 compare_and_identify，传递音频时长
        # 整改: 用 client_id 当默认名 (SessionContext 没 session_title 属性, 简化用 client_id)
        _default_name = ctx.client_id
        # compare_and_identify 现在返回 (spk_id, score) — 把置信度也透出给前端做可视化
        spk_id, spk_score = get_speaker_engine().compare_and_identify(
            embedding,
            ctx.client_id,
            audio_duration,
            default_name=_default_name,
        )
        incr_text = ctx.get_incremental_text(full_text)
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
                }
                # 字级时间戳:在 incr_text 上做近似对齐(整体偏移到 segment 起始时间 0)
                # 真实精确对齐需要 segment 累积时间偏移,留作 v0.3.x 增量
                if seg_words:
                    msg["words"] = seg_words
                await websocket.send_json(msg)
                logger.info(f"[{client_id} | {spk_id}]: {incr_text}")
            except Exception as e:
                logger.debug(f"[PROCESSOR] 发送结果失败: {e}")

        # Bug-10: 自动存档 — 有 segment 累积就存档,不再要求 rename 才创建
        if config.storage.history_enabled and full_text:
            # 懒创建 session(用 client_id + 时间为默认 title)
            session_id = getattr(websocket, "_session_id", None)
            if session_id is None:
                try:
                    repo = websocket.app.state.transcript_repo
                    default_title = f"{ctx.client_id}-{time.strftime('%H%M%S')}"
                    session_id = repo.create_session(
                        source="websocket",
                        title=default_title,
                        client_id=ctx.client_id,
                    )
                    websocket._session_id = session_id
                    logger.info(f"[WS] {client_id} 自动创建会话: {session_id} ({default_title})")
                except Exception as e:
                    logger.warning(f"[WS] 创建 session 失败: {e}")
                    session_id = None

            if session_id:
                try:
                    repo = websocket.app.state.transcript_repo
                    segs = repo.list_segments(session_id)
                    import json as _json
                    words_json = _json.dumps(seg_words, ensure_ascii=False) if seg_words else None
                    repo.insert_segment(
                        session_id,
                        segment_index=len(segs),
                        text=full_text,
                        start_time=0.0,  # v0.2 MVP: 不记精确时间
                        end_time=audio_duration,
                        speaker_id=spk_id,
                        words_json=words_json,
                    )
                except Exception as e:
                    logger.warning(f"[WS] 存档失败: {e}")


@router.websocket("/ws/v1/stream/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """实时音频流 WebSocket 入口（队列优化版）
    
    简化版：不使用手动心跳，依赖 receive 超时检测连接状态
    """
    # 验证 client_id
    client_id = validate_client_id(client_id)
    
    # 检查引擎是否初始化
    try:
        check_engines()
    except RuntimeError as e:
        logger.error(f"[WS] {e}")
        await websocket.close(code=1011, reason=str(e))
        return
    
    await websocket.accept()

    # Bug-89 (审核 #8): WebSocket 鉴权 — 接受后等首条 JSON {"action":"auth","token":"..."}
    # 5s 内没收到或鉴权失败, close(4401)
    # 测试模式绕过 (TEST_AUTH_BYPASS=1, 跟 HTTP 中间件同款)
    import os as _os
    if _os.environ.get("TEST_AUTH_BYPASS") == "1":
        logger.info(f"[WS] {client_id} 测试模式 bypass 鉴权")
    else:
        try:
            auth_msg = await asyncio.wait_for(websocket.receive(), timeout=5.0)
            auth_payload = json.loads(auth_msg.get("text", "{}"))
            if not (isinstance(auth_payload, dict) and auth_payload.get("action") == "auth"):
                logger.warning(f"[WS] {client_id} 首条消息不是 auth action")
                await websocket.close(code=4401, reason="需要 auth")
                return
            token = auth_payload.get("token", "")
            if not token:
                logger.warning(f"[WS] {client_id} 缺 token")
                await websocket.close(code=4401, reason="缺 token")
                return
            # 校验 token
            auth_service = websocket.app.state.auth_service
            decoded = auth_service.decode_token(token)
            if not decoded:
                logger.warning(f"[WS] {client_id} token 无效")
                await websocket.close(code=4401, reason="token 无效")
                return
            # 校验 pwd_iat (Bug-88 同款)
            try:
                user_id = int(decoded["sub"])
                user_row = auth_service.get_user(user_id)
                if not user_row or not user_row.get("is_active"):
                    await websocket.close(code=4401, reason="用户不存在/禁用")
                    return
                token_pwd_iat = float(decoded.get("pwd_iat", 0))
                current_pwd_iat = float(user_row.get("password_changed_at") or 0)
                if current_pwd_iat > token_pwd_iat:
                    await websocket.close(code=4401, reason="密码已修改, 请重新登录")
                    return
            except (ValueError, TypeError, KeyError):
                await websocket.close(code=4401, reason="token 格式错")
                return
            logger.info(f"[WS] {client_id} 鉴权通过 (user_id={user_id})")
        except asyncio.TimeoutError:
            logger.warning(f"[WS] {client_id} 5s 内没发 auth, 关闭")
            await websocket.close(code=4401, reason="auth 超时")
            return
        except json.JSONDecodeError:
            logger.warning(f"[WS] {client_id} 首条消息不是 JSON")
            await websocket.close(code=4401, reason="auth 格式错")
            return
    # end TEST_AUTH_BYPASS else

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
                            new_title = cmd.get("title")
                            if not hasattr(websocket, "_session_id"):
                                # 第一次命名：创建会话
                                repo = websocket.app.state.transcript_repo
                                sid = repo.create_session(
                                    source="websocket",
                                    title=new_title,
                                    client_id=client_id,
                                )
                                websocket._session_id = sid
                                logger.info(f"[WS] {client_id} 命名会话: {sid} ({new_title})")
                            else:
                                websocket.app.state.transcript_repo.update_session(
                                    websocket._session_id, title=new_title
                                )
                                logger.info(f"[WS] {client_id} 重命名: {new_title}")
                            await websocket.send_json({"type": "renamed", "title": new_title})
                    except (json.JSONDecodeError, KeyError, AttributeError) as e:
                        logger.debug(f"[WS] 文本命令解析失败: {e}")
                    continue  # 跳过后续 bytes 处理

                if "bytes" in message:
                    data = message["bytes"]
                else:
                    continue

                # 尝试放入队列
                try:
                    queue.put_nowait(data)
                except asyncio.QueueFull:
                    # 队列满，丢弃最旧的数据
                    try:
                        queue.get_nowait()
                        queue.put_nowait(data)
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

        # Bug-01: 给 processor 2s 自然退出,让它执行残余 buffer flush(短音频)
        # 不立刻 cancel,避免打断短音频的最后一次 ASR 识别
        try:
            await asyncio.wait_for(asyncio.shield(processor_task), timeout=2.0)
        except asyncio.TimeoutError:
            logger.warning(f"[WS] {client_id} processor 2s 内未退出,强制 cancel")
            processor_task.cancel()
            try:
                await processor_task
            except asyncio.CancelledError:
                pass
        except Exception as e:
            logger.warning(f"[WS] {client_id} processor 异常: {e}")

        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

        # 清理客户端资源，防止内存泄漏
        get_speaker_engine().cleanup_client(client_id)
        logger.info(f"[WS] 用户 {client_id} 连接已释放")