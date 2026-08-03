<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useI18n } from 'vue-i18n'
import { setLocale } from '../i18n'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const { t: ti18n, locale: i18nLocale } = useI18n() as unknown as {
  t: (k: string, ...a: (string | number)[]) => string
  locale: { value: 'zh' | 'en' }
}
const t = (k: string, ...args: (string | number)[]) =>
  (ti18n as unknown as (k: string, ...a: (string | number)[]) => string)(k, ...args)

const username = ref('')
const password = ref('')
const errMsg = ref('')
const submitting = ref(false)
const showPwd = ref(false)
const remember = ref(true)

const safeNext = computed(() => {
  const n = (route.query.next as string) || '/live'
  // 只允许跳解析到具名 SPA 路由的路径, 防 open redirect 与误跳 API/catch-all。
  if (!n.startsWith('/') || n.startsWith('//')) return '/live'
  const resolved = router.resolve(n)
  return resolved.name && resolved.name !== 'login' ? n : '/live'
})

async function submit() {
  if (!username.value || !password.value) {
    errMsg.value = t('login.err.empty') || '请输入用户名和密码'
    return
  }
  errMsg.value = ''
  submitting.value = true
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 30000)
  try {
    let r: Response
    try {
      r = await fetch('/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.value, password: password.value }),
        signal: ctrl.signal,
      })
    } catch (e) {
      errMsg.value =
        e instanceof DOMException && e.name === 'AbortError'
          ? t('login.err.timeout') || '请求超时,请重试'
          : e instanceof Error
            ? e.message
            : String(e)
      return
    }
    if (!r.ok) {
      const d = await r.json().catch(() => ({}))
      errMsg.value = d.detail || t('login.err.fail') || '登录失败'
      return
    }
    const data = await r.json()
    auth.setToken(data.token, data.user, remember.value)
    router.push(safeNext.value)
  } catch (e) {
    errMsg.value = e instanceof Error ? e.message : String(e)
  } finally {
    clearTimeout(timer)
    submitting.value = false
  }
}

function toggleLang() {
  setLocale(i18nLocale.value === 'en' ? 'zh' : 'en')
}

onMounted(() => {
  // 已登录直接跳走
  if (auth.isLoggedIn) router.push(safeNext.value)
})
</script>

