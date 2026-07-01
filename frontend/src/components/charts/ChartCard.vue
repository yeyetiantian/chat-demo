<template>
  <div class="chart-card">
    <!-- 图表加载状态 -->
    <div v-if="!fullChart" class="card-loading">加载中...</div>

    <!-- 图表主体 -->
    <template v-else>
      <div class="card-header">
        <div class="card-info">
          <div class="card-name">{{ fullChart.name }}</div>
          <div class="card-meta">
            <span class="card-type">{{ typeLabel }}</span>
            <span v-if="fullChart.source === 'ai'" class="card-source" title="AI 生成">🤖 AI</span>
          </div>
        </div>
        <div class="card-actions">
          <button class="card-btn" @click="$emit('edit', fullChart.chart_id)" title="编辑">✏️</button>
          <button class="card-btn" @click="handleDuplicate" title="复制">📋</button>
          <button class="card-btn danger" @click="handleDelete" title="删除">🗑️</button>
        </div>
      </div>

      <div class="card-chart">
        <ChartRenderer
          :chartType="fullChart.chart_type as ChartType"
          :data="fullChart.data ? { columns: fullChart.columns, rows: fullChart.data } : null"
          :chartSpec="fullChart.chart_spec ? (typeof fullChart.chart_spec === 'string' ? fullChart.chart_spec : JSON.stringify(fullChart.chart_spec)) : undefined"
          :height="300"
        />
      </div>

      <div v-if="fullChart.source_query" class="card-query">
        💬 {{ fullChart.source_query }}
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import * as api from '../../api'
import ChartRenderer from './ChartRenderer.vue'
import type { ChartType } from './ChartRenderer.vue'

const props = defineProps<{ chart: any }>()

const emit = defineEmits<{
  edit: [id: string]
  deleted: [id: string]
  duplicated: [id: string]
}>()

const fullChart = ref<any>(null)

const typeLabel = computed(() => {
  const m: Record<string, string> = {
    bar: '柱状图', pie: '饼状图', line: '折线图',
    waveform: '波形图', radar: '雷达图', scatter: '散点图',
  }
  return m[fullChart.value?.chart_type] || fullChart.value?.chart_type || ''
})

async function loadChart() {
  try {
    const { data: res } = await api.getChartDetail(props.chart.chart_id)
    if (res.success) fullChart.value = res.chart
  } catch {
    // 静默
  }
}

async function handleDelete() {
  if (!confirm(`删除图表「${props.chart.name}」？`)) return
  await api.deleteChart(props.chart.chart_id)
  emit('deleted', props.chart.chart_id)
}

async function handleDuplicate() {
  const { data: res } = await api.duplicateChart(props.chart.chart_id)
  if (res.success) emit('duplicated', res.chart.chart_id)
}

onMounted(loadChart)
</script>

<style scoped>
.chart-card {
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  transition: box-shadow 0.2s;
}
.chart-card:hover { box-shadow: 0 2px 12px rgba(0, 0, 0, 0.08); }
.card-loading {
  padding: 60px;
  text-align: center;
  color: #909399;
}
.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 12px 14px 0;
  gap: 8px;
}
.card-info { flex: 1; min-width: 0; }
.card-name { font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-meta { display: flex; gap: 6px; align-items: center; margin-top: 4px; }
.card-type { font-size: 11px; color: #909399; background: #f0f2f5; padding: 2px 8px; border-radius: 4px; }
.card-source { font-size: 11px; }
.card-actions { display: flex; gap: 4px; flex-shrink: 0; }
.card-btn {
  padding: 4px 8px; border: none; background: transparent;
  font-size: 14px; cursor: pointer; border-radius: 4px; line-height: 1;
}
.card-btn:hover { background: #f0f2f5; }
.card-btn.danger:hover { background: #fef0f0; }
.card-chart {
  padding: 8px 14px 4px;
  min-height: 280px;
}
.card-query {
  padding: 6px 14px 10px;
  font-size: 11px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
