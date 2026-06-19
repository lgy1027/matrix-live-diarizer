// 音频工具: Float32 → Int16LE, RMS, AudioContext 启动, 实时降采样
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

// bug-fix: 部分浏览器(Mac Chrome)忽略 AudioContext({sampleRate:16000}) 强制参数,
// 实际采样率是 48000/44100。后端按 16kHz 解析样本,音频会被加速 3 倍播放,ASR 识别率暴跌。
// 这里做实时降采样:48k→16k 简单抽取(语音 < 4kHz,奈奎斯特 8k 够用,16k 更没问题)。
// 简单低通(平均 3 个相邻样本)减少 aliasing,但保留语音可懂度优先,不做 SRC 精度优化。
export function resampleTo16k(input: Float32Array, fromRate: number): Float32Array {
  if (fromRate === 16000 || fromRate < 16000) return input  // 已是 16k 或更低,直接返回
  const ratio = fromRate / 16000
  const outLen = Math.floor(input.length / ratio)
  const out = new Float32Array(outLen)
  // 简单低通 + 抽取:每 3 个样本均值后取 1 个(Mac 48k → 16k)
  const group = Math.round(ratio)
  for (let i = 0; i < outLen; i++) {
    let sum = 0
    const start = i * group
    const end = Math.min(start + group, input.length)
    for (let j = start; j < end; j++) sum += input[j]
    out[i] = sum / (end - start)
  }
  return out
}

export interface MicHandle {
  stream: MediaStream
  audioCtx: AudioContext
  source: MediaStreamAudioSourceNode
  processor: ScriptProcessorNode
  actualSampleRate: number   // 浏览器实际采样率(可能不等于 16000)
  stop: () => void
}

export async function startMic(): Promise<MicHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      // 注意:sampleRate 在 constraints 里只是 hint, 浏览器经常忽略
      sampleRate: 16000,
      echoCancellation: true,
      noiseSuppression: true,
    },
  })
  // 即使传 sampleRate:16000,部分浏览器(尤其 Mac Chrome)仍用 48000
  const audioCtx = new AudioContext({ sampleRate: 16000 })
  const actualSampleRate = audioCtx.sampleRate
  if (actualSampleRate !== 16000) {
    console.warn(
      `[mic] AudioContext 强制 16kHz 失败, 实际 ${actualSampleRate} Hz — 启用实时降采样`,
    )
  }
  const source = audioCtx.createMediaStreamSource(stream)
  const processor = audioCtx.createScriptProcessor(2048, 1, 1)
  source.connect(processor)
  processor.connect(audioCtx.destination)
  return {
    stream,
    audioCtx,
    source,
    processor,
    actualSampleRate,
    stop: () => {
      processor.disconnect()
      source.disconnect()
      stream.getTracks().forEach((t) => t.stop())
      audioCtx.close()
    },
  }
}
