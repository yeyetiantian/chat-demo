<template>
  <div class="pivot-page">
    <div class="pivot-tabs">
      <button :class="{ active: activeTab === 'dashboard' }" @click="activeTab = 'dashboard'">
        📊 柔性报表
      </button>
      <button :class="{ active: activeTab === 'config' }" @click="switchToConfig()">
        ⚙️ 配置
      </button>
    </div>

    <ChartDashboard
      v-if="activeTab === 'dashboard'"
      @edit="openEditor"
      @add="switchToConfig()"
    />

    <PivotConfigPanel
      v-if="activeTab === 'config'"
      :initial-chart-id="editingChartId"
      @saved="onSaved"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import ChartDashboard from '../components/charts/ChartDashboard.vue'
import PivotConfigPanel from '../components/pivot/PivotConfigPanel.vue'

const router = useRouter()
const activeTab = ref<'dashboard' | 'config'>('dashboard')
const editingChartId = ref<string | undefined>(undefined)

function openEditor(chartId: string) {
  editingChartId.value = chartId
  activeTab.value = 'config'
}

function switchToConfig() {
  // 新建时不传 chartId
  editingChartId.value = undefined
  activeTab.value = 'config'
}

function onSaved(chartId: string) {
  editingChartId.value = chartId
  // 保存后显示在仪表盘
  activeTab.value = 'dashboard'
}

// 如果路由参数中有 chartId，直接打开编辑
onMounted(() => {
  const params = new URLSearchParams(window.location.hash.split('?')[1] || '')
  const chartId = params.get('edit')
  if (chartId) {
    openEditor(chartId)
  }
})
</script>

<style scoped>
.pivot-page {
  height: calc(100vh - 60px);
  display: flex;
  flex-direction: column;
}
.pivot-tabs {
  display: flex;
  background: #fff;
  border-bottom: 1px solid var(--border-color);
  flex-shrink: 0;
}
.pivot-tabs button {
  padding: 12px 20px;
  border: none;
  background: transparent;
  font-size: 14px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  color: #909399;
}
.pivot-tabs button.active {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color);
  font-weight: 600;
}
.pivot-tabs button:hover {
  color: var(--primary-color);
}
</style>

