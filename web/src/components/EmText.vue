<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ text: string }>()

const parts = computed(() => {
  const out: Array<{ text: string; em: boolean }> = []
  const re = /<em>(.*?)<\/em>/g
  let last = 0
  let match: RegExpExecArray | null
  while ((match = re.exec(props.text)) !== null) {
    if (match.index > last) out.push({ text: props.text.slice(last, match.index), em: false })
    out.push({ text: match[1], em: true })
    last = match.index + match[0].length
  }
  if (last < props.text.length) out.push({ text: props.text.slice(last), em: false })
  return out
})
</script>

<template>
  <template v-for="(part, index) in parts" :key="index">
    <em v-if="part.em">{{ part.text }}</em>
    <template v-else>{{ part.text }}</template>
  </template>
</template>
