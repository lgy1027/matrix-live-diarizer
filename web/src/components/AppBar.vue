<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useLiveStore } from '../stores/live'
import LangSwitch from './LangSwitch.vue'
import UserMenu from './UserMenu.vue'

const route = useRoute()
const { t } = useI18n()
const live = useLiveStore()

// SPA v3: 顶栏左侧 只在 Live 录音且有 sessionTitle 时显示 (取代之前的"实时 · 实时转写"重复 crumb)
// 其他 view 顶栏左侧留空 (侧栏 4 个图标已是导航)
const sub = computed(() => {
  if (route.name === 'live' && live.sessionTitle) return live.sessionTitle
  return null
})
</script>

<template>
  <header class="bar">
    <div class="left">
      <span v-if="sub" class="session-tag">
        <span class="dot" />
        <span id="crumbSub">{{ sub }}</span>
      </span>
    </div>
    <div class="right">
      <UserMenu />
      <LangSwitch />
    </div>
  </header>
</template>

<style scoped>
.bar {
  height: 56px;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-soft);
  background: var(--ink);
}
.left { display: flex; align-items: center; gap: 12px; }
.session-tag {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px 4px 10px;
  background: var(--ink-2);
  border: 1px solid var(--border-soft);
  border-radius: 16px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--amber);
  letter-spacing: 0.04em;
  text-transform: uppercase;
}
.session-tag .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--amber);
  box-shadow: 0 0 0 3px var(--amber-soft);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
.right {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
