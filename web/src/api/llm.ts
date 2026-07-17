import { call } from './client'

export async function getLlmStatus() {
  return call<{
    enabled: boolean
    available: boolean | null
    last_tested_at?: string | null
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

export async function testLlmConnection() {
  return call<Awaited<ReturnType<typeof getLlmStatus>>>({
    url: '/v1/llm/test',
    method: 'POST',
  })
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
