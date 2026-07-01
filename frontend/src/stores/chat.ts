import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatStream, getChatHistory } from '../api'

export interface ThinkingStep {
  type: 'text' | 'tool' | 'sql'
  message: string
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'thinking'
  content: string
  chartType?: string
  config?: any
  _chartData?: any
  _chartType?: string
  _chartSpec?: string
  _followups?: string[]
  _saved?: boolean
  _thinkingSteps?: ThinkingStep[]
  _thinkingStatus?: string
  _thinkingExpanded?: boolean
}

export const useChatStore = defineStore('chat', () => {
  const messages = ref<ChatMessage[]>([])

  // 从 sessionStorage 恢复上次的 sessionId（仅存 ID，不存消息）
  const savedSid = sessionStorage.getItem('datapivot_session_id') || null
  const sessionId = ref<string | null>(savedSid)

  const loading = ref(false)
  const thinkingText = ref('')
  const thinkingSteps = ref<ThinkingStep[]>([])

  let abortCtrl: AbortController | null = null

  async function restoreHistory(sid?: string) {
    const target = sid || sessionId.value
    if (!target) return
    sessionId.value = target
    sessionStorage.setItem('datapivot_session_id', target)
    try {
      const { data: res } = await getChatHistory(target)
      if (res.success) {
        messages.value = (res.messages || []).map((m: any) => {
          // 从保存的 _columns 和 _data 重建 _chartData
          const chartData = (m._columns?.length || m._data?.length)
            ? { columns: m._columns || [], rows: m._data || [] }
            : undefined
          return {
            ...m,
            _chartData: chartData,
          }
        })
      }
    } catch {
      // 静默
    }
  }

  function sendMessage(text: string) {
    const q = text.trim()
    if (!q || loading.value) return

    messages.value.push({ role: 'user', content: q })
    loading.value = true
    thinkingText.value = ''
    thinkingSteps.value = []

    let currentStatus = ''

    abortCtrl = chatStream(
      q,
      sessionId.value ? { session_id: sessionId.value } : undefined,
      (event) => {
        switch (event.type) {
          case 'status':
            currentStatus = event.data.message || ''
            thinkingText.value = currentStatus
            // 从初始状态事件中获取 sessionId（不等 result 事件）
            if (event.data.session_id && !sessionId.value) {
              sessionId.value = event.data.session_id
              sessionStorage.setItem('datapivot_session_id', sessionId.value)
            }
            break

          case 'thinking':
            thinkingSteps.value.push({ type: 'text', message: event.data.message || '' })
            break

          case 'tool':
            thinkingSteps.value.push({ type: 'tool', message: event.data.message || '' })
            break

          case 'sql':
            thinkingSteps.value.push({ type: 'sql', message: event.data.message || '' })
            break

          case 'result': {
            const res = event.data
            if (res.config?.session_id) {
              sessionId.value = res.config.session_id
              sessionStorage.setItem('datapivot_session_id', sessionId.value)
            }
            const answer = res.message || `已生成图表`

            const savedSteps = [...thinkingSteps.value]
            const savedStatus = currentStatus || thinkingText.value || ''

            messages.value.push({
              role: 'assistant',
              content: answer,
              chartType: res.chart_type,
              config: res.config,
              _chartData: res.data,
              _chartType: res.chart_type || 'bar',
              _chartSpec: res.data?.chart_spec || '',
              _followups: res.followup_questions || [],
              _thinkingSteps: savedSteps.length > 0 ? savedSteps : undefined,
              _thinkingStatus: savedStatus || undefined,
              _thinkingExpanded: false,
            })
            loading.value = false
            thinkingText.value = ''
            thinkingSteps.value = []
            break
          }

          case 'error':
            messages.value.push({
              role: 'assistant',
              content: `出错了: ${event.data.message || '未知错误'}`,
              _thinkingSteps: [...thinkingSteps.value],
              _thinkingStatus: currentStatus,
            })
            loading.value = false
            thinkingText.value = ''
            thinkingSteps.value = []
            break

          case 'done':
            loading.value = false
            if (thinkingText.value) thinkingText.value = ''
            break
        }
      }
    )
  }

  function cancelRequest() {
    if (abortCtrl) {
      abortCtrl.abort()
      abortCtrl = null
    }
    loading.value = false
    thinkingText.value = ''
  }

  function clearHistory() {
    cancelRequest()
    messages.value = []
    sessionId.value = null
    thinkingSteps.value = []
    sessionStorage.removeItem('datapivot_session_id')
  }

  return {
    messages,
    sessionId,
    loading,
    thinkingText,
    thinkingSteps,
    sendMessage,
    cancelRequest,
    clearHistory,
    restoreHistory,
  }
})
