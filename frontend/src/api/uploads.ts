/**
 * 附件上传 API：multipart 直传（不能走 JSON 封装），后端抽取文本后暂存，
 * 返回 id 供发送消息时引用。
 */
import { getUserId } from './client'

export interface AttachmentMeta {
  id: string
  name: string
  size: number
  kind: string
}

export async function uploadAttachments(files: File[]): Promise<AttachmentMeta[]> {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  const resp = await fetch('/api/uploads', {
    method: 'POST',
    headers: { 'X-User-Id': getUserId() },
    body: form,
  })
  if (!resp.ok) {
    let detail = `上传失败（${resp.status}）`
    try {
      const body = await resp.json()
      if (body?.detail) detail = body.detail
    } catch {
      /* 非 JSON 错误体：保留默认提示 */
    }
    throw new Error(detail)
  }
  return (await resp.json()).attachments as AttachmentMeta[]
}
