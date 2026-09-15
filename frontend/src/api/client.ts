/**
 * API 客户端：统一携带 X-User-Id 身份头（宿主系统注入；开发态本地选择）。
 * 后端直连（Vite 代理 /api → :8000），SSE 场景单独处理。
 */

const DEV_USER_KEY = 'yixin.user-id'
const DEFAULT_USER = 'dev-local-user'

export function getUserId(): string {
  return localStorage.getItem(DEV_USER_KEY) || DEFAULT_USER
}

export function setUserId(id: string): void {
  localStorage.setItem(DEV_USER_KEY, id)
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('X-User-Id', getUserId())
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  const resp = await fetch(`/api${path}`, { ...init, headers })
  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new ApiError(resp.status, text || resp.statusText)
  }
  return (await resp.json()) as T
}
