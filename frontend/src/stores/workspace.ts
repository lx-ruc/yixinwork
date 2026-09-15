import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  createSession,
  listMessages,
  listSessions,
  patchSession,
  streamMessage,
  type MessageInfo,
  type SessionInfo,
} from '../api/sessions'

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
    messages.value = await listMessages(s.id)
  }

  async function switchMode(mode: 'chat' | 'work') {
    if (!currentSession.value) return
    const updated = await patchSession(currentSession.value.id, { mode })
    currentSession.value = updated
    const idx = sessions.value.findIndex((x) => x.id === updated.id)
    if (idx >= 0) sessions.value[idx] = updated
  }

  /** 发送消息：SSE 事件驱动渲染（直答模式）。 */
  async function send(content: string) {
    if (!currentSession.value || streaming.value) return
    streaming.value = true
    let assistant: MessageInfo | null = null
    try {
      await streamMessage(currentSession.value.id, content, (ev) => {
        if (ev.type === 'user_message') {
          messages.value.push(ev.message)
        } else if (ev.type === 'delta') {
          if (!assistant) {
            assistant = { id: '', role: 'assistant', content: '', extra: null, created_at: null }
            messages.value.push(assistant)
          }
          assistant.content += ev.content
        } else if (ev.type === 'done') {
          const last = messages.value[messages.value.length - 1]
          if (last && last.role === 'assistant') {
            messages.value[messages.value.length - 1] = ev.message
          } else {
            messages.value.push(ev.message)
          }
          assistant = null
        }
      })
    } finally {
      streaming.value = false
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
  }
})
