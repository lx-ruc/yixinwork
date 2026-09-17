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
    } else {
      // 首次进入:自动备好一个会话,别让用户对着禁用的输入框找"新建"
      await store.newSession()
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
  <nav class="session-list" aria-label="会话列表">
    <div class="session-actions">
      <button class="new-session" type="button" @click="onCreate">
        <span class="plus" aria-hidden="true">+</span>
        新建会话
      </button>
    </div>
    <button
      v-for="s in store.sessions"
      :key="s.id"
      type="button"
      class="session-item"
      :class="{ active: store.currentSession?.id === s.id }"
      @click="store.selectSession(s)"
    >
      <span class="session-title">{{ s.title }}</span>
      <span v-if="s.mode === 'work'" class="mode-chip">工作</span>
    </button>
    <div v-if="store.sessions.length === 0" class="session-empty">还没有会话</div>
  </nav>
</template>

<style scoped>
.session-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px 10px 16px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.session-actions {
  padding: 0 2px 10px;
}
/* 新建:实底白卡 + 朱砂字(栏内最高频操作,层级最高) */
.new-session {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 0;
  border: 1px solid var(--yx-red-border);
  border-radius: 8px;
  background: #fff;
  color: var(--yx-red);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(32, 32, 30, 0.04);
  transition:
    border-color 0.15s,
    background 0.15s;
}
.new-session:hover {
  border-color: var(--yx-red);
  background: var(--yx-red-wash);
}
.plus {
  font-size: 15px;
  line-height: 1;
  font-weight: 700;
}
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  border-left: 3px solid transparent;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  color: var(--yx-ink-2);
  text-align: left;
  transition:
    background 0.15s,
    color 0.15s;
}
.session-item:hover {
  background: var(--yx-paper);
  color: var(--yx-ink);
}
/* 激活:朱砂脊 + 朱晕底 */
.session-item.active {
  background: var(--yx-red-wash);
  border-left-color: var(--yx-red);
  color: var(--yx-ink);
  font-weight: 500;
}
.session-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mode-chip {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--yx-ink-2);
  border: 1px solid var(--yx-line);
  border-radius: 4px;
  padding: 0 5px;
  line-height: 18px;
  background: #fff;
}
.session-empty {
  padding: 20px 8px;
  text-align: center;
  font-size: 12px;
  color: var(--yx-ink-3);
}
</style>
