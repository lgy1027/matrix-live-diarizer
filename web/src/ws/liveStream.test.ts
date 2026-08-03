import { beforeEach, describe, expect, it, vi } from 'vitest'

import { LiveWs, type WsState } from './liveStream'

class FakeWebSocket {
  static readonly OPEN = 1
  static instances: FakeWebSocket[] = []

  readonly url: string
  readyState = FakeWebSocket.OPEN
  bufferedAmount = 0
  binaryType = ''
  sent: unknown[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  onerror: (() => void) | null = null

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(value: unknown) {
    this.sent.push(value)
  }

  close(code = 1000) {
    this.onclose?.({ code })
  }
}

describe('LiveWs', () => {
  beforeEach(() => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
  })

  it('authenticates on open and sends only the requested PCM view', () => {
    const states: WsState[] = []
    const client = new LiveWs({
      clientId: 'room/a', token: 'secret', onMessage: () => {},
      onState: (state) => states.push(state),
    })
    client.connect()
    const socket = FakeWebSocket.instances[0]
    socket.onopen?.()

    expect(socket.url).toBe('/ws/v1/stream/room%2Fa')
    expect(socket.sent[0]).toBe(JSON.stringify({ action: 'auth', token: 'secret' }))
    const backing = new Int16Array([10, 20, 30, 40])
    const frame = backing.subarray(1, 3)
    client.sendAudio(frame)
    expect(socket.sent[1]).toBe(frame)
    expect(states).toEqual(['connecting', 'live'])
  })

  it('drops audio while the browser send buffer is over the limit', () => {
    const client = new LiveWs({
      clientId: 'room', token: 'secret', onMessage: () => {}, onState: () => {},
    })
    client.connect()
    const socket = FakeWebSocket.instances[0]
    socket.bufferedAmount = 1_048_577
    client.sendAudio(new Int16Array([1, 2]))
    expect(socket.sent).toEqual([])
  })

  it('does not reconnect after an authentication close', () => {
    vi.useFakeTimers()
    const states: WsState[] = []
    const client = new LiveWs({
      clientId: 'room', token: 'bad', onMessage: () => {},
      onState: (state) => states.push(state),
    })
    client.connect()
    FakeWebSocket.instances[0].onclose?.({ code: 4401 })
    vi.runAllTimers()

    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(states.at(-1)).toBe('auth-failed')
    vi.useRealTimers()
  })
})
