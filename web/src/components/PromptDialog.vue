<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'

interface Props {
  title: string
  message?: string
  placeholder?: string
  initialValue?: string
  confirmText?: string
  cancelText?: string
  validate?: (v: string) => string | null
}
const props = defineProps<Props>()
const emit = defineEmits<{ close: []; submit: [v: string] }>()
const { t } = useI18n()

const value = ref(props.initialValue || '')
const err = ref<string | null>(null)
const inputEl = ref<HTMLInputElement | null>(null)

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

function submit() {
  if (props.validate) {
    const msg = props.validate(value.value)
    if (msg) { err.value = msg; return }
  }
  emit('submit', value.value)
}

onMounted(() => {
  document.addEventListener('keydown', onKey)
  setTimeout(() => inputEl.value?.focus(), 50)
})
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal-card" role="dialog">
      <div class="modal-title">{{ props.title }}</div>
      <p v-if="props.message" class="msg">{{ props.message }}</p>
      <input
        ref="inputEl"
        v-model="value"
        class="field"
        :placeholder="props.placeholder"
        @keydown.enter="submit"
      />
      <p v-if="err" class="err">{{ err }}</p>
      <div class="modal-actions">
        <button class="btn ghost" type="button" @click="emit('close')">
          {{ props.cancelText || t('btn.cancel') }}
        </button>
        <button class="btn primary" type="button" @click="submit">
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
}
.modal-title {
  font-family: var(--serif);
  font-size: 22px;
  margin-bottom: 14px;
  color: var(--teal);
}
.msg { font-size: 13px; color: var(--text); margin-bottom: 14px; line-height: 1.5; }
.field { margin-bottom: 6px; }
.err { color: var(--red); font-size: 12px; margin: 6px 0; font-family: 'JetBrains Mono', monospace; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
</style>
