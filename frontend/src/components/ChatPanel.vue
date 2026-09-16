<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { useWorkspaceStore, type CardEntry, type ThinkSegment, type ThinkingEntry } from '../stores/workspace'
import type { MessageInfo } from '../api/sessions'

const store = useWorkspaceStore()
const input = ref('')
const streamRef = ref<HTMLDivElement | null>(null)
const inputRef = ref<{ focus: () => void } | null>(null)

/** 空态快捷指令:点击填入输入框(等用户补充细节后发送)。 */
const QUICK_PROMPTS = [
  '帮我写一份项目周报',
  '把这份资料做成幻灯片',
  '设计一张活动海报',
  '整理一份数据表格',
]

/** 助手已完成消息:markdown → 净化 HTML(流式中的消息仍按纯文本增量渲染)。 */
function renderMd(text: string): string {
  return DOMPurify.sanitize(marked.parse(text, { async: false }) as string)
}

/**
 * 回车发送、Shift+回车换行。
 * 中文输入法按回车确认拼音/候选词时 keydown 也是 Enter,必须放行给输入法,
 * 否则"输入 PPT 敲回车"会把未上屏的字母直接提交(isComposing / 229 判定)。
 */
function onInputKeydown(e: KeyboardEvent): void {
  if (e.key !== 'Enter') return
  if (e.isComposing || e.keyCode === 229) return
  if (e.shiftKey) return
  e.preventDefault()
  void onSend()
}

async function onSend() {
  const content = input.value.trim()
  if (!content || store.streaming) return
  if (!store.currentSession) {
    ElMessage.warning('请先选择或新建会话')
    return
  }
  input.value = ''
  try {
    await store.send(content)
  } catch (e) {
    ElMessage.error(`发送失败: ${(e as Error).message}`)
  }
}

function usePrompt(text: string) {
  input.value = text
  inputRef.value?.focus()
}

async function onResolve(messageId: string, action: 'confirm' | 'decline') {
  try {
    await store.resolveRoute(messageId, action)
  } catch (e) {
    ElMessage.error(`操作失败: ${(e as Error).message}`)
  }
}

async function onApprove() {
  try {
    await store.approvePreview()
    ElMessage.success('已交付')
  } catch (e) {
    ElMessage.error(`交付失败: ${(e as Error).message}`)
  }
}

const inputPlaceholder = computed(() => {
  if (!store.currentSession) return '请先选择会话'
  if (store.activePreview) return '输入修改意见，Enter 发送（增量修改）'
  if (store.currentSession.mode === 'work') return '工作模式：描述任务；执行中输入即为补充指令'
  return '输入消息，Enter 发送'
})

function cardOf(m: MessageInfo): CardEntry {
  return m as CardEntry
}

/** 流式中的消息(无 id)按纯文本渲染,已完成的按 markdown 渲染。 */
function isStreamingMsg(m: MessageInfo): boolean {
  return m.role === 'assistant' && m.id === ''
}

/** 思考块展开态:流式默认展开,完成默认折叠;用户点击覆盖。 */
const openOverrides = ref<Record<string, boolean>>({})

function thinkDone(m: MessageInfo): boolean {
  return (m.extra as { done?: boolean } | null)?.done === true
}

/** 思考块段：推理文本 + 过程动作行（历史回放的块无 segments 时回退纯文本）。 */
function thinkSegs(m: MessageInfo): ThinkSegment[] {
  const segs = (m as ThinkingEntry).segments
  if (segs && segs.length) return segs
  return m.content ? [{ kind: 'reason', text: m.content }] : []
}

function thinkOpen(m: MessageInfo): boolean {
  return openOverrides.value[m.id] ?? !thinkDone(m)
}

function toggleThink(m: MessageInfo) {
  openOverrides.value = { ...openOverrides.value, [m.id]: !thinkOpen(m) }
}

/** 流式思考块内部滚到底(块内滚动,不扰动整体消息流位置)。 */
watch(
  () =>
    store.messages
      .filter((m) => m.role === 'thinking' && !thinkDone(m))
      .map((m) => m.content.length)
      .join(','),
  async () => {
    await nextTick()
    const live = streamRef.value?.querySelector<HTMLDivElement>('.think-body.live')
    if (live) live.scrollTop = live.scrollHeight
  },
)

