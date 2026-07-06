<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useVoiceStore } from '../stores/voice'
import { listHistory } from '../api/history'
import { getSpeakerImpact } from '../api/speakers'
import { useDialog } from '../composables/useDialog'
import { useEnrollSpeaker } from '../composables/useEnrollSpeaker'
import { spkColor } from '../utils/spk'
import { fmtMinutes, fmtRel } from '../utils/format'
import EmText from '../components/EmText.vue'

const { t: ti18n } = useI18n()
const t = (key: string, ...args: (string | number)[]): string => {
  // vue-i18n v10 typed t expects named/Record, 简单场景用 number/string OK
  return (ti18n as unknown as (k: string, ...a: (string | number)[]) => string)(key, ...args)
}
const voice = useVoiceStore()
const dialog = useDialog()

const searchInput = ref<HTMLInputElement | null>(null)
const popoverFor = ref<string | null>(null)

const isAllSelected = computed(
  () => voice.filtered.length > 0 && voice.selectedCount === voice.filtered.length,
)

async function loadAll() {
  await voice.load()
  // 顺便拉一下 sessions 数 (聚合)
  try {
    const r = await listHistory({ page: 1, page_size: 200 })
    const ids = new Set<string>()
    r.items.forEach((it) => (it.speakers || []).forEach((s) => ids.add(s.id)))
    voice.setSessionsCount(Math.min(voice.speakers.length, ids.size))
  } catch { /* noop */ }
}

onMounted(loadAll)

function onSearchInput(e: Event) {
  voice.toggleFilter((e.target as HTMLInputElement).value)
}
function clearSearch() {
  voice.clearFilter()
  if (searchInput.value) searchInput.value.value = ''
}

function onSearchKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') (e.target as HTMLInputElement).blur()
}

function toggleMode() {
  voice.selectMode ? voice.exitSelectMode() : voice.enterSelectMode()
}

function onRowClick(id: string) {
  if (voice.selectMode) voice.toggleSelect(id)
  else openPopover(id)
}

function openPopover(id: string) {
  popoverFor.value = popoverFor.value === id ? null : id
}
function closePopover() {
  popoverFor.value = null
}
function onDocClick(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.vl-actions')) closePopover()
}

async function onRename(id: string) {
  closePopover()
  const sp = voice.speakers.find((s) => s.id === id)
  const newName = await dialog.showPrompt({
    title: t('voice.menu.rename') || '重命名',
    placeholder: (t('voice.rename.ph') as string) || '新名称',
    initialValue: sp?.name || '',
  })
  if (newName === null) return
  try {
    await voice.rename(id, newName)
    window.toast?.(t('voice.rename.ok') || '已重命名', 'ok')
  } catch (e) {
    window.toast?.(`${t('toast.error')}: ${e instanceof Error ? e.message : e}`, 'error')
  }
}

async function onDelete(id: string) {
  closePopover()
  const sp = voice.speakers.find((s) => s.id === id)
  // 整改: 删声纹前先查影响 (引用了多少 segment / session), confirm 里展示
  let impactMsg = t('voice.delete.confirmBody') || '此操作不可撤销。'
  let impact: Awaited<ReturnType<typeof getSpeakerImpact>> | null = null
  try {
    impact = await getSpeakerImpact(id)
  } catch { /* 404 等忽略, 用默认文案 */ }
  if (impact && impact.segments_count > 0) {
    impactMsg = `将清空 ${impact.segments_count} 个 segment 引用 (涉及 ${impact.sessions_count} 个 session)\n\n此操作不可撤销。`
  }

  const ok = await dialog.showConfirm({
    title: t('voice.delete.confirmTitle', sp?.id || '') || `删除 ${sp?.id || id}?`,
    message: impactMsg,
    confirmText: t('btn.delete') || '删除',
    cancelText: t('btn.cancel') || '取消',
    danger: true,
  })
  if (!ok) return
  try {
    const r = await voice.remove(id)
    const cleared = r?.cascade_segments_cleared ?? 0
    if (cleared > 0) {
      window.toast?.(`已删除声纹, 清空 ${cleared} 个 segment 引用`, 'ok')
    } else {
      window.toast?.(t('voice.delete.ok') || '已删除', 'ok')
    }
  } catch (e) {
    window.toast?.(`${t('toast.error')}: ${e instanceof Error ? e.message : e}`, 'error')
  }
}

