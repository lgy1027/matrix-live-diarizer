<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

interface Props {
  speaker: string        // 派生的显示名 (Speaker 1 / Alice / 未知)
  score?: number         // 0-1, undefined = unknown
  showQuestion?: boolean // 强制显示 ?
}
const props = withDefaults(defineProps<Props>(), {
  score: undefined,
  showQuestion: false,
})
const { t } = useI18n()

const tier = computed(() => {
  if (props.score === undefined || props.score === null) return 'unknown'
  if (props.score >= 0.65) return 'high'
  if (props.score >= 0.4) return 'medium'
  return 'low'
})

const displayText = computed(() => {
  if (tier.value === 'low') return t('speaker.unknown')
  if (tier.value === 'medium' || props.showQuestion) return `${props.speaker}?`
  // high 或 unknown(score 缺失):保留原 speaker 名字,只换样式
  return props.speaker
})
</script>

<template>
  <span class="seg-speaker" :class="`confidence-${tier}`">{{ displayText }}</span>
</template>

<style scoped>
.seg-speaker {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.85em;
  font-weight: 500;
  user-select: none;
}
.confidence-high {
  border: 1px solid var(--amber, #ff6b35);
  color: var(--amber, #ff6b35);
  background: transparent;
}
.confidence-medium {
  border: 1px dashed var(--muted, #888);
  color: var(--muted, #888);
  background: transparent;
}
.confidence-low,
.confidence-unknown {
  border: 1px solid var(--border-soft, #ddd);
  color: var(--muted, #999);
  background: var(--ink-3, #f5f5f5);
}
</style>
