<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { getEngines, getModels, switchAsrEngine, switchEngine, type AsrInfo, type EngineInfo, type ModelsInfo } from '../api/engines'
import { getLlmSettings, getLlmStatus, saveLlmSettings, testLlmConnection, type LlmSettings } from '../api/llm'
type LlmResp = Awaited<ReturnType<typeof getLlmStatus>>
import { useDialog } from '../composables/useDialog'
import EmText from '../components/EmText.vue'

const { t, locale } = useI18n()
const dialog = useDialog()

const engines = ref<Record<string, EngineInfo>>({})
const currentEngine = ref<string | null>(null)
const models = ref<ModelsInfo | null>(null)
const llm = ref<LlmResp | null>(null)
const llmSettings = ref<LlmSettings | null>(null)
const savingLlm = ref(false)
const testingLlm = ref(false)
const switchingEngine = ref<string | null>(null)
const switchingAsr = ref<string | null>(null)

const engineList = computed(() => {
  const order = ['campplus', 'eres2net', 'wespeaker']
  const e = engines.value
  return [...order.filter((k) => e[k]), ...Object.keys(e).filter((k) => !order.includes(k))]
})

const asrEngines = computed<Record<string, AsrInfo>>(() => models.value?.asr_engines?.engines || {})
const currentAsr = computed(() => models.value?.asr_engines?.current || models.value?.asr?.type || 'qwen3')
const cachedAsr = computed(() => new Set(models.value?.asr_engines?.cached || [currentAsr.value]))
const asrList = computed(() => {
  const order = ['qwen3', 'sensevoice', 'paraformer', 'paraformer_streaming']
  const e = asrEngines.value
  return [...order.filter((k) => e[k]), ...Object.keys(e).filter((k) => !order.includes(k))]
})
const isEnglish = computed(() => String(locale.value).startsWith('en'))

function asrLanguages(info?: AsrInfo) {
  if (!info) return '—'
  return isEnglish.value ? (info.languages_en || info.languages || '—') : (info.languages || info.languages_en || '—')
}

function asrDescription(info?: AsrInfo) {
  if (!info) return ''
  return isEnglish.value ? (info.description_en || info.description || '') : (info.description || info.description_en || '')
}

function asrUnavailableMessage(info?: AsrInfo) {
  if (!info) return ''
  if (isEnglish.value) return info.install_hint_en || info.reason || asrDescription(info)
  return info.install_hint || asrDescription(info)
}

function yesNo(v: unknown) {
  return v ? (t('common.yes') || 'Yes') : (t('common.no') || 'No')
}

function asrCapabilityNote(info?: AsrInfo) {
  const caps = info?.capabilities || {}
  const note = isEnglish.value ? (caps.notes_en || caps.notes) : (caps.notes || caps.notes_en)
  const parts = [
    `${t('settings.asr.cap.upload') || 'Upload'}: ${yesNo(caps.upload)}`,
    `${t('settings.asr.cap.realtime') || 'Realtime'}: ${yesNo(caps.realtime_segmented)}`,
    `${t('settings.asr.cap.words') || 'Word timestamps'}: ${yesNo(caps.word_timestamps)}`,
    `${t('settings.asr.cap.speaker') || 'Speaker ID'}: ${yesNo(caps.speaker_diarization)}`,
  ]
  if (caps.true_streaming === 'adapter_not_yet') {
    parts.push(t('settings.asr.cap.streamingAdapter') || 'Token streaming: adapter not yet')
  } else {
    parts.push(`${t('settings.asr.cap.tokenStreaming') || 'Token streaming'}: ${yesNo(caps.true_streaming)}`)
  }
  if (info?.customized) {
    parts.push(t('settings.asr.cap.customized') || 'Customized')
  }
  if (note) parts.push(String(note))
  return parts.join(' · ')
}

function engineSpeed(info?: EngineInfo) {
  if (!info) return '—'
  return isEnglish.value ? (info.speed_en || info.speed || '—') : (info.speed || info.speed_en || '—')
}

function engineDescription(info?: EngineInfo) {
  if (!info) return ''
  return isEnglish.value ? (info.description_en || info.description || '') : (info.description || info.description_en || '')
}

