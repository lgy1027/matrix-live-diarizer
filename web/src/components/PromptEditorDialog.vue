<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { LlmPrompts } from '../api/llm'

const props = defineProps<{ initial: LlmPrompts; saving?: boolean }>()
const emit = defineEmits<{ close: []; save: [LlmPrompts] }>()
const { t } = useI18n()

const summarize = ref(props.initial.summarize)
const actionItems = ref(props.initial.action_items)
const minutes = ref(props.initial.minutes)

function submit() {
  emit('save', {
    summarize: summarize.value,
    action_items: actionItems.value,
    minutes: minutes.value,
  })
}
</script>

<template>
  <div class="modal-mask" @click.self="emit('close')">
    <div class="modal-card" role="dialog">
      <div class="modal-title">📝 {{ t('settings.llm.promptsTitle') || 'Prompt 模板' }}</div>
      <p class="modal-sub">{{ t('settings.llm.promptsDesc') || '自定义摘要/行动项/纪要的 LLM 提示词模板,保存后立即生效,重启不丢。' }}</p>
      <div class="field-block">
        <label>{{ t('settings.llm.promptSummarize') || '摘要' }}</label>
        <textarea v-model="summarize" rows="5"></textarea>
        <em class="hint">{{ (t('settings.llm.promptPlaceholder') || '占位符 {transcript} = 转写文本') + (t('settings.llm.promptMaxWordsHint') || '，{max_words} = 目标字数(按时长自适应)') }}</em>
      </div>
      <div class="field-block">
        <label>{{ t('settings.llm.promptActions') || '行动项' }}</label>
        <textarea v-model="actionItems" rows="5"></textarea>
        <em class="hint">{{ t('settings.llm.promptPlaceholder') || '占位符 {transcript} = 转写文本' }}</em>
      </div>
      <div class="field-block">
        <label>{{ t('settings.llm.promptMinutes') || '纪要' }}</label>
        <textarea v-model="minutes" rows="6"></textarea>
        <em class="hint">{{ t('settings.llm.promptPlaceholder') || '占位符 {transcript} = 转写文本' }}</em>
      </div>
      <div class="modal-actions">
        <button class="btn ghost" type="button" @click="emit('close')">{{ t('btn.cancel') || '取消' }}</button>
        <button class="btn primary" type="button" :disabled="props.saving" @click="submit">
          {{ props.saving ? '…' : (t('settings.llm.promptsSave') || '保存') }}
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
  overflow-y: auto;
  padding: 40px 0;
  animation: fadeIn 0.15s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
.modal-card {
  background: var(--ink-2);
  border: 1px solid var(--teal);
  border-radius: 10px;
  padding: 28px 32px;
  width: min(680px, 92vw);
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.6);
}
.modal-title {
  font-family: var(--serif);
  font-size: 22px;
  margin-bottom: 8px;
  color: var(--teal);
}
.modal-sub {
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.6;
  margin-bottom: 18px;
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
.field-block textarea {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--ink-1);
  color: var(--text);
  padding: 8px 10px;
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.5;
  resize: vertical;
}
.hint {
  display: block;
  font-style: normal;
  font-family: var(--mono);
  font-size: 10px;
  color: var(--text-3);
  line-height: 1.5;
  margin-top: 4px;
}
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
</style>
