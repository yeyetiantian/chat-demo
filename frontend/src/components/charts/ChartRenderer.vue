<template>
  <div class="chart-wrapper" :style="{ minHeight: inline ? '280px' : '350px' }">
    <!-- 错误状态 -->
    <div v-if="error" class="chart-status error">{{ error }}</div>
    <!-- 无数据状态（除非有 chartSpec） -->
    <div v-else-if="!hasData && !props.chartSpec" class="chart-status">暂无数据</div>
    <!-- 正常渲染 -->
    <template v-else>
      <div ref="vegaContainer" class="vega-container" :style="{ width: '100%', minHeight: inline ? '280px' : '350px' }"></div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted, computed, nextTick } from 'vue'
import embed from 'vega-embed'

export type ChartType = 'bar' | 'pie' | 'line' | 'waveform' | 'radar' | 'scatter'

const props = defineProps<{
  chartType: ChartType
  data: any
  width?: number | string
  height?: number
  /** Vega-Lite spec JSON 字符串 — 由 backend 生成，优先使用 */
  chartSpec?: string
  /** 嵌入式模式：高度缩小，适合在卡片/气泡内展示 */
  inline?: boolean
}>()

const vegaContainer = ref<HTMLElement | null>(null)
const error = ref<string | null>(null)

const hasData = computed(() => {
  return props.data?.rows?.length > 0 || props.data?.data?.length > 0
})

function getChartMark(chartType: ChartType): any {
  const marks: Record<ChartType, any> = {
    bar: 'bar',
    pie: { type: 'arc', innerRadius: 0, outerRadius: 140 },
    line: { type: 'line', point: true },
    waveform: { type: 'area', line: { strokeWidth: 2 }, opacity: 0.6 },
    radar: { type: 'line', point: true },
    scatter: { type: 'point', filled: true, size: 60 },
  }
  return marks[chartType] || 'bar'
}

/** 剥离 Vue reactive Proxy，返回纯净数据供 Vega-Lite 使用 */
function toRawData(obj: any): any {
  if (!obj) return obj
  return JSON.parse(JSON.stringify(obj))
}

/** 从 Vega-Lite encoding 中提取所有引用的 field 名称 */
function _extract_fields(encoding: any): string[] {
  if (!encoding) return []
  const fields: string[] = []
  for (const ch of ['x', 'y', 'color', 'theta', 'radius', 'detail', 'facet', 'row', 'column']) {
    const c = encoding[ch]
    if (c?.field) fields.push(c.field)
  }
  return fields
}

