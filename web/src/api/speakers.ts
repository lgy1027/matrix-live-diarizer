import { call } from './client'

export interface Speaker {
  id: string
  name?: string
  session_id?: string
  sample_count: number
  last_update: number
  total_duration?: number
}

export async function listSpeakers() {
  return call<{ speakers: Speaker[]; total: number }>({ url: '/v1/speakers' })
}

export async function patchSpeaker(id: string, name: string) {
  return call<{ message: string }>({ url: `/v1/speakers/${id}`, method: 'PATCH', data: { name } })
}

export async function deleteSpeaker(id: string) {
  return call<{ message: string }>({ url: `/v1/speakers/${id}`, method: 'DELETE' })
}

export interface CleanupResult {
  dry_run: boolean
  candidates: string[]
  deleted: string[]
  total_before: number
  total_after: number
  cascade_segments_cleared: number
}

export async function cleanupSpeakers(body: {
  max_count?: number
  dry_run: boolean
  cascade?: boolean
  speaker_ids?: string[]
}) {
  return call<CleanupResult>({ url: '/v1/speakers/cleanup', method: 'POST', data: body })
}

export async function mergeSpeakers(target_id: string, source_ids: string[]) {
  return call<{ target_id: string; merged_source_ids: string[]; segments_updated: number }>({
    url: '/v1/speakers/merge',
    method: 'POST',
    data: { target_id, source_ids },
  })
}

export async function enrollSpeaker(file: File, speaker_id: string, name?: string) {
  const fd = new FormData()
  fd.append('file', file)
  const qs = new URLSearchParams({ speaker_id })
  if (name) qs.set('name', name)
  return call<{ speaker_id: string; name?: string; duration_sec: number; sample_count: number }>({
    url: `/v1/speakers/enroll?${qs.toString()}`,
    method: 'POST',
    data: fd,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export async function uploadAudio(
  file: File,
  opts: { enable_diarization?: boolean } = {},
) {
  const fd = new FormData()
  fd.append('file', file)
  const qs = new URLSearchParams()
  if (opts.enable_diarization !== undefined) qs.set('enable_diarization', String(opts.enable_diarization))
  return call<{
    status: string
    filename: string
    speaker?: string
    text: string
    duration: number
    segments?: Array<{ speaker: string; text: string; start_time: number; end_time: number; words?: { text: string; start: number; end: number }[] }>
    speakers?: string[]
    session_id?: string
  }>({
    url: `/v1/upload?${qs.toString()}`,
    method: 'POST',
    data: fd,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
