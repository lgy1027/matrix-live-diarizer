import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  listHistory,
  deleteHistory,
  getSession,
  type HistoryItem,
  type ListHistoryParams,
} from '../api/history'

export const useLibraryStore = defineStore('library', () => {
  const items = ref<HistoryItem[]>([])
  const total = ref(0)
  const filterSrc = ref<'all' | 'websocket' | 'upload'>('all')
  const filterQ = ref('')
  const loading = ref(false)
  const error = ref<string | null>(null)
  const currentDetail = ref<{
    item: HistoryItem
    segments: NonNullable<Awaited<ReturnType<typeof getSession>>>['segments']
    statistics: NonNullable<Awaited<ReturnType<typeof getSession>>>['statistics']
  } | null>(null)
  const detailLoading = ref(false)
  const llmResult = ref<{ text?: string; items?: string[]; source?: string } | null>(null)

  async function load() {
    loading.value = true
    error.value = null
    try {
      const r = await listHistory({
        source: filterSrc.value,
        q: filterQ.value || undefined,
        page: 1,
        page_size: 50,
      })
      items.value = r.items
      total.value = r.total
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  async function remove(id: string) {
    await deleteHistory(id)
    await load()
  }

  async function openDetail(id: string) {
    detailLoading.value = true
    currentDetail.value = null
    llmResult.value = null
    try {
      const r = await getSession(id)
      const item = items.value.find((it) => it.id === id) || (r.session as unknown as HistoryItem)
      currentDetail.value = { item, segments: r.segments, statistics: r.statistics }
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      detailLoading.value = false
    }
  }

  function closeDetail() {
    currentDetail.value = null
    llmResult.value = null
  }

  const totalHours = computed(() => items.value.reduce((s, it) => s + (it.duration_sec || 0), 0) / 3600)
  const totalSpeakers = computed(() => {
    const set = new Set<string>()
    items.value.forEach((it) => (it.speakers || []).forEach((s) => set.add(s)))
    return set.size
  })

  return {
    items,
    total,
    filterSrc,
    filterQ,
    loading,
    error,
    currentDetail,
    detailLoading,
    llmResult,
    totalHours,
    totalSpeakers,
    load,
    remove,
    openDetail,
    closeDetail,
  }
})
