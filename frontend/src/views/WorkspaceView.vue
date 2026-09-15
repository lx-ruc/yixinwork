<script setup lang="ts">
import ChatPanel from '../components/ChatPanel.vue'
import ArtifactPanel from '../components/ArtifactPanel.vue'
</script>

<template>
  <div class="workspace-split">
    <section class="chat-side">
      <ChatPanel />
    </section>
    <section class="artifact-side">
      <ArtifactPanel />
    </section>
  </div>
</template>

<style scoped>
.workspace-split {
  display: flex;
  flex: 1;
  min-height: 0;
}
.chat-side {
  flex: 1 1 60%;
  min-width: 0;
  border-right: 1px solid var(--el-border-color-light);
}
.artifact-side {
  flex: 1 1 40%;
  min-width: 0;
}
</style>
