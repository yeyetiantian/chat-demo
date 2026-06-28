<template>
  <div class="pivot-page">
    <!-- 左侧字段区 -->
    <aside class="field-panel">
      <div class="panel-section">
        <div class="section-title">📋 固定字段</div>
        <div class="field-chips">
          <div
            v-for="f in fixedFields"
            :key="f.column_name"
            class="field-chip fixed"
            draggable="true"
            @dragstart="onDrag($event, f.column_name, 'row')"
            @dblclick="store.addRowField(f.column_name)"
          >
            {{ f.column_name }}
            <span class="field-type">{{ f.column_type }}</span>
          </div>
        </div>
      </div>

      <div class="panel-section">
        <div class="section-title">📡 信号字段</div>
        <div class="field-search">
          <input
            v-model="signalSearch"
            type="text"
            placeholder="搜索信号字段..."
            class="search-input"
          />
        </div>
        <div class="field-chips scrollable">
          <div
            v-for="f in filteredDynamicFields"
            :key="f.column_name"
            class="field-chip dynamic"
            draggable="true"
            @dragstart="onDrag($event, f.column_name, 'value')"
            @dblclick="store.addValueField(f.column_name)"
            :title="f.column_name"
          >
            {{ f.column_name.length > 22 ? f.column_name.substring(0,22)+'...' : f.column_name }}
          </div>
        </div>
        <div class="field-count">
          显示 {{ filteredDynamicFields.length }} / {{ dynamicFields.length }} 个信号
        </div>
      </div>
    </aside>

    <!-- 中间透视配置区 + 图表区 -->
    <div class="main-area">
      <!-- 透视配置 -->
      <div class="pivot-config">
        <div class="config-row">
          <div class="config-zone">
            <div class="zone-label">行维度</div>
            <div class="zone-drop" @drop="onDrop($event, 'row')" @dragover.prevent>
              <span
                v-for="f in store.rowFields"
                :key="'r-'+f"
                class="zone-chip"
                @click="store.removeRowField(f)"
              >
                {{ f }} ✕
              </span>
              <span v-if="store.rowFields.length === 0" class="zone-placeholder">
                拖拽字段到此处
              </span>
            </div>
          </div>
          <div class="config-zone">
            <div class="zone-label">列维度</div>
            <div class="zone-drop" @drop="onDrop($event, 'col')" @dragover.prevent>
              <span
                v-for="f in store.columnFields"
                :key="'c-'+f"
                class="zone-chip"
                @click="store.removeColumnField(f)"
              >
                {{ f }} ✕
              </span>
              <span v-if="store.columnFields.length === 0" class="zone-placeholder">
                拖拽字段到此处
              </span>
            </div>
          </div>
          <div class="config-zone">
            <div class="zone-label">值字段</div>
            <div class="zone-drop" @drop="onDrop($event, 'value')" @dragover.prevent>
              <span
                v-for="f in store.valueFields"
                :key="'v-'+f"
                class="zone-chip"
                @click="store.removeValueField(f)"
              >
                {{ f }} ✕
              </span>
              <span v-if="store.valueFields.length === 0" class="zone-placeholder">
                拖拽字段到此处
              </span>
            </div>
          </div>
        </div>
        <div class="config-actions">
          <select v-model="aggregation" class="agg-select">
            <option value="count">计数 COUNT</option>
            <option value="sum">求和 SUM</option>
            <option value="avg">平均 AVG</option>
            <option value="min">最小 MIN</option>
            <option value="max">最大 MAX</option>
          </select>
          <button class="btn-primary" @click="runQuery" :disabled="store.isLoading">
            {{ store.isLoading ? '查询中...' : '🔍 执行查询' }}
          </button>
          <button class="btn-reset" @click="store.reset()">重置</button>
        </div>
        <div v-if="store.recommendedChart" class="config-recommend">
          💡 推荐图表类型：
          <strong>{{ typeLabel(store.recommendedChart) }}</strong>
        </div>
      </div>

      <!-- 图表标签 + 透视表标签 -->
      <div class="result-tabs">
        <button :class="{ active: viewMode === 'chart' }" @click="viewMode = 'chart'">
          📈 图表
        </button>
        <button :class="{ active: viewMode === 'table' }" @click="viewMode = 'table'">
          📋 数据透视表
        </button>
        <button :class="{ active: viewMode === 'raw' }" @click="viewMode = 'raw'; loadRawData()">
          📄 原始数据
        </button>
      </div>

      <!-- 图表视图 -->
      <div v-if="viewMode === 'chart'" class="result-content">
        <div v-if="!store.chartData" class="result-empty">
          请选择字段并点击「执行查询」生成图表
        </div>
        <template v-else>
          <div class="chart-type-tabs">
            <button
              v-for="ct in chartTypes"
              :key="ct"
              :class="{ active: store.currentChartType === ct }"
              @click="store.setChartType(ct)"
            >
              {{ typeLabel(ct) }}
            </button>
          </div>
          <div class="chart-container">
            <ChartRenderer :chartType="store.currentChartType as ChartType" :data="store.chartData" />
          </div>
        </template>
      </div>

      <!-- 透视表视图 -->
      <div v-else class="result-content">
        <PivotTable :data="store.chartData || store.rawData" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { usePivotStore } from '../stores/pivot'
