import { call } from './client'

export async function getLlmStatus() {
  return call<{
    enabled: boolean
    available: boolean
    endpoint?: string
    model?: string
    mock: boolean
    fallback: string
  }>({ url: '/v1/llm/status' })
}

export async function llmSummarize(session_id: string, max_words = 200) {
  return call<{ text: string; source: string }>({
    url: '/v1/llm/summarize',
    method: 'POST',
    data: { session_id, max_words },
  })
}

export async function llmActionItems(session_id: string) {
  return call<{ items: string[]; source: string }>({
    url: '/v1/llm/action-items',
    method: 'POST',
    data: { session_id },
  })
}

export async function llmMinutes(session_id: string) {
  return call<{ text: string; source: string }>({
    url: '/v1/llm/minutes',
    method: 'POST',
    data: { session_id },
  })
}
