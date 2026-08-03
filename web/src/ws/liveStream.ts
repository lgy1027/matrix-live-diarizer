// WebSocket 客户端: 实时音频流 (与后端 app/api/websocket.py 协议对接)
// 协议:
//   客户端 → 服务端:
//     [0] 首条 JSON: {action: "auth", token: "..."}
//     [1] JSON: {action: "rename", title: "..."}
//     [2] 二进制: Int16LE 16kHz mono PCM frame
//   服务端 → 客户端:
//     finalized meeting-time utterance | control event | system event
//   close(4401) = 鉴权失败

export type FinalUtterance = { speaker: string; text: string; time?: string; start: number; end: number; timebase: 'meeting'; is_final: true; speaker_state: 'unknown'|'provisional'|'final'; words?: { text: string; start: number; end: number }[]; score?: number; seq?: number }

export type AsrMessage =
  | FinalUtterance
  | { type: 'renamed'; title: string; meeting_id?: string }
  | { type: 'meeting'; title: string; meeting_id: string }
  | { type: 'meeting_finalized'; meeting_id: string; job_id?: string; refinement_status: 'queued'|'ready'|'unavailable' }
  | { type: 'transcribing'; seq: number }
  | { speaker: 'SYSTEM'; text: string; time?: never; words?: never }

export type WsState = 'idle' | 'connecting' | 'live' | 'disconnected' | 'auth-failed' | 'reconnecting'

export interface LiveWsOpts {
  clientId: string
  token: string
  onMessage: (m: AsrMessage) => void
  onState: (s: WsState) => void
  onClose?: (code: number) => void
  onReconnectAttempt?: (attempt: number, maxAttempts: number, delayMs: number) => void
  onReconnectFailed?: () => void
  onReconnected?: () => void
}

function wsBase(): string {
  if (typeof window === 'undefined') return ''
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}`
}

export class LiveWs {
  private ws: WebSocket | null = null
  private opts: LiveWsOpts
  private intentionalClose = false
  private reconnectAttempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  static readonly MAX_RECONNECT_ATTEMPTS = 5

  constructor(opts: LiveWsOpts) {
    this.opts = opts
  }

  connect() {
    this.intentionalClose = false
    this.reconnectAttempts = 0
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    this.openSocket()
  }

  private openSocket() {
    this.opts.onState('connecting')
    const url = `${wsBase()}/ws/v1/stream/${encodeURIComponent(this.opts.clientId)}`
    this.ws = new WebSocket(url)
    this.ws.binaryType = 'arraybuffer'
    this.ws.onopen = () => {
      this.sendJson({ action: 'auth', token: this.opts.token })
      this.opts.onState('live')
      if (this.reconnectAttempts > 0) {
        this.opts.onReconnected?.()
      }
      this.reconnectAttempts = 0
    }
    this.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data as string) as AsrMessage
        this.opts.onMessage(data)
      } catch {
        // ignore non-JSON frames
      }
    }
    this.ws.onclose = (ev) => {
      this.opts.onClose?.(ev.code)
      this.ws = null
      if (ev.code === 4401) {
        this.opts.onState('auth-failed')
        return
      }
      if (this.intentionalClose) {
        this.opts.onState('idle')
        return
      }
      // 自动重连:指数退避 1s / 2s / 4s / 8s / 16s,最多 5 次
      if (this.reconnectAttempts >= LiveWs.MAX_RECONNECT_ATTEMPTS) {
        this.opts.onReconnectFailed?.()
        this.opts.onState('disconnected')
        return
      }
      this.reconnectAttempts++
      const delay = 1000 * Math.pow(2, this.reconnectAttempts - 1)
      this.opts.onState('reconnecting')
      this.opts.onReconnectAttempt?.(this.reconnectAttempts, LiveWs.MAX_RECONNECT_ATTEMPTS, delay)
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null
        if (!this.intentionalClose) this.openSocket()
      }, delay)
    }
    this.ws.onerror = () => {
      // onclose 会处理重连,这里不重复
    }
  }

  sendAudio(int16: Int16Array) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      // 背压保护:慢网络下浏览器发送缓冲持续累积,超过阈值丢帧避免
      // 内存膨胀 + 时间戳越拉越滞后。
      if (this.ws.bufferedAmount > 1_048_576) {
        return
      }
      // Send the view, not its backing buffer: callers may pass a subarray and
      // the backing buffer can contain samples outside the requested frame.
      this.ws.send(int16)
    }
  }

  sendRename(title: string) {
    this.sendJson({ action: 'rename', title })
  }

  private sendJson(o: object) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(o))
    }
  }

  close() {
    this.intentionalClose = true
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    if (this.ws) {
      this.ws.close(1000)
      this.ws = null
    }
    this.opts.onState('idle')
  }
}
