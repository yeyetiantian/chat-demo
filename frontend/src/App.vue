<template>
  <div id="app">
    <header class="app-header">
      <h1 class="app-logo" @click="$router.push('/')">DataPivot</h1>
      <nav class="app-nav">
        <router-link to="/chat" class="nav-link" active-class="nav-active">
          💬 AI 对话
        </router-link>
        <router-link to="/pivot" class="nav-link" active-class="nav-active">
          📊 拖拽透视
        </router-link>
        <router-link to="/dashboard" class="nav-link" active-class="nav-active">
          🖥️ Chat Demo
        </router-link>
        <router-link to="/trace" class="nav-link" active-class="nav-active">
          🔍 链路追踪
        </router-link>
      </nav>
      <span class="app-version">v2.0</span>
    </header>
    <router-view />
  </div>
</template>

<script setup lang="ts">
// App shell — 顶部导航 + 路由视图
</script>

<style scoped>
#app {
  width: 100vw;
  height: 100vh;
  display: flex;
  flex-direction: column;
}
.app-header {
  height: 60px;
  background: var(--primary-color);
  color: white;
  display: flex;
  align-items: center;
  padding: 0 20px;
  gap: 24px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
  z-index: 100;
  flex-shrink: 0;
}
.app-logo {
  font-size: 20px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.app-nav {
  display: flex;
  gap: 8px;
  flex: 1;
}
.nav-link {
  padding: 8px 16px;
  color: rgba(255, 255, 255, 0.75);
  text-decoration: none;
  border-radius: 6px;
  font-size: 14px;
  transition: all 0.2s;
}
.nav-link:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.15);
}
.nav-active {
  color: #fff;
  background: rgba(255, 255, 255, 0.2);
}
.app-version {
  font-size: 12px;
  opacity: 0.6;
  white-space: nowrap;
}
</style>