<template>
  <div class="login-page">
    <!-- 顶部 brand bar (跟主 app 一致) -->
    <header class="login-top">
      <div class="brand">
        <span class="mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="9" />
            <path d="M3 12h18M12 3v18M5.6 5.6l12.8 12.8M18.4 5.6L5.6 18.4" />
          </svg>
        </span>
        <span class="brand-text">Matrix<em>·</em>Studio</span>
      </div>
      <div class="lang-toggle">
        <button type="button" class="lang-btn" :class="{ active: i18nLocale.value === 'zh' }" @click="setLocale('zh')">中文</button>
        <button type="button" class="lang-btn" :class="{ active: i18nLocale.value === 'en' }" @click="setLocale('en')">EN</button>
      </div>
    </header>

    <!-- 主区 -->
    <main class="login-main">
      <form class="login-card" @submit.prevent="submit" autocomplete="on">
        <div class="eyebrow">
          <span class="bar" />
          <span>Authentication</span>
        </div>
        <h1>Log<em>·</em>in</h1>
        <p class="sub">
          {{ t('login.sub') || 'Live transcription & speaker diarization' }}
        </p>

        <div class="field">
          <label for="username">
            <span class="key">USERNAME</span>
          </label>
          <input
            id="username"
            v-model="username"
            type="text"
            autocomplete="username"
            required
            spellcheck="false"
            placeholder="admin"
            :disabled="submitting"
          />
        </div>

        <div class="field">
          <label for="password">
            <span class="key">PASSWORD</span>
            <button type="button" class="show-pwd" @click="showPwd = !showPwd">{{ t(showPwd ? 'login.hidePassword' : 'login.showPassword') }}</button>
          </label>
          <input
            id="password"
            v-model="password"
            :type="showPwd ? 'text' : 'password'"
            autocomplete="current-password"
            required
            placeholder="••••••"
            :disabled="submitting"
          />
        </div>

        <div class="row-extra">
          <label class="remember">
            <input v-model="remember" type="checkbox" />
            <span>{{ t('login.remember') || '记住我' }}</span>
          </label>
        </div>

        <button class="submit-btn" type="submit" :disabled="submitting">
          {{ submitting ? (t('login.submitting') || '登录中…') : (t('login.submit') || '登 录') }}
        </button>
        <p v-if="errMsg" class="err" role="alert">{{ errMsg }}</p>

        <p class="hint">
          {{ t('login.hint1') || '默认账户' }} <strong>admin</strong> · {{ t('login.hint2') || '密码' }} <strong>admin</strong>
          <br />
          <span class="muted">{{ t('login.hint3') || '首次登录后系统强制修改密码' }}</span>
        </p>
      </form>
    </main>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr;
  background: var(--ink);
  position: relative;
  overflow: hidden;
}
.login-page::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image: radial-gradient(circle, var(--border) 1px, transparent 1px);
  background-size: 24px 24px;
  opacity: 0.18;
  pointer-events: none;
  z-index: 0;
}
.login-page::after {
  content: '';
  position: fixed;
  top: -200px;
  right: -200px;
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, var(--amber-soft) 0%, transparent 60%);
  pointer-events: none;
  z-index: 0;
}
.login-top {
  position: relative;
  z-index: 1;
  height: 56px;
  padding: 0 28px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--border-soft);
  background: var(--ink);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--serif);
  font-size: 18px;
  font-variation-settings: 'SOFT' 30, 'WONK' 1;
}
.brand .mark {
  width: 24px;
  height: 24px;
  color: var(--amber);
  display: grid;
  place-items: center;
}
.brand .mark svg { width: 100%; height: 100%; }
.brand-text em { font-style: italic; color: var(--amber); margin: 0 2px; }
.lang-toggle {
  display: inline-flex;
  gap: 0;
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  overflow: hidden;
  background: rgba(20, 17, 15, 0.6);
}
.lang-btn {
  background: transparent;
  border: none;
  color: var(--text-3);
  padding: 5px 12px;
  font-family: 'Outfit', sans-serif;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.5px;
  cursor: pointer;
  transition: all 0.2s;
}
.lang-btn:hover { color: var(--text-2); }
.lang-btn.active { background: var(--amber); color: var(--ink); font-weight: 600; }
.login-main {
  position: relative;
  z-index: 1;
  display: grid;
  place-items: center;
  padding: 40px 16px;
}
.login-card {
  width: 100%;
  max-width: 420px;
  background: var(--ink-2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 44px 40px 36px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(255, 255, 255, 0.02) inset;
}
.eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--amber);
  margin-bottom: 12px;
}
.eyebrow .bar {
  width: 24px;
  height: 1px;
  background: var(--amber);
}
.login-card h1 {
  font-family: var(--serif);
  font-size: 44px;
  font-variation-settings: 'SOFT' 50, 'WONK' 1, 'opsz' 144;
  font-weight: 400;
  letter-spacing: -0.02em;
  line-height: 1;
  margin-bottom: 8px;
}
.login-card h1 em {
  font-style: italic;
  color: var(--amber);
  font-variation-settings: 'SOFT' 80, 'WONK' 1, 'opsz' 144;
}
.sub {
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--text-2);
  margin-bottom: 28px;
  padding-bottom: 22px;
  border-bottom: 1px solid var(--border);
}
.field { margin-bottom: 14px; }
.field label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.12em;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.field label .key { color: var(--text-2); font-weight: 500; }
.show-pwd {
  background: transparent;
  border: none;
  color: var(--text-3);
  font-family: var(--mono);
  font-size: 9px;
  cursor: pointer;
  letter-spacing: 0.08em;
}
.show-pwd:hover { color: var(--amber); }
.field input {
  width: 100%;
  padding: 13px 14px;
  background: var(--ink-3);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-family: var(--mono);
  font-size: 14px;
  letter-spacing: 0.02em;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
}
.field input:focus {
  border-color: var(--amber);
  background: var(--ink-2);
  outline: none;
  box-shadow: 0 0 0 3px var(--amber-soft);
}
.field input::placeholder { color: var(--text-3); }
.field input:disabled { opacity: 0.6; cursor: not-allowed; }
.row-extra {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 4px 0 14px;
}
.remember {
  display: flex;
  align-items: center;
  gap: 6px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.06em;
  cursor: pointer;
}
.remember input { width: auto !important; height: auto !important; margin: 0; }
.submit-btn {
  width: 100%;
  padding: 13px 18px;
  background: var(--amber);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.04em;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  transition: opacity 0.15s, transform 0.1s;
}
.submit-btn:hover:not(:disabled) { opacity: 0.88; }
.submit-btn:active:not(:disabled) { transform: scale(0.985); }
.submit-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.err {
  margin-top: 14px;
  padding: 11px 14px;
  background: rgba(255, 71, 87, 0.1);
  border: 1px solid rgba(255, 71, 87, 0.4);
  border-radius: 6px;
  color: var(--red);
  font-family: var(--mono);
  font-size: 12px;
}
.hint {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--border-soft);
  font-family: var(--mono);
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--text-2);
  text-align: center;
  line-height: 1.7;
}
.hint strong { color: var(--text); font-weight: 500; }
.hint .muted { color: var(--text-3); font-size: 10px; display: block; margin-top: 6px; }
</style>
