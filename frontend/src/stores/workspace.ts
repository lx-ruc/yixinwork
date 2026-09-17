import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  listTaskArtifacts,
  type ArtifactInfo,
} from '../api/artifacts'
import {
  createSession,
  listMessages,
  listSessions,
  listTasks,
  patchSession,
  routeConfirm,
  streamMessage,
  taskFeedback,
  type MessageInfo,
  type SessionInfo,
} from '../api/sessions'
import { uploadAttachments, type AttachmentMeta } from '../api/uploads'

/** 确认卡片在消息流中的伪消息角色（对应后端 route_card 事件）。 */
export type CardEntry = MessageInfo & {
  role: 'route_card'
  extra: { reason: string; status: 'pending' | 'confirmed' | 'declined' }
}

/** 思考块内段：推理文本或过程动作（任务创建/工具调用等），分开着色。 */
export interface ThinkSegment {
  kind: 'reason' | 'action'
  text: string
}

/** 思考过程在消息流中的伪消息角色：渲染为提问下方的小字折叠块（非对话气泡）。 */
export type ThinkingEntry = MessageInfo & {
  role: 'thinking'
  segments: ThinkSegment[]
  extra: { done: boolean } | null
}

/** 预览就绪状态：满意交付 / 输入修改意见（跟随最近任务）。 */
export interface ActivePreview {
  taskId: string
  content: string
}

/** 过程事件：并入思考块作为动作行，而非独立系统行。 */
const PROCESS_EVENTS = new Set([
  'task_created',
  'task_started',
  'tool_call',
  'tool_result',
  'agent_message', // 执行中间的解说（如"重新整理后再次保存"）；最终总结由 preview_ready 气泡呈现
  'steering_queued',
  'steering_injected',
  'task_revising',
])

