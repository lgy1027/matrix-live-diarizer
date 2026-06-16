<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { getEngines, switchEngine, type EngineInfo } from '../api/engines'
import { getLlmStatus } from '../api/llm'
type LlmResp = Awaited<ReturnType<typeof getLlmStatus>>
import { getStorageStatus } from '../api/storage'
import { useDialog } from '../composables/useDialog'

const { t } = useI18n()
const dialog = useDialog()

const engines = ref<Record<string, EngineInfo>>({})
const currentEngine = ref<string | null>(null)
const llm = ref<LlmResp | null>(null)
const historyEnabled = ref<boolean | null>(null)

const engineList = computed(() => {
  const order = ['campplus', 'eres2net', 'wespeaker']
  const e = engines.value
  return [...order.filter((k) => e[k]), ...Object.keys(e).filter((k) => !order.includes(k))]
})

async function load() {
  try {
    const r = await getEngines()
    engines.value = r.engines
    currentEngine.value = r.current
  } catch { /* 后端 8000 不通时静默 */ }
  try {
    llm.value = await getLlmStatus()
  } catch {
    llm.value = null
  }
  try {
    const s = await getStorageStatus()
    historyEnabled.value = s.history_enabled
  } catch {
    historyEnabled.value = null
  }
}

async function pickEngine(key: string) {
  if (key === currentEngine.value) return
  try {
    await switchEngine(key)
    currentEngine.value = key
    window.toast?.(t('settings.engine.switched', key) || `已切换到 ${key}`, 'ok')
  } catch (e) {
    window.toast?.(`${t('toast.error')}: ${e instanceof Error ? e.message : e}`, 'error')
  }
}

function toggleLlm(on: boolean) {
  // 后端无 toggle endpoint, 只读展示
  if (on && !llm.value?.available) {
    window.toast?.(t('settings.llm.notRunning') || '本地 LLM 未运行 — 请检查 endpoint', 'error')
  }
}

function showLlmHelp() {
  dialog.showConfirm({
    title: t('settings.llm.helpTitle') || '本地 LLM 配置说明',
    message: t('settings.llm.helpBody') || '支持任意 OpenAI-compatible 接口规范',
    detail: [
      'Ollama    →  http://127.0.0.1:11434/v1   (默认端口 11434)',
      '                ollama pull qwen2.5:1.5b',
      'LM Studio →  http://127.0.0.1:1234/v1    (默认端口 1234)',
      'LocalAI   →  http://127.0.0.1:8080/v1',
      'vLLM      →  http://127.0.0.1:8000/v1    (自部署)',
      'OpenRouter / 自建反向代理 (OpenAI 协议)',
      '',
      '在 .env 中设置:',
      '  LLM_ENABLED=true',
      '  LLM_ENDPOINT=http://127.0.0.1:11434/v1',
      '  LLM_MODEL=qwen2.5:1.5b',
      '',
      '重启 Matrix Live Diarizer 即生效。',
    ].join('\n'),
    confirmText: t('btn.confirm') || '知道了',
    cancelText: t('btn.cancel') || '关闭',
    danger: false,
  })
}

onMounted(load)
</script>

