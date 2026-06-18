<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLiveStore } from '../stores/live'
import { useDialog } from '../composables/useDialog'
import { useRouter } from 'vue-router'
import { spkColor } from '../utils/spk'
import { fmtClock, fmtRel } from '../utils/format'
import { uploadAudio } from '../api/speakers'
type UploadResp = Awaited<ReturnType<typeof uploadAudio>>

const { t } = useI18n()
const live = useLiveStore()
const dialog = useDialog()
const router = useRouter()

const waveCanvas = ref<HTMLCanvasElement | null>(null)
const dropActive = ref(false)

let dragCounter = 0

function fmtTime(sec: number) {
  return fmtClock(sec)
}

function drawWave() {
  const c = waveCanvas.value
  if (!c) return
  const dpr = window.devicePixelRatio || 1
  const w = c.clientWidth
  const h = c.clientHeight
  if (c.width !== w * dpr || c.height !== h * dpr) {
    c.width = w * dpr
    c.height = h * dpr
  }
  const ctx = c.getContext('2d')!
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)
  if (!live.rec) return
  const hist = live.waveHist
  const n = hist.length
  const barW = w / n
  ctx.shadowColor = 'rgba(255, 107, 53, 0.6)'
  ctx.shadowBlur = 4
  ctx.fillStyle = 'var(--amber)'
  for (let i = 0; i < n; i++) {
    const v = Math.min(h * 0.95, hist[i] * h * 0.8)
    const x = i * barW
    const y = h / 2 - v / 2
    ctx.fillRect(x, y, Math.max(1, barW - 1), v)
  }
  ctx.shadowBlur = 0
}

async function toggleRec() {
  if (live.rec) {
    live.stopRec()
  } else {
    await live.startRec()
  }
}

async function rename() {
  const newName = await dialog.showPrompt({
    title: t('view.live.renamePrompt') || '会话名称',
    initialValue: live.sessionTitle || '',
    placeholder: t('view.live.defaultSession', live.clientId) || live.clientId,
  })
  if (newName) live.rename(newName)
}

async function clearTranscript() {
  const ok = await dialog.showConfirm({
    title: t('live.clear.confirm') || '清空当前转写视图?',
    detail: t('live.clear.confirmDetail') || '（服务器端会话不受影响）',
    confirmText: t('btn.confirm') || '确认',
    cancelText: t('btn.cancel') || '取消',
  })
  if (ok) live.clearTranscript()
}

async function onFile(file: File) {
  if (!file) return
  try {
    window.toast?.(t('upload.processing') || '处理中…', 'info')
    const r: UploadResp = await uploadAudio(file, { enable_diarization: true })
    window.toast?.(t('upload.done') || '上传完成', 'ok')
    if (r.session_id) {
      router.push({ path: '/library', query: { open: r.session_id } })
    }
  } catch (e) {
    window.toast?.(`${t('upload.error')}: ${e instanceof Error ? e.message : e}`, 'error')
  }
}

function onDragEnter(e: DragEvent) {
  e.preventDefault()
  dragCounter++
  if (e.dataTransfer?.types.includes('Files')) dropActive.value = true
}
function onDragLeave() {
  dragCounter--
  if (dragCounter <= 0) { dropActive.value = false; dragCounter = 0 }
}
function onDragOver(e: DragEvent) { e.preventDefault() }
function onDrop(e: DragEvent) {
  e.preventDefault()
  dropActive.value = false
  dragCounter = 0
  const file = e.dataTransfer?.files?.[0]
  if (file) onFile(file)
}

function onPickFile() {
  const inp = document.createElement('input')
  inp.type = 'file'
  inp.accept = 'audio/wav,audio/mpeg,audio/mp4,audio/flac,.wav,.mp3,.m4a,.flac'
  inp.onchange = () => { if (inp.files?.[0]) onFile(inp.files[0]) }
  inp.click()
}

let rafId: number | null = null
function tick() {
  drawWave()
  rafId = requestAnimationFrame(tick)
}

onMounted(() => {
  rafId = requestAnimationFrame(tick)
  document.addEventListener('dragenter', onDragEnter)
  document.addEventListener('dragleave', onDragLeave)
  document.addEventListener('dragover', onDragOver)
  document.addEventListener('drop', onDrop)
  // 加载 recent
  // (简化: 留给 library view 加载)
})
onBeforeUnmount(() => {
  if (rafId !== null) cancelAnimationFrame(rafId)
  document.removeEventListener('dragenter', onDragEnter)
  document.removeEventListener('dragleave', onDragLeave)
  document.removeEventListener('dragover', onDragOver)
  document.removeEventListener('drop', onDrop)
  live.stopRec()
})

