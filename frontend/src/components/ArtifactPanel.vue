<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import PreviewStage from './PreviewStage.vue'
import {
  createDownloadLink,
  getArtifactPreview,
  type ArtifactInfo,
  type PreviewData,
} from '../api/artifacts'
import { ApiError } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

const store = useWorkspaceStore()

/** 幻灯片单页自然尺寸(与后端模板 960×540 对应)。 */
const SLIDE_W = 960
const SLIDE_H = 540
/** 海报自然尺寸(后端模板 750×1060)。 */
const POSTER_W = 750
const POSTER_H = 1060

const KIND_LABELS: Record<string, string> = {
  document: '文档',
  poster: '海报',
  table: '表格',
  slides: '幻灯片',
  data: '数据',
}

const selectedId = ref<string | null>(null)
/** null = 跟随最新版本（修改续跑出新版后自动跟上）；用户点击后固定。 */
const selectedVersion = ref<number | null>(null)
const preview = ref<PreviewData | null>(null)
const loading = ref(false)
const downloading = ref(false)
const pageIndex = ref(0)

const artifacts = computed<ArtifactInfo[]>(() => store.artifacts)
const current = computed(() =>
  artifacts.value.find((a) => a.id === selectedId.value) ?? null,
)
/** 版本按钮（旧 → 新）。 */
const versionOptions = computed(() =>
  current.value ? [...current.value.versions].sort((x, y) => x.version - y.version) : [],
)
/** 实际预览版本：显式选择 > 版本链中仍存在的固定值 > 最新。 */
const effectiveVersion = computed(() => {
  const opts = versionOptions.value
  if (!opts.length) return null
  if (
    selectedVersion.value != null &&
    opts.some((v) => v.version === selectedVersion.value)
  ) {
    return selectedVersion.value
  }
  return opts[opts.length - 1].version
})

watch(
  artifacts,
  (list) => {
    if (!list.length) {
      selectedId.value = null
      selectedVersion.value = null
      return
    }
    if (!list.some((a) => a.id === selectedId.value)) {
      selectedId.value = list[0].id
      selectedVersion.value = null // 切产物 → 跟随最新
    }
  },
  { immediate: true },
)

watch([selectedId, effectiveVersion], async ([id, version]) => {
  pageIndex.value = 0
  if (!id || !version) {
    preview.value = null
    return
  }
  loading.value = true
  try {
    preview.value = await getArtifactPreview(id, version)
  } catch (e) {
    preview.value = null
    ElMessage.error(e instanceof ApiError ? `预览失败：${e.message}` : '预览加载失败')
  } finally {
    loading.value = false
  }
})

/** 幻灯片拆页:整份 HTML → 单页 srcdoc(DOMParser 惰性解析,不执行脚本)。 */
const slidePages = computed<string[] | null>(() => {
  const p = preview.value
  if (!p || p.render !== 'html_slides' || !p.content) return null
  const dom = new DOMParser().parseFromString(p.content, 'text/html')
  const style = dom.querySelector('style')?.outerHTML ?? ''
  const slides = [...dom.body.querySelectorAll<HTMLElement>(':scope > .slide')]
  if (!slides.length) return null
  // 追加样式:去页间距,让单页文档尺寸恰为 960×540
  const shell =
    `<!DOCTYPE html><html><head><meta charset="utf-8">${style}` +
    `<style>body{margin:0}.slide{margin:0}</style></head><body>`
  return slides.map((el) => `${shell}${el.outerHTML}</body></html>`)
})

/** 海报(固定 750×1060)→ 画台。 */
const posterDoc = computed<string | null>(() => {
  const p = preview.value
  return p && p.render === 'html' && p.content ? p.content : null
})

/** 表格整页 HTML → 普通可滚动 iframe(宽度自适应,无需画台)。 */
const fluidDoc = computed<string | null>(() => {
  const p = preview.value
  return p && p.render === 'html_table' && p.content ? p.content : null
})

/** 无 content 只有 payload 的表格（csv 数据产物）→ 前端组装转义表格。 */
const tableRows = computed<{ headers: string[]; rows: string[][] } | null>(() => {
  const p = preview.value
  if (!p || p.render !== 'html_table' || p.content) return null
  const payload = p.payload as { headers?: unknown; rows?: unknown } | null
  if (!payload?.headers || !Array.isArray(payload.rows)) return null
  return {
    headers: (payload.headers as unknown[]).map((h) => escapeHtml(String(h))),
    rows: (payload.rows as unknown[][]).map((r) => r.map((c) => escapeHtml(String(c)))),
  }
})

