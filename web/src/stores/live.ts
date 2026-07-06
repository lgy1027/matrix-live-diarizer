import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
// 注: 'computed' 仅用于 segments/speakers 等响应式数据,timer 用普通函数
import { useRouter } from 'vue-router'
import { LiveWs, type AsrMessage, type WsState } from '../ws/liveStream'
import { useAuthStore } from './auth'
import { startMic, floatToInt16, rms, resampleTo16k, type MicHandle } from '../utils/audio'

export interface LiveSegment {
  id: number
  speaker: string
  text: string            // 服务端最终文本
  displayed: string       // 打字机当前显示到第几个字
  typewriterId?: number   // setTimeout 链 ID,新 ASR 到达时清掉旧链
  time: string
  words?: { text: string; start: number; end: number }[]
  status?: 'transcribing' | 'normal' | 'stale' | 'timeout'
  seq?: number            // 用于占位段 ↔ ASR 结果配对
  score?: number          // 声纹识别置信度 0-1,来自后端 compare_and_identify
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
  // 友好名:Spk_xxx → Speaker N (N 按会话内首次出现的顺序)
  // 同会话内稳定:同一个 Spk_xxx 始终映射到同一个 N
  const sessionSpeakers = ref<Map<string, number>>(new Map())
  const recent = ref<{ id: string; title?: string; original_filename?: string; source: string; duration_sec: number; created_at: string }[]>([])

  const segCount = computed(() => segments.value.length)
  const spkCount = computed(() => speakers.value.size)
  // bug-fix: 不要用 computed 包 Date.now() — Vue 永远认为依赖未变,返回首次缓存值
  // 模板里直接 {{ fmtTime(live.recTimer) }} 即可,recTimer 由 setInterval 自己推进
  const recTick = () => rec.value ? Math.floor((Date.now() - recStart.value) / 1000) : 0

  let mic: MicHandle | null = null
  let ws: LiveWs | null = null
  let rafId: number | null = null
  let timerId: ReturnType<typeof setInterval> | null = null
  let segSeq = 0

  function registerSpeaker(speaker: string) {
    if (!speaker) return
    const cur = speakers.value.get(speaker) || 0
    speakers.value.set(speaker, cur + 1)
    speakers.value = new Map(speakers.value)
    if (speaker.startsWith('Spk_') && !sessionSpeakers.value.has(speaker)) {
      sessionSpeakers.value.set(speaker, sessionSpeakers.value.size + 1)
      sessionSpeakers.value = new Map(sessionSpeakers.value)
    }
  }

  function onMessage(m: AsrMessage) {
    if ('type' in m && m.type === 'renamed') {
      sessionTitle.value = m.title
      return
    }
    // 转写中占位: VAD 进入 SPEECH 时服务端立刻推这条消息
    if ('type' in m && m.type === 'transcribing') {
      const seq = (m as any).seq as number
      // 如果已有占位段,标 stale(折叠成灰色细行)
      const existing = segments.value.find(s => s.status === 'transcribing')
      if (existing) {
        existing.status = 'stale'
      }
      segments.value.push({
        id: ++segSeq,
        speaker: '',
        text: '',
        displayed: '▌ 正在识别…',
        status: 'transcribing',
        seq,
        time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      })
      // 5s 超时兜底(超过则置为 timeout,UI 折叠)
      window.setTimeout(() => {
        const ph = segments.value.find(s => s.seq === seq && s.status === 'transcribing')
        if (ph) ph.status = 'timeout'
      }, 5000)
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
      registerSpeaker(asr.speaker)
      // 如果有匹配 seq 的占位段,用 ASR 结果替换它(而不是创建新段)
      const placeholder = segments.value.find(s => s.status === 'transcribing' && s.seq === (asr as any).seq)
      if (placeholder) {
        placeholder.speaker = asr.speaker
        placeholder.text = asr.text
        placeholder.status = 'normal'
        placeholder.displayed = ''
        placeholder.time = asr.time || placeholder.time
        placeholder.seq = undefined
        if (asr.words) placeholder.words = asr.words
        if (typeof (asr as any).score === 'number') placeholder.score = (asr as any).score
        // 启动打字机
        const fullText = asr.text
        let i = 0
        const tick = () => {
          if (i >= fullText.length) {
            placeholder.displayed = fullText
            placeholder.typewriterId = undefined
            return
          }
          i++
          placeholder.displayed = fullText.slice(0, i)
          placeholder.typewriterId = window.setTimeout(tick, 50)
        }
        tick()
        // speakers Map 更新已在方法顶部统一处理(避免重复逻辑)
        return
      }
      // 服务端已经做过 get_incremental_text(),这里 asr.text 是增量(不是完整文本)
      // bug-fix: 之前 last.text = asr.text (覆盖) 导致后续 ASR 把前面覆盖,只剩一段
      // 正确: last.text += asr.text (追加)
      const last = segments.value[segments.value.length - 1]
      const isMerge = last && last.speaker === asr.speaker

      let target: LiveSegment

      if (isMerge) {
        // merge: 把增量字符追加到 last.text,清掉旧打字机链,新链从 displayed 继续
        last.text = (last.text || '') + asr.text
        if (asr.words) last.words = asr.words
        if (typeof (asr as any).score === 'number') last.score = (asr as any).score
        if (last.typewriterId) {
          clearTimeout(last.typewriterId)
          last.typewriterId = undefined
        }
        target = last
      } else {
        // 新段:创建 + push
        target = {
          id: ++segSeq,
          speaker: asr.speaker,
          text: asr.text,
          displayed: '',
          time: asr.time || new Date().toLocaleTimeString('zh-CN', { hour12: false }),
          words: asr.words,
          score: typeof (asr as any).score === 'number' ? (asr as any).score : undefined,
        }
        segments.value.push(target)
      }

      // 启动打字机:从 target.displayed.length 开始,50ms 一字
      // 注: target.text 是完整累积,打字机从已显示位置继续显示到末尾
      const fullText = target.text
      const startFrom = Math.min(target.displayed.length, fullText.length)
      const tick = (i: number) => {
        if (i >= fullText.length) {
          target.displayed = fullText
          target.typewriterId = undefined
          return
        }
        target.displayed = fullText.slice(0, i + 1)
        target.typewriterId = window.setTimeout(() => tick(i + 1), 50)
      }
      if (startFrom < fullText.length) {
        tick(startFrom)
      } else {
        target.displayed = fullText
      }
    }
  }

