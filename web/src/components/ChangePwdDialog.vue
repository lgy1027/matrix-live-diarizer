<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const emit = defineEmits<{ close: []; submit: [oldPwd: string, newPwd: string] }>()
const { t } = useI18n()

const oldPwd = ref('')
const newPwd = ref('')
const err = ref('')
const submitting = ref(false)

async function submit() {
  if (!oldPwd.value || !newPwd.value) { err.value = '请填写完整'; return }
  if (newPwd.value.length < 8) { err.value = '新密码需 ≥8 字符'; return }
  if (!/[a-zA-Z]/.test(newPwd.value) || !/\d/.test(newPwd.value)) {
    err.value = '新密码需含字母+数字'
    return
  }
  if (oldPwd.value === newPwd.value) { err.value = '新密码不能与原密码相同'; return }
  err.value = ''
  submitting.value = true
  try {
    emit('submit', oldPwd.value, newPwd.value)
  } catch (e) {
    err.value = e instanceof Error ? e.message : '改密失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal-card" role="dialog">
      <div class="modal-title">🔑 {{ t('account.changePwd') || '修改密码' }}</div>
      <div class="field-block">
        <label>{{ t('account.pwd.old') || '原密码' }}</label>
        <input v-model="oldPwd" class="field" type="password" autocomplete="current-password" />
      </div>
      <div class="field-block">
        <label>{{ t('account.pwd.new') || '新密码 (≥8 字符, 需含字母+数字)' }}</label>
        <input v-model="newPwd" class="field" type="password" autocomplete="new-password" @keydown.enter="submit" />
      </div>
      <p v-if="err" class="err">{{ err }}</p>
      <div class="modal-actions">
        <button class="btn ghost" type="button" @click="emit('close')">{{ t('btn.cancel') }}</button>
        <button class="btn primary" type="button" :disabled="submitting" @click="submit">
          {{ submitting ? '…' : (t('btn.confirm') || '确认') }}
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
  margin-bottom: 18px;
  color: var(--teal);
}
.field-block { margin-bottom: 14px; }
.field-block label {
  display: block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  margin-bottom: 6px;
}
.err { color: var(--red); font-size: 12px; margin: 6px 0; font-family: 'JetBrains Mono', monospace; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
</style>
