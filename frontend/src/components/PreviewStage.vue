<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

/**
 * 产物画台:固定尺寸内容(幻灯片页/海报)的缩放 + 抓取平移 + 翻页视图。
 * 设计工具隐喻 —— 灰台上白纸投影,工具条浮于底部。
 */
const props = withDefaults(
  defineProps<{
    srcdoc: string
    /** 内容自然尺寸(px)。 */
    w: number
    h: number
    /** 翻页器:总页数与当前页(1 起);0 = 无翻页。 */
    total?: number
    page?: number
  }>(),
  { total: 0, page: 0 },
)

const emit = defineEmits<{
  (e: 'prev'): void
  (e: 'next'): void
}>()

const MIN_SCALE = 0.2
const MAX_SCALE = 3
const PAD = 24 // 画台四周留白
const SLACK = 28 // 平移越界余量

const stageRef = ref<HTMLElement | null>(null)
const scale = ref(1)
const fitMode = ref(true)
const pan = ref({ x: 0, y: 0 })
const dragging = ref(false)
const stageW = ref(0)
const stageH = ref(0)

const limits = computed(() => ({
  x: Math.max(0, (props.w * scale.value - stageW.value) / 2 + SLACK),
  y: Math.max(0, (props.h * scale.value - stageH.value) / 2 + SLACK),
}))
const pannable = computed(
  () =>
    props.w * scale.value > stageW.value + 1 || props.h * scale.value > stageH.value + 1,
)
const pct = computed(() => `${Math.round(scale.value * 100)}%`)

function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v))
}

function clampPan() {
  pan.value = {
    x: clamp(pan.value.x, -limits.value.x, limits.value.x),
    y: clamp(pan.value.y, -limits.value.y, limits.value.y),
  }
}

function applyFit() {
  const s = Math.min(
    (stageW.value - PAD * 2) / props.w,
    (stageH.value - PAD * 2) / props.h,
    1,
  )
  scale.value = Number.isFinite(s) && s > 0 ? s : 1
  fitMode.value = true
  pan.value = { x: 0, y: 0 }
}

function zoomBy(factor: number) {
  scale.value = clamp(scale.value * factor, MIN_SCALE, MAX_SCALE)
  fitMode.value = false
  clampPan()
}

function zoom100() {
  scale.value = 1
  fitMode.value = false
  clampPan()
}

/* ── 抓取平移 ─────────────────────────────────────────── */
let drag: { id: number; x: number; y: number } | null = null

function onPointerDown(ev: PointerEvent) {
  if (ev.button !== 0 || !pannable.value) return
  drag = { id: ev.pointerId, x: ev.clientX, y: ev.clientY }
  dragging.value = true
  ;(ev.currentTarget as HTMLElement).setPointerCapture(ev.pointerId)
}

function onPointerMove(ev: PointerEvent) {
  if (!drag || ev.pointerId !== drag.id) return
  pan.value = {
    x: pan.value.x + (ev.clientX - drag.x),
    y: pan.value.y + (ev.clientY - drag.y),
  }
  drag.x = ev.clientX
  drag.y = ev.clientY
  clampPan()
}

function onPointerUp(ev: PointerEvent) {
  if (!drag || ev.pointerId !== drag.id) return
  drag = null
  dragging.value = false
  const el = ev.currentTarget as HTMLElement
  if (el.hasPointerCapture?.(ev.pointerId)) el.releasePointerCapture(ev.pointerId)
}

/** Ctrl/⌘+滚轮缩放;普通滚轮平移。 */
function onWheel(ev: WheelEvent) {
  if (ev.ctrlKey || ev.metaKey) {
    zoomBy(ev.deltaY < 0 ? 1.12 : 1 / 1.12)
  } else {
    pan.value = { x: pan.value.x - ev.deltaX, y: pan.value.y - ev.deltaY }
    clampPan()
  }
}

function onKeydown(ev: KeyboardEvent) {
  if (props.total > 1 && ev.key === 'ArrowLeft') {
    ev.preventDefault()
    emit('prev')
  } else if (props.total > 1 && ev.key === 'ArrowRight') {
    ev.preventDefault()
    emit('next')
  } else if (ev.key === '+' || ev.key === '=') {
    ev.preventDefault()
    zoomBy(1.12)
  } else if (ev.key === '-') {
    ev.preventDefault()
    zoomBy(1 / 1.12)
  } else if (ev.key === '0') {
    ev.preventDefault()
    applyFit()
  }
}

