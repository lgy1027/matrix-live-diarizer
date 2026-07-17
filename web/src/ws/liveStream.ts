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

export type WsState = 'idle' | 'connecting' | 'live' | 'disconnected' | 'auth-failed'

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
  private intentionalClose = false

  constructor(opts: LiveWsOpts) {
    this.opts = opts
  }

  connect() {
    this.intentionalClose = false
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
      this.ws = null
      if (!this.intentionalClose) this.opts.onState('disconnected')
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
    this.intentionalClose = true
    if (this.ws) {
      this.ws.close(1000)
      this.ws = null
    }
    this.opts.onState('idle')
  }
}
