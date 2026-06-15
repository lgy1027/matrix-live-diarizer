<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useLibraryStore } from '../stores/library'
import { llmSummarize, llmActionItems, llmMinutes } from '../api/llm'
import { useDialog } from '../composables/useDialog'
import { spkColor } from '../utils/spk'
import { fmtSec, fmtDate, fmtClock } from '../utils/format'

const { t } = useI18n()
const lib = useLibraryStore()
const dialog = useDialog()
const route = useRoute()

const searchInput = ref<HTMLInputElement | null>(null)
const activeDetailTab = ref<'trans' | 'stats' | 'exp' | 'llm'>('trans')
const llmLoading = ref(false)

let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => lib.load(), 300)
}

function switchTab(src: 'all' | 'websocket' | 'upload') {
  if (lib.filterSrc === src) return
  lib.filterSrc = src
  lib.load()
}

async function onDelete(id: string) {
  const it = lib.items.find((x) => x.id === id)
  const ok = await dialog.showConfirm({
    title: t('view.library.delete.confirm') || 'Delete this session?',
    message: it?.title || it?.original_filename || id,
    detail: t('view.library.delete.detail') || 'Cannot be undone.',
    confirmText: t('btn.delete') || '删除',
    cancelText: t('btn.cancel') || '取消',
    danger: true,
  })
  if (!ok) return
  try {
    await lib.remove(id)
    window.toast?.(t('view.library.deleted') || 'Session deleted', 'ok')
  } catch (e) {
    window.toast?.(`${t('toast.error')}: ${e instanceof Error ? e.message : e}`, 'error')
  }
}

function dl(sessionId: string, fmt: 'srt' | 'vtt' | 'markdown' | 'json') {
  const it = lib.items.find((x) => x.id === sessionId)
  const a = document.createElement('a')
  a.href = `/v1/exports/${sessionId}?format=${fmt}`
  a.download = `${it?.title || sessionId}.${fmt}`
  a.click()
}

async function llmOp(op: 'summarize' | 'action-items' | 'minutes') {
  if (!lib.currentDetail) return
  llmLoading.value = true
  lib.llmResult = null
  try {
    if (op === 'summarize') {
      const r = await llmSummarize(lib.currentDetail.item.id)
      lib.llmResult = { text: r.text, source: r.source }
    } else if (op === 'action-items') {
      const r = await llmActionItems(lib.currentDetail.item.id)
      lib.llmResult = { items: r.items, source: r.source }
    } else {
      const r = await llmMinutes(lib.currentDetail.item.id)
      lib.llmResult = { text: r.text, source: r.source }
    }
  } catch (e) {
    lib.llmResult = { text: `${t('toast.error')}: ${e instanceof Error ? e.message : e}` }
  } finally {
    llmLoading.value = false
  }
}

// search.py jump_url: /?open={id}&seg={seg} 形式, 接住 ?open 自动开 detail
watch(
  () => route.query.open,
  (id) => {
    if (typeof id === 'string' && id) lib.openDetail(id)
  },
  { immediate: true },
)

onMounted(() => {
  lib.load()
})
</script>

