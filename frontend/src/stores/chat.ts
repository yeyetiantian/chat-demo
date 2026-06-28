import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatStream } from '../api'

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
  /** 该消息的思考过程（完成后保留） */
  _thinkingSteps?: ThinkingStep[]
  /** 该消息的状态文本 */
  _thinkingStatus?: string
  /** UI 状态：思考过程是否展开 */
  _thinkingExpanded?: boolean
}

export const useChatStore = defineStore('chat', () => {
  // ---- 状态（跨页面持久化） ----
  const messages = ref<ChatMessage[]>([])
  const sessionId = ref<string | null>(null)
  const loading = ref(false)
  const thinkingText = ref('')
  const thinkingSteps = ref<ThinkingStep[]>([])

  let abortCtrl: AbortController | null = null

  // ---- 方法 ----

  function sendMessage(text: string) {
    const q = text.trim()
    if (!q || loading.value) return

    messages.value.push({ role: 'user', content: q })
    loading.value = true
    thinkingText.value = ''
    thinkingSteps.value = []

    // 局部变量：本次请求的思考过程
    let currentStatus = ''

    abortCtrl = chatStream(
      q,
      sessionId.value ? { session_id: sessionId.value } : undefined,
      (event) => {
        switch (event.type) {
          case 'status':
            currentStatus = event.data.message || ''
            thinkingText.value = currentStatus
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
            }
            const answer = res.message || `已生成图表`

            // 将本次思考过程快照保存到消息中
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
              _thinkingExpanded: false,  // 默认收起
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
  }
})
