<script setup lang="ts">
import { ref, computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { changePassword as apiChangePassword } from '../api/auth'
import { useI18n } from 'vue-i18n'

const auth = useAuthStore()
const { t } = useI18n()

const visible = ref(true)
const oldPwd = ref('')
const newPwd = ref('')
const err = ref('')
const submitting = ref(false)

const show = computed(() => auth.isLoggedIn && auth.mustChangePwd && visible.value)

async function submit() {
  if (!oldPwd.value || newPwd.value.length < 8) {
    err.value = t('account.pwd.errShort') || '新密码需 ≥ 8 字符'
    return
  }
  if (!/[a-zA-Z]/.test(newPwd.value) || !/\d/.test(newPwd.value)) {
    err.value = t('account.pwd.errFmt') || '新密码需含字母+数字'
    return
  }
  err.value = ''
  submitting.value = true
  try {
    const r = await apiChangePassword(oldPwd.value, newPwd.value)
    if (r.token) auth.setToken(r.token, { ...auth.user!, must_change_password: false })
    window.toast?.(t('account.pwd.changed') || '密码已修改', 'ok')
    visible.value = false
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div v-if="show" class="modal-mask" @click.self="void 0">
    <div class="modal-card force" role="dialog" aria-labelledby="pcg-title">
      <div id="pcg-title" class="modal-title" style="color: var(--amber)">
        ⚠ {{ t('account.pwd.forceTitle') || '首次登录需修改默认密码' }}
      </div>
      <p class="msg">
        {{ t('account.pwd.forceBody') || '为了账号安全,请立即修改默认密码 admin。' }}
      </p>
      <div class="field-block">
        <label for="pcg-old">{{ t('account.pwd.old') || '原密码' }}</label>
        <input
          id="pcg-old"
          v-model="oldPwd"
          class="field"
          type="password"
          autocomplete="current-password"
          placeholder="admin"
        />
      </div>
      <div class="field-block">
        <label for="pcg-new">{{ t('account.pwd.new') || '新密码 (≥8 字符, 需含字母+数字)' }}</label>
        <input
          id="pcg-new"
          v-model="newPwd"
          class="field"
          type="password"
          autocomplete="new-password"
          @keydown.enter="submit"
        />
      </div>
      <p v-if="err" class="err">{{ err }}</p>
      <div class="modal-actions">
        <button class="btn primary" type="button" :disabled="submitting" @click="submit">
          {{ submitting ? '...' : (t('btn.confirm') || '确认修改') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1100;  /* 高于 userMenu 触发的普通 modal (z 1000), 强制在最前 */
  background: rgba(0, 0, 0, 0.75);
  display: grid;
  place-items: center;
  animation: pmFadeIn 0.15s ease;
}
@keyframes pmFadeIn { from { opacity: 0; } to { opacity: 1; } }
.modal-card.force {
  background: var(--ink-2);
  border: 2px solid var(--amber);
  border-radius: 10px;
  padding: 28px 32px;
  width: min(440px, 92vw);
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
}
.modal-title {
  font-family: var(--serif);
  font-size: 22px;
  margin-bottom: 12px;
}
.msg {
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 18px;
  line-height: 1.5;
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
.err {
  color: var(--red);
  font-size: 12px;
  margin: 6px 0;
  font-family: 'JetBrains Mono', monospace;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
</style>