async function onCleanup() {
  try {
    const dry = await voice.previewCleanup(5)
    if (!dry.candidates || dry.candidates.length === 0) {
      window.toast?.(t('view.voice.cleanupEmpty') || '没有低质量声纹', 'ok')
      return
    }
    const items = dry.candidates.slice(0, 10)
    const ok = await dialog.showList({
      title: t('view.voice.cleanupConfirmTitle', dry.candidates.length) || `删除 ${dry.candidates.length} 个低质量声纹?`,
      body: t('view.voice.cleanupConfirmBody') || '样本 ≤ 5，将清空它们在 segments 表中的引用。',
      items,
      itemCount: dry.candidates.length,
      itemCountLabel: t('view.voice.cleanupItems') || '待删除',
      confirmText: t('btn.delete') || '删除',
      cancelText: t('btn.cancel') || '取消',
      danger: true,
    })
    if (!ok) return
    const r = await voice.doCleanup(5, true)
    window.toast?.(
      t('view.voice.cleanupDone', r.deleted.length, r.cascade_segments_cleared) ||
        `已删除 ${r.deleted.length} 个, 清空 ${r.cascade_segments_cleared} 段引用`,
      'ok',
    )
  } catch (e) {
    window.toast?.(`${t('toast.error')}: ${e instanceof Error ? e.message : e}`, 'error')
  }
}

async function onBulkDelete() {
  if (voice.selectedCount === 0) return
  const ids = Array.from(voice.selectedIds)
  const ok = await dialog.showConfirm({
    title: t('view.voice.bulkDeleteConfirmTitle', ids.length) || `删除 ${ids.length} 个声纹?`,
    message:
      t('view.voice.bulkDeleteConfirmBody', ids.length, 0) ||
      `将删除 ${ids.length} 个声纹, 并清空相关段落引用。此操作不可撤销。`,
    confirmText: t('btn.delete') || '删除',
    cancelText: t('btn.cancel') || '取消',
    danger: true,
  })
  if (!ok) return
  try {
    // 走 cleanup 流, 但限定 speaker_ids
    await voice.previewCleanup(5) // 占位: 实际批量删除也可走 cleanup 或直接 delete
    for (const id of ids) {
      try { await voice.remove(id) } catch { /* skip */ }
    }
    voice.exitSelectMode()
    window.toast?.(t('view.voice.bulkDeleteDone', ids.length, 0) || `已删除 ${ids.length} 个`, 'ok')
  } catch (e) {
    window.toast?.(`${t('toast.error')}: ${e instanceof Error ? e.message : e}`, 'error')
  }
}

async function onBulkMerge() {
  if (voice.selectedCount < 2) return
  const ids = Array.from(voice.selectedIds)
  // 让用户选 target
  const target = await dialog.showPrompt({
    title: t('view.voice.mergeTitle') || '选择保留的声纹',
    placeholder: 'Spk_xxx',
    initialValue: ids[0],
  })
  if (!target) return
  if (!ids.includes(target)) {
    window.toast?.(t('toast.error') || '目标必须在已选项中', 'error')
    return
  }
  const sources = ids.filter((i) => i !== target)
  try {
    const r = await voice.merge(target, sources)
    voice.exitSelectMode()
    window.toast?.(
      t('view.voice.mergeDone', sources.length, r.segments_updated) ||
        `已合并 ${sources.length} 个声纹, 更新 ${r.segments_updated} 段`,
      'ok',
    )
  } catch (e) {
    window.toast?.(`${t('toast.error')}: ${e instanceof Error ? e.message : e}`, 'error')
  }
}