const llmProviders = [
  { key: 'ollama', label: 'Ollama', endpoint: 'http://127.0.0.1:11434/v1', model: 'qwen2.5:1.5b', allowPublic: false },
  { key: 'lmstudio', label: 'LM Studio', endpoint: 'http://127.0.0.1:1234/v1', model: 'qwen2.5-1.5b-instruct', allowPublic: false },
  { key: 'localai', label: 'LocalAI', endpoint: 'http://127.0.0.1:8080/v1', model: 'qwen2.5:1.5b', allowPublic: false },
  { key: 'vllm', label: 'vLLM', endpoint: 'http://127.0.0.1:8000/v1', model: 'Qwen/Qwen2.5-1.5B-Instruct', allowPublic: false },
  { key: 'openai', label: 'OpenAI-compatible', endpoint: 'https://api.openai.com/v1', model: 'gpt-4o-mini', allowPublic: true },
  { key: 'custom', label: 'Custom', endpoint: '', model: '', allowPublic: false },
]

async function load() {
  try {
    const r = await getEngines()
    engines.value = r.engines
    currentEngine.value = r.current
  } catch { /* 后端 8000 不通时静默 */ }
  try {
    models.value = await getModels()
  } catch {
    models.value = null
  }
  try {
    llm.value = await getLlmStatus()
    llmSettings.value = await getLlmSettings()
  } catch {
    llm.value = null
    llmSettings.value = null
  }
}

async function pickEngine(key: string) {
  if (key === currentEngine.value || switchingEngine.value) return
  const info = engines.value[key]
  const ok = await dialog.showConfirm({
    title: t('settings.engine.switchTitle', info?.name || key) || `切换到 ${info?.name || key}?`,
    message: t('settings.engine.switchMessage') || '切换声纹引擎会重新加载对应模型,完成前请避免开始新的识别任务。',
    detail: [
      `${t('settings.engine.params') || '参数量'}: ${info?.params || '—'}`,
      `${t('settings.engine.speed') || '速度'}: ${engineSpeed(info)}`,
      engineDescription(info),
    ].filter(Boolean).join('\n'),
    confirmText: t('settings.engine.switchConfirm') || '切换',
    cancelText: t('btn.cancel') || '取消',
    danger: false,
  })
  if (!ok) return
  try {
    switchingEngine.value = key
    window.toast?.(t('settings.engine.switching', info?.name || key) || `正在切换声纹引擎: ${info?.name || key}`, 'info')
    await switchEngine(key)
    currentEngine.value = key
    models.value = await getModels()
    window.toast?.(t('settings.engine.switched', key) || `已切换到 ${key}`, 'ok')
  } catch (e) {
    window.toast?.(`${t('toast.error')}: ${e instanceof Error ? e.message : e}`, 'error')
  } finally {
    switchingEngine.value = null
  }
}

async function pickAsr(key: string) {
  if (key === currentAsr.value || switchingAsr.value) return
  const info = asrEngines.value[key]
  if (info?.available === false) {
    window.toast?.(info.install_hint || info.reason || (t('settings.asr.unavailable') || '当前环境不可用'), 'error')
    return
  }
  const cached = cachedAsr.value.has(key)
  const ok = await dialog.showConfirm({
    title: t('settings.asr.switchTitle', info?.name || key) || `切换到 ${info?.name || key}?`,
    message: cached
      ? (t('settings.asr.switchCached') || '该模型已加载,切换通常很快。')
      : (t('settings.asr.switchDownload') || '如果本机还没有该模型,后端会先下载并加载。下载/加载期间旧 ASR 会继续工作,完成后才切换。'),
    confirmText: t('settings.asr.switchConfirm') || '切换',
    cancelText: t('btn.cancel') || '取消',
    danger: false,
  })
  if (!ok) return
  try {
    switchingAsr.value = key
    window.toast?.(t('settings.asr.switching', info?.name || key) || `正在切换 ASR: ${info?.name || key}`, 'info')
    await switchAsrEngine(key)
    models.value = await getModels()
    window.toast?.(t('settings.asr.switched', info?.name || key) || `ASR 已切换到 ${info?.name || key}`, 'ok')
  } catch (e) {
    window.toast?.(`${t('settings.asr.switchFail') || 'ASR 切换失败'}: ${e instanceof Error ? e.message : e}`, 'error')
  } finally {
    switchingAsr.value = null
  }
}

