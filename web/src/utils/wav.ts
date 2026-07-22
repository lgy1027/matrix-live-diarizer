// WAV 编码:攒好的 Float32 PCM → 16-bit PCM LE 单声道 WAV Blob。
// 用于人物声样在线录音:录完产出 WAV File 走现有 uploadVoiceSample,
// 后端 librosa.load / assess_voice_sample 原样处理。
import { floatToInt16 } from './audio'

export function encodeWav(pcm: Float32Array, sampleRate: number): Blob {
  const i16 = floatToInt16(pcm)
  const buffer = new ArrayBuffer(44 + i16.length * 2)
  const view = new DataView(buffer)

  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i))
  }

  // RIFF header
  writeString(0, 'RIFF')
  view.setUint32(4, 36 + i16.length * 2, true)
  writeString(8, 'WAVE')
  // fmt chunk
  writeString(12, 'fmt ')
  view.setUint32(16, 16, true)          // PCM chunk size
  view.setUint16(20, 1, true)            // PCM format
  view.setUint16(22, 1, true)            // mono
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // byte rate (16-bit mono)
  view.setUint16(32, 2, true)            // block align
  view.setUint16(34, 16, true)           // bits per sample
  // data chunk
  writeString(36, 'data')
  view.setUint32(40, i16.length * 2, true)

  let offset = 44
  for (let i = 0; i < i16.length; i++) {
    view.setInt16(offset, i16[i], true)
    offset += 2
  }

  return new Blob([view], { type: 'audio/wav' })
}