function buildSpec(): any | null {
  // 优先使用 backend 生成的 Vega-Lite spec
  if (props.chartSpec) {
    try {
      const spec = typeof props.chartSpec === 'string' ? JSON.parse(props.chartSpec) : props.chartSpec
      const rawRows = toRawData(props.data?.rows || props.data?.data) || []

      // 没数据但有 spec → 直接用 spec（可能需要嵌入的 data）
      if (rawRows.length === 0) {
        return {
          ...spec,
          width: props.width || 'container',
          height: props.inline ? 260 : (props.height || 350),
        }
      }

      // 验证 spec 的 encoding 字段名是否与数据匹配
      const specFields = _extract_fields(spec.encoding)
      const dataKeys = rawRows.length > 0 ? Object.keys(rawRows[0]) : []
      const allFieldsValid = specFields.length === 0 || specFields.every(
        (f: string) => dataKeys.includes(f) || f === '__' || f === '_____'
      )
      // 检测占位符字段名（Chat Demo 生成的无意义名称）
      const hasPlaceholders = specFields.some((f: string) => f === '__' || f === '_____' || f.startsWith('___'))

      if (!allFieldsValid || hasPlaceholders) {
        console.log('[ChartRenderer] chartSpec 字段名无效或含占位符，降级为 auto-build',
          '| specFields:', specFields, '| dataKeys:', dataKeys)
        // 降级到 auto-build
      } else {
        return {
          ...spec,
          width: props.width || 'container',
          height: props.inline ? 260 : (props.height || 350),
          data: spec.data ? spec.data : { values: rawRows },
        }
      }
    } catch {
      // fall through to auto-build
    }
  }

  const rows = props.data?.rows || props.data?.data || []
  if (!rows || rows.length === 0) return null

  const rawRows = toRawData(rows)
  if (!rawRows || rawRows.length === 0) return null

  const columns: string[] = toRawData(props.data?.columns) || Object.keys(rawRows[0])
  const dimensions: string[] = toRawData(props.data?.dimensions) || []

  // 维度字段：优先用 backend 标注的 dimensions，否则找非数值列
  const dimCols = dimensions.length > 0
    ? dimensions
    : columns.filter(c => typeof rawRows[0][c] !== 'number')

  // x 轴取第一个维度，如有第二维度用颜色区分
  const xField = dimCols[0] || columns[0] || 'category'
  const colorField = dimCols.length > 1 ? dimCols[1] : undefined

  // y 轴：找至少有一个非 null 数值的列（排除维度列）
  const yFields = columns.filter((c: string) => {
    if (dimCols.includes(c)) return false
    return rawRows.some((r: any) => typeof r[c] === 'number' && r[c] !== null)
  })
  const yField = yFields.length > 0 ? yFields[0] : undefined

  // 统计有效数据量
  const validCount = yField ? rawRows.filter((r: any) => typeof r[yField!] === 'number' && r[yField!] !== null).length : 0

  console.log('[ChartRenderer] auto-build | chartType:', props.chartType,
    '| xField:', xField, '| colorField:', colorField,
    '| yField:', yField, `| valid/total: ${validCount}/${rawRows.length}`,
    '| columns:', columns, '| row[0]:', rawRows[0])

  // y 轴无效时显示提示
  if (!yField || validCount === 0) {
    error.value = '所选度量字段的值全部为空，请尝试其他字段组合'
    return null
  }

  // 构建 encoding
  const encoding: any = buildEncoding(props.chartType, xField, yField, colorField, rawRows)

  return {
    $schema: 'https://vega.github.io/schema/vega-lite/v5.json',
    width: props.width || 'container',
    height: props.inline ? 260 : (props.height || 350),
    mark: getChartMark(props.chartType),
    encoding,
    data: { values: rawRows },
  }
}

/** 根据 chartType 和数据构建 Vega-Lite encoding */
function buildEncoding(
  chartType: ChartType,
  xField: string,
  yField: string,
  colorField: string | undefined,
  rows: any[],
): any {
  const isXTime = rows.length > 0 && (
    typeof rows[0][xField] === 'string' && /^\d{4}-\d{2}-\d{2}/.test(rows[0][xField])
  )

  const enc: any = {
    x: {
      field: xField,
      type: isXTime ? 'temporal' : 'nominal',
      axis: { labelAngle: rows.length > 8 ? -45 : 0 },
    },
    y: { field: yField, type: 'quantitative' },
  }

  if (colorField) {
    enc.color = { field: colorField, type: 'nominal' }
  }

  if (chartType === 'pie') {
    delete enc.x
    delete enc.y
    enc.theta = { field: yField, type: 'quantitative' }
    enc.color = { field: xField, type: 'nominal' }
  }

  if (chartType === 'scatter') {
    enc.color = { field: colorField || xField, type: 'nominal' }
    enc.size = { value: 80 }
  }

  if (chartType === 'waveform') {
    enc.x = { field: xField, type: 'temporal', axis: { labelAngle: -45 } }
  }

  return enc
}

async function renderChart() {
  if (!vegaContainer.value) {
    console.warn('[ChartRenderer] vegaContainer ref 为空，延迟重试')
    await nextTick()
    if (!vegaContainer.value) return
  }

  const spec = buildSpec()
  console.log('[ChartRenderer] buildSpec result:', spec)
  if (!spec) {
    console.warn('[ChartRenderer] buildSpec 返回 null, props.data:', props.data)
    return
  }

  error.value = null

  try {
    await embed(vegaContainer.value, spec, {
      actions: { export: true, source: false, compiled: false, editor: false },
      renderer: 'svg',
    })
    console.log('[ChartRenderer] vega-embed 成功')
  } catch (e: any) {
    console.error('[ChartRenderer] vega-embed 失败:', e)
    error.value = e.message
  }
}

watch(
  () => [props.chartType, props.data, props.chartSpec],
  () => renderChart(),
)

onMounted(() => {
  renderChart()
})
</script>

<style scoped>
.chart-wrapper {
  width: 100%;
}
.vega-container {
  width: 100%;
}
.vega-container canvas,
.vega-container svg {
  max-width: 100%;
}
.chart-status {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: #909399;
  font-size: 14px;
}
.chart-status.error {
  color: #f56c6c;
}
</style>