<template>
  <section class="set-wrap">
    <header class="set-head">
      <h1 class="page-title" v-html="t('view.settings.title')" />
      <p class="page-sub">{{ t('view.settings.sub') || '声纹引擎 / 本地 LLM / 历史存储' }}</p>
    </header>
    <div class="set-grid">

    <!-- 声纹引擎 -->
    <div class="set-row engine-row">
      <div class="l">
        <span>{{ t('settings.engine.label') }}</span>
        <em>{{ t('view.settings.engine') }}</em>
      </div>
      <div class="d">{{ t('settings.engine.desc') }}</div>
      <div class="eng-list">
        <div
          v-for="key in engineList"
          :key="key"
          class="eng-row"
          :class="{ active: key === currentEngine }"
          @click="pickEngine(key)"
        >
          <div class="radio" />
          <div class="info">
            <div class="n">{{ engines[key]?.name || key }}</div>
            <div class="m">
              <b>{{ engines[key]?.params || '—' }}</b>
              <span class="sep">·</span>
              {{ engines[key]?.speed || '—' }}
              <span class="sep">·</span>
              {{ engines[key]?.description || '' }}
            </div>
          </div>
          <div
            class="swatch"
            :style="{ background: ['#FF6B35', '#4ECDC4', '#D4A574', '#C589E8', '#7BC96F'][Object.keys(engines).indexOf(key) % 5] }"
          />
        </div>
        <div v-if="engineList.length === 0" class="empty">
          {{ t('settings.engine.loading') }}
        </div>
      </div>
    </div>

    <!-- LLM -->
    <div v-if="llm" class="set-row">
      <div class="l">
        <span>{{ t('view.settings.llm') }}</span>
        <em>LLM</em>
      </div>
      <div class="d">{{ t('view.settings.llm.desc') }}</div>
      <div class="toggle-group">
        <button
          :class="{ active: !llm.enabled }"
          type="button"
          @click="toggleLlm(false)"
        >
          <span class="r" />
          <span>{{ t('settings.llm.off') }}</span>
        </button>
        <button
          :class="{ active: llm.enabled }"
          type="button"
          @click="toggleLlm(true)"
        >
          <span class="r" />
          <span>{{ t('settings.llm.on') }}</span>
        </button>
      </div>
      <div class="llm-status">
        <span>{{ t('settings.llm.statusLabel') }}</span>
        <b v-if="llm.available" class="on">{{ t('settings.llm.statusAvail') }}</b>
        <b v-else class="off">{{ t('settings.llm.statusNotRun') }}</b>
        <span v-if="llm.model" class="model">· {{ llm.model }}</span>
      </div>
      <div class="llm-detail">
        <span>Endpoint: <b class="teal">{{ llm.endpoint || '—' }}</b></span>
        <span class="sep">·</span>
        <span>Model: <b class="teal">{{ llm.model || '—' }}</b></span>
        <button class="btn ghost sm help" type="button" @click="showLlmHelp">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="10" />
            <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3M12 17h.01" />
          </svg>
          {{ t('settings.llm.help') || '配置说明' }}
        </button>
      </div>
    </div>

    <!-- 历史存储 -->
    <div class="set-row">
      <div class="l" v-html="t('view.settings.storage')" />
      <div class="d">{{ t('settings.storage.desc') || '所有转写会话是否持久化到本地 SQLite,可在历史会话(Library)页查看。重启服务后生效。' }}</div>
      <div class="storage-state">
        <span v-if="historyEnabled === true" class="tag green">● {{ t('settings.storage.on') || '已启用' }}</span>
        <span v-else-if="historyEnabled === false" class="tag">○ {{ t('settings.storage.off') || '已停用' }}</span>
        <span v-else class="tag">? {{ t('settings.storage.unknown') || '未知' }}</span>
        <small>
          {{ t('settings.storage.hint') || '运行时配置 · 由' }}
          <code>STORAGE_HISTORY_ENABLED</code>
          {{ t('settings.storage.envHint') || '环境变量控制' }}
        </small>
      </div>
    </div>

    <!-- About -->
    <div class="set-row">
      <div class="l" v-html="t('view.settings.about')" />
      <div class="about">
        <span>{{ t('settings.about.text') }}</span><br />
        <span>
          {{ t('settings.about.enginesLabel') || 'Diarization:' }}
          <a href="#">{{ t('settings.about.engines', Object.keys(engines).length) }}</a>
        </span><br />
        <a href="/docs" target="_blank" rel="noopener">{{ t('settings.about.docs') }}</a>
        &nbsp;·&nbsp;
        <a href="/health" target="_blank" rel="noopener">Health →</a>
      </div>
    </div>
    </div>
  </section>
</template>

