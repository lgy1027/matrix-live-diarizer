"""WebSocket 实时音频流路由"""
import asyncio
import time
import re
import numpy as np
import logging
from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketState

from app.config import config
from app.constants import SYSTEM_SPEAKER
from app.services import SessionContext

logger = logging.getLogger("Matrix_Core")

router = APIRouter()

asr_engine = None
spk_engine = None
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
    if asr_engine is None or spk_engine is None or inference_lock is None:
        raise RuntimeError("Engines not initialized. Call init_engines() first.")


def init_engines(asr, spk, lock):
    """初始化引擎实例"""
    global asr_engine, spk_engine, inference_lock
    asr_engine = asr
    spk_engine = spk
    inference_lock = lock


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
    STATE_SILENCE = 0
    STATE_SPEECH = 1
    state = STATE_SILENCE
    
    # 语音累积缓冲区
    speech_buffer = np.array([], dtype=np.float32)
    
    # 静音帧计数（用于判断语音结束）
    silence_frame_count = 0
    SILENCE_THRESHOLD_FRAMES = 3  # 连续 N 帧静音才算语音结束
    
    # 超时追踪
    last_active_time = time.time()
    
    # 统计信息
    total_frames = 0
    skipped_frames = 0

    while not stop_event.is_set():
        # 跳帧策略
        queue_size = queue.qsize()
        if queue_size > skip_frame_threshold:
            frames_to_skip = queue_size - 1
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
                    websocket, ctx, speech_buffer, client_id
                )
                speech_buffer = np.array([], dtype=np.float32)
                ctx.last_full_text = ""  # 超时后重置上下文
            continue
        except asyncio.CancelledError:
            break
        
        total_frames += 1
        
        # 转换音频格式
        chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        
        # 快速能量检测
        chunk_rms = np.sqrt(np.mean(chunk**2))
        is_loud_chunk = chunk_rms > 0.015  # 稍微提高阈值
        
        # 使用 VAD 精确检测（抽样）
        is_speech_chunk = False
        if is_loud_chunk:
            # 只有能量足够才做 VAD 检测（减少计算）
            is_speech_chunk = not asr_engine.is_silent(chunk, use_vad=True)
        
        # 状态机处理
        if state == STATE_SILENCE:
            if is_speech_chunk:
                # 静音 → 语音：开始累积
                state = STATE_SPEECH
                speech_buffer = chunk.copy()
                silence_frame_count = 0
                logger.debug(f"[PROCESSOR] {client_id} 语音开始")
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
                max_buffer = sample_rate * max_segment_seconds
                if len(speech_buffer) >= max_buffer:
                    logger.debug(f"[PROCESSOR] {client_id} 达到上限，强制识别")
                    await _process_speech_segment(
                        websocket, ctx, speech_buffer, client_id
                    )
                    # 保留最后 0.5 秒作为上下文
                    keep_samples = int(sample_rate * 0.5)
                    speech_buffer = speech_buffer[-keep_samples:] if len(speech_buffer) > keep_samples else np.array([], dtype=np.float32)
            
            else:
                # 语音中检测到静音帧
                speech_buffer = np.concatenate([speech_buffer, chunk])
                silence_frame_count += 1
                
                # 连续静音帧达到阈值：语音结束
                if silence_frame_count >= SILENCE_THRESHOLD_FRAMES:
                    logger.debug(f"[PROCESSOR] {client_id} 语音结束，开始识别")
                    
                    # 触发 ASR
                    if len(speech_buffer) > sample_rate * 0.1:  # 至少 0.1 秒
                        await _process_speech_segment(
                            websocket, ctx, speech_buffer, client_id
                        )
                    
                    # 重置状态
                    state = STATE_SILENCE
                    speech_buffer = np.array([], dtype=np.float32)
                    silence_frame_count = 0
                    ctx.last_full_text = ""  # 语音段结束，重置上下文
                    spk_engine.reset_buffer(client_id)
                    logger.info(f"[RESET] {client_id} 语义重置（语音段结束）")

    # 打印统计
    if total_frames > 0:
        skip_rate = skipped_frames / total_frames * 100
        logger.info(f"[STATS] {client_id} frames={total_frames}, skipped={skipped_frames} ({skip_rate:.1f}%)")


async def _process_speech_segment(
    websocket: WebSocket,
    ctx: SessionContext,
    audio_data: np.ndarray,
    client_id: str
):
    """处理一个语音段"""
    if len(audio_data) < 1600:  # 至少 0.1 秒
        return
    
    # 并行执行 ASR 和声纹提取
    async with inference_lock:
        try:
            asr_task = asr_engine.run_asr(audio_data, use_preprocessing=True)
            spk_task = asyncio.to_thread(spk_engine.extract_feat, audio_data)
            full_text, embedding = await asyncio.gather(asr_task, spk_task)
        except Exception as e:
            logger.error(f"[ENGINE ERROR] {e}")
            return
    
    # 处理识别结果
    if full_text and full_text.strip():
        spk_id = spk_engine.compare_and_identify(embedding, ctx.client_id)
        incr_text = ctx.get_incremental_text(full_text)
        
        if incr_text:
            try:
                await websocket.send_json({
                    "speaker": spk_id,
                    "text": incr_text,
                    "time": time.strftime("%H:%M:%S")
                })
                logger.info(f"[{client_id} | {spk_id}]: {incr_text}")
            except Exception as e:
                logger.debug(f"[PROCESSOR] 发送结果失败: {e}")


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
                # 获取二进制数据
                if "bytes" in message:
                    data = message["bytes"]
                elif "text" in message:
                    # 文本消息，忽略
                    continue
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
        
        # 取消任务
        processor_task.cancel()
        monitor_task.cancel()
        
        # 等待取消完成
        await asyncio.gather(processor_task, monitor_task, return_exceptions=True)
        
        # 清理客户端资源，防止内存泄漏
        spk_engine.cleanup_client(client_id)
        logger.info(f"[WS] 用户 {client_id} 连接已释放")