/* ── 尺寸跟随 ─────────────────────────────────────────── */
let observer: ResizeObserver | null = null

onMounted(() => {
  observer = new ResizeObserver((entries) => {
    const box = entries[0]?.contentRect
    if (!box) return
    stageW.value = box.width
    stageH.value = box.height
    if (fitMode.value) applyFit()
    else clampPan()
  })
  if (stageRef.value) observer.observe(stageRef.value)
})

onBeforeUnmount(() => observer?.disconnect())

watch(
  () => props.srcdoc,
  () => {
    applyFit()
  },
)

const paperStyle = computed(() => ({
  width: `${props.w}px`,
  height: `${props.h}px`,
  transform: `translate(${pan.value.x}px, ${pan.value.y}px) scale(${scale.value})`,
}))
</script>

<template>
  <div
    ref="stageRef"
    class="stage"
    :class="{ pannable, dragging }"
    tabindex="0"
    role="application"
    aria-label="预览画台:滚轮平移,Ctrl 加滚轮缩放,方向键翻页"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
    @wheel.prevent="onWheel"
    @keydown="onKeydown"
  >
    <div class="paper" :style="paperStyle">
      <iframe class="paper-frame" sandbox="" :srcdoc="srcdoc" title="产物预览" />
    </div>

    <div class="stage-bar" @pointerdown.stop>
      <template v-if="total > 1">
        <button type="button" class="sbtn" :disabled="page <= 1" aria-label="上一页" @click="emit('prev')">
          ‹
        </button>
        <span class="ind">{{ page }} / {{ total }}</span>
        <button type="button" class="sbtn" :disabled="page >= total" aria-label="下一页" @click="emit('next')">
          ›
        </button>
        <i class="bar-div" aria-hidden="true" />
      </template>
      <button type="button" class="sbtn" aria-label="缩小" @click="zoomBy(1 / 1.25)">−</button>
      <span class="ind">{{ pct }}</span>
      <button type="button" class="sbtn" aria-label="放大" @click="zoomBy(1.25)">+</button>
      <button type="button" class="sbtn txt" :class="{ on: fitMode }" @click="applyFit">适应</button>
      <button type="button" class="sbtn txt" @click="zoom100">1:1</button>
    </div>
  </div>
</template>

<style scoped>
.stage {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  background: var(--yx-stage);
  display: flex;
  align-items: center;
  justify-content: center;
  touch-action: none;
  outline-offset: -2px;
}
.stage.pannable {
  cursor: grab;
}
.stage.dragging {
  cursor: grabbing;
}
/* 拖动时让 iframe 不吞指针事件 */
.stage.dragging .paper-frame {
  pointer-events: none;
}
.paper {
  position: relative;
  flex-shrink: 0;
  background: #fff;
  box-shadow:
    0 12px 36px rgba(32, 32, 30, 0.16),
    0 2px 8px rgba(32, 32, 30, 0.08);
  will-change: transform;
}
.paper-frame {
  width: 100%;
  height: 100%;
  border: 0;
  display: block;
  background: #fff;
}
/* 浮动工具条 */
.stage-bar {
  position: absolute;
  left: 50%;
  bottom: 16px;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 4px 6px;
  background: rgba(255, 255, 255, 0.94);
  backdrop-filter: blur(6px);
  border: 1px solid var(--yx-line);
  border-radius: 999px;
  box-shadow: 0 4px 14px rgba(32, 32, 30, 0.1);
  user-select: none;
}
.sbtn {
  height: 26px;
  min-width: 26px;
  padding: 0 7px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  font-size: 14px;
  line-height: 1;
  color: var(--yx-ink-2);
  cursor: pointer;
  display: grid;
  place-items: center;
  transition:
    background 0.15s,
    color 0.15s;
}
.sbtn:hover:not(:disabled) {
  background: var(--yx-paper);
  color: var(--yx-ink);
}
.sbtn:disabled {
  opacity: 0.35;
  cursor: default;
}
.sbtn.txt {
  font-size: 12px;
}
/* 「适应」激活 = 状态指示而非行动点,用中性墨色,不与朱砂 CTA 抢色 */
.sbtn.txt.on {
  color: var(--yx-ink);
  background: var(--yx-paper);
}
.ind {
  font-size: 12px;
  color: var(--yx-ink-2);
  font-variant-numeric: tabular-nums;
  text-align: center;
  min-width: 46px;
  line-height: 26px;
}
.bar-div {
  width: 1px;
  height: 14px;
  background: var(--yx-line);
  margin: 0 4px;
}
</style>
