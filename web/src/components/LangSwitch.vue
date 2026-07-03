<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { setLocale } from '../i18n'

const { locale } = useI18n()
const open = ref(false)
const trigger = ref<HTMLButtonElement | null>(null)
const dropdown = ref<HTMLDivElement | null>(null)

const currentLabel = computed(() => (locale.value === 'en' ? 'EN' : '中'))

function pick(lang: 'zh' | 'en') {
  if (lang === locale.value) {
    open.value = false
    return
  }
  setLocale(lang)
  open.value = false
}

function toggle(e: Event) {
  e.stopPropagation()
  open.value = !open.value
}

onMounted(() => {
  document.addEventListener('click', () => (open.value = false))
})
</script>

<template>
  <div class="lang-switch">
    <button
      ref="trigger"
      class="ls-trigger"
      type="button"
      :aria-label="'Language'"
      :title="'Language'"
      @click="toggle"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
      </svg>
      <span class="ls-label">{{ currentLabel }}</span>
      <span class="ls-caret">▾</span>
    </button>
    <div ref="dropdown" class="ls-dropdown" :hidden="!open">
      <button class="ls-item" :class="{ active: locale === 'zh' }" type="button" @click="pick('zh')">
        <span class="ls-dot" />中文
      </button>
      <button class="ls-item" :class="{ active: locale === 'en' }" type="button" @click="pick('en')">
        <span class="ls-dot" />English
      </button>
    </div>
  </div>
</template>

<style scoped>
.lang-switch { position: relative; display: inline-block; }
.ls-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 10px 0 11px;
  background: rgba(20, 17, 15, 0.6);
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  color: var(--text-2);
  cursor: pointer;
  font-family: 'Outfit', sans-serif;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.04em;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
}
.ls-trigger:hover {
  background: var(--ink-3);
  border-color: var(--border);
  color: var(--text);
}
.ls-trigger svg { width: 14px; height: 14px; flex-shrink: 0; }
.ls-label { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text); }
.ls-caret { color: var(--text-3); font-size: 9px; margin-top: -1px; }
.ls-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  min-width: 160px;
  background: var(--ink-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5);
  padding: 6px;
  z-index: 60;
  animation: lsIn 0.15s ease;
}
@keyframes lsIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
.ls-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  padding: 9px 12px;
  background: transparent;
  border: none;
  border-radius: 5px;
  color: var(--text);
  font-family: 'Outfit', sans-serif;
  font-size: 12px;
  cursor: pointer;
  text-align: left;
  transition: background 0.12s;
}
.ls-item:hover { background: var(--ink-3); }
.ls-item.active { color: var(--amber); }
.ls-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
  flex-shrink: 0;
}
.ls-item.active .ls-dot {
  background: var(--amber);
  box-shadow: 0 0 0 2px var(--amber-soft);
}
</style>
