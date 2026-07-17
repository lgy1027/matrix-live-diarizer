<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { uploadMeeting } from '../api/product'

const router = useRouter()
const { t } = useI18n()
const file = ref<File | null>(null)
const input = ref<HTMLInputElement | null>(null)
const mode = ref<'quick' | 'meeting'>('meeting')
const busy = ref(false)
const progress = ref(0)
const error = ref('')
const dragging = ref(false)

function choose(next?: File | null) {
  if (!next) return
  file.value = next
  error.value = ''
}

async function submit() {
  if (!file.value || busy.value) return
  busy.value = true
  progress.value = 0
  error.value = ''
  try {
    await uploadMeeting(file.value, mode.value, value => { progress.value = value })
    await router.push({ name: 'meetings', query: { processing: '1' } })
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="product-page home">
    <header class="hero">
      <div class="eyebrow">{{ t('product.home.eyebrow') }}</div>
      <h1>{{ t('product.home.title') }}</h1>
      <p>{{ t('product.home.lead') }}</p>
    </header>

    <div class="entry-grid">
      <section class="entry upload-entry" :class="{ dragging, chosen: file }">
        <div class="entry-index">01 / FILE</div>
        <button
          class="file-target"
          type="button"
          @click="input?.click()"
          @dragenter.prevent="dragging = true"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="dragging = false; choose($event.dataTransfer?.files?.[0])"
        >
          <span class="entry-icon">↥</span>
          <b>{{ file?.name || t('product.home.chooseFile') }}</b>
          <small>{{ file ? t('product.home.replaceFile') : t('product.home.fileHint') }}</small>
        </button>
        <input ref="input" class="sr-only" type="file" accept="audio/*,.mp4,.m4a,.wav,.mp3,.flac,.ogg" @change="choose(($event.target as HTMLInputElement).files?.[0])">

        <div v-if="file" class="upload-options">
          <label :class="{ active: mode === 'meeting' }">
            <input v-model="mode" value="meeting" type="radio">
            <span><b>{{ t('product.home.meetingMode') }}</b><small>{{ t('product.home.meetingModeHint') }}</small></span>
          </label>
          <label :class="{ active: mode === 'quick' }">
            <input v-model="mode" value="quick" type="radio">
            <span><b>{{ t('product.home.quickMode') }}</b><small>{{ t('product.home.quickModeHint') }}</small></span>
          </label>
          <button class="primary-action" type="button" :disabled="busy" @click="submit">
            {{ busy ? t('product.home.uploading', { progress }) : t('product.home.start') }}
          </button>
          <div v-if="busy" class="progress" aria-hidden="true"><i :style="{ width: `${progress}%` }" /></div>
        </div>
      </section>

      <button class="entry live-entry" type="button" @click="router.push({ name: 'live' })">
        <span class="entry-index">02 / LIVE</span>
        <span class="live-mark"><i /></span>
        <span class="entry-copy"><b>{{ t('product.home.live') }}</b><small>{{ t('product.home.liveHint') }}</small></span>
        <span class="arrow">→</span>
      </button>
    </div>

    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <footer><span>LOCAL-FIRST</span>{{ t('product.home.tip') }}</footer>
  </section>
</template>

<style scoped>
.home{max-width:1180px;padding-top:clamp(44px,8vh,96px)}.hero{max-width:880px}.hero h1{font:500 clamp(42px,6vw,78px)/1.02 var(--serif);letter-spacing:-.035em;margin:18px 0 22px}.hero p{font-size:17px;color:var(--text-2);max-width:680px;line-height:1.7}.entry-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:16px;margin-top:48px}.entry{position:relative;min-height:260px;border:1px solid var(--border);background:var(--ink-2);border-radius:14px;overflow:hidden}.entry-index{position:absolute;top:20px;left:22px;color:var(--text-3);font:10px var(--mono);letter-spacing:.12em}.file-target{width:100%;min-height:258px;padding:58px 26px 28px;display:flex;flex-direction:column;align-items:flex-start;justify-content:flex-end;text-align:left}.entry-icon{margin-bottom:auto;color:var(--amber);font:36px/1 var(--mono)}.entry b{font-size:20px;max-width:100%;overflow-wrap:anywhere}.entry small{display:block;color:var(--text-3);margin-top:7px}.upload-entry{transition:border-color .2s,background .2s}.upload-entry:hover,.upload-entry.dragging{border-color:var(--amber);background:linear-gradient(145deg,var(--ink-2),var(--amber-soft))}.upload-entry.chosen{min-height:360px}.upload-options{padding:0 22px 22px;display:grid;grid-template-columns:1fr 1fr auto;gap:10px}.upload-options label{display:flex;gap:9px;padding:12px;border:1px solid var(--border);border-radius:8px;cursor:pointer}.upload-options label.active{border-color:rgba(255,107,53,.6);background:var(--amber-soft)}.upload-options label input{accent-color:var(--amber);margin-top:3px}.upload-options label span{min-width:0}.upload-options label b{font-size:13px}.upload-options label small{font-size:11px;line-height:1.35}.progress{grid-column:1/-1;height:3px;background:var(--ink-4);border-radius:3px;overflow:hidden}.progress i{display:block;height:100%;background:var(--amber)}.live-entry{display:flex;flex-direction:column;align-items:flex-start;padding:58px 26px 28px;text-align:left;transition:border-color .2s,transform .2s}.live-entry:hover{border-color:var(--amber);transform:translateY(-2px)}.live-mark{width:62px;height:62px;border:1px solid rgba(255,107,53,.45);border-radius:50%;display:grid;place-items:center;margin-bottom:auto;box-shadow:0 0 0 12px rgba(255,107,53,.05)}.live-mark i{width:18px;height:18px;border-radius:50%;background:var(--amber);box-shadow:0 0 20px rgba(255,107,53,.75)}.entry-copy{display:block}.arrow{position:absolute;right:24px;bottom:30px;color:var(--amber);font-size:24px}.error{color:var(--red);margin-top:14px}footer{display:flex;gap:14px;margin-top:30px;color:var(--text-3);font:10px/1.6 var(--mono)}footer span{color:var(--teal)}.sr-only{position:absolute;width:1px;height:1px;clip:rect(0,0,0,0);overflow:hidden}.primary-action:disabled{opacity:.55;cursor:wait}@media(max-width:800px){.entry-grid{grid-template-columns:1fr}.entry{min-height:220px}.file-target{min-height:220px}.upload-options{grid-template-columns:1fr}.progress{grid-column:1}.live-entry{min-height:220px}.hero h1{font-size:44px}footer{flex-direction:column;gap:4px}}
</style>