  // 说话人手动覆盖:session 内本地生效,刷新重置
  // 不持久化到数据库,跟"实时显示"对齐
  const speakerOverride = ref<Map<number, string>>(new Map())

  function renameSegmentSpeaker(segId: number, newName: string) {
    if (!newName) return
    speakerOverride.value.set(segId, newName)
    speakerOverride.value = new Map(speakerOverride.value)  // Vue 响应式触发
  }

  function revertSegmentRename(segId: number) {
    speakerOverride.value.delete(segId)
    speakerOverride.value = new Map(speakerOverride.value)
  }

  function mergeSegmentSpeaker(segId: number, targetSpeakerId: string) {
    const seg = segments.value.find(s => s.id === segId)
    if (!seg) return
    // 直接修改 speaker,让 getDisplayName 派生出 target 的友好名
    seg.speaker = targetSpeakerId
    // 清掉 override(避免覆盖)
    speakerOverride.value.delete(segId)
    speakerOverride.value = new Map(speakerOverride.value)
  }

  function getDisplayName(seg: LiveSegment): string {
    // override 优先(用户手动改的名字)
    const overridden = speakerOverride.value.get(seg.id)
    if (overridden) return overridden

    if (!seg.speaker) return '未知说话人'
    if (seg.speaker === 'SYSTEM') return '系统'
    if (seg.speaker.startsWith('Spk_')) {
      const n = sessionSpeakers.value.get(seg.speaker)
      return n !== undefined ? `Speaker ${n}` : '未知说话人'
    }
    // 已注册声纹的 ID (非 Spk_ 前缀) — 走 speakers store 解析别名
    // 这里先返回原值;后续 commit 接 alias
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
      // bug-fix: 浏览器可能忽略 sampleRate:16000,实际 48kHz — 实时降采样到 16kHz
      const fromRate = mic.actualSampleRate
      const needResample = fromRate !== 16000
      if (needResample) {
        console.info(`[live] 降采样 ${fromRate}→16000 Hz`)
      }
      mic.processor.onaudioprocess = (ev) => {
        if (!mic) return
        const inp = ev.inputBuffer.getChannelData(0)
        recRMS.value = rms(inp)
        // RMS 在原始 48k 上算更准(不会被降采样平滑掉);但为了一致性,降采样后再算也可
        const pcm16k = needResample ? resampleTo16k(inp, fromRate) : inp
        const i16 = floatToInt16(pcm16k)
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
      timerId = setInterval(() => { recTimer.value = recTick() }, 1000)
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
    if (!title) return
    if (ws) {
      // ws 已连:发到服务端 + 本地更新
      ws.sendRename(title)
    } else {
      // 没录音时:本地更新 sessionTitle 用于显示,后端下次重连不会自动同步
      // (实际场景:rename 按钮只在 live.rec 时显示,所以这个分支几乎不会触发)
      console.warn('[live] rename called but ws not connected, sessionTitle 仅本地生效')
    }
    sessionTitle.value = title
  }

  async function clearTranscript() {
    segments.value = []
    speakers.value = new Map()
    sessionSpeakers.value = new Map()
    console.info('[live] 转写视图已清空(服务端会话不受影响)')
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
    speakerOverride,
    startRec,
    stopRec,
    rename,
    clearTranscript,
    getDisplayName,
    renameSegmentSpeaker,
    revertSegmentRename,
    mergeSegmentSpeaker,
    // 测试用:让 Playwright 能注入假 ASR 消息(无需真实麦克风)
    __testInject: (m: unknown) => onMessage(m as never),
  }
})
