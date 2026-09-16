<script setup lang="ts">
import { onMounted, ref } from 'vue'
import ChatPanel from '../components/ChatPanel.vue'
import ArtifactPanel from '../components/ArtifactPanel.vue'
import SplitHandle from '../components/SplitHandle.vue'

/** 预览区宽度占比:拖动/微调后写入 localStorage 记忆。 */
const SPLIT_KEY = 'yx-preview-split'
const MIN_PCT = 0.26
const MAX_PCT = 0.74
const DEFAULT_PCT = 0.44

const rootRef = ref<HTMLElement | null>(null)
const previewPct = ref(DEFAULT_PCT)

function clampPct(v: number): number {
  return Math.min(MAX_PCT, Math.max(MIN_PCT, v))
}

function persist() {
  localStorage.setItem(SPLIT_KEY, String(Math.round(previewPct.value * 1000) / 1000))
}

onMounted(() => {
  const saved = Number.parseFloat(localStorage.getItem(SPLIT_KEY) ?? '')
  if (Number.isFinite(saved) && saved > 0 && saved <= 1) {
    previewPct.value = clampPct(saved)
  }
})

function onResize(clientX: number) {
  const rect = rootRef.value?.getBoundingClientRect()
  if (!rect || rect.width <= 0) return
  previewPct.value = clampPct((rect.right - clientX) / rect.width)
  persist()
}

function onNudge(direction: -1 | 1) {
  previewPct.value = clampPct(previewPct.value + direction * 0.02)
  persist()
}

function onReset() {
  previewPct.value = DEFAULT_PCT
  persist()
}
</script>

<template>
  <div ref="rootRef" class="workspace-split">
    <section class="chat-side">
      <ChatPanel />
    </section>
    <SplitHandle @resize="onResize" @nudge="onNudge" @reset="onReset" />
    <section class="artifact-side" :style="{ flexBasis: `${previewPct * 100}%` }">
      <ArtifactPanel />
    </section>
  </div>
</template>

<style scoped>
.workspace-split {
  display: flex;
  flex: 1;
  min-height: 0;
}
.chat-side {
  flex: 1 1 auto;
  min-width: 360px;
}
.artifact-side {
  flex: 0 0 44%;
  min-width: 320px;
  display: flex;
  flex-direction: column;
  background: var(--yx-stage);
}
</style>