<template>
  <section class="lib-wrap">
    <h1 class="page-title" v-html="t('view.library.title')" />
    <p class="page-sub">{{ t('view.library.sub') }}</p>
    <div class="lib-stats">
      <div class="item">
        <div class="n">{{ lib.items.length }}</div>
        <span class="l">{{ t('library.stats.sessions') }}</span>
      </div>
      <div class="item">
        <div class="n">{{ lib.totalHours.toFixed(1) }}<em>h</em></div>
        <span class="l">{{ t('library.stats.recorded') }}</span>
      </div>
      <div class="item">
        <div class="n">{{ lib.totalSpeakers }}</div>
        <span class="l">{{ t('library.stats.voices') }}</span>
      </div>
    </div>

    <div class="lib-filter">
      <div class="tabs">
        <div
          v-for="src in (['all', 'websocket', 'upload'] as const)"
          :key="src"
          class="tab"
          :class="{ active: lib.filterSrc === src }"
          @click="switchTab(src)"
        >
          {{ src === 'all' ? (t('library.tab.all') || 'All') : src === 'websocket' ? (t('library.tab.live') || 'Live') : (t('library.tab.upload') || 'Upload') }}
        </div>
      </div>
      <div class="search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.35-4.35" />
        </svg>
        <input
          ref="searchInput"
          type="text"
          :placeholder="t('placeholder.search')"
          @input="onSearchInput"
        />
      </div>
    </div>

    <div class="list">
      <div v-if="lib.loading && lib.items.length === 0" class="empty">
        <em>{{ t('common.loading') || 'Loading…' }}</em>
      </div>
      <div v-else-if="lib.items.length === 0" class="empty">
        <em>{{ t('view.library.empty.title') || 'Library is empty.' }}</em>
        <span>{{ t('view.library.empty.hint') || 'Record a session or upload audio.' }}</span>
      </div>
      <template v-else>
        <div
          v-for="it in lib.items"
          :key="it.id"
          class="row"
          :class="{ open: lib.currentDetail?.item.id === it.id }"
        >
          <div class="row-main" @click="lib.currentDetail?.item.id === it.id ? lib.closeDetail() : lib.openDetail(it.id)">
            <div class="meta">
              <div class="title">{{ it.title || it.original_filename || (t('library.untitled') || '未命名') }}</div>
              <div class="sub">
                <span class="src-tag" :class="it.source">{{ it.source === 'websocket' ? (t('view.library.source.live') || 'Live') : (t('view.library.source.upload') || 'Upload') }}</span>
                <span class="sep">·</span>
                <span>{{ fmtClock(it.duration_sec || 0) }}</span>
                <span class="sep">·</span>
                <span>{{ it.segments_count }} {{ t('view.library.meta.turns') || 'turns' }}</span>
                <span class="sep">·</span>
                <span>{{ fmtDate(it.created_at) }}</span>
              </div>
            </div>
            <div class="row-actions" @click.stop>
              <button class="btn ghost sm" type="button" @click="onDelete(it.id)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="width:12px;height:12px" aria-hidden="true">
                  <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          </div>

          <!-- 内嵌 Detail -->
          <div v-if="lib.currentDetail?.item.id === it.id" class="detail">
            <div v-if="lib.detailLoading" class="empty"><em>{{ t('common.loading') }}</em></div>
            <template v-else-if="lib.currentDetail">
              <div class="detail-tabs">
                <div class="tab" :class="{ active: activeDetailTab === 'trans' }" @click="activeDetailTab = 'trans'">
                  {{ t('detail.tab.transcript') || '📝 转写' }}
                </div>
                <div class="tab" :class="{ active: activeDetailTab === 'stats' }" @click="activeDetailTab = 'stats'">
                  {{ t('detail.tab.stats') || '📊 统计' }}
                </div>
                <div class="tab" :class="{ active: activeDetailTab === 'exp' }" @click="activeDetailTab = 'exp'">
                  {{ t('detail.tab.export') || '📤 导出' }}
                </div>
                <div class="tab" :class="{ active: activeDetailTab === 'llm' }" @click="activeDetailTab = 'llm'">
                  {{ t('detail.tab.ai') || '✨ AI' }}
                </div>
                <button class="close" type="button" :aria-label="t('btn.cancel')" @click="lib.closeDetail()">×</button>
              </div>

              <!-- 转写 -->
              <div v-show="activeDetailTab === 'trans'" class="pane">
                <div v-if="lib.currentDetail.segments.length === 0" class="empty">
                  <em>{{ t('view.library.segments.empty') || 'No transcript yet' }}</em>
                </div>
                <div v-else class="seg-list">
                  <div
                    v-for="(s, i) in lib.currentDetail.segments"
                    :key="i"
                    class="seg"
                    :style="{ borderLeftColor: spkColor(s.speaker_id) }"
                  >
                    <div class="seg-head">
                      <span class="name" :style="{ color: spkColor(s.speaker_id) }">{{ s.speaker_id || (t('speaker.anon') || 'Speaker') }}</span>
                      <span class="id">#{{ i + 1 }}</span>
                      <span class="time">{{ fmtSec(s.start_time) }} → {{ fmtSec(s.end_time) }}</span>
                    </div>
                    <div class="seg-body">{{ s.text }}</div>
                  </div>
                </div>
              </div>

              <!-- 统计 -->
              <div v-show="activeDetailTab === 'stats'" class="pane">
                <div v-if="!lib.currentDetail.statistics.speakers?.length" class="empty">
                  <em>{{ t('detail.empty.stats') || '无统计数据' }}</em>
                </div>
                <template v-else>
                  <h3 class="pane-title">{{ t('view.library.stats.talkTime') || 'Talk Time' }}</h3>
                  <div class="bars">
                    <div
                      v-for="(sp, i) in [...lib.currentDetail.statistics.speakers].sort((a, b) => b.talk_time_sec - a.talk_time_sec)"
                      :key="i"
                      class="b"
                      :class="{ gold: i === 0 }"
                    >
                      <div class="k">{{ sp.display_name || sp.speaker_id }}</div>
                      <div class="t"><i :style="{ width: `${(sp.talk_time_sec / Math.max(1, ...lib.currentDetail.statistics.speakers.map(x => x.talk_time_sec))) * 100}%` }" /></div>
                      <div class="v">{{ fmtClock(sp.talk_time_sec) }} ({{ (sp.talk_ratio * 100).toFixed(1) }}%)</div>
                    </div>
                  </div>
                  <h3 class="pane-title" style="margin-top: 18px">{{ t('view.library.stats.hotWords') || '热词' }}</h3>
                  <div class="chips">
                    <div v-for="(w, i) in (lib.currentDetail.statistics.hot_words || []).slice(0, 15)" :key="i" class="chip">
                      <b>{{ w.count }}</b>{{ w.word }}
                    </div>
                  </div>
                </template>
              </div>

              <!-- 导出 -->
              <div v-show="activeDetailTab === 'exp'" class="pane">
                <div class="export-grid">
                  <button class="btn" type="button" @click="dl(it.id, 'srt')">SRT <small>{{ t('detail.exp.srt.desc') || '字幕' }}</small></button>
                  <button class="btn" type="button" @click="dl(it.id, 'vtt')">VTT <small>{{ t('detail.exp.vtt.desc') || 'WebVTT' }}</small></button>
                  <button class="btn" type="button" @click="dl(it.id, 'markdown')">MD <small>{{ t('detail.exp.md.desc') || 'Markdown' }}</small></button>
                  <button class="btn" type="button" @click="dl(it.id, 'json')">JSON <small>{{ t('detail.exp.json.desc') || '无损' }}</small></button>
                </div>
              </div>

              <!-- AI -->
              <div v-show="activeDetailTab === 'llm'" class="pane">
                <div class="llm-actions">
                  <button class="btn primary" type="button" :disabled="llmLoading" @click="llmOp('summarize')">{{ t('view.library.ai.summarize') || '生成摘要' }}</button>
                  <button class="btn ghost" type="button" :disabled="llmLoading" @click="llmOp('action-items')">{{ t('view.library.ai.actionItems') || '提取行动项' }}</button>
                  <button class="btn ghost" type="button" :disabled="llmLoading" @click="llmOp('minutes')">{{ t('view.library.ai.minutes') || '生成纪要' }}</button>
                </div>
                <div v-if="llmLoading" class="empty"><em>{{ t('view.library.ai.generating') || '生成中…' }}</em></div>
                <div v-else-if="lib.llmResult" class="llm-result">
                  <div v-if="lib.llmResult.source === 'extractive-fallback'" class="tag gold" style="margin-bottom: 8px">本地摘要 (未配置 LLM)</div>
                  <pre v-if="lib.llmResult.text">{{ lib.llmResult.text }}</pre>
                  <ul v-else-if="lib.llmResult.items">
                    <li v-for="(it, i) in lib.llmResult.items" :key="i">{{ it }}</li>
                  </ul>
                </div>
              </div>
            </template>
          </div>
        </div>
      </template>
    </div>
  </section>
