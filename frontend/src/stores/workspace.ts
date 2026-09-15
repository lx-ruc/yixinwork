import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createSession,
  listMessages,
  listSessions,
  patchSession,
  routeConfirm,
  streamMessage,
  type MessageInfo,
  type SessionInfo,
} from '../api/sessions'

/** 确认卡片在消息流中的伪消息角色（对应后端 route_card 事件）。 */
export type CardEntry = MessageInfo & {
  role: 'route_card'
  extra: { reason: string; status: 'pending' | 'confirmed' | 'declined' }
}

/** 工作台全局状态：会话列表、当前会话、消息、流式状态。 */
export const useWorkspaceStore = defineStore('workspace', () => {
  const sessions = ref<SessionInfo[]>([])
  const currentSession = ref<SessionInfo | null>(null)
  const messages = ref<MessageInfo[]>([])
  const streaming = ref(false)

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
    messages.value = expandCards(await listMessages(s.id))
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

  /** 发送消息：SSE 事件驱动渲染。 */
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

  /** 统一处理流事件（直答/拒绝直答共用 delta·done；路由卡片/任务事件各自入流）。 */
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
      messages.value.push({
        id: ev.task.id,
        role: 'system',
        content: `任务已创建（${ev.task.status}）：${ev.task.instruction}`,
        extra: null,
        created_at: ev.task.created_at,
      })
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
    refreshSessions,
    newSession,
    selectSession,
    switchMode,
    send,
    resolveRoute,
  }
})
