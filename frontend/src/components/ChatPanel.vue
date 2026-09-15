<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useWorkspaceStore, type CardEntry } from '../stores/workspace'
import type { MessageInfo } from '../api/sessions'

const store = useWorkspaceStore()
const input = ref('')
const streamRef = ref<HTMLDivElement | null>(null)

async function onSend() {
  const content = input.value.trim()
  if (!content || store.streaming) return
  if (!store.currentSession) {
    ElMessage.warning('请先选择或新建会话')
    return
  }
  input.value = ''
  try {
    await store.send(content)
  } catch (e) {
    ElMessage.error(`发送失败: ${(e as Error).message}`)
  }
}

async function onResolve(messageId: string, action: 'confirm' | 'decline') {
  try {
    await store.resolveRoute(messageId, action)
  } catch (e) {
    ElMessage.error(`操作失败: ${(e as Error).message}`)
  }
}

function cardOf(m: MessageInfo): CardEntry {
  return m as CardEntry
}

watch(
  () => store.messages.length,
  async () => {
    await nextTick()
    streamRef.value?.scrollTo({ top: streamRef.value.scrollHeight })
  },
)
</script>

<template>
  <div class="chat-panel">
    <header class="chat-header">
      <el-radio-group
        :model-value="store.currentSession?.mode ?? 'chat'"
        :disabled="!store.currentSession"
        @update:model-value="(v: string | number | boolean | undefined) => store.switchMode(v as 'chat' | 'work')"
      >
        <el-radio-button value="chat">普通对话</el-radio-button>
        <el-radio-button value="work">工作模式</el-radio-button>
      </el-radio-group>
    </header>

    <div ref="streamRef" class="chat-stream">
      <el-empty v-if="store.messages.length === 0" description="开始对话吧" />
      <template v-for="m in store.messages" :key="m.role + '-' + (m.id ?? m.content.length)">
        <!-- 路由确认卡片：任务型消息弹出，确认入工作模式 / 拒绝回直答 -->
        <div v-if="m.role === 'route_card'" class="msg-row assistant">
          <div class="route-card">
            <div class="route-title">🧭 这看起来像一项工作</div>
            <div class="route-quote">“{{ m.content }}”</div>
            <div class="route-reason">{{ cardOf(m).extra.reason }}</div>
            <div v-if="cardOf(m).extra.status === 'pending'" class="route-actions">
              <el-button
                size="small"
                type="primary"
                :disabled="store.streaming"
                @click="onResolve(m.id, 'confirm')"
              >
                切换到工作模式
              </el-button>
              <el-button size="small" :disabled="store.streaming" @click="onResolve(m.id, 'decline')">
                继续对话
              </el-button>
            </div>
            <div v-else class="route-result">
              {{ cardOf(m).extra.status === 'confirmed' ? '✅ 已进入工作模式' : '↩ 已按普通对话回答' }}
            </div>
          </div>
        </div>
        <!-- 系统提示行（任务创建等） -->
        <div v-else-if="m.role === 'system'" class="system-row">{{ m.content }}</div>
        <!-- 常规消息气泡 -->
        <div v-else class="msg-row" :class="m.role">
          <div class="bubble" :class="m.role">
            <span class="content">{{ m.content }}</span>
            <span v-if="m.id === ''" class="cursor">▌</span>
          </div>
        </div>
      </template>
    </div>

    <footer class="chat-input">
      <el-input
        v-model="input"
        type="textarea"
        :rows="2"
        :placeholder="store.currentSession ? '输入消息，Enter 发送' : '请先选择会话'"
        :disabled="!store.currentSession || store.streaming"
        @keydown.enter.exact.prevent="onSend"
      />
      <el-button
        type="primary"
        :loading="store.streaming"
        :disabled="!store.currentSession"
        @click="onSend"
      >
        发送
      </el-button>
    </footer>
  </div>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.chat-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-light);
}
.chat-stream {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.msg-row {
  display: flex;
}
.msg-row.user {
  justify-content: flex-end;
}
.bubble {
  max-width: 76%;
  padding: 8px 12px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble.user {
  background: var(--el-color-primary);
  color: #fff;
}
.bubble.assistant {
  background: var(--el-fill-color-light);
}
.route-card {
  max-width: 86%;
  padding: 12px 14px;
  border: 1px solid var(--el-color-primary-light-7);
  border-left: 3px solid var(--el-color-primary);
  border-radius: 10px;
  background: var(--el-color-primary-light-9);
  font-size: 14px;
}
.route-title {
  font-weight: 600;
  margin-bottom: 6px;
}
.route-quote {
  color: var(--el-text-color-secondary);
  margin-bottom: 4px;
  word-break: break-word;
}
.route-reason {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-bottom: 10px;
}
.route-actions {
  display: flex;
  gap: 8px;
}
.route-result {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.system-row {
  align-self: center;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 4px 10px;
}
.cursor {
  animation: blink 1s step-start infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.chat-input {
  padding: 12px 16px;
  border-top: 1px solid var(--el-border-color-light);
  display: flex;
  gap: 12px;
  align-items: flex-end;
}
</style>
