import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  listSpeakers,
  patchSpeaker,
  deleteSpeaker,
  cleanupSpeakers,
  mergeSpeakers,
  enrollSpeaker,
  type Speaker,
} from '../api/speakers'

export const useVoiceStore = defineStore('voice', () => {
  const speakers = ref<Speaker[]>([])
  const filter = ref('')
  const selectMode = ref(false)
  const selectedIds = ref<Set<string>>(new Set())
  const sessionsCount = ref(0)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const filtered = computed(() => {
    const q = filter.value.trim().toLowerCase()
    if (!q) return speakers.value
    return speakers.value.filter(
      (s) => (s.name || '').toLowerCase().includes(q) || s.id.toLowerCase().includes(q),
    )
  })

  const selectedCount = computed(() => selectedIds.value.size)

  async function load() {
    loading.value = true
    error.value = null
    try {
      const r = await listSpeakers()
      speakers.value = r.speakers || []
      // 清理已不存在的 selectedIds
      for (const id of Array.from(selectedIds.value)) {
        if (!speakers.value.some((s) => s.id === id)) selectedIds.value.delete(id)
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function setSessionsCount(n: number) {
    sessionsCount.value = n
  }

  function toggleFilter(v: string) {
    filter.value = v
  }
  function clearFilter() {
    filter.value = ''
  }

  function enterSelectMode() {
    selectMode.value = true
  }
  function exitSelectMode() {
    selectMode.value = false
    selectedIds.value = new Set()
  }
  function toggleSelect(id: string) {
    const next = new Set(selectedIds.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    selectedIds.value = next
  }
  function selectAll() {
    selectedIds.value = new Set(filtered.value.map((s) => s.id))
  }
  function selectNone() {
    selectedIds.value = new Set()
  }

  async function rename(id: string, newName: string) {
    await patchSpeaker(id, newName)
    await load()
  }
  async function remove(id: string) {
    await deleteSpeaker(id)
    await load()
  }

  async function previewCleanup(maxCount = 5) {
    const r = await cleanupSpeakers({ max_count: maxCount, dry_run: true })
    return r
  }
  async function doCleanup(maxCount = 5, cascade = true) {
    const r = await cleanupSpeakers({ max_count: maxCount, dry_run: false, cascade })
    await load()
    return r
  }

  async function merge(targetId: string, sourceIds: string[]) {
    const r = await mergeSpeakers(targetId, sourceIds)
    await load()
    return r
  }

  async function enroll(file: File, speakerId: string, name?: string) {
    const r = await enrollSpeaker(file, speakerId, name)
    await load()
    return r
  }

  return {
    speakers,
    filter,
    selectMode,
    selectedIds,
    sessionsCount,
    loading,
    error,
    filtered,
    selectedCount,
    load,
    setSessionsCount,
    toggleFilter,
    clearFilter,
    enterSelectMode,
    exitSelectMode,
    toggleSelect,
    selectAll,
    selectNone,
    rename,
    remove,
    previewCleanup,
    doCleanup,
    merge,
    enroll,
  }
})
