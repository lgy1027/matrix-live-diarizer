import { call } from './client'

export async function getStorageStatus() {
  return call<{ history_enabled: boolean; source: string }>({ url: '/v1/storage/status' })
}
