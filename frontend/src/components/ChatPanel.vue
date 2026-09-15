<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useWorkspaceStore } from '../stores/workspace'

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
      <div
        v-for="m in store.messages"
        :key="m.id || m.content.length"
        class="msg-row"
        :class="m.role"
      >
        <div class="bubble" :class="m.role">
          <span class="content">{{ m.content }}</span>
          <span v-if="m.id === ''" class="cursor">▌</span>
        </div>
      </div>
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
