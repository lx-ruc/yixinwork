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

export type StreamEvent =
  | { type: 'user_message'; message: MessageInfo }
  | { type: 'delta'; content: string }
  | { type: 'done'; message: MessageInfo; usage: unknown }
  | { type: 'error'; detail: string }

export const listSessions = () => api<SessionInfo[]>('/sessions')
export const createSession = () =>
  api<SessionInfo>('/sessions', { method: 'POST', body: JSON.stringify({}) })
export const patchSession = (id: string, body: { mode?: string }) =>
  api<SessionInfo>(`/sessions/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
export const listMessages = (id: string) =>
  api<MessageInfo[]>(`/sessions/${id}/messages`)

/** 发送消息并以 SSE 接收事件流（直答模式）。 */
export async function streamMessage(
  sessionId: string,
  content: string,
  onEvent: (ev: StreamEvent) => void,
): Promise<void> {
  const resp = await fetch(`/api/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-User-Id': getUserId() },
    body: JSON.stringify({ content }),
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
