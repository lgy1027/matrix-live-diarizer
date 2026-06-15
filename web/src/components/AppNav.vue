<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { computed } from 'vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

const items = [
  { name: 'live', icon: 'mic', label: t('nav.live') },
  { name: 'library', icon: 'lib', label: t('nav.library') },
  { name: 'voice', icon: 'voice', label: t('nav.voice') },
] as const

function go(name: string) {
  if (route.name !== name) router.push({ name })
}
</script>

<template>
  <aside class="nav">
    <div class="brand" :title="t('app.name')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3v18M5.6 5.6l12.8 12.8M18.4 5.6L5.6 18.4" />
      </svg>
    </div>
    <button
      v-for="it in items"
      :key="it.name"
      class="nav-item"
      :class="{ active: route.name === it.name }"
      :data-view="it.name"
      :title="it.label"
      :aria-label="it.label"
      @click="go(it.name)"
    >
      <svg v-if="it.icon === 'mic'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3" />
      </svg>
      <svg v-else-if="it.icon === 'lib'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
        <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
      </svg>
      <svg v-else-if="it.icon === 'voice'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
        <circle cx="9" cy="7" r="4" />
        <path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
      </svg>
    </button>
    <div class="spacer" />
    <button
      class="nav-item"
      :class="{ active: route.name === 'settings' }"
      data-view="settings"
      :title="t('nav.settings')"
      :aria-label="t('nav.settings')"
      @click="go('settings')"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
      </svg>
    </button>
  </aside>
</template>

<style scoped>
.nav {
  background: var(--ink-2);
  border-right: 1px solid var(--border-soft);
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px 0 16px;
  gap: 4px;
  z-index: 10;
}
.brand {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  margin-bottom: 24px;
  color: var(--amber);
}
.brand svg { width: 100%; height: 100%; }
.nav-item {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: 8px;
  color: var(--text-3);
  position: relative;
  transition: color 0.15s, background 0.15s;
  background: transparent;
  border: none;
  cursor: pointer;
}
.nav-item:hover { color: var(--text); background: var(--ink-3); }
.nav-item.active { color: var(--amber); }
.nav-item.active::before {
  content: '';
  position: absolute;
  left: -1px;
  top: 50%;
  transform: translateY(-50%);
  width: 2px;
  height: 18px;
  background: var(--amber);
  border-radius: 0 2px 2px 0;
}
.nav-item svg { width: 18px; height: 18px; }
.spacer { flex: 1; }
</style>
