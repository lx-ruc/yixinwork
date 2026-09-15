<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import {
  createDownloadLink,
  getArtifactPreview,
  type ArtifactInfo,
  type PreviewData,
} from '../api/artifacts'
import { ApiError } from '../api/client'
import { useWorkspaceStore } from '../stores/workspace'

const store = useWorkspaceStore()

const KIND_LABELS: Record<string, string> = {
  document: '📄 文档',
  poster: '🖼 海报',
  table: '📊 表格',
  slides: '📽 幻灯片',
  data: '🧮 数据',
}

const selectedId = ref<string | null>(null)
/** null = 跟随最新版本（修改续跑出新版后自动跟上）；用户点击后固定。 */
const selectedVersion = ref<number | null>(null)
const preview = ref<PreviewData | null>(null)
const loading = ref(false)
const downloading = ref(false)

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

/** markdown → 净化 HTML（DOMPurify 兜底，服务端已限制为纯文本格式）。 */
const markdownHtml = computed(() => {
  if (preview.value?.render !== 'markdown') return ''
  const raw = marked.parse(preview.value.content, { async: false }) as string
  return DOMPurify.sanitize(raw)
})

/** html 系预览统一走无脚本沙箱 iframe（sandbox 空串：禁脚本/同源/表单/弹窗）。 */
const iframeDoc = computed(() => {
  const p = preview.value
  if (!p) return ''
  if (['html', 'html_slides'].includes(p.render) && p.content) return p.content
  if (p.render === 'html_table' && p.content) return p.content
  return ''
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

async function download() {
  if (!selectedId.value || !effectiveVersion.value || downloading.value) return
  downloading.value = true
  try {
    const link = await createDownloadLink(selectedId.value, effectiveVersion.value)
    window.open(link.url, '_blank')
  } catch (e) {
    ElMessage.error(e instanceof ApiError ? `下载失败：${e.message}` : '下载失败')
  } finally {
    downloading.value = false
  }
}

const kindLabel = (kind: string) => KIND_LABELS[kind] ?? `📦 ${kind}`
</script>

<template>
  <div class="artifact-panel">
    <header class="artifact-header">产物预览</header>

    <template v-if="artifacts.length">
      <div class="artifact-toolbar">
        <div class="artifact-tabs">
          <button
            v-for="a in artifacts"
            :key="a.id"
            class="artifact-tab"
            :class="{ active: a.id === selectedId }"
            :title="a.title"
            @click="selectedId = a.id"
          >
            {{ kindLabel(a.kind) }}
          </button>
        </div>
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
      </div>

      <div v-loading="loading" class="artifact-body">
        <template v-if="preview">
          <div class="preview-title">
            {{ preview.title }}
            <el-tag size="small" type="info">v{{ preview.version }}</el-tag>
          </div>

          <!-- markdown：净化后直接渲染 -->
          <div v-if="preview.render === 'markdown'" class="markdown-body" v-html="markdownHtml" />

          <!-- html 海报/表格/幻灯片：无脚本沙箱 iframe -->
          <iframe
            v-else-if="iframeDoc"
            class="preview-frame"
            sandbox=""
            :srcdoc="iframeDoc"
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

          <el-empty v-else description="该产物为二进制格式，请直接下载查看" />
        </template>
        <el-empty v-else-if="!loading" description="暂无预览" />
      </div>

      <footer class="artifact-footer">
        <el-button
          type="primary"
          :loading="downloading"
          :disabled="!selectedId || !effectiveVersion"
          @click="download"
        >
          下载{{ current?.kind === 'document' ? ' docx' : current?.kind === 'slides' ? ' pptx' : '' }}
        </el-button>
        <span class="download-hint">签名链接 10 分钟内有效</span>
      </footer>
    </template>

    <div v-else class="artifact-empty">
      <el-empty description="任务产物将在这里展示：版本切换 / 预览 / 下载" />
    </div>
  </div>
</template>

<style scoped>
.artifact-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.artifact-header {
  padding: 12px 16px;
  font-weight: 600;
  border-bottom: 1px solid var(--el-border-color-light);
}
.artifact-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  flex-wrap: wrap;
}
.artifact-tabs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.artifact-tab {
  border: 1px solid var(--el-border-color);
  background: var(--el-fill-color-blank);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 13px;
  cursor: pointer;
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.artifact-tab.active {
  border-color: var(--el-color-primary);
  color: var(--el-color-primary);
  background: var(--el-color-primary-light-9);
}
.version-single {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.artifact-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
}
.artifact-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}
.preview-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 12px;
}
.preview-frame {
  flex: 1;
  min-height: 320px;
  width: 100%;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: #fff;
}
.preview-table {
  border-collapse: collapse;
  font-size: 13px;
}
.preview-table th,
.preview-table td {
  border: 1px solid var(--el-border-color);
  padding: 5px 12px;
}
.preview-table th {
  background: var(--el-fill-color-light);
}
.markdown-body {
  line-height: 1.75;
  font-size: 14px;
  word-break: break-word;
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
  background: var(--el-fill-color-light);
  padding: 1px 5px;
  border-radius: 4px;
}
.markdown-body :deep(pre) {
  background: var(--el-fill-color-light);
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
}
.artifact-footer {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-top: 1px solid var(--el-border-color-light);
}
.download-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
