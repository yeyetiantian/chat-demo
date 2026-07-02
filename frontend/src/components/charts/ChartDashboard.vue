<template>
  <div class="chart-dashboard">
    <div class="dashboard-header">
      <h2>📊 柔性报表</h2>
      <span class="dashboard-count" v-if="charts.length">{{ charts.length }} 个图表</span>
      <button class="btn-add" @click="$emit('add')">➕ 新建图表</button>
      <button class="btn-refresh" @click="loadCharts" :disabled="loading">🔄</button>
    </div>

    <!-- 固定在左上角的 AI 对话按钮 -->
    <button class="btn-ai-float" @click="showChat = true" title="AI 对话">💬</button>
    <ChatDialog :visible="showChat" @close="showChat = false" />

    <div v-if="loading" class="loading-state">加载中...</div>

    <div v-else-if="charts.length === 0" class="empty-state">
      <div class="empty-icon">📊</div>
      <div class="empty-title">暂无已保存的图表</div>
      <div class="empty-desc">在「配置」页面创建图表，或从 AI 对话结果中保存</div>
    </div>

    <div v-else class="chart-grid">
      <ChartCard
        v-for="c in charts" :key="c.chart_id"
        :chart="c"
        @edit="(id) => $emit('edit', id)"
        @deleted="loadCharts"
        @duplicated="loadCharts"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import * as api from '../../api'
import ChartCard from './ChartCard.vue'
import ChatDialog from './ChatDialog.vue'

defineEmits<{
  edit: [id: string]
  add: []
}>()

const charts = ref<any[]>([])
const loading = ref(false)
const showChat = ref(false)

async function loadCharts() {
  loading.value = true
  try {
    const { data: res } = await api.getChartList()
    if (res.success) charts.value = res.charts || []
  } finally {
    loading.value = false
  }
}

onMounted(loadCharts)
</script>

<style scoped>
.chart-dashboard {
  height: calc(100vh - 60px);
  overflow-y: auto;
  padding: 20px;
  background: #f5f7fa;
  position: relative;
}
.btn-ai-float {
  position: fixed;
  bottom: 72px;
  right: 20px;
  z-index: 99;
  width: 48px; height: 48px;
  border-radius: 50%;
  background: var(--primary-color);
  color: #fff;
  border: none;
  font-size: 22px;
  cursor: pointer;
  box-shadow: 0 2px 12px rgba(64,158,255,0.4);
  transition: transform 0.2s;
}
.btn-ai-float:hover { transform: scale(1.1); }
.dashboard-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.dashboard-header h2 { font-size: 18px; margin: 0; }
.dashboard-count { font-size: 12px; color: #909399; }
.btn-add {
  margin-left: auto;
  padding: 7px 16px;
  background: var(--primary-color);
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}
.btn-refresh {
  padding: 7px 10px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
}
.loading-state, .empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 400px;
  color: #909399;
}
.empty-icon { font-size: 48px; margin-bottom: 12px; }
.empty-title { font-size: 16px; font-weight: 600; margin-bottom: 6px; color: #606266; }
.empty-desc { font-size: 13px; }
.chart-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}
</style>
