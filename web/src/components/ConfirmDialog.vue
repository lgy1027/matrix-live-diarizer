<script setup lang="ts">
import { onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'

interface Props {
  title: string
  message?: string
  detail?: string
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
    <div class="modal-card" :class="{ danger }" role="dialog" aria-labelledby="cd-title">
      <div id="cd-title" class="modal-title" :class="{ danger }">{{ props.title }}</div>
      <p v-if="props.message" class="msg">{{ props.message }}</p>
      <p v-if="props.detail" class="detail">{{ props.detail }}</p>
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
  border: 1px solid var(--teal);
  border-radius: 10px;
  padding: 28px 32px;
  width: min(440px, 92vw);
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
  animation: slideIn 0.2s ease;
}
.modal-card.danger { border-color: var(--red); }
@keyframes slideIn { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: none; } }
.modal-title {
  font-family: var(--serif);
  font-variation-settings: 'SOFT' 50, 'WONK' 1;
  font-size: 22px;
  font-weight: 400;
  margin-bottom: 14px;
  color: var(--teal);
}
.modal-title.danger { color: var(--red); }
.msg {
  font-family: 'Outfit', sans-serif;
  font-size: 13px;
  color: var(--text);
  line-height: 1.5;
  margin-bottom: 8px;
}
.detail {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-2);
  line-height: 1.5;
  margin-bottom: 18px;
  white-space: pre-wrap;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 18px;
}
</style>