<style scoped>
.set-wrap { padding: 32px 48px 48px; }  /* 整改: 删 max-width */
.set-head { padding-bottom: 24px; border-bottom: 1px solid var(--border); margin-bottom: 0; }
/* 整改 1: 改用 .page-title / .page-sub (components.css), scoped 块里不再重复定义 */
.set-grid {
  display: grid;
  grid-template-columns: 1.6fr 1fr 1fr;
  grid-auto-rows: auto;
  gap: 16px;
}
.set-grid .set-row { background: var(--ink-2); border: 1px solid var(--border-soft); border-radius: 8px; padding: 22px 24px; }
/* 声纹引擎 (第 1 个 set-row): 占左 1 列, 跨 2 行 (引擎列表高度自适应) */
.set-grid .set-row.engine-row { grid-row: span 2; }
/* 整改 1: 删除 dead .set-wrap h1 规则 (无 live 元素匹配, 行内 section header 实际用 .set-row .l) */
.set-row { padding: 22px 24px; background: var(--ink-2); }
.set-row + .set-row { border-top: 1px solid var(--border-soft); }
.set-row .l {
  font-family: var(--serif);
  font-size: 18px;
  color: var(--text);
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 4px;
}
.set-row .l span { color: var(--text); }
.set-row .l em { font-style: italic; color: var(--amber); font-variation-settings: 'SOFT' 100, 'WONK' 1; opacity: 0.55; }  /* 整改 4: em 英文副标与主标同字号 18px, 只 italic + amber, 透明度温和降以视觉二级 */
.set-row .d {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.04em;
  line-height: 1.5;
  margin-bottom: 14px;
}
.eng-list { display: flex; flex-direction: column; gap: 0; border: 1px solid var(--border-soft); border-radius: 8px; overflow: hidden; }
.eng-row {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 14px;
  align-items: center;
  padding: 14px 18px;
  background: var(--ink-2);
  cursor: pointer;
  transition: background 0.15s;
  border-bottom: 1px solid var(--border-soft);
}
.eng-row:last-child { border-bottom: none; }
.eng-row:hover { background: var(--ink-3); }
.eng-row.active { background: var(--ink-3); }
.radio { width: 14px; height: 14px; border-radius: 50%; border: 1.5px solid var(--text-3); position: relative; }
.eng-row.active .radio { border-color: var(--amber); }
.eng-row.active .radio::after { content: ''; position: absolute; inset: 3px; border-radius: 50%; background: var(--amber); }
.info .n { font-family: var(--serif); font-size: 16px; color: var(--text); }
.info .m { font-family: var(--mono); font-size: 11px; color: var(--text-2); margin-top: 2px; }
.info .m b { color: var(--teal); font-weight: 500; margin-right: 4px; }
.info .m .sep { color: var(--text-3); margin: 0 4px; }
.swatch { width: 4px; height: 28px; border-radius: 2px; }
.toggle-group { display: inline-flex; gap: 0; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.toggle-group button {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: var(--ink-2);
  color: var(--text-2);
  font-family: 'Outfit', sans-serif;
  font-size: 12px;
  font-weight: 500;
  border: none;
  cursor: pointer;
  transition: all 0.15s;
}
.toggle-group button.active { background: var(--amber); color: var(--ink); }
.toggle-group button .r { width: 6px; height: 6px; border-radius: 50%; background: var(--text-3); }
.toggle-group button.active .r { background: var(--ink); }
.llm-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-2);
  letter-spacing: 0.04em;
}
.llm-status b.on { color: var(--green); }
.llm-status b.off { color: var(--text-3); }
.llm-status .model { color: var(--text-3); }
.llm-detail {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 0.04em;
}
.llm-detail .sep { color: var(--text-3); }
.llm-detail b { font-weight: 500; }
.llm-detail .help { margin-left: auto; }
.storage-state {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}
.storage-state small {
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.06em;
}
.storage-state code { color: var(--amber); font-family: 'JetBrains Mono', monospace; font-size: 10px; }
.about { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-2); line-height: 1.7; }
.about a { color: var(--amber); }
.about a:hover { text-decoration: underline; }
.empty { padding: 30px; text-align: center; color: var(--text-3); font-family: var(--mono); font-size: 12px; }
</style>