</template>

<style scoped>
.lib-wrap { padding: 32px 48px 48px; max-width: 1280px; margin: 0 auto; }
/* 整改 1: 删除 .lib-head 容器, 改用 .page-title + .page-sub (components.css) */
/* 旧的 .head-right (10px mono 标签) 也已删除 */
.lib-stats {
  display: flex;
  gap: 36px;
  margin-bottom: 32px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
}
.lib-stats .n {
  font-family: var(--serif);
  font-variation-settings: 'SOFT' 50, 'WONK' 1, 'opsz' 144;
  font-size: 48px;
  line-height: 1;
  font-weight: 400;
  letter-spacing: -0.03em;
  color: var(--text);
}
.lib-stats .n em { color: var(--teal); font-style: italic; font-size: 32px; }
.lib-stats .l {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-top: 4px;
  display: block;
}
/* 整改 1: 删除 dead .head-right (旧 10px mono 标签), 改用 .page-title / .page-sub */

.lib-filter {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 12px;
  flex-wrap: wrap;
}
.tabs { display: inline-flex; border-bottom: 1px solid var(--border-soft); }
.tab {
  padding: 8px 16px;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-3);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  transition: color 0.12s, border-color 0.12s;
}
.tab:hover { color: var(--text-2); }
.tab.active { color: var(--amber); border-bottom-color: var(--amber); }
.search {
  position: relative;
  display: flex;
  align-items: center;
  width: 280px;
  max-width: 100%;
}
.search svg {
  position: absolute;
  left: 10px;
  width: 13px;
  height: 13px;
  color: var(--text-3);
  pointer-events: none;
}
.search input {
  width: 100%;
  height: 34px;
  padding: 0 12px 0 32px;
  background: var(--ink-2);
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  color: var(--text);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  transition: border-color 0.15s, background 0.15s;
}
.search input:focus { border-color: var(--amber); background: var(--ink-3); outline: none; box-shadow: 0 0 0 3px var(--amber-soft); }
.search input::placeholder { color: var(--text-3); }

