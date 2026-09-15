<script setup lang="ts">
</script>

<template>
  <div class="artifact-panel">
    <header class="artifact-header">产物预览</header>
    <div class="artifact-body">
      <el-empty description="产物版本链 / 预览 / 下载（G8 实现）" />
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
.artifact-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
</style>
