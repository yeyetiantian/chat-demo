import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api'

export interface Field {
  column_name: string
  column_type: string
}

export const usePivotStore = defineStore('pivot', () => {
  // ---- 状态 ----
  const fixedFields = ref<Field[]>([])
  const dynamicFields = ref<Field[]>([])
  const rowFields = ref<string[]>([])
  const columnFields = ref<string[]>([])
  const valueFields = ref<string[]>([])
  const currentChartType = ref<string>('bar')
  const chartData = ref<any>(null)
  const rawData = ref<any>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const recommendedChart = ref<string | null>(null)

  // ---- 方法 ----
  async function fetchFields() {
    try {
      const { data: res } = await api.getFields()
      if (res.success) {
        fixedFields.value = res.data?.fixed || []
        dynamicFields.value = res.data?.dynamic || []
      }
    } catch (e: any) {
      error.value = e.message
    }
  }

  async function fetchData() {
    try {
      isLoading.value = true
      const { data: res } = await api.getData(100)
      if (res.success) {
        rawData.value = res.data
      }
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function recommendChart() {
    if (rowFields.value.length === 0 && valueFields.value.length === 0) return
    try {
      const dimensions = [...rowFields.value, ...columnFields.value]
      const measures = valueFields.value.length > 0 ? valueFields.value : ['持续时间']
      const { data: res } = await api.getChartRecommend({ dimensions, measures })
      if (res.success) {
        recommendedChart.value = res.recommended
      }
    } catch (e: any) {
      console.error('推荐失败:', e)
    }
  }

  async function loadChartData(chartType?: string, _aggregation?: string) {
    const type = chartType || currentChartType.value
    if (rowFields.value.length === 0 && valueFields.value.length === 0) return

    try {
      isLoading.value = true
      error.value = null

      const dimensions = [...rowFields.value, ...columnFields.value]
      const measures = valueFields.value.length > 0 ? valueFields.value : ['持续时间']

      // 使用统一 chart data API
      const resp = await api.getChartData(type, dimensions, measures)
      if (resp.data.success) {
        chartData.value = resp.data.data
        currentChartType.value = type
        await recommendChart()
      }
    } catch (e: any) {
      // API 查询失败（如 AI 生成的字段名数据库不存在）
      // 如果已有数据则保留，不覆盖
      if (!chartData.value) {
        error.value = e.message
      }
    } finally {
      isLoading.value = false
    }
  }

  // ---- 字段操作 ----
  function addRowField(field: string) {
    if (!rowFields.value.includes(field)) {
      rowFields.value.push(field)
      recommendChart()
    }
  }
  function addColumnField(field: string) {
    if (!columnFields.value.includes(field)) {
      columnFields.value.push(field)
      recommendChart()
    }
  }
  function addValueField(field: string) {
    if (!valueFields.value.includes(field)) {
      valueFields.value.push(field)
      recommendChart()
    }
  }
  function removeRowField(field: string) {
    rowFields.value = rowFields.value.filter(f => f !== field)
  }
  function removeColumnField(field: string) {
    columnFields.value = columnFields.value.filter(f => f !== field)
  }
  function removeValueField(field: string) {
    valueFields.value = valueFields.value.filter(f => f !== field)
  }
  function setChartType(type: string) {
    currentChartType.value = type
    // 已有数据（如 AI 保存的）则只换渲染方式，不重新查库
    if (!chartData.value?.rows && !chartData.value?.data) {
      loadChartData(type)
    }
  }
  function reset() {
    rowFields.value = []
    columnFields.value = []
    valueFields.value = []
    chartData.value = null
    rawData.value = null
    recommendedChart.value = null
  }

  return {
    fixedFields, dynamicFields, rowFields, columnFields, valueFields,
    currentChartType, chartData, rawData, isLoading, error, recommendedChart,
    fetchFields, fetchData, recommendChart, loadChartData,
    addRowField, addColumnField, addValueField,
    removeRowField, removeColumnField, removeValueField,
    setChartType, reset,
  }
})
