import { call } from './client'

export interface EngineInfo {
  name: string
  model: string
  description: string
  description_en?: string
  speed: string
  speed_en?: string
  params?: string
  eer_voxceleb?: string
  eer_cnceleb?: string
}

export async function getEngines() {
  return call<{ current: string; engines: Record<string, EngineInfo> }>({
    url: '/v1/engines',
  })
}

export async function switchEngine(engine_type: string) {
  return call<{ success: boolean; current: string; error?: string }>({
    url: '/v1/engine',
    method: 'PUT',
    data: { engine_type },
  })
}