watch(
  () => store.messages.length,
  async () => {
    await nextTick()
    streamRef.value?.scrollTo({ top: streamRef.value.scrollHeight })
  },
)
</script>

<template>
  <div class="chat-panel">
    <header class="chat-header">
      <el-radio-group
        :model-value="store.currentSession?.mode ?? 'chat'"
        :disabled="!store.currentSession"
        @update:model-value="(v: string | number | boolean | undefined) => store.switchMode(v as 'chat' | 'work')"
      >
        <el-radio-button value="chat">普通对话</el-radio-button>
        <el-radio-button value="work">工作模式</el-radio-button>
      </el-radio-group>
      <span v-if="store.currentSession" class="session-title" :title="store.currentSession.title">
        {{ store.currentSession.title }}
      </span>
    </header>

    <div ref="streamRef" class="chat-stream">
      <!-- 空态:印章 + 快捷指令 -->
      <div v-if="store.messages.length === 0" class="chat-empty">
        <span class="seal-ghost" aria-hidden="true">亿</span>
        <h3>把一句话,交成一件事</h3>
        <p>描述你要的结果 —— 工作模式里完成起草、排版与修订,交付前可预览</p>
        <div class="prompts">
          <button v-for="q in QUICK_PROMPTS" :key="q" type="button" @click="usePrompt(q)">
            {{ q }}
          </button>
        </div>
      </div>
      <template v-for="m in store.messages" :key="m.role + '-' + (m.id ?? m.content.length)">
        <!-- 路由确认卡片：任务型消息弹出，确认入工作模式 / 拒绝回直答 -->
        <div v-if="m.role === 'route_card'" class="msg-row assistant">
          <div class="route-card">
            <div class="route-title">这看起来像一项工作</div>
            <div class="route-quote">“{{ m.content }}”</div>
            <div class="route-reason">{{ cardOf(m).extra.reason }}</div>
            <div v-if="cardOf(m).extra.status === 'pending'" class="route-actions">
              <el-button
                size="small"
                type="primary"
                :disabled="store.streaming"
                @click="onResolve(m.id, 'confirm')"
              >
                切换到工作模式
              </el-button>
              <el-button size="small" :disabled="store.streaming" @click="onResolve(m.id, 'decline')">
                继续对话
              </el-button>
            </div>
            <div v-else class="route-result">
              {{ cardOf(m).extra.status === 'confirmed' ? '已进入工作模式' : '已按普通对话回答' }}
            </div>
          </div>
        </div>
        <!-- 系统提示行（任务创建等） -->
        <div v-else-if="m.role === 'system'" class="system-row">{{ m.content }}</div>
        <!-- 思考过程：提问下方的小字折叠块（流式展开，完成折叠；非对话气泡） -->
        <div v-else-if="m.role === 'thinking'" class="think-row">
          <div class="think-block">
            <button
              type="button"
              class="think-head"
              :aria-expanded="thinkOpen(m)"
              @click="toggleThink(m)"
            >
              <span class="chev" aria-hidden="true">{{ thinkOpen(m) ? '▾' : '▸' }}</span>
              <span v-if="!thinkDone(m)" class="think-live">
                <i class="dot" aria-hidden="true" />
                思考中
              </span>
              <span v-else>思考过程 · {{ m.content.length }} 字</span>
            </button>
            <div v-if="thinkOpen(m)" class="think-body" :class="{ live: !thinkDone(m) }">
              <span
                v-for="(seg, i) in thinkSegs(m)"
                :key="i"
                class="think-seg"
                :class="seg.kind"
              >{{ seg.text }}</span>
            </div>
          </div>
        </div>
        <!-- 常规消息气泡：用户 = 朱砂,助手 = 白卡(markdown) -->
        <div v-else class="msg-row" :class="m.role">
          <div v-if="m.role === 'assistant' && !isStreamingMsg(m)" class="bubble assistant md" v-html="renderMd(m.content)" />
          <div v-else class="bubble" :class="m.role">
            <span class="content">{{ m.content }}</span>
            <span v-if="isStreamingMsg(m)" class="cursor">▌</span>
          </div>
        </div>
      </template>
    </div>

    <footer class="chat-input">
      <!-- 预览就绪：满意交付；修改意见直接走输入框（后端 preview_ready 分支） -->
      <div v-if="store.activePreview" class="preview-bar">
        <span class="preview-bar-text">预览已就绪</span>
        <el-button size="small" type="primary" :disabled="store.streaming" @click="onApprove">
          确认交付
        </el-button>
        <span class="hint">或直接在下方输入修改意见</span>
      </div>
      <div class="input-row">
        <el-input
          ref="inputRef"
          v-model="input"
          type="textarea"
          :rows="2"
          resize="none"
          :placeholder="inputPlaceholder"
          :disabled="!store.currentSession || store.streaming"
          @keydown="onInputKeydown"
        />
        <el-button
          type="primary"
          class="send-btn"
          :loading="store.streaming"
          :disabled="!store.currentSession"
          @click="onSend"
        >
          发送
        </el-button>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--yx-paper);
}
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  background: #fff;
  border-bottom: 1px solid var(--yx-line);
}
.session-title {
  font-size: 13px;
  color: var(--yx-ink-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 模式切换:轻量态(选中=朱晕底,不与主 CTA 抢实心红) */
.chat-header :deep(.el-radio-button__inner) {
  background: #fff;
  border-color: var(--yx-line);
  color: var(--yx-ink-2);
  box-shadow: none;
  font-weight: 400;
}
.chat-header :deep(.el-radio-button.is-active .el-radio-button__inner) {
  background: var(--yx-red-wash);
  border-color: var(--yx-red-border);
  color: var(--yx-red);
  font-weight: 600;
  box-shadow: none;
}
.chat-stream {
  flex: 1;
  overflow-y: auto;
  padding: 20px 18px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
/* ── 空态 ─────────────────────────────────────────── */
.chat-empty {
  margin: auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
  padding: 24px;
  max-width: 420px;
}
.seal-ghost {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 10px;
  border: 1.5px dashed var(--yx-red-border);
  background: var(--yx-red-wash);
  color: var(--yx-red);
  font-family: var(--yx-serif);
  font-size: 21px;
  font-weight: 700;
  margin-bottom: 6px;
  user-select: none;
}
.chat-empty h3 {
  margin: 0;
  font-family: var(--yx-serif);
  font-size: 19px;
  font-weight: 600;
  color: var(--yx-ink);
  letter-spacing: 1px;
}
.chat-empty p {
  margin: 0;
  font-size: 13px;
  color: var(--yx-ink-3);
  line-height: 1.8;
}
.prompts {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
  margin-top: 8px;
}
.prompts button {
  border: 1px solid var(--yx-line);
  background: #fff;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  color: var(--yx-ink-2);
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s,
    background 0.15s;
}
.prompts button:hover {
  border-color: var(--yx-red);
  color: var(--yx-red);
  background: var(--yx-red-wash);
}
/* ── 消息 ─────────────────────────────────────────── */
.msg-row {
  display: flex;
}
.msg-row.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 76%;
  padding: 9px 14px;
  font-size: 14px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
/* 用户:朱砂实心,右下小圆角(话音方向) */
.bubble.user {
  background: var(--yx-red);
  color: #fff;
  border-radius: 12px 12px 4px 12px;
  box-shadow: 0 2px 8px rgba(201, 37, 45, 0.22);
}
/* 助手:白纸卡(行宽封顶,长文可读) */
.bubble.assistant {
  background: #fff;
  border: 1px solid var(--yx-line);
  border-radius: 12px 12px 12px 4px;
  box-shadow: 0 1px 3px rgba(32, 32, 30, 0.05);
  max-width: min(76%, 560px);
}
/* 助手 markdown 排版 */
.bubble.md :deep(p) {
  margin: 0 0 6px;
}
.bubble.md :deep(p:last-child) {
  margin-bottom: 0;
}
.bubble.md :deep(ul),
.bubble.md :deep(ol) {
  margin: 4px 0 6px;
  padding-left: 20px;
}
.bubble.md :deep(li) {
  margin: 2px 0;
}
.bubble.md :deep(strong) {
  font-weight: 600;
}
.bubble.md :deep(h1),
.bubble.md :deep(h2),
.bubble.md :deep(h3) {
  margin: 10px 0 6px;
  font-size: 15px;
  font-weight: 600;
}
.bubble.md :deep(code) {
  background: var(--yx-paper);
  padding: 1px 5px;
  border-radius: 4px;
  font-size: 13px;
}
.bubble.md :deep(pre) {
  background: var(--yx-paper);
  padding: 10px 12px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 6px 0;
}
.bubble.md :deep(pre code) {
  background: none;
  padding: 0;
}
.bubble.md :deep(blockquote) {
  margin: 6px 0;
  padding: 2px 10px;
  border-left: 2px solid var(--yx-red-border);
  color: var(--yx-ink-2);
}
.bubble.md :deep(table) {
  border-collapse: collapse;
  margin: 6px 0;
  font-size: 13px;
}
.bubble.md :deep(th),
.bubble.md :deep(td) {
  border: 1px solid var(--yx-line);
  padding: 4px 10px;
}
/* ── 路由卡片:红脊白卡 ─────────────────────────────── */
.route-card {
  max-width: 86%;
  padding: 12px 16px;
  border: 1px solid var(--yx-line);
  border-left: 3px solid var(--yx-red);
  border-radius: 10px;
  background: #fff;
  font-size: 14px;
  box-shadow: 0 1px 3px rgba(32, 32, 30, 0.05);
}
.route-title {
  font-weight: 600;
  margin-bottom: 6px;
}
.route-quote {
  color: var(--yx-ink-2);
  margin-bottom: 4px;
  word-break: break-word;
}
.route-reason {
  color: var(--yx-ink-3);
  font-size: 12px;
  margin-bottom: 10px;
}
.route-actions {
  display: flex;
  gap: 8px;
}
.route-result {
  color: var(--yx-ink-3);
  font-size: 12px;
}
/* ── 思考过程:提问下方的安静小字 ──────────────────── */
.think-row {
  display: flex;
}
.think-block {
  max-width: min(76%, 560px);
}
.think-head {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  background: none;
  padding: 2px 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--yx-ink-3);
  cursor: pointer;
  border-radius: 4px;
  transition: color 0.15s;
}
.think-head:hover {
  color: var(--yx-ink-2);
}
.think-head:focus-visible {
  outline: 2px solid var(--yx-red-border);
  outline-offset: 2px;
}
.chev {
  font-size: 10px;
  width: 10px;
  text-align: center;
}
.think-live {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--yx-ink-2);
}
.think-live .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--yx-red);
  animation: think-pulse 1.1s ease-in-out infinite;
}
@keyframes think-pulse {
  50% {
    opacity: 0.25;
  }
}
.think-body {
  margin-top: 2px;
  padding: 2px 0 2px 10px;
  border-left: 2px solid var(--yx-line);
  font-size: 12px;
  line-height: 1.75;
  color: var(--yx-ink-3);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 176px;
  overflow-y: auto;
}
.think-body.live {
  color: var(--yx-ink-2);
}
/* 推理文本段:随文流排 */
.think-seg.reason {
  display: inline;
}
/* 动作行:块级独占,更安静,带 › 记号 */
.think-seg.action {
  display: block;
  margin: 3px 0;
  color: var(--yx-ink-3);
}
.think-seg.action::before {
  content: '› ';
  color: var(--yx-red-border);
}
@media (prefers-reduced-motion: reduce) {
  .think-live .dot {
    animation: none;
  }
}
/* ── 系统行 ───────────────────────────────────────── */
.system-row {
  align-self: center;
  color: var(--yx-ink-3);
  font-size: 12px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--yx-line-soft);
  border-radius: 8px;
  padding: 3px 12px;
  max-width: 88%;
  text-align: center;
}
.cursor {
  animation: blink 1s step-start infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
/* ── 输入区 ───────────────────────────────────────── */
.chat-input {
  padding: 12px 16px 14px;
  background: var(--yx-paper);
  border-top: 1px solid var(--yx-line);
}
.preview-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  margin-bottom: 10px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid var(--yx-red-border);
  font-size: 13px;
}
.preview-bar-text {
  font-weight: 500;
}
.preview-bar .hint {
  color: var(--yx-ink-3);
  font-size: 12px;
}
.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.input-row :deep(.el-textarea__inner) {
  background: #fff;
  border-color: var(--yx-line);
  border-radius: 10px;
  box-shadow: none;
}
.input-row :deep(.el-textarea__inner:focus) {
  border-color: var(--yx-red);
}
.send-btn {
  height: 54px;
  border-radius: 10px;
  padding: 0 22px;
}
</style>
