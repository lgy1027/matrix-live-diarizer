import { call } from './client'

export interface HistoryItem {
  id: string
  title?: string
  original_filename?: string
  source: 'websocket' | 'upload'
  duration_sec: number
  segments_count: number
  speakers: string[]
  created_at: string
  size_bytes?: number
}

export interface ListHistoryParams {
  source?: 'websocket' | 'upload' | 'all'
  q?: string
  page?: number
  page_size?: number
}

export async function listHistory(params: ListHistoryParams = {}) {
  const qs = new URLSearchParams()
  if (params.source && params.source !== 'all') qs.set('source', params.source)
  if (params.q) qs.set('q', params.q)
  qs.set('page', String(params.page || 1))
  qs.set('page_size', String(params.page_size || 50))
  return call<{ total: number; items: HistoryItem[] }>({
    url: `/v1/history?${qs.toString()}`,
  })
}

export async function deleteHistory(id: string) {
  return call<{ message: string }>({ url: `/v1/history/${id}`, method: 'DELETE' })
}

export async function getSession(id: string) {
  return call<{
    session: HistoryItem & Record<string, unknown>
    segments: Array<{
      text: string
      speaker_id?: string
      start_time: number
      end_time: number
      words?: { text: string; start: number; end: number }[]
    }>
    statistics: {
      speakers?: Array<{ speaker_id: string; display_name?: string; talk_time_sec: number; talk_ratio: number }>
      hot_words?: Array<{ word: string; count: number }>
      total_duration_sec?: number
      silence_ratio?: number
      turn_taking_count?: number
    }
  }>({ url: `/v1/sessions/${id}` })
}

export async function patchSession(id: string, body: { title?: string; is_archived?: 0 | 1 }) {
  return call<{ message: string; session: HistoryItem }>({
    url: `/v1/sessions/${id}`,
    method: 'PATCH',
    data: body,
  })
}

export interface SearchHit {
  segment_id: number
  session_id: string
  session_title?: string
  session_filename?: string
  speaker_id?: string
  text: string
  snippet: string
  start_time: number
  end_time: number
  jump_url: string
}

export async function search(q: string, opts: { session_id?: string; speaker_id?: string; limit?: number } = {}) {
  const qs = new URLSearchParams({ q })
  if (opts.session_id) qs.set('session_id', opts.session_id)
  if (opts.speaker_id) qs.set('speaker_id', opts.speaker_id)
  if (opts.limit) qs.set('limit', String(opts.limit))
  return call<{ query: string; total: number; hits: SearchHit[] }>({ url: `/v1/search?${qs.toString()}` })
}