function toggleLlm(on: boolean) {
  if (llmSettings.value) {
    llmSettings.value.enabled = on
  }
}

function pickLlmProvider(providerKey: string) {
  if (!llmSettings.value) return
  const preset = llmProviders.find((p) => p.key === providerKey)
  llmSettings.value.provider = providerKey
  if (preset && providerKey !== 'custom') {
    llmSettings.value.endpoint = preset.endpoint
    llmSettings.value.model = preset.model
    llmSettings.value.allow_public = preset.allowPublic
  }
}

async function saveLlmConfig() {
  if (!llmSettings.value) return
  try {
    savingLlm.value = true
    await saveLlmSettings(llmSettings.value)
    llm.value = await getLlmStatus()
    llmSettings.value = await getLlmSettings()
    window.toast?.(t('settings.llm.savedPassive') || 'LLM 配置已保存，未发起连接测试', 'ok')
  } catch (e) {
    window.toast?.(`${t('settings.llm.saveFail') || '保存失败'}: ${e instanceof Error ? e.message : e}`, 'error')
  } finally {
    savingLlm.value = false
  }
}

async function testLlmConfig() {
  if (!llm.value?.enabled || testingLlm.value) return
  const ok = await dialog.showConfirm({
    title: t('view.settings.llm.test') || '测试连接',
    message: t('settings.llm.testNotice', llm.value.endpoint || '—')
      || `测试将向已保存的 ${llm.value.endpoint || '—'} 发送一次最小 ping 请求。`,
    detail: t('settings.llm.testPrivacy') || '不会发送会议文稿，但可能产生极少量 API 用量。',
    confirmText: t('settings.llm.testConfirm') || '继续测试',
    cancelText: t('btn.cancel') || '取消',
    danger: false,
  })
  if (!ok) return
  try {
    testingLlm.value = true
    llm.value = await testLlmConnection()
    window.toast?.(
      llm.value.available
        ? (t('settings.llm.testSuccess') || 'LLM 连接可用')
        : (llm.value.error || t('settings.llm.testFailed') || 'LLM 连接不可用'),
      llm.value.available ? 'ok' : 'error',
    )
  } catch (e) {
    window.toast?.(`${t('settings.llm.testFailed') || '连接测试失败'}: ${e instanceof Error ? e.message : e}`, 'error')
  } finally {
    testingLlm.value = false
  }
}