.list { display: flex; flex-direction: column; gap: 0; }
.row {
  background: var(--ink-2);
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  margin-bottom: 10px;
  overflow: hidden;
}
.row.open { border-color: var(--amber); }
.row-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  cursor: pointer;
  transition: background 0.12s;
  gap: 14px;
}
.row-main:hover { background: var(--ink-3); }
.meta { min-width: 0; flex: 1; }
.title {
  font-family: 'Outfit', sans-serif;
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sub {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.04em;
  flex-wrap: wrap;
}
.sub .sep { color: var(--border); }
.src-tag {
  padding: 1px 6px;
  font-size: 9px;
  border-radius: 2px;
  background: var(--ink-3);
  border: 1px solid var(--border);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-2);
}
.src-tag.websocket { color: var(--amber); border-color: rgba(255, 107, 53, 0.3); background: var(--amber-soft); }
.src-tag.upload { color: var(--teal); border-color: rgba(78, 205, 196, 0.3); background: var(--teal-soft); }
.row-actions { display: flex; gap: 6px; flex-shrink: 0; }

.detail {
  border-top: 1px solid var(--border-soft);
  background: var(--ink-3);
}
.detail-tabs {
  display: flex;
  align-items: center;
  padding: 6px 20px;
  border-bottom: 1px solid var(--border-soft);
  background: var(--ink-2);
  gap: 4px;
}
.detail-tabs .tab {
  padding: 8px 14px;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-3);
  cursor: pointer;
  border: none;
  background: transparent;
  border-radius: 4px;
  transition: color 0.12s, background 0.12s;
}
.detail-tabs .tab:hover { color: var(--text-2); background: var(--ink-3); }
.detail-tabs .tab.active { color: var(--amber); background: var(--amber-soft); }
.close {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--text-3);
  font-size: 18px;
  cursor: pointer;
  width: 28px;
  height: 28px;
  border-radius: 4px;
}
.close:hover { color: var(--text); background: var(--ink-3); }
.pane { padding: 20px; }
.pane-title {
  font-family: var(--serif);
  font-size: 14px;
  color: var(--text);
  margin-bottom: 12px;
}
.seg-list { display: flex; flex-direction: column; gap: 0; }
.seg {
  padding: 10px 14px;
  border-left: 2px solid var(--border);
  margin-bottom: 8px;
  background: var(--ink-2);
  border-radius: 0 4px 4px 0;
}
.seg:last-child { margin-bottom: 0; }
.seg-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.seg-head .name { font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 500; }
.seg-head .id { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--text-3); }
.seg-head .time { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--text-3); margin-left: auto; }
.seg-body { font-family: 'Outfit', sans-serif; font-size: 13px; line-height: 1.6; color: var(--text); }

.bars { display: flex; flex-direction: column; gap: 8px; }
.b { display: grid; grid-template-columns: 160px 1fr 120px; gap: 12px; align-items: center; }
.b .k { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text); }
.b .t { height: 6px; background: var(--ink-2); border-radius: 3px; overflow: hidden; }
.b .t i { display: block; height: 100%; background: var(--teal); border-radius: 3px; transition: width 0.4s ease; }
.b.gold .t i { background: linear-gradient(90deg, var(--gold), var(--amber)); }
.b .v { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--text-3); text-align: right; }

.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  padding: 4px 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  background: var(--ink-2);
  border: 1px solid var(--border);
  border-radius: 3px;
  color: var(--text-2);
}
.chip b { color: var(--amber); font-weight: 500; margin-right: 4px; }

.export-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; }
.export-grid .btn {
  justify-content: space-between;
  padding: 12px 14px;
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.export-grid .btn small { color: var(--text-3); font-size: 9px; }

.llm-actions { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
.llm-result {
  margin-top: 8px;
  padding: 18px;
  background: var(--ink-2);
  border-radius: 4px;
  border-left: 2px solid var(--gold);
  font-family: var(--serif);
  font-size: 14px;
  line-height: 1.7;
  color: var(--text);
}
.llm-result pre { font-family: 'JetBrains Mono', monospace; font-size: 12px; white-space: pre-wrap; line-height: 1.6; }
.llm-result ul { padding-left: 20px; }
.llm-result li { font-family: 'Outfit', sans-serif; margin: 4px 0; }
</style>
