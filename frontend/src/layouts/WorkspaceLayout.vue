<script setup lang="ts">
import SessionList from '../components/SessionList.vue'
</script>

<template>
  <el-container class="workspace-root">
    <el-aside width="232px" class="workspace-aside">
      <div class="brand">
        <span class="seal" aria-hidden="true">亿心</span>
        <span class="brand-name">
          <strong>亿心工作</strong>
          <small>一句话,成交付</small>
        </span>
      </div>
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
  border-right: 1px solid var(--yx-line);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}
/* 品牌块:朱砂印章 + 产品名 */
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 16px 14px;
  border-bottom: 1px solid var(--yx-line-soft);
}
.seal {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 7px;
  background: var(--yx-red);
  box-shadow:
    inset 0 0 0 1.5px rgba(255, 255, 255, 0.38),
    0 2px 6px rgba(201, 37, 45, 0.28);
  color: #fff;
  font-family: var(--yx-serif);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: 1px;
  writing-mode: vertical-rl;
  user-select: none;
}
.brand-name {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.brand-name strong {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.brand-name small {
  font-size: 11px;
  color: var(--yx-ink-2);
  letter-spacing: 1px;
}
.workspace-main {
  padding: 0;
  display: flex;
  flex-direction: column;
}
</style>
