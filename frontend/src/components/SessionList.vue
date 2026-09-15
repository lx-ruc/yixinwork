<script setup lang="ts">
import { onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useWorkspaceStore } from '../stores/workspace'

const store = useWorkspaceStore()

onMounted(async () => {
  try {
    await store.refreshSessions()
    if (store.sessions.length > 0) {
      await store.selectSession(store.sessions[0])
    }
  } catch (e) {
    ElMessage.error(`加载会话失败: ${(e as Error).message}`)
  }
})

async function onCreate() {
  try {
    await store.newSession()
  } catch (e) {
    ElMessage.error(`新建会话失败: ${(e as Error).message}`)
  }
}
</script>

<template>
  <div class="session-list">
    <div class="session-actions">
      <el-button type="primary" size="small" @click="onCreate">新建会话</el-button>
    </div>
    <div
      v-for="s in store.sessions"
      :key="s.id"
      class="session-item"
      :class="{ active: store.currentSession?.id === s.id }"
      @click="store.selectSession(s)"
    >
      <span class="session-title">{{ s.title }}</span>
      <el-tag v-if="s.mode === 'work'" size="small" type="warning">工作</el-tag>
    </div>
    <el-empty v-if="store.sessions.length === 0" description="暂无会话" :image-size="60" />
  </div>
</template>

<style scoped>
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.session-actions {
  padding: 4px 8px 12px;
}
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.session-item:hover {
  background: var(--el-fill-color-light);
}
.session-item.active {
  background: var(--el-color-primary-light-9);
}
.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
