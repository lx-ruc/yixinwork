<script setup lang="ts">
/**
 * 可拖动分隔条:对话区 ↔ 产物预览区。
 * 指针拖动 / 双击复位 / 左右方向键微调;宽度逻辑由父组件持有。
 */
const emit = defineEmits<{
  /** 拖动中,上报指针 clientX(父组件换算成比例)。 */
  (e: 'resize', clientX: number): void
  (e: 'nudge', direction: -1 | 1): void
  (e: 'reset'): void
}>()

function onPointerDown(ev: PointerEvent) {
  if (ev.button !== 0) return
  emit('resize', ev.clientX)
  const target = ev.currentTarget as HTMLElement
  target.setPointerCapture(ev.pointerId)
  target.classList.add('dragging')
}

function onPointerMove(ev: PointerEvent) {
  if (!(ev.currentTarget as HTMLElement).hasPointerCapture?.(ev.pointerId)) return
  emit('resize', ev.clientX)
}

function onPointerUp(ev: PointerEvent) {
  const target = ev.currentTarget as HTMLElement
  target.classList.remove('dragging')
  if (target.hasPointerCapture?.(ev.pointerId)) target.releasePointerCapture(ev.pointerId)
}

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'ArrowLeft') {
    ev.preventDefault()
    emit('nudge', -1)
  } else if (ev.key === 'ArrowRight') {
    ev.preventDefault()
    emit('nudge', 1)
  }
}
</script>

<template>
  <div
    class="split-handle"
    role="separator"
    aria-orientation="vertical"
    aria-label="拖动调整预览区宽度,双击复位"
    tabindex="0"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
    @dblclick="emit('reset')"
    @keydown="onKeydown"
  >
    <span class="grip" aria-hidden="true" />
  </div>
</template>

<style scoped>
.split-handle {
  flex: 0 0 10px;
  margin: 0 -5px;
  z-index: 5;
  cursor: col-resize;
  touch-action: none;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
}
/* 中线:默认发丝线,悬停/拖动/聚焦转朱砂 */
.split-handle::before {
  content: '';
  width: 1px;
  height: 100%;
  background: var(--yx-line);
  transition: background 0.15s;
}
.split-handle:hover::before,
.split-handle:focus-visible::before,
.split-handle.dragging::before {
  background: var(--yx-red);
}
.grip {
  width: 3px;
  height: 26px;
  border-radius: 2px;
  background: var(--yx-line);
  transition: background 0.15s;
}
.split-handle:hover .grip,
.split-handle.dragging .grip {
  background: var(--yx-red-border);
}
/* 拖动时全局统一光标 */
.split-handle.dragging {
  cursor: col-resize;
}
</style>