// SPA v3: enroll 流程抽到 composable, 顶栏 + 列表底部都能用
const { enroll: onEnroll } = useEnrollSpeaker()

onMounted(() => {
  document.addEventListener('click', onDocClick)
})
</script>

<template>
  <section class="voice-wrap" @click="closePopover">
    <!-- head -->
    <header class="voice-head">
      <div class="voice-titles">
        <h1 class="page-title"><EmText :text="t('view.voice.title')" /></h1>
        <p class="page-sub">{{ t('view.voice.sub') }}</p>
      </div>
      <div class="voice-stats">
        <div>
          <div class="n">{{ voice.speakers.length }}</div>
          <span class="l">{{ t('voice.stats.voices') }}</span>
        </div>
        <div>
          <div class="n"><em>{{ voice.sessionsCount }}</em></div>
          <span class="l">{{ t('voice.stats.sessions') }}</span>
        </div>
      </div>
    </header>

    <!-- 工具条: 搜索 / 清理 / 选择 (无 hint 文字, 顺序自然) -->
    <div class="voice-toolbar">
      <div class="voice-search" :class="{ 'has-val': voice.filter }">
        <svg class="vs-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="M21 21l-4.3-4.3" />
        </svg>
        <input
          ref="searchInput"
          type="text"
          :placeholder="t('voice.search.ph')"
          autocomplete="off"
          spellcheck="false"
          @input="onSearchInput"
          @keydown="onSearchKeydown"
        />
        <button v-show="voice.filter" class="vs-clear" type="button" :aria-label="t('btn.cancel') || '清除'" @click.stop="clearSearch">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
      <button id="btnCleanupNoisy" class="btn ghost" type="button" @click="onCleanup">
        {{ t('view.voice.cleanup') || '清理低质量' }}
      </button>
      <button id="btnSelectMode" class="btn ghost" type="button" @click="toggleMode">
        {{ voice.selectMode ? (t('view.voice.bulkDone') || '完成') : (t('view.voice.select') || '选择') }}
      </button>
      <!-- SPA v3: 注册声纹入口搬到顶栏 (不滚到底也能点) -->
      <span class="bar-sep" aria-hidden="true" />
      <button id="btnEnroll" class="btn primary" type="button" @click="onEnroll" :title="t('voice.enroll.btn')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        <span>{{ t('voice.enroll.btn') || '注册声纹' }}</span>
      </button>
    </div>

    <!-- bulk-bar (选中模式) -->
    <div v-if="voice.selectMode" class="bulk-bar">
      <div class="bulk-left">
        <span class="bulk-count">
          <em>{{ t('view.voice.bulkSelected') || '已选' }}</em>
          <b>{{ voice.selectedCount }}</b>
        </span>
        <button class="bulk-link" type="button" @click="isAllSelected ? voice.selectNone() : voice.selectAll()">
          {{ isAllSelected ? (t('view.voice.bulkNone') || '全不选') : (t('view.voice.bulkAll') || '全选') }}
        </button>
      </div>
      <div class="bulk-right">
        <button class="btn" type="button" :disabled="voice.selectedCount < 2" @click="onBulkMerge">
          {{ t('view.voice.bulkMerge') || '合并' }}
        </button>
        <button class="btn danger" type="button" :disabled="voice.selectedCount === 0" @click="onBulkDelete">
          {{ t('btn.delete') || '删除' }}
        </button>
        <button class="btn ghost" type="button" @click="voice.exitSelectMode()">
          {{ t('btn.cancel') || '取消' }}
        </button>
      </div>
    </div>

    <!-- 列表 -->
    <div class="voice-list">
      <div class="vl-head">
        <div class="vl-spacer" />
        <div>{{ t('voice.col.name') || '名称 / ID' }}</div>
        <div>{{ t('voice.col.talk') || '发言时长' }}</div>
        <div>{{ t('voice.col.samples') || '样本数' }}</div>
        <div>{{ t('voice.col.last') || '最近' }}</div>
        <div style="text-align: right">{{ t('voice.col.action') || '操作' }}</div>
      </div>
      <div v-if="voice.loading && voice.speakers.length === 0" class="vl-empty">
        {{ t('common.loading') || '加载中…' }}
      </div>
      <div v-else-if="voice.filtered.length === 0" class="vl-empty">
        {{ voice.filter
            ? (t('voice.empty.filtered') || `没有匹配 "${voice.filter}" 的声纹`)
            : (t('view.voice.addNew') || '暂无声纹')
        }}
      </div>
      <div
        v-for="sp in voice.filtered"
        :key="sp.id"
        class="vl-row"
        :class="{ selected: voice.selectedIds.has(sp.id) }"
        :data-id="sp.id"
        @click="onRowClick(sp.id)"
      >
        <button
          class="sp-check"
          type="button"
          :aria-label="t('btn.confirm') || '选择'"
          @click.stop="voice.selectMode ? voice.toggleSelect(sp.id) : null"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M5 12l5 5L20 7" />
          </svg>
        </button>
        <div class="vl-name">
          <span class="vl-dot" :style="{ background: spkColor(sp.id) }" />
          <!-- 优化: 只在 name 跟 id 不同时才显示副号 (避免 "Spk_xxx" 重复两行) -->
          <span class="vl-spk-id">{{ sp.name && sp.name !== sp.id ? sp.name : (sp.id.startsWith('Spk_') ? sp.id.replace(/^Spk_/, '') : sp.id) }}</span>
          <span v-if="sp.name && sp.name !== sp.id" class="vl-id-tag">{{ sp.id }}</span>
        </div>
        <div class="vl-talk">{{ fmtMinutes(sp.total_duration ?? (sp.sample_count * 3)) }}<em>m</em></div>
        <div class="vl-samples">{{ sp.sample_count || 0 }}</div>
        <div class="vl-last">{{ fmtRel(sp.last_update || 0) }}</div>
        <div class="vl-actions">
          <button class="menu" type="button" :aria-label="t('voice.menu.label') || '操作'" @click.stop="openPopover(sp.id)">
            <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <circle cx="5" cy="12" r="1.6" />
              <circle cx="12" cy="12" r="1.6" />
              <circle cx="19" cy="12" r="1.6" />
            </svg>
          </button>
          <div v-if="popoverFor === sp.id" class="menu-pop" @click.stop>
            <button type="button" @click="onRename(sp.id)">{{ t('voice.menu.rename') || '重命名' }}</button>
            <button type="button" class="danger" @click="onDelete(sp.id)">{{ t('btn.delete') || '删除' }}</button>
          </div>
        </div>
      </div>
      <div class="vl-new-row" role="button" tabindex="0" @click="onEnroll">
        <div class="vl-new-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </div>
        <div class="vl-new-text">{{ t('voice.enroll.btn') || '注册新声纹' }}</div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.voice-wrap { padding: 32px 48px 48px; }  /* 整改: 删 max-width, 让内容平铺整页 */
