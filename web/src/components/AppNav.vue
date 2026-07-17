<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const items = [
  { name: 'home', icon: 'home', labelKey: 'product.nav.home' },
  { name: 'meetings', icon: 'lib', labelKey: 'product.nav.meetings' },
  { name: 'people', icon: 'voice', labelKey: 'product.nav.people' },
] as const
const activeName = computed(() => route.name === 'meeting-detail' ? 'meetings' : route.name)

function go(name: string) {
  if (route.name !== name) router.push({ name })
}
</script>

<template>
  <aside class="nav">
    <div class="brand" title="Matrix">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3v18M5.6 5.6l12.8 12.8M18.4 5.6L5.6 18.4" />
      </svg>
    </div>
    <button
      v-for="it in items"
      :key="it.name"
      class="nav-item"
      :class="{ active: activeName === it.name }"
      :data-view="it.name"
      :title="t(it.labelKey)"
      :aria-label="t(it.labelKey)"
      @click="go(it.name)"
    >
      <svg v-if="it.icon === 'home'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M3 11 12 3l9 8v9a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z" />
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
      :title="t('product.nav.settings')"
      :aria-label="t('product.nav.settings')"
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

@media (max-width: 700px) {
  .nav {
    position: fixed;
    inset: auto 0 0;
    height: 58px;
    flex-direction: row;
    align-items: stretch;
    padding: 0;
    gap: 0;
    border-right: 0;
    border-top: 1px solid var(--border-soft);
    z-index: 50;
  }
  .brand,
  .spacer { display: none; }
  .nav-item {
    width: auto;
    height: auto;
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;
    border-radius: 0;
    font-size: 9px;
  }
  .nav-item::after {
    content: attr(aria-label);
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .nav-item.active::before {
    left: 50%;
    top: 0;
    width: 24px;
    height: 2px;
    transform: translateX(-50%);
    border-radius: 0 0 2px 2px;
  }
}
</style>
