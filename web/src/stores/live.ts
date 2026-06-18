import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { LiveWs, type AsrMessage, type WsState } from '../ws/liveStream'
import { useAuthStore } from './auth'
import { startMic, floatToInt16, rms, type MicHandle } from '../utils/audio'

export interface LiveSegment {
  id: number
  speaker: string
  text: string
  time: string
  words?: { text: string; start: number; end: number }[]
}

export const useLiveStore = defineStore('live', () => {
  const auth = useAuthStore()
  const router = useRouter()
  const clientId = ref<string>('studio_' + Math.random().toString(36).slice(2, 10))
  const sessionId = ref<string | null>(null)
  const sessionTitle = ref<string | null>(null)
  const wsState = ref<WsState>('idle')
  const rec = ref(false)
  const recRMS = ref(0)
  const recStart = ref(0)
  const recTimer = ref(0)
  const segments = ref<LiveSegment[]>([])
  const speakers = ref<Map<string, number>>(new Map())
  // 友好名映射:Spk_xxx → Speaker N (N 按会话内首次出现的顺序分配)
  // 同会话内稳定:同一个 Spk_xxx 始终映射到同一个 N
  const sessionSpeakers = ref<Map<string, number>>(new Map())
  const recent = ref<{ id: string; title?: string; original_filename?: string; source: string; duration_sec: number; created_at: string }[]>([])

  const segCount = computed(() => segments.value.length)
  const spkCount = computed(() => speakers.value.size)
  const elapsed = computed(() => (rec.value ? Math.floor((Date.now() - recStart.value) / 1000) : 0))

  let mic: MicHandle | null = null
  let ws: LiveWs | null = null
  let rafId: number | null = null
  let timerId: ReturnType<typeof setInterval> | null = null
  let segSeq = 0

  function onMessage(m: AsrMessage) {
    if ('type' in m && m.type === 'renamed') {
      sessionTitle.value = m.title
      return
    }
    if ('speaker' in m && m.speaker === 'SYSTEM') {
      if ('text' in m && m.text === 'LINK_IDLE_TIMEOUT') {
        stopRec()
      }
      return
    }
    // ASR 片段
    if ('text' in m && 'speaker' in m && m.speaker !== 'SYSTEM') {
      const asr = m as Extract<AsrMessage, { speaker: string; text: string }>
      const seg: LiveSegment = {
        id: ++segSeq,
        speaker: asr.speaker,
        text: asr.text,
        time: asr.time || new Date().toLocaleTimeString('zh-CN', { hour12: false }),
        words: asr.words,
      }
      // SPA v3: 增量文本提取 (跟旧 SessionContext 一样 SequenceMatcher)
      // 简化: 每次 ASR 输出整段, 截取相对上一段的新增
      const last = segments.value[segments.value.length - 1]
      if (last && last.speaker === seg.speaker) {
        const merged = diffText(last.text, seg.text)
        if (merged) {
          last.text = merged
          last.words = seg.words
        } else {
          segments.value.push(seg)
        }
      } else {
        segments.value.push(seg)
      }
      // 更新 speakers Map
      if (seg.speaker) {
        const cur = speakers.value.get(seg.speaker) || 0
        speakers.value.set(seg.speaker, cur + 1)
        // 触发响应式更新
        speakers.value = new Map(speakers.value)
        // 友好名:Spk_xxx 第一次见 → Speaker N;已见过 → 同 N
        if (seg.speaker.startsWith('Spk_')) {
          if (!sessionSpeakers.value.has(seg.speaker)) {
            const next = sessionSpeakers.value.size + 1
            sessionSpeakers.value.set(seg.speaker, next)
            sessionSpeakers.value = new Map(sessionSpeakers.value)
          }
        }
      }
    }
  }

  function getDisplayName(seg: LiveSegment): string {
    if (!seg.speaker) return '未知说话人'
    if (seg.speaker === 'SYSTEM') return '系统'
    if (seg.speaker.startsWith('Spk_')) {
      const n = sessionSpeakers.value.get(seg.speaker)
      return n !== undefined ? `Speaker ${n}` : '未知说话人'
    }
    // 已注册声纹的 ID (非 Spk_ 前缀) — 后续接 alias 解析
    return seg.speaker
  }

  // 简单版: 找出 a → b 的新增部分 (类似 SequenceMatcher)
  function diffText(a: string, b: string): string | null {
    if (b.length <= a.length) return null
    if (b.startsWith(a)) return b
    // 找最长公共前缀
    let i = 0
    while (i < a.length && i < b.length && a[i] === b[i]) i++
    if (i < a.length * 0.6) return null
    return b.slice(i)
  }

  async function startRec() {
    if (rec.value) return
    if (!auth.token) return
    segments.value = []
    speakers.value = new Map()
    sessionSpeakers.value = new Map()
    segSeq = 0
    recStart.value = Date.now()
    rec.value = true
    try {
      mic = await startMic()
      mic.processor.onaudioprocess = (ev) => {
        if (!mic) return
        const inp = ev.inputBuffer.getChannelData(0)
        recRMS.value = rms(inp)
        const i16 = floatToInt16(inp)
        ws?.sendAudio(i16)
      }
      // 启动 WS
      ws = new LiveWs({
        clientId: clientId.value,
        token: auth.token,
        onMessage,
        onState: (s) => { wsState.value = s },
        onClose: (code) => {
          if (code === 4401) {
            auth.clear()
            router.push({ name: 'login', query: { next: '/live' } })
          }
        },
      })
      ws.connect()
      // 启动 timer
      timerId = setInterval(() => { recTimer.value = elapsed.value }, 1000)
      rafId = requestAnimationFrame(drawWave)
    } catch (e) {
      window.toast?.(`${e instanceof Error ? e.message : String(e)}`, 'error')
      stopRec()
    }
  }

  function stopRec() {
    rec.value = false
    if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null }
    if (timerId) { clearInterval(timerId); timerId = null }
    if (mic) { mic.stop(); mic = null }
    if (ws) { ws.close(); ws = null }
    recRMS.value = 0
  }

  function rename(title: string) {
    if (title && ws) {
      ws.sendRename(title)
      sessionTitle.value = title
    }
  }

  async function clearTranscript() {
    segments.value = []
    speakers.value = new Map()
    sessionSpeakers.value = new Map()
  }

  // 简化: 用历史 RMS 数组驱动伪波形 (50 段)
  const waveHist = ref<number[]>(Array(80).fill(0))
  function drawWave() {
    if (!rec.value) return
    const arr = waveHist.value
    arr.shift()
    arr.push(recRMS.value * 6)  // 放大便于显示
    waveHist.value = [...arr]
    rafId = requestAnimationFrame(drawWave)
  }

  return {
    clientId,
    sessionId,
    sessionTitle,
    wsState,
    rec,
    recRMS,
    recTimer,
    segments,
    speakers,
    sessionSpeakers,
    recent,
    segCount,
    spkCount,
    waveHist,
    startRec,
    stopRec,
    rename,
    clearTranscript,
    getDisplayName,
    // 测试用:让 Playwright 能注入假 ASR 消息(无需真实麦克风)
    __testInject: (m: unknown) => onMessage(m as never),
  }
})
