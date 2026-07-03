<script setup lang="ts">
import { reactive } from 'vue'

export interface ToastItem { id: number; text: string; kind: 'ok' | 'error' | 'info' }

const state = reactive<{ items: ToastItem[] }>({ items: [] })
let seq = 1

function show(text: string, kind: ToastItem['kind'] = 'info', ms = 3000) {
  const id = seq++
  state.items.push({ id, text, kind })
  setTimeout(() => {
    const i = state.items.findIndex((t) => t.id === id)
    if (i >= 0) state.items.splice(i, 1)
  }, ms)
}

// 暴露到 window 方便非组件代码直接调
declare global {
  interface Window {
    toast: (text: string, kind?: ToastItem['kind']) => void
  }
}
if (typeof window !== 'undefined') {
  window.toast = (text, kind) => show(text, kind)
}
</script>

<template>
  <div class="toast-host">
    <transition-group name="toast">
      <div v-for="t in state.items" :key="t.id" class="toast" :class="t.kind">{{ t.text }}</div>
    </transition-group>
  </div>
</template>

<style scoped>
.toast-host {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-end;
  pointer-events: none;
}
.toast {
  background: var(--ink-2);
  border: 1px solid var(--border);
  border-left: 3px solid var(--text-3);
  border-radius: 6px;
  padding: 10px 14px;
  color: var(--text);
  font-family: 'Outfit', sans-serif;
  font-size: 12px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  max-width: 360px;
  pointer-events: auto;
}
.toast.ok { border-left-color: var(--green); }
.toast.error { border-left-color: var(--red); color: var(--red); }
.toast.info { border-left-color: var(--teal); }
.toast-enter-active, .toast-leave-active { transition: all 0.2s ease; }
.toast-enter-from { opacity: 0; transform: translateX(20px); }
.toast-leave-to { opacity: 0; transform: translateY(8px); }
</style>
