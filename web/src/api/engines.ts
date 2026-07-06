import { call } from './client'

export interface EngineInfo {
  name: string
  model: string
  description: string
  description_en?: string
  speed?: string
  speed_en?: string
  params?: string
  eer_voxceleb?: string
  eer_cnceleb?: string
}

export interface AsrInfo {
  name: string
  model: string
  description: string
  description_en?: string
  languages?: string
  languages_en?: string
  supports_streaming?: boolean
  supports_words?: boolean
  optional_dependency?: string
  available?: boolean
  dependency?: string
  reason?: string
  install_hint?: string
  install_hint_en?: string
  python?: string
  type?: string
  word_timestamps_enabled?: boolean
  customized?: boolean
  capabilities?: {
    transcription?: boolean
    upload?: boolean
    realtime_segmented?: boolean
    true_streaming?: boolean | string
    word_timestamps?: boolean
    speaker_diarization?: boolean
    recommended_for?: string[]
    notes?: string
    notes_en?: string
    [key: string]: unknown
  }
}

export interface ModelsInfo {
  current: string
  asr: AsrInfo
  asr_engines?: {
    current: string
    engines: Record<string, AsrInfo>
    switching?: boolean
    pending?: string | null
    cached?: string[]
  }
  speakers: Record<string, EngineInfo>
}

export interface AsrSwitchResponse {
  success: boolean
  engine_type: string
  previous_type?: string
  engine_info?: AsrInfo
  already_active?: boolean
  downloaded?: boolean
  switched?: boolean
  error?: string
}

export async function getEngines() {
  return call<{ current: string; engines: Record<string, EngineInfo> }>({
    url: '/v1/engines',
  })
}

export async function getModels() {
  return call<ModelsInfo>({
    url: '/v1/models',
  })
}

export async function getAsrEngines() {
  return call<NonNullable<ModelsInfo['asr_engines']>>({
    url: '/v1/asr/engines',
  })
}

export async function switchAsrEngine(engine_type: string) {
  return call<AsrSwitchResponse>({
    url: '/v1/asr/engine',
    method: 'PUT',
    data: { engine_type },
  })
}

export async function switchEngine(engine_type: string) {
  return call<{ success: boolean; current: string; error?: string }>({
    url: '/v1/engine',
    method: 'PUT',
    data: { engine_type },
  })
}
