import { defineStore } from 'pinia'
import { ref } from 'vue'
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

/** 确认卡片在消息流中的伪消息角色（对应后端 route_card 事件）。 */
export type CardEntry = MessageInfo & {
  role: 'route_card'
  extra: { reason: string; status: 'pending' | 'confirmed' | 'declined' }
}

/** 预览就绪状态：满意交付 / 输入修改意见（跟随最近任务）。 */
export interface ActivePreview {
  taskId: string
  content: string
}

/** 工作台全局状态：会话列表、当前会话、消息、流式状态、预览反馈。 */
export const useWorkspaceStore = defineStore('workspace', () => {
  const sessions = ref<SessionInfo[]>([])
  const currentSession = ref<SessionInfo | null>(null)
  const messages = ref<MessageInfo[]>([])
  const streaming = ref(false)
  const activePreview = ref<ActivePreview | null>(null)

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

  /** 发送消息：SSE 事件驱动渲染（语义由后端按会话模式/任务状态决定）。 */
  async function send(content: string) {
    if (!currentSession.value || streaming.value) return
    streaming.value = true
    try {
      await streamMessage(currentSession.value.id, content, handleEvent)
    } finally {
      streaming.value = false
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

  /** 统一处理流事件（直答 delta·done；路由卡片；Agent 执行过程）。 */
  function handleEvent(ev: Parameters<Parameters<typeof streamMessage>[2]>[0]) {
    if (ev.type === 'user_message') {
      messages.value.push(ev.message)
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
      pushSystem(`📋 任务已创建：${ev.task.instruction}`)
    } else if (ev.type === 'task_started') {
      pushSystem('🚀 开始执行…')
    } else if (ev.type === 'agent_message') {
      messages.value.push({
        id: `agent-${messages.value.length}`,
        role: 'assistant',
        content: ev.content,
        extra: null,
        created_at: null,
      })
    } else if (ev.type === 'tool_call') {
      pushSystem(`🔧 调用工具 ${ev.name} ${JSON.stringify(ev.args).slice(0, 80)}`)
    } else if (ev.type === 'tool_result') {
      pushSystem(`📄 ${ev.name} 完成`)
    } else if (ev.type === 'steering_queued') {
      pushSystem('⏳ 补充指令已加入执行队列')
    } else if (ev.type === 'steering_injected') {
      pushSystem(`🔁 已在执行中注入：${ev.content}`)
    } else if (ev.type === 'task_revising') {
      activePreview.value = null
      pushSystem('✏️ 按修改意见调整中…')
    } else if (ev.type === 'preview_ready') {
      const content = ev.preview?.preview ?? ''
      messages.value.push({
        id: `preview-${ev.task_id}`,
        role: 'assistant',
        content,
        extra: { task_id: ev.task_id, kind: 'preview' },
        created_at: null,
      })
      activePreview.value = { taskId: ev.task_id, content }
      pushSystem('🎯 预览就绪：满意请点「满意，交付」；或直接输入修改意见')
    } else if (ev.type === 'task_completed') {
      activePreview.value = null
      pushSystem('✅ 任务已交付')
    } else if (ev.type === 'task_failed') {
      activePreview.value = null
      pushSystem(`❌ 任务失败：${ev.detail}`)
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

  /** 回放历史时，为待处理的路由卡片插入卡片行。 */
  function expandCards(raw: MessageInfo[]): MessageInfo[] {
    const out: MessageInfo[] = []
    for (const m of raw) {
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
    refreshSessions,
    newSession,
    selectSession,
    switchMode,
    send,
    resolveRoute,
    approvePreview,
  }
})