function formatTestedAt(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale.value)
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
      <h1 class="page-title"><EmText :text="t('view.settings.title')" /></h1>
      <p class="page-sub">{{ t('view.settings.sub') || '声纹引擎 / 本地 LLM / 历史存储' }}</p>
    </header>
    <section class="capability-map" aria-labelledby="capability-title">
      <div class="capability-intro"><span>HOW IT WORKS</span><h2 id="capability-title">{{ t('product.settings.capabilities') }}</h2><p>{{ t('product.settings.capabilitiesHint') }}</p></div>
      <article><b>01</b><h3>{{ t('product.settings.transcription') }}</h3><p>{{ t('product.settings.transcriptionHint') }}</p></article>
      <article><b>02</b><h3>{{ t('product.settings.diarization') }}</h3><p>{{ t('product.settings.diarizationHint') }}</p></article>
      <article><b>03</b><h3>{{ t('product.settings.identity') }}</h3><p>{{ t('product.settings.identityHint') }}</p></article>
    </section>
    <div class="set-grid">

    <!-- ASR 引擎 -->
    <div class="set-row asr-row">
      <div class="l">
        <span>{{ t('settings.asr.label') || 'ASR 引擎' }}</span>
        <em>ASR</em>
      </div>
      <div class="d">{{ t('settings.asr.desc') || '当前语音识别模型由后端 ASR_ENGINE 环境变量决定,修改后需重启服务。' }}</div>
      <div class="eng-list compact">
        <div
          v-for="key in asrList"
          :key="key"
          class="eng-row"
          :class="{ active: key === currentAsr, switching: key === switchingAsr, disabled: asrEngines[key]?.available === false }"
          @click="pickAsr(key)"
        >
          <div class="radio" />
          <div class="info">
            <div class="n">{{ asrEngines[key]?.name || key }}</div>
            <div class="m">
              <b>{{ asrLanguages(asrEngines[key]) }}</b>
              <span class="sep">·</span>
              {{ asrEngines[key]?.supports_streaming ? (t('settings.asr.streaming') || '实时') : (t('settings.asr.offline') || '离线') }}
              <span v-if="asrEngines[key]?.optional_dependency" class="sep">·</span>
              <span v-if="asrEngines[key]?.optional_dependency">{{ asrEngines[key]?.optional_dependency }}</span>
              <span v-if="asrEngines[key]?.available === false" class="sep">·</span>
              <span v-if="asrEngines[key]?.available === false">{{ t('settings.asr.unavailable') || '不可用' }}</span>
              <span v-if="!cachedAsr.has(key)" class="sep">·</span>
              <span v-if="!cachedAsr.has(key)">{{ t('settings.asr.notCached') || '未加载' }}</span>
            </div>
            <div class="m muted">{{ asrEngines[key]?.available === false ? asrUnavailableMessage(asrEngines[key]) : asrDescription(asrEngines[key]) }}</div>
            <div class="m model-source">{{ t('product.settings.modelId') }}: {{ asrEngines[key]?.model || t('product.settings.modelIdUnavailable') }}</div>
            <div class="m capability">{{ asrCapabilityNote(asrEngines[key]) }}</div>
          </div>
          <span v-if="key === currentAsr" class="pill">{{ t('settings.asr.current') || '当前' }}</span>
          <span v-else-if="key === switchingAsr" class="pill">{{ t('settings.asr.switchingShort') || '切换中' }}</span>
        </div>
        <div v-if="asrList.length === 0" class="empty">
          {{ t('settings.engine.loading') }}
        </div>
      </div>
      <div class="config-hint">
        <code>ASR_ENGINE={{ currentAsr }}</code>
        <span>{{ t('settings.asr.dynamicHint') || '点击可动态切换;新模型加载完成前继续使用旧 ASR' }}</span>
      </div>
      <p class="run-provenance-hint">{{ t('product.settings.futureRunsHint') }}</p>
    </div>

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
          :class="{ active: key === currentEngine, switching: key === switchingEngine }"
          @click="pickEngine(key)"
        >
          <div class="radio" />
          <div class="info">
            <div class="n">{{ engines[key]?.name || key }}</div>
            <div class="m">
              <b>{{ engines[key]?.params || '—' }}</b>
              <span class="sep">·</span>
              {{ engineSpeed(engines[key]) }}
              <span class="sep">·</span>
              {{ engineDescription(engines[key]) }}
            </div>
            <div class="m model-source">{{ t('product.settings.modelId') }}: {{ engines[key]?.model || t('product.settings.modelIdUnavailable') }}</div>
          </div>
          <div
            class="swatch"
            :style="{ background: ['#FF6B35', '#4ECDC4', '#D4A574', '#C589E8', '#7BC96F'][Object.keys(engines).indexOf(key) % 5] }"
          />
          <span v-if="key === currentEngine" class="pill">{{ t('settings.asr.current') || '当前' }}</span>
          <span v-else-if="key === switchingEngine" class="pill">{{ t('settings.asr.switchingShort') || '切换中' }}</span>
        </div>
        <div v-if="engineList.length === 0" class="empty">
          {{ t('settings.engine.loading') }}
        </div>
      </div>
      <p class="run-provenance-hint">{{ t('product.settings.voiceSuggestionHint') }}</p>
    </div>

    <!-- LLM -->
    <div v-if="llm && llmSettings" class="set-row llm-row">
      <div class="l">
        <span>{{ t('view.settings.llm') }}</span>
        <em>LLM</em>
      </div>
      <div class="d">{{ t('view.settings.llm.desc') }}</div>
      <div class="toggle-group">
        <button
          :class="{ active: !llmSettings.enabled }"
          type="button"
          @click="toggleLlm(false)"
        >
          <span class="r" />
          <span>{{ t('settings.llm.off') }}</span>
        </button>
        <button
          :class="{ active: llmSettings.enabled }"
          type="button"
          @click="toggleLlm(true)"
        >
          <span class="r" />
          <span>{{ t('settings.llm.on') }}</span>
        </button>
      </div>
      <div class="llm-form">
        <label>
          <span>{{ t('settings.llm.provider') || '提供商' }}</span>
          <select v-model="llmSettings.provider" @change="pickLlmProvider(llmSettings.provider)">
            <option v-for="p in llmProviders" :key="p.key" :value="p.key">{{ p.label }}</option>
          </select>
        </label>
        <label>
          <span>Endpoint</span>
          <input v-model.trim="llmSettings.endpoint" placeholder="http://127.0.0.1:11434/v1" />
        </label>
        <label>
          <span>Model</span>
          <input v-model.trim="llmSettings.model" placeholder="qwen2.5:1.5b" />
        </label>
        <div class="llm-secret-note">
          {{ llmSettings.has_api_key ? t('settings.llm.keyFromEnv') : t('settings.llm.keyEnvHint') }}
        </div>
      </div>
      <div class="llm-options">
        <label>
          <input v-model="llmSettings.allow_public" type="checkbox" />
          <span>{{ t('settings.llm.allowPublic') || '允许公网 endpoint' }}</span>
        </label>
        <label>
          <input v-model="llmSettings.mock" type="checkbox" />
          <span>{{ t('settings.llm.mock') || 'Mock 模式' }}</span>
        </label>
        <button class="btn primary sm" type="button" :disabled="savingLlm" @click="saveLlmConfig">
          {{ savingLlm ? (t('settings.llm.saving') || '保存中…') : (t('settings.llm.save') || '保存配置') }}
        </button>
        <button
          class="btn ghost sm"
          type="button"
          :disabled="!llm.enabled || savingLlm || testingLlm"
          @click="testLlmConfig"
        >
          {{ testingLlm ? t('view.settings.llm.testing') : t('view.settings.llm.test') }}
        </button>
      </div>
      <div class="llm-test-notice">{{ t('settings.llm.testNotice', llm.endpoint || '—') }}</div>
      <div class="llm-status">
        <span>{{ t('settings.llm.statusLabel') }}</span>
        <b v-if="llm.available === true" class="on">{{ t('settings.llm.statusAvail') }}</b>
        <b v-else-if="llm.available === false" class="off">{{ t('settings.llm.statusUnavailable') }}</b>
        <b v-else class="off">{{ t('settings.llm.statusNeverTested') }}</b>
        <span v-if="llm.model" class="model">· {{ llm.model }}</span>
        <span class="model">· {{ llm.config_source || 'env' }}</span>
        <span v-if="llm.last_tested_at" class="model">· {{ t('settings.llm.lastTested', formatTestedAt(llm.last_tested_at)) }}</span>
      </div>
      <div v-if="llm.error" class="llm-error">{{ llm.error }}</div>
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

    <!-- About -->
    <div class="set-row">
      <div class="l"><EmText :text="t('view.settings.about')" /></div>
      <div class="about">
        <span>{{ t('settings.about.text') }}</span><br />
        <a href="/docs" target="_blank" rel="noopener">{{ t('settings.about.docs') }}</a>
        &nbsp;·&nbsp;
        <a href="/health" target="_blank" rel="noopener">Health →</a>
      </div>
    </div>
    </div>
  </section>