import ChartRenderer from '../components/charts/ChartRenderer.vue'
import PivotTable from '../components/pivot/PivotTable.vue'
import type { ChartType } from '../components/charts/ChartRenderer.vue'

const store = usePivotStore()
const signalSearch = ref('')
const aggregation = ref('count')
const viewMode = ref<'chart' | 'table' | 'raw'>('chart')
const chartTypes: ChartType[] = ['bar', 'pie', 'line', 'waveform', 'radar', 'scatter']
let draggedField = ''

const fixedFields = computed(() => store.fixedFields)
const dynamicFields = computed(() => store.dynamicFields)

const filteredDynamicFields = computed(() => {
  if (!signalSearch.value) return store.dynamicFields
  const q = signalSearch.value.toLowerCase()
  return store.dynamicFields.filter((f: any) =>
    f.column_name.toLowerCase().includes(q)
  )
})

function typeLabel(t: string): string {
  const m: Record<string, string> = {
    bar: '柱状图', pie: '饼状图', line: '折线图',
    waveform: '波形图', radar: '雷达图', scatter: '散点图',
  }
  return m[t] || t
}

function onDrag(e: DragEvent, field: string, target: string) {
  draggedField = field
  draggedTarget = target
  e.dataTransfer?.setData('text/plain', field)
}

function onDrop(e: DragEvent, target: string) {
  const field = e.dataTransfer?.getData('text/plain') || draggedField
  if (!field) return
  if (target === 'row') store.addRowField(field)
  else if (target === 'col') store.addColumnField(field)
  else if (target === 'value') store.addValueField(field)
}

async function runQuery() {
  if (store.rowFields.length === 0 && store.valueFields.length === 0) return
  await store.loadChartData(store.currentChartType, aggregation.value)
}

async function loadRawData() {
  await store.fetchData()
}

onMounted(async () => {
  await store.fetchFields()
})
</script>

<style scoped>
.pivot-page {
  display: flex;
  height: calc(100vh - 60px);
  overflow: hidden;
}

/* 左侧字段面板 */
.field-panel {
  width: 280px;
  background: #fff;
  border-right: 1px solid var(--border-color);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.panel-section {
  padding: 12px;
  border-bottom: 1px solid var(--border-color);
}
.panel-section:last-child {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.section-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  color: #303133;
}
.field-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.field-chips.scrollable {
  overflow-y: auto;
  flex: 1;
  align-content: flex-start;
}
.field-chip {
  padding: 5px 10px;
  border-radius: 4px;
  font-size: 12px;
  cursor: grab;
  user-select: none;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s;
}
.field-chip.fixed { background: #ecf5ff; color: var(--primary-color); }
.field-chip.dynamic { background: #f0f9eb; color: #67c23a; }
.field-chip:hover { transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,0.1); }
.field-type { font-size: 9px; opacity: 0.6; }
.field-search { margin-bottom: 8px; }
.search-input {
  width: 100%;
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 12px;
  outline: none;
}
.search-input:focus { border-color: var(--primary-color); }
.field-count {
  font-size: 11px;
  color: #909399;
  padding: 4px 0;
}

/* 主区域 */
.main-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #f5f7fa;
}
.pivot-config {
  background: #fff;
  border-bottom: 1px solid var(--border-color);
}
.config-row {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
}
.config-zone {
  flex: 1;
}
.zone-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 6px;
  font-weight: 500;
}
.zone-drop {
  min-height: 42px;
  padding: 6px 10px;
  background: var(--bg-color);
  border: 2px dashed #dcdfe6;
  border-radius: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  transition: border-color 0.2s;
}
.zone-drop:hover {
  border-color: var(--primary-color);
}
.zone-chip {
  padding: 3px 8px;
  background: var(--primary-color);
  color: #fff;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
}
.zone-placeholder {
  font-size: 12px;
  color: #c0c4cc;
}
.config-actions {
  padding: 0 16px 12px;
  display: flex;
  gap: 10px;
  align-items: center;
}
.agg-select {
  padding: 6px 10px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 13px;
  outline: none;
}
.btn-primary {
  padding: 7px 18px;
  background: var(--primary-color);
  color: #fff;
  border: none;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-reset {
  padding: 7px 14px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
  color: #606266;
}
.config-recommend {
  padding: 0 16px 12px;
  font-size: 13px;
  color: #67c23a;
}
.result-tabs {
  display: flex;
  gap: 2px;
  padding: 0 16px;
  background: #fff;
  border-bottom: 1px solid var(--border-color);
}
.result-tabs button {
  padding: 10px 16px;
  border: none;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  color: #909399;
}
.result-tabs button.active {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color);
}
.result-content { flex: 1; overflow: auto; }
.result-empty {
  display: flex; align-items: center; justify-content: center;
  height: 300px; color: #909399; font-size: 14px;
}
.chart-type-tabs {
  display: flex; gap: 4px;
  padding: 10px 16px;
  background: #fff;
}
.chart-type-tabs button {
  padding: 6px 12px;
  border: none;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  border-radius: 4px;
  color: #606266;
}
.chart-type-tabs button.active {
  background: #ecf5ff;
  color: var(--primary-color);
}
.chart-container {
  padding: 16px;
  min-height: 400px;
  width: 100%;
}
</style>
