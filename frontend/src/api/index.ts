import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 1000 * 120,  // 2分钟，Chat Demo agent 推理需要较长时间
})

// ---- 透视相关 ----
export const getFields = () => api.get('/pivot/fields')
export const getData = (limit = 100) => api.get(`/pivot/data?limit=${limit}`)

export const aggregate = (data: {
  rows: string[]
  columns: string[]
  values: string[]
  aggregations: string[]
  filters?: Record<string, any[]>
}) => api.post('/pivot/aggregate', data)

export const groupBy = (data: {
  group_by: string[]
  values: string[]
  aggregations: string[]
}) => api.post('/pivot/groupby', data)

// ---- 下钻查询 ----
export const getPersons = () => api.get('/pivot/persons')
export const getTasksByPerson = (person: string) =>
  api.get('/pivot/drill/tasks', { params: { person } })
export const getRulesByTask = (taskId: number) =>
  api.get('/pivot/drill/rules', { params: { task_id: taskId } })
export const getAlarmsByRule = (ruleId: number) =>
  api.get('/pivot/drill/alarms', { params: { rule_id: ruleId } })
export const getSignalsByAlarm = (alarmId: number) =>
  api.get('/pivot/drill/signals', { params: { alarm_id: alarmId } })
export const getSignalTimeline = (signalName: string, alarmResultIds: number[]) =>
  api.post('/pivot/drill/signal-timeline', {
    signal_name: signalName,
    alarm_result_ids: alarmResultIds,
  })

// ---- 图表相关 ----
export const getChartRecommend = (data: { dimensions: string[]; measures: string[] }) =>
  api.post('/chart/recommend', data)

export const getChartData = (
  chartType: string,
  dimensions: string[],
  measures: string[]
) => api.post('/chart/data', { chart_type: chartType, dimensions, measures })

export const renderChart = (data: {
  chart_type: string
  x_column: string
  y_columns: string[]
  title?: string
  dimensions?: string[]
  measures?: string[]
  data?: any[]
}) => api.post('/chart/render', data)

// ---- AI 对话 ----
export const chatQuery = (query: string, context?: Record<string, any>) =>
  api.post('/chat/query', { query, context })

/**
 * SSE 流式对话 — 实时推送思考过程
 * @param query 用户问题
 * @param context 上下文（含 session_id）
 * @param onEvent 事件回调：{ type, data }
 * @returns AbortController 用于取消
 */
export function chatStream(
  query: string,
  context: Record<string, any> | undefined,
  onEvent: (event: { type: string; data: any }) => void
): AbortController {
  const controller = new AbortController()

  fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, context: context || {} }),
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      onEvent({ type: 'error', data: { message: `HTTP ${response.status}` } })
      return
    }
    const reader = response.body?.getReader()
    if (!reader) return
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      // 解析 SSE 事件
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''  // 保留未完成的行

      let currentEvent = 'message'
      let currentData = ''

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          currentData = line.slice(6)
        } else if (line === '' && currentData) {
          // 空行表示事件结束
          try {
            const parsed = JSON.parse(currentData)
            onEvent({ type: currentEvent, data: parsed })
          } catch {
            onEvent({ type: currentEvent, data: currentData })
          }
          currentEvent = 'message'
          currentData = ''
        }
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      onEvent({ type: 'error', data: { message: err.message } })
    }
  })

  return controller
}

// ---- 链路追踪 ----
export const getTraceList = (limit = 50) => api.get('/trace/list', { params: { limit } })
export const getTraceDetail = (traceId: string) => api.get(`/trace/${traceId}`)
export const getTraceStats = () => api.get('/trace/stats')
export const deleteTrace = (traceId: string) => api.delete(`/trace/${traceId}`)

// ---- Chat Demo 联动 ----
export const getChatDemoIntrospect = () => api.get('/chatdemo/introspect')
export const getChatDemoTableColumns = (tableName: string) =>
  api.get('/chatdemo/table/columns', { params: { table_name: tableName } })
export const getChatDemoTableStats = (tableName: string) =>
  api.get('/chatdemo/table/stats', { params: { table_name: tableName } })
export const getChatDemoColumnDistinct = (
  tableName: string,
  columnName: string,
  limit = 50
) =>
  api.get('/chatdemo/column/distinct', {
    params: { table_name: tableName, column_name: columnName, limit },
  })

export default api