.voice-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  margin-bottom: 28px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border);
  gap: 48px;
}
.voice-titles { flex: 0 0 auto; min-width: 0; }
.voice-titles .page-sub { border-bottom: 0; margin-bottom: 0; padding-bottom: 0; }
.voice-stats {
  display: flex;
  gap: 56px;
  flex: 0 0 auto;
}
.voice-stats .n {
  font-family: var(--serif);
  font-variation-settings: 'SOFT' 50, 'WONK' 1, 'opsz' 144;
  font-size: 48px;
  line-height: 1;
  font-weight: 400;
  letter-spacing: -0.03em;
  color: var(--text);
}
.voice-stats .n em { color: var(--teal); font-style: italic; }
.voice-stats .l {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-top: 4px;
  display: block;
}
/* 整改 1: 删除 dead .head-right (旧 10px mono 标签), 改用 .page-title / .page-sub */
.voice-toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.voice-toolbar .bar-sep,
.controls .bar-sep {
  width: 1px;
  height: 22px;
  background: var(--border);
  margin: 0 4px;
}
.voice-search { position: relative; flex: 1; min-width: 220px; max-width: 380px; }
.voice-search input {
  width: 100%;
  height: 36px;
  padding: 0 12px 0 36px;
  background: var(--ink-2);
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  color: var(--text);
  font-family: 'Outfit', sans-serif;
  font-size: 12px;
  letter-spacing: 0.02em;
  transition: border-color 0.15s, background 0.15s;
}
.voice-search input:focus {
  border-color: var(--amber);
  background: var(--ink-3);
  outline: none;
  box-shadow: 0 0 0 3px var(--amber-soft);
}
.voice-search input::placeholder { color: var(--text-3); }
.voice-search .vs-icon {
  position: absolute;
  left: 11px;
  top: 50%;
  transform: translateY(-50%);
  width: 14px;
  height: 14px;
  color: var(--text-3);
  pointer-events: none;
}
.voice-search .vs-clear {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: none;
  place-items: center;
  color: var(--text-3);
  cursor: pointer;
  background: transparent;
  border: none;
}
.voice-search .vs-clear svg { width: 10px; height: 10px; }
.voice-search .vs-clear:hover { color: var(--text); background: var(--ink-4); }
.voice-search.has-val .vs-clear { display: grid; }

