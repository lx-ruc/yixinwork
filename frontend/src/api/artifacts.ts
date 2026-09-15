/**
 * 产物 API：版本链查询 / 预览 / 签名下载（G8 生命周期）。
 */
import { api } from './client'

export interface ArtifactVersionInfo {
  version: number
  format: string
  final_format: string | null
  created_at: string | null
}

export interface ArtifactInfo {
  id: string
  kind: 'document' | 'poster' | 'table' | 'slides' | 'data' | string
  title: string
  versions: ArtifactVersionInfo[]
}

/** 预览数据：render 决定前端渲染方式（markdown / html* / binary）。 */
export interface PreviewData {
  artifact_id: string
  title: string
  kind: string
  version: number
  render: 'markdown' | 'html' | 'html_table' | 'html_slides' | 'binary' | string
  content: string
  payload: Record<string, unknown> | null
}

export interface DownloadLink {
  format: string
  filename: string
  url: string
  expires_at: number
}

export const listTaskArtifacts = (taskId: string) =>
  api<ArtifactInfo[]>(`/tasks/${taskId}/artifacts`)

export const getArtifactPreview = (artifactId: string, version?: number) =>
  api<PreviewData>(
    `/artifacts/${artifactId}/preview${version ? `?version=${version}` : ''}`,
  )

/** 换取签名下载 URL 后新窗口打开（后端校验 HMAC 签名与过期时间）。 */
export const createDownloadLink = (artifactId: string, version: number) =>
  api<DownloadLink>(`/artifacts/${artifactId}/versions/${version}/download`, {
    method: 'POST',
  })