</template>

<style scoped>
.capability-map{display:grid;grid-template-columns:1.25fr repeat(3,1fr);gap:1px;margin:0 0 34px;border:1px solid var(--border);background:var(--border);border-radius:10px;overflow:hidden}.capability-map>*{background:var(--ink-2);padding:20px}.capability-intro span,.capability-map article>b{color:var(--amber);font:9px var(--mono);letter-spacing:.12em}.capability-intro h2{font:22px var(--serif);margin:8px 0}.capability-map h3{font-size:13px;margin:10px 0 5px}.capability-map p{color:var(--text-3);font-size:11px;line-height:1.55}@media(max-width:900px){.capability-map{grid-template-columns:1fr 1fr}}@media(max-width:560px){.capability-map{grid-template-columns:1fr}}
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
.set-grid .set-row.engine-row,
.set-grid .set-row.asr-row { grid-row: span 2; }
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
.eng-row.readonly { cursor: default; }
.eng-row.readonly:hover { background: var(--ink-2); }
.eng-row.readonly.active:hover { background: var(--ink-3); }
.eng-row.switching { opacity: 0.72; pointer-events: none; }
.eng-row.disabled { opacity: 0.58; cursor: not-allowed; }
.eng-row.disabled:hover { background: var(--ink-2); }
.eng-row.active { background: var(--ink-3); }
.eng-list.compact .eng-row { padding: 12px 14px; }
.radio { width: 14px; height: 14px; border-radius: 50%; border: 1.5px solid var(--text-3); position: relative; }
.eng-row.active .radio { border-color: var(--amber); }
.eng-row.active .radio::after { content: ''; position: absolute; inset: 3px; border-radius: 50%; background: var(--amber); }
.info .n { font-family: var(--serif); font-size: 16px; color: var(--text); }
.info .m { font-family: var(--mono); font-size: 11px; color: var(--text-2); margin-top: 2px; }
.info .m b { color: var(--teal); font-weight: 500; margin-right: 4px; }
.info .m .sep { color: var(--text-3); margin: 0 4px; }
.info .m.muted { color: var(--text-3); line-height: 1.45; }
.pill {
  padding: 4px 8px;
  border: 1px solid var(--amber);
  border-radius: 999px;
  color: var(--amber);
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.06em;
}

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
.llm-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  margin-top: 14px;
}
.llm-form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.llm-form label span,
.llm-options label span {
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.06em;
}
.model-source{overflow-wrap:anywhere;color:var(--text-3)}
.run-provenance-hint{margin-top:12px;color:var(--text-3);font-size:10px;line-height:1.55}