function escapeHtml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
}

/** markdown → 净化 HTML（DOMPurify 兜底，服务端已限制为纯文本格式）。 */
const markdownHtml = computed(() => {
  if (preview.value?.render !== 'markdown') return ''
  const raw = marked.parse(preview.value.content, { async: false }) as string
  return DOMPurify.sanitize(raw)
})

const downloadLabel = computed(() => {
  const kind = current.value?.kind
  if (kind === 'document') return '下载 docx'
  if (kind === 'slides') return '下载 pptx'
  return '下载'
})

/** Blob 下载：文件名取自签名链接响应（不依赖浏览器解析 Content-Disposition）。 */
async function download() {
  if (!selectedId.value || !effectiveVersion.value || downloading.value) return
  downloading.value = true
  try {
    const link = await createDownloadLink(selectedId.value, effectiveVersion.value)
    const resp = await fetch(link.url)
    if (!resp.ok) throw new ApiError(resp.status, `签名链接无效（HTTP ${resp.status}）`)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = link.filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    ElMessage.success(`已下载 ${link.filename}`)
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? `下载失败：${e.message}` : '下载失败')
  } finally {
    downloading.value = false
  }
}

function prevPage() {
  if (pageIndex.value > 0) pageIndex.value -= 1
}

function nextPage() {
  if (slidePages.value && pageIndex.value < slidePages.value.length - 1) {
    pageIndex.value += 1
  }
}

const kindLabel = (kind: string) => KIND_LABELS[kind] ?? kind
</script>

<template>
  <div class="artifact-panel">
    <template v-if="artifacts.length">
      <div class="artifact-toolbar">
        <span class="toolbar-label">产物</span>
        <div class="artifact-tabs">
          <button
            v-for="a in artifacts"
            :key="a.id"
            type="button"
            class="artifact-tab"
            :class="{ active: a.id === selectedId }"
            :title="a.title"
            @click="selectedId = a.id"
          >
            {{ kindLabel(a.kind) }}
          </button>
        </div>
        <div class="toolbar-right">
          <el-radio-group
            v-if="versionOptions.length > 1"
            :model-value="effectiveVersion"
            size="small"
            @update:model-value="selectedVersion = $event as number"
          >
            <el-radio-button
              v-for="v in versionOptions"
              :key="v.version"
              :value="v.version"
            >
              v{{ v.version }}
            </el-radio-button>
          </el-radio-group>
          <span v-else-if="current" class="version-single">v{{ effectiveVersion ?? '–' }}</span>
          <el-button
            type="primary"
            plain
            size="small"
            :loading="downloading"
            :disabled="!selectedId || !effectiveVersion"
            title="签名链接 10 分钟内有效"
            @click="download"
          >
            {{ downloadLabel }}
          </el-button>
        </div>
      </div>

      <div v-if="preview" class="preview-caption">
        <span class="caption-title">{{ preview.title }}</span>
        <span v-if="slidePages" class="caption-meta">{{ slidePages.length }} 页</span>
      </div>

      <div v-loading="loading" class="artifact-body">
        <template v-if="preview">
          <!-- 幻灯片:拆页画台 + 翻页器 -->
          <PreviewStage
            v-if="slidePages"
            :srcdoc="slidePages[pageIndex] ?? ''"
            :w="SLIDE_W"
            :h="SLIDE_H"
            :total="slidePages.length"
            :page="pageIndex + 1"
            @prev="prevPage"
            @next="nextPage"
          />

          <!-- 海报:固定尺寸画台 -->
          <PreviewStage v-else-if="posterDoc" :srcdoc="posterDoc" :w="POSTER_W" :h="POSTER_H" />

          <!-- markdown：净化后直接渲染 -->
          <div v-else-if="preview.render === 'markdown'" class="markdown-body" v-html="markdownHtml" />

          <!-- 表格整页：普通沙箱 iframe -->
          <iframe
            v-else-if="fluidDoc"
            class="preview-frame"
            sandbox=""
            :srcdoc="fluidDoc"
            title="产物预览"
          />

          <!-- csv 数据产物：payload 组装转义表格 -->
          <table v-else-if="tableRows" class="preview-table">
            <thead>
              <tr><th v-for="(h, i) in tableRows.headers" :key="i" v-text="h" /></tr>
            </thead>
            <tbody>
              <tr v-for="(row, ri) in tableRows.rows" :key="ri">
                <td v-for="(c, ci) in row" :key="ci" v-text="c" />
              </tr>
            </tbody>
          </table>

          <div v-else class="binary-note">该产物为二进制格式，请直接下载查看</div>
        </template>
        <div v-else-if="!loading" class="binary-note">暂无预览</div>
      </div>
    </template>

    <div v-else class="artifact-empty">
      <span class="seal-ghost" aria-hidden="true">物</span>
      <p class="empty-title">产物将在这里出现</p>
      <p class="empty-sub">工作模式完成任务后,可在这里预览、翻页、缩放与下载</p>
    </div>
  </div>
