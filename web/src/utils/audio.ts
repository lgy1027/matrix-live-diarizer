// 音频工具: Float32 → Int16LE, RMS, AudioContext 启动
export function floatToInt16(f32: Float32Array): Int16Array {
  const i16 = new Int16Array(f32.length)
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]))
    i16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return i16
}

export function rms(f32: Float32Array): number {
  let s = 0
  for (let i = 0; i < f32.length; i++) s += f32[i] * f32[i]
  return Math.sqrt(s / f32.length)
}

export interface MicHandle {
  stream: MediaStream
  audioCtx: AudioContext
  source: MediaStreamAudioSourceNode
  processor: ScriptProcessorNode
  stop: () => void
}

export async function startMic(): Promise<MicHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      sampleRate: 16000,
      echoCancellation: true,
      noiseSuppression: true,
    },
  })
  const audioCtx = new AudioContext({ sampleRate: 16000 })
  const source = audioCtx.createMediaStreamSource(stream)
  const processor = audioCtx.createScriptProcessor(2048, 1, 1)
  source.connect(processor)
  processor.connect(audioCtx.destination)
  return {
    stream,
    audioCtx,
    source,
    processor,
    stop: () => {
      processor.disconnect()
      source.disconnect()
      stream.getTracks().forEach((t) => t.stop())
      audioCtx.close()
    },
  }
}