.llm-secret-note {
  grid-column: 1 / -1;
  color: var(--text-muted);
  font-size: 0.82rem;
  line-height: 1.5;
}
.llm-form input,
.llm-form select {
  width: 100%;
  min-width: 0;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--ink-1);
  color: var(--text);
  padding: 0 10px;
  font-family: var(--mono);
  font-size: 11px;
}
.llm-options {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 12px;
}
.llm-options label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.llm-test-notice {
  margin-top: 10px;
  color: var(--text-3);
  font-family: var(--mono);
  font-size: 10px;
  line-height: 1.5;
}
.llm-error {
  margin-top: 10px;
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.5;
  color: #ff5f6d;
}
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
.config-hint {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  letter-spacing: 0.05em;
}
.config-hint code { color: var(--amber); font-family: var(--mono); font-size: 10px; }
.about { font-family: 'JetBrains Mono', monospace; font-size: 12px; color: var(--text-2); line-height: 1.7; }
.about a { color: var(--amber); }
.about a:hover { text-decoration: underline; }
.empty { padding: 30px; text-align: center; color: var(--text-3); font-family: var(--mono); font-size: 12px; }

/* 移动端适配:主网格原本固定三列(1.6fr 1fr 1fr)且无断点,手机上引擎卡片被挤、内容看不全。
   窄屏改单列堆叠,取消 engine/asr-row 的跨行(span 2 在单列无意义且会留空行),
   LLM 表单两列改单列,外边距收紧。eng-row 内部 auto/1fr/auto 不动(外层单列后已有足够宽度)。 */
@media (max-width: 900px) {
  .set-wrap { padding: 24px 20px 32px; }
  .set-grid { grid-template-columns: 1fr; }
  .set-grid .set-row.engine-row,
  .set-grid .set-row.asr-row { grid-row: auto; }
  .llm-form { grid-template-columns: 1fr; }
  .llm-detail .help { margin-left: 0; }
}
</style>
