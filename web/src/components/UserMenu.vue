<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { logout as apiLogout } from '../api/auth'
import { useDialog } from '../composables/useDialog'

const auth = useAuthStore()
const router = useRouter()
const { t } = useI18n()
const dialog = useDialog()

const open = ref(false)
const host = ref<HTMLDivElement | null>(null)

const username = computed(() => auth.user?.username || '?')
const initial = computed(() => (auth.user?.username || '?').charAt(0).toUpperCase())

function toggle(e: Event) {
  e.stopPropagation()
  open.value = !open.value
}

async function onChangePwd() {
  open.value = false
  dialog.showChangePassword()
}

async function onLogout() {
  open.value = false
  const ok = await dialog.showConfirm({
    title: t('account.logout.title') || '退出登录',
    message: t('account.logout.msg') || '确认退出当前会话?',
    detail: t('account.logout.detail') || '将清除本地 token 并跳转到登录页。',
    confirmText: t('account.logout.confirm') || '退出',
    cancelText: t('btn.cancel') || '取消',
    danger: true,
  })
  if (!ok) return
  try { await apiLogout() } catch { /* noop */ }
  auth.clear()
  router.push({ name: 'login', query: { next: '/' } })
}

function onDocClick(e: MouseEvent) {
  if (!host.value) return
  if (!host.value.contains(e.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onBeforeUnmount(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div ref="host" class="user-menu">
    <button
      class="um-trigger"
      type="button"
      :title="username"
      :aria-label="t('account.menu')"
      @click="toggle"
    >
      <span class="um-avatar">{{ initial }}</span>
      <span class="um-name">{{ username }}</span>
      <span class="um-caret">▾</span>
    </button>
    <div class="um-dropdown" :hidden="!open">
      <div class="um-info">
        <div class="um-info-name">{{ username }}</div>
        <div class="um-info-tag">{{ t('account.loggedIn') || '已登录' }}</div>
      </div>
      <button class="um-item" type="button" @click="onChangePwd">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
        </svg>
        {{ t('account.changePwd') || '修改密码' }}
      </button>
      <button class="um-item danger" type="button" @click="onLogout">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
          <polyline points="16 17 21 12 16 7" />
          <line x1="21" y1="12" x2="9" y2="12" />
        </svg>
        {{ t('account.logout') || '退出登录' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.user-menu { position: relative; display: inline-block; }
.um-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 10px 0 6px;
  background: rgba(20, 17, 15, 0.6);
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  font-family: 'Outfit', sans-serif;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}
.um-trigger:hover { background: var(--ink-3); border-color: var(--border); }
.um-avatar {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--amber-soft);
  border: 1px solid rgba(255, 107, 53, 0.35);
  color: var(--amber);
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 600;
  display: grid;
  place-items: center;
  flex-shrink: 0;
}
.um-name { color: var(--text); font-weight: 500; letter-spacing: 0.04em; }
.um-caret { color: var(--text-3); font-size: 9px; margin-top: -1px; }
.um-dropdown {
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  min-width: 220px;
  background: var(--ink-2);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.5);
  padding: 6px;
  z-index: 60;
  animation: umIn 0.15s ease;
}
@keyframes umIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
.um-info { padding: 10px 12px 8px; border-bottom: 1px solid var(--border-soft); margin-bottom: 4px; }
.um-info-name { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text); font-weight: 500; margin-bottom: 2px; }
.um-info-tag { font-family: 'JetBrains Mono', monospace; font-size: 9px; color: var(--green); letter-spacing: 0.1em; text-transform: uppercase; }
.um-item {
  display: flex;
  align-items: center;
  gap: 9px;
  width: 100%;
  text-align: left;
  padding: 9px 12px;
  background: transparent;
  border: none;
  border-radius: 5px;
  color: var(--text);
  font-family: 'Outfit', sans-serif;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.12s;
}
.um-item:hover { background: var(--ink-3); }
.um-item.danger { color: var(--red); }
.um-item.danger:hover { background: rgba(255, 71, 87, 0.12); }
.um-item svg { width: 13px; height: 13px; flex-shrink: 0; }
</style>
