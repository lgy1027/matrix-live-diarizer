import { call } from './client'

export async function getLlmStatus() {
  return call<{
    enabled: boolean
    available: boolean
    endpoint?: string
    model?: string
    mock: boolean
    provider?: string
    allow_public?: boolean
    timeout_sec?: number
    max_input_tokens?: number
    has_api_key?: boolean
    config_source?: string
    error?: string | null
    fallback: string
  }>({ url: '/v1/llm/status' })
}

export interface LlmSettings {
  provider: string
  enabled: boolean
  endpoint: string
  model: string
  allow_public: boolean
  timeout_sec: number
  max_input_tokens: number
  mock: boolean
  has_api_key?: boolean
  config_source?: string
}

export interface LlmSettingsPayload extends LlmSettings {
  api_key?: string | null
}

export async function getLlmSettings() {
  return call<LlmSettings>({ url: '/v1/llm/settings' })
}

export async function saveLlmSettings(data: LlmSettingsPayload) {
  return call<LlmSettings>({
    url: '/v1/llm/settings',
    method: 'PUT',
    data,
  })
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
