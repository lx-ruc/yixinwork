<script setup lang="ts">
import SessionList from '../components/SessionList.vue'
</script>

<template>
  <el-container class="workspace-root">
    <el-aside width="220px" class="workspace-aside">
      <div class="brand">亿心智能体</div>
      <SessionList />
    </el-aside>
    <el-main class="workspace-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<style scoped>
.workspace-root {
  height: 100vh;
}
.workspace-aside {
  border-right: 1px solid var(--el-border-color-light);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.brand {
  font-weight: 600;
  padding: 16px;
  font-size: 16px;
}
.aside-placeholder {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  padding: 0 16px;
}
.workspace-main {
  padding: 0;
  display: flex;
  flex-direction: column;
}
</style>
