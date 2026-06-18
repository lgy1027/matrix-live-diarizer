<script setup lang="ts">
import { ref, watch } from 'vue'
import { useLiveStore, type LiveSegment } from '../stores/live'

interface Props {
  seg: LiveSegment | null
  visible: boolean
}
const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'close'): void
}>()

const live = useLiveStore()
const newName = ref('')

function doRename() {
  if (!props.seg || !newName.value.trim()) return
  live.renameSegmentSpeaker(props.seg.id, newName.value.trim())
  newName.value = ''
  emit('close')
}

function doMerge(target: string) {
  if (!props.seg) return
  live.mergeSegmentSpeaker(props.seg.id, target)
  emit('close')
}

function doRevert() {
  if (!props.seg) return
  live.revertSegmentRename(props.seg.id)
  emit('close')
}

function doEnroll() {
  // 后续接入 enroll 流程;本 commit 占位
  console.info('[speaker-menu] enroll placeholder', props.seg?.id)
  emit('close')
}

watch(() => props.visible, (v) => {
  if (!v) newName.value = ''
})
</script>

<template>
  <div v-if="visible && seg" class="speaker-menu-overlay" @click.self="emit('close')">
    <div class="speaker-menu">
      <h4 class="menu-title">说话人操作</h4>
      <div class="menu-row">
        <input
          v-model="newName"
          placeholder="改成本次新名字"
          class="menu-input"
          @keyup.enter="doRename"
        />
        <button class="menu-btn" :disabled="!newName.trim()" @click="doRename">改名</button>
      </div>

      <div class="menu-row">
        <span class="menu-label">合并到已有:</span>
        <div class="menu-btns">
          <button
            v-for="[spkId, n] in live.sessionSpeakers"
            :key="spkId"
            class="menu-btn"
            :disabled="seg && spkId === seg.speaker"
            @click="doMerge(spkId)"
          >
            Speaker {{ n }}
          </button>
        </div>
      </div>

      <div class="menu-row">
        <button class="menu-btn" @click="doEnroll">保存为新声纹</button>
        <button
          v-if="seg && live.speakerOverride.has(seg.id)"
          class="menu-btn"
          @click="doRevert"
        >恢复原始 ID</button>
      </div>

      <button class="menu-close" @click="emit('close')">取消</button>
    </div>
  </div>
</template>

<style scoped>
.speaker-menu-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.speaker-menu {
  background: var(--bg, #fff);
  color: var(--fg, #111);
  padding: 24px;
  border-radius: 12px;
  min-width: 320px;
  max-width: 480px;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
}
.menu-title {
  margin: 0 0 16px;
  font-size: 1.05em;
  font-weight: 600;
}
.menu-row {
  display: flex;
  gap: 8px;
  margin: 12px 0;
  flex-wrap: wrap;
  align-items: center;
}
.menu-label {
  font-size: 0.85em;
  color: var(--muted, #666);
}
.menu-btns {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.menu-input {
  flex: 1;
  min-width: 0;
  padding: 8px;
  border: 1px solid var(--border-soft, #ccc);
  border-radius: 6px;
  background: transparent;
  color: inherit;
  font: inherit;
}
.menu-btn {
  padding: 6px 12px;
  border: 1px solid var(--border-soft, #ccc);
  border-radius: 6px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
}
.menu-btn:hover:not(:disabled) {
  border-color: var(--amber, #f59e0b);
}
.menu-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.menu-close {
  margin-top: 16px;
  width: 100%;
  padding: 8px;
  border: none;
  background: var(--ink-3, #f5f5f5);
  color: inherit;
  border-radius: 6px;
  cursor: pointer;
  font: inherit;
}
</style>