/** 工作台全局状态：会话列表、当前会话、消息、流式状态、预览反馈。 */
export const useWorkspaceStore = defineStore('workspace', () => {
  const sessions = ref<SessionInfo[]>([])
  const currentSession = ref<SessionInfo | null>(null)
  const messages = ref<MessageInfo[]>([])
  const streaming = ref(false)
  const activePreview = ref<ActivePreview | null>(null)
  const artifacts = ref<ArtifactInfo[]>([])

  async function refreshSessions() {
    sessions.value = await listSessions()
  }

  async function newSession() {
    const s = await createSession()
    sessions.value.unshift(s)
    await selectSession(s)
  }

  async function selectSession(s: SessionInfo) {
    currentSession.value = s
    pendingAttachments.value = [] // 待发附件不跨会话携带
    const [raw, tasks] = await Promise.all([
      listMessages(s.id),
      listTasks(s.id).catch(() => []),
    ])
    messages.value = expandCards(raw)
    // 恢复未完结任务的预览反馈态
    const pending = tasks.find((t) => t.status === 'preview_ready')
    const previewMsg = [...raw].reverse().find((m) => m.extra?.kind === 'preview')
    activePreview.value =
      pending && previewMsg ? { taskId: pending.id, content: previewMsg.content } : null
    // 恢复最近任务的产物版本链（交付/预览任务均可见可下载）
    const artifactTask = pending ?? tasks[0]
    if (artifactTask) {
      void refreshArtifacts(artifactTask.id)
    } else {
      artifacts.value = []
    }
  }

  /** 拉取任务产物版本链（preview_ready / 交付后 / 会话切换时）。 */
  async function refreshArtifacts(taskId: string) {
    artifacts.value = await listTaskArtifacts(taskId).catch(() => [])
  }

  async function switchMode(mode: 'chat' | 'work') {
    if (!currentSession.value || currentSession.value.mode === mode) return
    await applyMode(mode, true)
  }

  async function applyMode(mode: 'chat' | 'work', patchRemote = false) {
    if (!currentSession.value) return
    const updated = patchRemote
      ? await patchSession(currentSession.value.id, { mode })
      : { ...currentSession.value, mode }
    currentSession.value = updated
    const idx = sessions.value.findIndex((x) => x.id === updated.id)
    if (idx >= 0) sessions.value[idx] = updated
  }

  /** 待发附件（已上传暂存）；服务端确认收到消息（user_message）后清空。 */
  const pendingAttachments = ref<AttachmentMeta[]>([])
  const uploading = ref(false)

  /** 选择文件即上传暂存（失败抛给组件提示；成功后追加到待发列表）。 */
  async function addAttachments(files: File[]) {
    uploading.value = true
    try {
      const metas = await uploadAttachments(files)
      pendingAttachments.value = [...pendingAttachments.value, ...metas]
    } finally {
      uploading.value = false
    }
  }

  function removeAttachment(id: string) {
    pendingAttachments.value = pendingAttachments.value.filter((a) => a.id !== id)
  }

  /** 发送消息：SSE 事件驱动渲染（语义由后端按会话模式/任务状态决定）。 */
  async function send(content: string) {
    if (!currentSession.value || streaming.value) return
    streaming.value = true
    const attachmentIds = pendingAttachments.value.map((a) => a.id)
    try {
      await streamMessage(currentSession.value.id, content, handleEvent, attachmentIds)
    } finally {
      streaming.value = false
      void syncAutoTitle()
    }
  }

  /** 首条消息后后端已按内容改写标题；仍是占位标题时拉最新列表同步（失败静默）。 */
  async function syncAutoTitle() {
    const cur = currentSession.value
    if (!cur || cur.title !== '新会话') return
    try {
      const fresh = (await listSessions()).find((s) => s.id === cur.id)
      if (fresh && fresh.title !== cur.title) {
        currentSession.value = fresh
        const idx = sessions.value.findIndex((s) => s.id === fresh.id)
        if (idx >= 0) sessions.value[idx] = fresh
      }
    } catch {
      /* 标题同步失败不影响会话本身 */
    }
  }

  /** 确认卡片流转：confirm=携带原消息入工作模式；decline=原消息直答。 */
  async function resolveRoute(messageId: string, action: 'confirm' | 'decline') {
    if (!currentSession.value || streaming.value) return
    streaming.value = true
    try {
      await routeConfirm(currentSession.value.id, messageId, action, (ev) => {
        if (ev.type === 'mode_switched') {
          void applyMode(ev.mode)
        } else {
          handleEvent(ev)
        }
      })
      markCard(messageId, action === 'confirm' ? 'confirmed' : 'declined')
    } finally {
      streaming.value = false
    }
  }

  /** 预览满意 → 交付（修改意见走普通 send：preview_ready 分支即修改续跑）。 */
  async function approvePreview() {
    if (!activePreview.value || streaming.value) return
    streaming.value = true
    try {
      await taskFeedback(activePreview.value.taskId, 'approve', handleEvent)
    } finally {
      streaming.value = false
    }
  }

  function pushSystem(text: string) {
    messages.value.push({
      id: `sys-${messages.value.length}`,
      role: 'system',
      content: text,
      extra: null,
      created_at: null,
    })
  }

  function thinkDone(m: MessageInfo): boolean {
    return m.role === 'thinking' && (m.extra as { done?: boolean } | null)?.done === true
  }

  /** 任何非过程事件到达即封口当前思考块（回复/预览/终态之后各成一块）。 */
  function closeThinking() {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'thinking' && !thinkDone(last)) {
      last.extra = { done: true }
    }
  }

  /** 取未封口的思考块；没有则新开一块（过程事件与推理流共用）。 */
  function ensureOpenThinking(): ThinkingEntry {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'thinking' && !thinkDone(last)) {
      return last as ThinkingEntry
    }
    const entry: ThinkingEntry = {
      id: `think-${messages.value.length}`,
      role: 'thinking',
      content: '',
      segments: [],
      extra: { done: false },
      created_at: null,
    }
    messages.value.push(entry)
    return entry
  }

  /** 推理增量：续写末段文本；动作之后则另起文本段。 */
  function appendReason(delta: string) {
    const entry = ensureOpenThinking()
    const lastSeg = entry.segments[entry.segments.length - 1]
    if (lastSeg && lastSeg.kind === 'reason') {
      lastSeg.text += delta
    } else {
      entry.segments = [...entry.segments, { kind: 'reason', text: delta }]
    }
    entry.content += delta
  }

  /** 过程动作行：并入思考块（不单独成行打断消息流）。 */
  function appendAction(text: string) {
    const entry = ensureOpenThinking()
    entry.segments = [...entry.segments, { kind: 'action', text }]
    entry.content += text
  }

  /** 末段解说若与最终总结同文（interrupt 复用最后一条 AI 消息），从思考块移除（气泡呈现一次即可）。 */
  function stripDupSummary(content: string) {
    if (!content) return
    const last = messages.value[messages.value.length - 1]
    if (!last || last.role !== 'thinking') return
    const entry = last as ThinkingEntry
    const lastSeg = entry.segments[entry.segments.length - 1]
    if (lastSeg && lastSeg.kind === 'action' && lastSeg.text === content) {
      entry.segments = entry.segments.slice(0, -1)
      entry.content = entry.content.slice(0, entry.content.length - content.length)
    }
  }

  /** 统一处理流事件（直答 delta·done；路由卡片；Agent 执行过程）。 */
  function handleEvent(ev: Parameters<Parameters<typeof streamMessage>[2]>[0]) {
    if (ev.type !== 'reasoning_delta' && !PROCESS_EVENTS.has(ev.type)) closeThinking()
    if (ev.type === 'user_message') {
      messages.value.push(ev.message)
      pendingAttachments.value = [] // 服务端已并入消息，待发列表清空
    } else if (ev.type === 'reasoning_delta') {
      appendReason(ev.content)
    } else if (ev.type === 'delta') {
      const last = messages.value[messages.value.length - 1]
      if (last && last.role === 'assistant' && last.id === '') {
        last.content += ev.content
      } else {
        messages.value.push({
          id: '',
          role: 'assistant',
          content: ev.content,
          extra: null,
          created_at: null,
        })
      }
    } else if (ev.type === 'route_card') {
      messages.value.push({
        id: ev.message.id,
        role: 'route_card',
        content: ev.message.content,
        extra: { reason: ev.reason, status: 'pending' },
        created_at: ev.message.created_at,
      } satisfies CardEntry)
    } else if (ev.type === 'task_created') {
      appendAction('任务已创建')
    } else if (ev.type === 'task_started') {
      appendAction('开始执行')
    } else if (ev.type === 'agent_message') {
      appendAction(ev.content) // 执行中间解说并入思考块，不打断消息流
    } else if (ev.type === 'tool_call') {
      appendAction(`调用工具 ${ev.name}`)
    } else if (ev.type === 'tool_result') {
      appendAction(`${ev.name} 完成`)
    } else if (ev.type === 'steering_queued') {
      appendAction('补充指令已加入队列')
    } else if (ev.type === 'steering_injected') {
      appendAction(`已注入补充指令：${ev.content}`)
    } else if (ev.type === 'task_revising') {
      activePreview.value = null
      artifacts.value = [] // 版本链变动中，待新 preview_ready 刷新
      appendAction('按修改意见调整中')
    } else if (ev.type === 'preview_ready') {
      // 末条 agent_message 与预览载荷是同一段话（interrupt 取最后一条 AI 消息），去重
      const content = ev.preview?.preview ?? ''
      stripDupSummary(content)
      const last = messages.value[messages.value.length - 1]
      if (!(last && last.role === 'assistant' && last.content === content)) {
        messages.value.push({
          id: `preview-${ev.task_id}`,
          role: 'assistant',
          content,
          extra: { task_id: ev.task_id, kind: 'preview' },
          created_at: null,
        })
      }
      activePreview.value = { taskId: ev.task_id, content }
      void refreshArtifacts(ev.task_id)
    } else if (ev.type === 'task_completed') {
      activePreview.value = null
      void refreshArtifacts(ev.task_id) // 交付后仍可查看/下载（final_format 已补齐）
      pushSystem('✅ 任务已交付')
    } else if (ev.type === 'task_failed') {
      activePreview.value = null
      pushSystem(`❌ 任务失败：${ev.detail}`)
    } else if (ev.type === 'task_broken') {
      pushSystem(`⚠️ ${ev.detail}`)
    } else if (ev.type === 'error') {
      pushSystem(`⚠️ 出错了：${ev.detail}`)
    } else if (ev.type === 'done') {
      if (ev.message) {
        const last = messages.value[messages.value.length - 1]
        if (last && last.role === 'assistant') {
          messages.value[messages.value.length - 1] = ev.message
        } else {
          messages.value.push(ev.message)
        }
      }
    }
  }

  /** 回放历史时：为带思考的助手消息插入折叠思考块；为待处理路由卡片插入卡片行。 */
  function expandCards(raw: MessageInfo[]): MessageInfo[] {
    const out: MessageInfo[] = []
    for (const m of raw) {
      const reasoning =
        m.role === 'assistant' ? (m.extra?.reasoning as string | undefined) : undefined
      if (typeof reasoning === 'string' && reasoning) {
        const thinkEntry: ThinkingEntry = {
          id: `${m.id}-think`,
          role: 'thinking',
          content: reasoning,
          segments: [{ kind: 'reason', text: reasoning }],
          extra: { done: true },
          created_at: m.created_at,
        }
        out.push(thinkEntry)
      }
      out.push(m)
      const route = m.extra?.route as
        | { kind: string; status: string; reason?: string }
        | undefined
      if (m.role === 'user' && route && route.status === 'pending') {
        out.push({
          id: m.id,
          role: 'route_card',
          content: m.content,
          extra: { reason: route.reason ?? '', status: 'pending' },
          created_at: m.created_at,
        } satisfies CardEntry)
      }
    }
    return out
  }

  function markCard(messageId: string, status: CardEntry['extra']['status']) {
    const card = messages.value.find((m) => m.role === 'route_card' && m.id === messageId)
    if (card) {
      card.extra = { ...(card.extra as CardEntry['extra']), status }
    }
  }

  return {
    sessions,
    currentSession,
    messages,
    streaming,
    activePreview,
    artifacts,
    pendingAttachments,
    uploading,
    refreshSessions,
    newSession,
    selectSession,
    switchMode,
    send,
    addAttachments,
    removeAttachment,
    resolveRoute,
    approvePreview,
    refreshArtifacts,
  }
})
