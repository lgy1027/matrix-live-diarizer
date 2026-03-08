"""WebSocket 实时音频流路由（优化版）"""
import asyncio
import time
import numpy as np
import logging
from fastapi import APIRouter, WebSocket

from app.config import config
from app.constants import SYSTEM_SPEAKER, WS_CLOSE_NORMAL
from app.services import SessionContext

logger = logging.getLogger("Matrix_Core")

router = APIRouter()

asr_engine = None
spk_engine = None
inference_lock = None


def init_engines(asr, spk, lock):
    """初始化引擎实例"""
    global asr_engine, spk_engine, inference_lock
    asr_engine = asr
    spk_engine = spk
    inference_lock = lock


@router.websocket("/ws/v1/stream/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """实时音频流 WebSocket 入口（优化版）"""
    await websocket.accept()
    
    ctx = SessionContext(client_id)
    
    # 状态追踪
    silent_count = 0
    last_active_time = time.time()
    speech_active = False  # 当前是否有语音活动
    speech_start_time = None  # 语音开始时间
    consecutive_speech_frames = 0  # 连续语音帧计数
    
    # 自适应缓冲参数
    adaptive_buffer = config.audio.buffer_threshold
    max_buffer = int(config.audio.buffer_threshold * 2)  # 最大缓冲 4 秒

    logger.info(f"[WS] 用户 {client_id} 已接入")

    try:
        while True:
            try:
                data = await websocket.receive_bytes()
            except Exception:
                break

            # 转换音频格式
            chunk = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
            ctx.audio_buffer = np.concatenate([ctx.audio_buffer, chunk])

            # 计算当前帧能量（快速预判）
            chunk_rms = np.sqrt(np.mean(chunk**2))
            is_loud_chunk = chunk_rms > 0.01

            # 更新语音活动状态
            if is_loud_chunk:
                consecutive_speech_frames += 1
                if consecutive_speech_frames >= 2 and not speech_active:
                    speech_active = True
                    speech_start_time = time.time()
                    logger.debug(f"[WS] {client_id} 检测到语音开始")
            else:
                consecutive_speech_frames = max(0, consecutive_speech_frames - 1)
                if consecutive_speech_frames == 0 and speech_active:
                    speech_active = False
                    logger.debug(f"[WS] {client_id} 语音结束")

            # 自适应缓冲：语音活跃时减少缓冲延迟
            if speech_active:
                adaptive_buffer = min(
                    int(config.audio.buffer_threshold * 0.75),  # 减少到 1.5 秒
                    config.audio.buffer_threshold
                )
            else:
                adaptive_buffer = config.audio.buffer_threshold

            # 缓冲区处理
            if len(ctx.audio_buffer) >= adaptive_buffer:
                process_data = ctx.audio_buffer.copy()
                
                # 保留重叠部分
                overlap = min(config.audio.overlap_samples, len(process_data) // 4)
                ctx.audio_buffer = process_data[-overlap:] if overlap > 0 else np.array([], dtype=np.float32)

                # 使用 VAD 进行静音检测
                is_silent = asr_engine.is_silent(process_data, use_vad=True)
                
                if is_silent:
                    silent_count += 1
                    
                    # 连续静音处理
                    if silent_count >= 2:
                        logger.info(f"[RESET] {client_id} 语义重置（静音 {silent_count} 次）")
                        ctx.last_full_text = ""
                        spk_engine.reset_buffer(client_id)
                        silent_count = 0
                        speech_active = False
                    
                    # 超时断开
                    if time.time() - last_active_time > config.audio.timeout_seconds:
                        logger.warning(f"[TIMEOUT] {client_id} 超时断开")
                        await websocket.send_json({"speaker": SYSTEM_SPEAKER, "text": "LINK_IDLE_TIMEOUT"})
                        await websocket.close(code=WS_CLOSE_NORMAL)
                        break
                    continue
                
                # 有语音活动
                last_active_time = time.time()
                silent_count = 0

                # 并行执行 ASR 和声纹提取
                async with inference_lock:
                    try:
                        asr_task = asr_engine.run_asr(process_data, use_preprocessing=True)
                        spk_task = asyncio.to_thread(spk_engine.extract_feat, process_data)
                        full_text, embedding = await asyncio.gather(asr_task, spk_task)
                    except Exception as e:
                        logger.error(f"[ENGINE ERROR] {e}")
                        continue

                # 处理识别结果
                if full_text and full_text.strip():
                    spk_id = spk_engine.compare_and_identify(embedding, ctx.client_id)
                    incr_text = ctx.get_incremental_text(full_text)
                    
                    if incr_text:
                        await websocket.send_json({
                            "speaker": spk_id,
                            "text": incr_text,
                            "time": time.strftime("%H:%M:%S")
                        })
                        logger.info(f"[{client_id} | {spk_id}]: {incr_text}")

    except Exception as e:
        logger.error(f"[WS ERROR] {e}")
    finally:
        logger.info(f"[WS] 用户 {client_id} 连接已释放")