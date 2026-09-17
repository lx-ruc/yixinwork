/**
 * 会话与消息 API：CRUD 走 fetch 封装；直答走 SSE 流（fetch ReadableStream 解析）。
 */
import { api, ApiError, getUserId } from './client'

export interface SessionInfo {
  id: string
  title: string
  mode: 'chat' | 'work'
  created_at: string | null
  updated_at: string | null
}

export interface MessageInfo {
  id: string
  role: string
  content: string
  extra: Record<string, unknown> | null
  created_at: string | null
}

export interface TaskInfo {
  id: string
  status: string
  instruction: string
  error: string | null
  created_at: string | null
}

export type StreamEvent =
  | { type: 'user_message'; message: MessageInfo }
  | { type: 'reasoning_delta'; content: string }
  | { type: 'delta'; content: string }
  | { type: 'route_card'; message: MessageInfo; reason: string }
  | { type: 'mode_switched'; mode: 'chat' | 'work' }
  | { type: 'task_created'; task: TaskInfo }
  | { type: 'task_started'; task_id: string }
  | { type: 'agent_message'; content: string }
  | { type: 'tool_call'; name: string; args: Record<string, unknown> }
  | { type: 'tool_result'; name: string; content: string }
  | { type: 'steering_queued'; task_id: string; content: string }
  | { type: 'steering_injected'; content: string }
  | { type: 'task_revising'; task_id: string }
  | { type: 'preview_ready'; task_id: string; preview: { preview?: string } }
  | { type: 'task_completed'; task_id: string; status: string }
  | { type: 'task_failed'; task_id: string; detail: string }
  | { type: 'task_broken'; task_id: string; detail: string }
  | { type: 'done'; message: MessageInfo | null; usage: unknown }
  | { type: 'error'; detail: string }

export const listSessions = () => api<SessionInfo[]>('/sessions')
export const createSession = () =>
  api<SessionInfo>('/sessions', { method: 'POST', body: JSON.stringify({}) })
export const patchSession = (id: string, body: { mode?: string }) =>
  api<SessionInfo>(`/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
export const listMessages = (id: string) =>
  api<MessageInfo[]>(`/sessions/${id}/messages`)
export const listTasks = (sessionId: string) =>
  api<TaskInfo[]>(`/sessions/${sessionId}/tasks`)

/** 预览反馈：approve=满意交付；revise 由会话消息入口承担（修改指令续跑）。 */
export const taskFeedback = (
  taskId: string,
  action: 'approve',
  onEvent: (ev: StreamEvent) => void,
) => ssePost(`/tasks/${taskId}/feedback`, { action }, onEvent)

/** POST + SSE 事件流解析（ReadableStream，事件以空行分隔）。 */
async function ssePost(
  path: string,
  body: unknown,
  onEvent: (ev: StreamEvent) => void,
): Promise<void> {
  const resp = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-User-Id': getUserId() },
    body: JSON.stringify(body),
  })
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => '')
    throw new ApiError(resp.status, text || '请求失败')
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      const line = part.split('\n').find((l) => l.startsWith('data: '))
      if (line) onEvent(JSON.parse(line.slice(6)) as StreamEvent)
    }
  }
}

/** 发送消息并以 SSE 接收事件流（普通对话=路由/直答；工作模式=任务流）。 */
export const streamMessage = (
  sessionId: string,
  content: string,
  onEvent: (ev: StreamEvent) => void,
  attachmentIds: string[] = [],
) =>
  ssePost(
    `/sessions/${sessionId}/messages`,
    { content, attachments: attachmentIds.map((id) => ({ id })) },
    onEvent,
  )

/** 确认卡片动作：confirm=进入工作模式；decline=原消息直答。 */
export const routeConfirm = (
  sessionId: string,
  messageId: string,
  action: 'confirm' | 'decline',
  onEvent: (ev: StreamEvent) => void,
) =>
  ssePost(
    `/sessions/${sessionId}/route-confirm`,
    { message_id: messageId, action },
    onEvent,
  )
