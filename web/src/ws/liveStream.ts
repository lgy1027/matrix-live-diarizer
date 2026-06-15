// WebSocket 客户端: 实时音频流 (与后端 app/api/websocket.py 协议对接)
// 协议:
//   客户端 → 服务端:
//     [0] 首条 JSON: {action: "auth", token: "..."}
//     [1] JSON: {action: "rename", title: "..."}
//     [2] 二进制: Int16LE 16kHz mono PCM frame
//   服务端 → 客户端:
//     {speaker, text, time, words?} | {type: "renamed", title} | {speaker: "SYSTEM", text: "LINK_IDLE_TIMEOUT"}
//   close(4401) = 鉴权失败

export type AsrMessage =
  | { speaker: string; text: string; time?: string; words?: { text: string; start: number; end: number }[] }
  | { type: 'renamed'; title: string }
  | { speaker: 'SYSTEM'; text: string; time?: never; words?: never }

export type WsState = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'auth-failed'

export interface LiveWsOpts {
  clientId: string
  token: string
  onMessage: (m: AsrMessage) => void
  onState: (s: WsState) => void
  onClose?: (code: number) => void
}

function wsBase(): string {
  if (typeof window === 'undefined') return ''
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}`
}

export class LiveWs {
  private ws: WebSocket | null = null
  private opts: LiveWsOpts
  private shouldReconnect = false
  private attempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  constructor(opts: LiveWsOpts) {
    this.opts = opts
  }

  connect() {
    this.shouldReconnect = true
    this.openSocket()
  }

  private openSocket() {
    this.opts.onState(this.attempts === 0 ? 'connecting' : 'reconnecting')
    const url = `${wsBase()}/ws/v1/stream/${encodeURIComponent(this.opts.clientId)}`
    this.ws = new WebSocket(url)
    this.ws.binaryType = 'arraybuffer'
    this.ws.onopen = () => {
      this.attempts = 0
      this.sendJson({ action: 'auth', token: this.opts.token })
      this.opts.onState('live')
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
      if (ev.code === 4401) {
        this.opts.onState('auth-failed')
        return
      }
      if (!this.shouldReconnect) return
      // 指数退避 1/2/4/8/16s, 最多 5 次
      if (this.attempts >= 5) {
        this.opts.onState('reconnecting')
        return
      }
      const delay = 1000 * Math.pow(2, this.attempts)
      this.attempts++
      this.opts.onState('reconnecting')
      this.reconnectTimer = setTimeout(() => this.openSocket(), delay)
    }
    this.ws.onerror = () => {
      // onclose 会处理重连, 这里只记
    }
  }

  sendAudio(int16: Int16Array) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(int16.buffer)
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
    this.shouldReconnect = false
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    if (this.ws) {
      this.ws.close(1000)
      this.ws = null
    }
    this.opts.onState('idle')
  }
}