.bulk-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  margin-bottom: 16px;
  background: var(--ink-2);
  border: 1px solid var(--amber);
  border-radius: 6px;
}
.bulk-left, .bulk-right { display: flex; align-items: center; gap: 14px; }
.bulk-count { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-2); }
.bulk-count em { color: var(--text-3); margin-right: 6px; text-transform: uppercase; letter-spacing: 0.08em; }
.bulk-count b { color: var(--amber); font-size: 14px; font-weight: 500; }
.bulk-link {
  background: transparent;
  border: none;
  color: var(--teal);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  cursor: pointer;
  letter-spacing: 0.04em;
}
.bulk-link:hover { text-decoration: underline; }

.voice-list { background: var(--ink-2); border: 1px solid var(--border-soft); border-radius: 6px; overflow: hidden; }
.vl-head, .vl-row {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 130px 90px 110px 60px;
  gap: 14px;
  align-items: center;
  padding: 10px 18px;
}
.vl-head {
  background: var(--ink-3);
  border-bottom: 1px solid var(--border-soft);
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-3);
}
.vl-head .vl-spacer { width: 22px; height: 22px; }
.vl-row {
  border-bottom: 1px solid var(--border-soft);
  transition: background 0.12s;
  position: relative;
}
.vl-row:last-child { border-bottom: none; }
.vl-row:hover { background: var(--ink-3); }
.vl-row.selected { background: var(--ink-3); }
.vl-empty {
  padding: 48px 24px;
  text-align: center;
  color: var(--text-3);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
}

.sp-check {
  width: 18px;
  height: 18px;
  border-radius: 4px;
  border: 1.5px solid var(--text-3);
  display: grid;
  place-items: center;
  color: transparent;
  background: transparent;
  transition: border-color 0.15s, background 0.15s, color 0.15s, transform 0.15s;
  cursor: pointer;
  flex-shrink: 0;
  opacity: 0;
  pointer-events: none;
}
.sp-check svg { width: 11px; height: 11px; }
:global(.select-mode) .sp-check,
.vl-row.select-mode .sp-check { opacity: 1; pointer-events: auto; }
.vl-row.selected .sp-check { background: var(--amber); border-color: var(--amber); color: var(--ink); }

.vl-name { display: flex; align-items: center; gap: 10px; min-width: 0; }
.vl-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.vl-spk-id { font-family: 'Outfit', sans-serif; font-weight: 500; color: var(--text); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.vl-id-tag { font-family: 'JetBrains Mono', monospace; font-size: 10px; color: var(--text-3); letter-spacing: 0.04em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
.vl-talk { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text); font-weight: 500; }
.vl-talk em { color: var(--amber); font-style: normal; font-size: 10px; margin-left: 2px; }
.vl-samples, .vl-last { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-2); }