async function loadRecent() {
  // 简化: 复用 listHistory 拉最近 5 条
  try {
    const { listHistory } = await import('../api/history')
    const r = await listHistory({ page: 1, page_size: 5 })
    live.recent = r.items
  } catch { /* noop */ }
}
onMounted(loadRecent)
</script>

<template>
  <section class="live-wrap">
    <div class="live-grid">
      <div class="live-main">
        <h1 class="page-title" v-html="t('view.live.title')" />
        <div class="live-meta">
          <span><span>{{ t('view.live.meta.room') }}</span> <b>A</b></span>
          <template v-if="live.rec">
            <span class="sep">·</span>
            <span><span>{{ t('view.live.meta.started') }}</span> <b>{{ fmtTime(live.recTimer) }}</b></span>
          </template>
          <span class="sep">·</span>
          <span><span>{{ t('view.live.meta.asr') }}</span> <b>Qwen3-ASR</b></span>
          <span class="sep">·</span>
          <span><span>{{ t('view.live.meta.speaker') }}</span> <b>—</b></span>
        </div>
        <div class="wave-wrap" :class="{ 'drop-active': dropActive }">
          <canvas ref="waveCanvas" />
          <div v-if="!live.rec" class="placeholder">
            <b>◌</b><span>{{ t('view.live.wavePH') }}</span>
          </div>
        </div>
        <div class="controls">
          <button
            class="rec-btn"
            :class="{ live: live.rec }"
            type="button"
            :title="t('view.live.recBtn')"
            @click="toggleRec"
          >
            <span class="core" />
          </button>
          <div class="status-line">
            <span class="dot" :class="{ live: live.rec }" />
            <span>{{ live.rec ? (t('view.live.status.recording') || '录制中') : (t('view.live.status.ready') || 'Ready') }}</span>
            <span style="margin-left: 14px" v-if="live.rec">{{ fmtTime(live.recTimer) }}</span>
            <span style="margin-left: 14px" v-else-if="live.wsState === 'reconnecting'">{{ t('live.reconnecting') || 'reconnecting…' }}</span>
          </div>
          <div style="margin-left: auto; display: flex; gap: 6px; align-items: center">
            <button v-if="live.rec" class="btn ghost" type="button" :title="t('view.live.renameBtn.title')" @click="rename">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" /></svg>
              <span>{{ t('view.live.renameBtn') || '命名' }}</span>
            </button>
            <button v-if="live.rec || live.segments.length > 0" class="btn ghost" type="button" :title="t('view.live.clearBtn.title')" @click="clearTranscript">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
              <span>{{ t('view.live.clearBtn') || '清空' }}</span>
            </button>
            <!-- SPA v3: 删除 LiveView 顶栏的 "注册声纹" 按钮 (注册声纹是声纹库操作, 不该在实时页) -->
          </div>
        </div>
        <div class="h-mono" style="margin-bottom: 14px">
          <span>{{ t('view.live.transcript.label') }}</span>
          <span class="amber" style="text-transform: none; letter-spacing: 0; margin-left: 8px">
            {{ live.segCount }} {{ t('view.live.transcript.seg') || '段' }} · {{ live.spkCount }} {{ t('view.live.transcript.spk') || '人' }}
          </span>
        </div>
        <div class="transcript">
          <div v-if="live.segments.length === 0" class="empty empty-rich">
            <em>{{ t('view.live.empty.pre') }}</em>
            <span>{{ t('view.live.empty.post') }}</span>
            <div class="empty-tips">
              <div class="tip">
                <span class="tip-icon">🎙</span>
                <div>
                  <b>{{ t('view.live.tip1Title') || '实时麦克风' }}</b>
                  <small>{{ t('view.live.tip1Body') || '点击琥珀色按钮开始录音, 系统自动转写并识别说话人' }}</small>
                </div>
              </div>
              <div class="tip">
                <span class="tip-icon">📁</span>
                <div>
                  <b>{{ t('view.live.tip2Title') || '上传音频' }}</b>
                  <small>{{ t('view.live.tip2Body') || '拖入或点击右侧 "快速导入" 区, 支持 WAV/MP3 等格式' }}</small>
                </div>
              </div>
              <div class="tip">
                <span class="tip-icon">✎</span>
                <div>
                  <b>{{ t('view.live.tip3Title') || '命名会话' }}</b>
                  <small>{{ t('view.live.tip3Body') || '点击右上 "命名" 按钮给当前会话起名, 便于历史会话查找' }}</small>
                </div>
              </div>
            </div>
          </div>
          <div v-for="seg in live.segments" :key="seg.id" class="seg" :class="`seg-${seg.status ?? 'normal'}`">
            <template v-if="seg.status === 'transcribing'">
              <span class="spk placeholder">·</span>
              <span class="text placeholder-text">
                <span class="placeholder-dot"></span>
                {{ seg.displayed }}
              </span>
              <span class="time">{{ seg.time }}</span>
            </template>
            <template v-else-if="seg.status === 'stale' || seg.status === 'timeout'">
              <span class="spk collapsed">·</span>
              <span class="text collapsed-text">…</span>
              <span class="time">{{ seg.time }}</span>
            </template>
            <template v-else>
              <span class="spk" :style="{ color: spkColor(seg.speaker) }">{{ live.getDisplayName(seg) }}</span>
              <span class="text">{{ seg.displayed }}<span v-if="seg.typewriterId" class="cursor">▍</span></span>
              <span class="time">{{ seg.time }}</span>
            </template>
          </div>
        </div>
        <div class="dropzone" @click="onPickFile">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" />
          </svg>
          <b>{{ t('view.live.dropzone.title') }}</b>
          <small>{{ t('view.live.dropzone.hint') }}</small>
        </div>
      </div>
      <aside class="live-side">
        <div class="side-block">
          <div class="h-mono">
            <span>{{ t('view.live.recent') }}</span>
            <span class="act" @click="router.push('/library')">{{ t('view.live.seeAll') }}</span>
          </div>
          <div class="recent">
            <div v-if="live.recent.length === 0" class="empty">{{ t('view.live.recentEmpty') }}</div>
            <div v-for="it in live.recent" :key="it.id" class="rec-row" @click="router.push({ path: '/library', query: { open: it.id } })">
              <div class="rec-title">{{ it.title || it.original_filename || (t('library.untitled') || '未命名') }}</div>
              <div class="rec-meta">
                <span class="src-tag" :class="it.source">{{ it.source === 'websocket' ? (t('view.library.source.live') || 'Live') : (t('view.library.source.upload') || 'Upload') }}</span>
                · {{ fmtTime(it.duration_sec || 0) }} · {{ live.spkCount || 0 }} {{ t('voice.card.samples') || 'voices' }} · {{ fmtRel(it.created_at) }}
              </div>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.live-wrap { padding: 32px 48px 48px; }  /* 整改: 删 max-width, 让内容平铺整页 */