</template>

<style scoped>
.artifact-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
/* 工具条:白底,收纳 tabs / 版本 / 下载 */
.artifact-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: #fff;
  border-bottom: 1px solid var(--yx-line);
  flex-wrap: wrap;
}
.toolbar-label {
  font-size: 12px;
  color: var(--yx-ink-3);
  letter-spacing: 2px;
}
.artifact-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.artifact-tab {
  border: 1px solid var(--yx-line);
  background: #fff;
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 13px;
  line-height: 20px;
  color: var(--yx-ink-2);
  cursor: pointer;
  transition:
    border-color 0.15s,
    color 0.15s,
    background 0.15s;
}
.artifact-tab:hover {
  border-color: var(--yx-red-border);
  color: var(--yx-red);
}
.artifact-tab.active {
  border-color: var(--yx-red);
  color: var(--yx-red);
  background: var(--yx-red-wash);
  font-weight: 500;
}
.toolbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 10px;
}
.version-single {
  font-size: 12px;
  color: var(--yx-ink-3);
  font-variant-numeric: tabular-nums;
}
/* 标题行:安静的小字 */
.preview-caption {
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 8px 16px 0;
  background: var(--yx-stage);
}
.caption-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--yx-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.caption-meta {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--yx-ink-3);
  font-variant-numeric: tabular-nums;
}
.artifact-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 8px 0 0;
}
/* markdown / 表格内容区滚动 */
.markdown-body,
.preview-frame,
.preview-table {
  margin: 8px 16px 16px;
}
.preview-frame {
  flex: 1;
  min-height: 200px;
  border: 1px solid var(--yx-line);
  border-radius: 8px;
  background: #fff;
}
.markdown-body {
  line-height: 1.75;
  font-size: 14px;
  word-break: break-word;
  background: #fff;
  border: 1px solid var(--yx-line);
  border-radius: 8px;
  padding: 16px 20px;
  overflow-y: auto;
}
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin: 14px 0 8px;
}
.markdown-body :deep(ul) {
  padding-left: 22px;
}
.markdown-body :deep(code) {
  background: var(--yx-paper);
  padding: 1px 5px;
  border-radius: 4px;
}
.markdown-body :deep(pre) {
  background: var(--yx-paper);
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
}
.preview-table {
  border-collapse: collapse;
  font-size: 13px;
  background: #fff;
}
.preview-table th,
.preview-table td {
  border: 1px solid var(--yx-line);
  padding: 5px 12px;
}
.preview-table th {
  background: var(--yx-paper);
}
.binary-note {
  padding: 40px 20px;
  text-align: center;
  font-size: 13px;
  color: var(--yx-ink-3);
}
/* 空态:印章幽灵 */
.artifact-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 24px;
  text-align: center;
}
.seal-ghost {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 9px;
  border: 1.5px dashed var(--yx-red-border);
  background: var(--yx-red-wash);
  color: var(--yx-red);
  font-family: var(--yx-serif);
  font-size: 19px;
  font-weight: 700;
  margin-bottom: 8px;
  user-select: none;
}
.empty-title {
  margin: 0;
  font-family: var(--yx-serif);
  font-size: 16px;
  font-weight: 600;
  color: var(--yx-ink);
}
.empty-sub {
  margin: 0;
  font-size: 12px;
  color: var(--yx-ink-3);
  line-height: 1.7;
}
</style>
