<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'

interface Props {
  title: string
  body?: string
  items: string[]
  itemCount?: number
  itemCountLabel?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}
const props = withDefaults(defineProps<Props>(), { danger: false })
const emit = defineEmits<{ close: []; confirm: [] }>()
const { t } = useI18n()

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal-card" :class="{ danger }" role="dialog">
      <div class="modal-title" :class="{ danger }">{{ props.title }}</div>
      <p v-if="props.body" class="body">{{ props.body }}</p>
      <div v-if="props.itemCount && props.itemCountLabel" class="count">
        <strong>{{ props.itemCount }}</strong> {{ props.itemCountLabel }}
      </div>
      <ul class="list">
        <li v-for="(it, i) in props.items" :key="i" class="list-item">{{ it }}</li>
      </ul>
      <div class="modal-actions">
        <button class="btn ghost" type="button" @click="emit('close')">
          {{ props.cancelText || t('btn.cancel') }}
        </button>
        <button
          class="btn"
          :class="props.danger ? 'danger' : 'primary'"
          type="button"
          @click="emit('confirm')"
        >
          {{ props.confirmText || t('btn.confirm') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.6);
  display: grid;
  place-items: center;
  animation: fadeIn 0.15s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.modal-card {
  background: var(--ink-2);
  border: 1px solid var(--amber);
  border-radius: 10px;
  padding: 24px 28px;
  width: min(480px, 92vw);
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
}
.modal-card.danger { border-color: var(--red); }
.modal-title {
  font-family: var(--serif);
  font-size: 20px;
  color: var(--amber);
  margin-bottom: 10px;
}
.modal-title.danger { color: var(--red); }
.body { font-size: 12px; color: var(--text); margin-bottom: 10px; line-height: 1.5; }
.count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-3);
  margin-bottom: 10px;
}
.count strong { color: var(--amber); font-size: 14px; }
.list {
  flex: 1;
  overflow-y: auto;
  background: var(--ink-3);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  list-style: none;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-2);
  max-height: 220px;
}
.list-item {
  padding: 3px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
</style>