.live-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 48px; align-items: stretch; min-height: calc(100vh - 88px); }
.live-main { min-width: 0; display: flex; flex-direction: column; }
.live-main > .transcript { flex: 1; min-height: 200px; }
/* 整改 1: 改用 .page-title (components.css) 工具类; 保留 min-width 防止 reflow */
.page-title { min-width: 420px; display: inline-block; }
.live-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
  align-items: center;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-2);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--border-soft);
  margin-bottom: 24px;
}
.live-meta b { color: var(--text); font-weight: 500; }
.live-meta .sep { color: var(--text-3); }
.wave-wrap {
  position: relative;
  height: 96px;
  background: var(--ink-2);
  border: 1px solid var(--border-soft);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 6px;
  transition: border-color 0.15s, background 0.15s;
}
.wave-wrap.drop-active { border-color: var(--amber); background: var(--amber-soft); }
.wave-wrap canvas { width: 100%; height: 100%; display: block; }
.wave-wrap .placeholder {
  position: absolute; inset: 0;
  display: grid; place-items: center;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.18em;
  text-transform: uppercase;
  pointer-events: none;
  gap: 8px;
}
.wave-wrap .placeholder b { color: var(--text-2); animation: blink 1.4s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }
.controls {
  display: flex;
  align-items: center;
  gap: 14px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--border-soft);
  margin-bottom: 28px;
}
.rec-btn {
  width: 54px; height: 54px;
  border-radius: 50%;
  background: var(--ink-3);
  border: 2px solid var(--ink-4);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
  flex-shrink: 0;
}
.rec-btn .core { width: 18px; height: 18px; border-radius: 50%; background: var(--text-3); transition: all 0.2s; }
.rec-btn:hover { border-color: var(--amber); }
.rec-btn.live { border-color: var(--amber); background: var(--amber-soft); }
.rec-btn.live .core { background: var(--amber); border-radius: 4px; transform: scale(0.7); }
.status-line { display: flex; align-items: center; gap: 8px; font-family: var(--mono); font-size: 12px; color: var(--text-2); }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-3); }
.dot.live { background: var(--green); box-shadow: 0 0 0 3px rgba(107, 203, 119, 0.18); animation: pulse 2s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.transcript {
  min-height: 200px;
  font-family: var(--serif);
  font-size: 15px;
  line-height: 1.7;
  color: var(--text);
}
.transcript .empty {
  padding: 40px 24px 24px;
  text-align: center;
  color: var(--text-3);
}
.transcript .empty.empty-rich { text-align: left; padding: 24px 0 0; }
.transcript .empty.empty-rich em { display: inline-block; margin-bottom: 16px; text-align: center; width: 100%; }
.transcript .empty.empty-rich > span { display: block; text-align: center; margin-bottom: 24px; }
.empty-tips {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-top: 16px;
}
.empty-tips .tip {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 14px 16px;
  background: var(--ink-2);
  border: 1px solid var(--border-soft);
  border-radius: 8px;
}
.tip-icon { font-size: 22px; flex-shrink: 0; }
.empty-tips .tip b { display: block; font-family: 'Outfit', sans-serif; font-size: 13px; color: var(--text); margin-bottom: 4px; }
.empty-tips .tip small { display: block; font-family: var(--mono); font-size: 11px; color: var(--text-3); line-height: 1.5; }
.transcript .empty em {
  display: block;
  font-style: italic;
  font-family: var(--serif);
  font-size: 18px;
  color: var(--text-2);
  margin-bottom: 6px;
}
.seg {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
  font-family: 'Outfit', sans-serif;
}
.seg .spk {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 500;
  flex-shrink: 0;
}
.seg .text { flex: 1; }
.seg .time {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
}
/* Task 4: VAD 转写中占位符 + 折叠 stale/timeout */
.seg-transcribing .placeholder-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--amber, #f59e0b);
  margin-right: 8px;
  animation: placeholder-pulse 1s infinite ease-in-out;
}
.seg-transcribing .placeholder-text {
  color: var(--muted, #888);
  font-style: italic;
}
@keyframes placeholder-pulse {
  0%, 100% { opacity: 0.3; transform: scale(0.8); }
  50% { opacity: 1; transform: scale(1.2); }
}
.seg-stale .collapsed-text,
.seg-timeout .collapsed-text {
  color: var(--muted, #aaa);
  opacity: 0.4;
  font-style: italic;
}
.seg-stale .spk.collapsed,
.seg-timeout .spk.collapsed {
  color: var(--muted, #aaa);
  opacity: 0.4;
}

.live-side { display: flex; flex-direction: column; gap: 24px; }
.side-block { }
.side-block .h-mono { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
.side-block .h-mono .act { color: var(--amber); font-family: var(--mono); font-size: 10px; cursor: pointer; }
.side-block .h-mono .act:hover { text-decoration: underline; }
/* 主区底部的满宽 dashed 导入区 (整改 2: 从右侧侧栏迁来, 升级为 full-width) */
.dropzone {
  background: var(--ink-2);
  border: 1.5px dashed var(--border);
  border-radius: 8px;
  padding: 40px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  margin-top: 32px;
  transition: border-color 0.15s, background 0.15s;
}
.dropzone:hover { border-color: var(--amber); background: var(--amber-soft); }
.dropzone svg { width: 32px; height: 32px; color: var(--text-3); }
.dropzone b { font-family: var(--serif); font-size: 16px; color: var(--text); }
.dropzone small { font-family: var(--mono); font-size: 11px; color: var(--text-3); letter-spacing: 0.08em; }
.recent { display: flex; flex-direction: column; gap: 0; }
.recent .empty { padding: 24px 12px; text-align: center; color: var(--text-3); font-family: var(--mono); font-size: 11px; }
.rec-row {
  padding: 10px 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.12s;
}
.rec-row:hover { background: var(--ink-2); }
.rec-title {
  font-family: 'Outfit', sans-serif;
  font-size: 13px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-bottom: 3px;
}
.rec-meta {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.04em;
}
.src-tag {
  padding: 1px 5px;
  border-radius: 2px;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
}
.src-tag.websocket { color: var(--amber); background: var(--amber-soft); }
.src-tag.upload { color: var(--teal); background: var(--teal-soft); }
</style>