.vl-actions { display: flex; justify-content: flex-end; align-items: center; gap: 4px; position: relative; }
.menu {
  width: 26px;
  height: 26px;
  border-radius: 4px;
  display: grid;
  place-items: center;
  color: var(--text-3);
  cursor: pointer;
  background: transparent;
  border: none;
  transition: color 0.12s, background 0.12s;
}
.menu:hover { color: var(--text); background: var(--ink-4); }
.menu svg { width: 14px; height: 14px; }
.menu-pop {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  background: var(--ink-2);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  z-index: 30;
  min-width: 120px;
  padding: 4px;
}
.menu-pop button {
  display: block;
  width: 100%;
  text-align: left;
  padding: 7px 10px;
  background: transparent;
  border: none;
  color: var(--text);
  font-family: 'Outfit', sans-serif;
  font-size: 12px;
  border-radius: 4px;
  cursor: pointer;
}
.menu-pop button:hover { background: var(--ink-3); }
.menu-pop button.danger { color: var(--red); }
.menu-pop button.danger:hover { background: rgba(255, 71, 87, 0.12); }

/* 注册声纹入口:
 *   桌面端: 隐藏 (顶部工具栏 btnEnroll 是主入口)
 *   移动端 (≤768px): 改右下角浮动按钮 (FAB), 避免顶部工具栏按钮挤在小屏 tab bar 上方
 */
.vl-new-row {
  display: none;  /* 桌面端隐藏 — 顶栏 btnEnroll 已够用 */
}
.vl-new-icon {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: grid;
  place-items: center;
}
.vl-new-icon svg { width: 12px; height: 12px; }
.vl-new-text { font-family: 'Outfit', sans-serif; letter-spacing: 0.02em; }

/* 移动端 (≤768px) FAB 样式 — 仿 .rec-fab 的位置范式 */
@media (max-width:768px){
  /* 顶部 #btnEnroll 隐藏 — 移动端右下角 FAB 是主入口,避免重复 */
  #btnEnroll { display: none !important; }
  .vl-new-row {
    display: inline-flex;            /* 覆盖 desktop 的 none */
    align-items: center;
    gap: 8px;
    position: fixed;
    right: 16px;
    bottom: 72px;                    /* 56px 底部 nav + 16px gap */
    height: 48px;
    padding: 0 18px 0 14px;
    border-radius: 24px;             /* 胶囊形 */
    background: var(--amber);
    color: var(--ink);
    box-shadow: 0 6px 16px rgba(255,107,53,.35), 0 2px 4px rgba(0,0,0,.4);
    z-index: 40;                     /* nav z-index=50, FAB 低于 nav 但高于内容 */
    cursor: pointer;
    transition: transform .12s, box-shadow .12s;
  }
  .vl-new-row:hover {
    transform: translateY(-1px);
    box-shadow: 0 8px 20px rgba(255,107,53,.45), 0 3px 6px rgba(0,0,0,.45);
    background: var(--amber);        /* 桌面 hover 改背景色, FAB 保持主色 */
  }
  .vl-new-row:active { transform: translateY(0); }
  .vl-new-icon {
    width: 24px;
    height: 24px;
    background: rgba(10,9,8,.15);
  }
  .vl-new-icon svg { width: 14px; height: 14px; stroke-width: 2.4; }
  .vl-new-text { font-size: 13px; color: var(--ink); font-weight: 500; }
}

/* 极窄屏 (≤480px) 进一步压缩 */
@media (max-width:480px){
  .vl-new-row {
    right: 12px;
    bottom: 68px;                    /* 56px nav + 12px gap */
    height: 44px;
    padding: 0 14px 0 12px;
    gap: 6px;
    font-size: 11px;
  }
  .vl-new-icon { width: 20px; height: 20px; }
  .vl-new-icon svg { width: 12px; height: 12px; }
  .vl-new-text { font-size: 12px; }
}
</style>
