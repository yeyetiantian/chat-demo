<template>
  <Teleport to="body">
    <div v-if="visible" class="chat-dialog-overlay" @click.self="$emit('close')">
      <div class="chat-dialog">
        <div class="dialog-header">
          <h3>💬 AI 对话</h3>
          <button class="dialog-close" @click="$emit('close')">✕</button>
        </div>
        <div class="dialog-body" ref="msgRef">
          <!-- 欢迎页 -->
          <div v-if="store.messages.length === 0" class="welcome">
            <div class="welcome-icon">📊</div>
            <div class="welcome-title">AI 报表助手</div>
            <div class="welcome-desc">输入自然语言，AI 自动生成数据透视图表</div>
            <div class="suggestions">
              <div v-for="s in suggestions" :key="s" class="suggestion-chip" @click="sendMessage(s)">
                {{ s }}
              </div>
            </div>
          </div>

          <!-- 消息列表 -->
          <div v-for="(msg, i) in store.messages" :key="i" class="message" :class="msg.role">
            <div class="msg-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
            <div class="msg-body">
              <div class="msg-text" v-html="renderMarkdown(msg.content)"></div>

              <!-- 思考过程 -->
              <div v-if="msg._thinkingSteps?.length" class="thinking-recap" @click="toggleThinking(i)">
                <span>{{ msg._thinkingExpanded ? '▼' : '▶' }}</span>
                💭 思考过程 ({{ msg._thinkingSteps.length }}步)
              </div>
              <div v-if="msg._thinkingExpanded && msg._thinkingSteps" class="thinking-steps">
                <div v-for="(step, si) in msg._thinkingSteps" :key="si" class="thinking-step" :class="'step-' + step.type">
                  <span class="step-badge">{{ step.type === 'tool' ? '🔧' : step.type === 'sql' ? '📝' : '💭' }}</span>
                  <span class="step-text">{{ step.message }}</span>
                </div>
              </div>

              <!-- 图表 -->
              <div v-if="msg.chartType && (msg._chartData || msg._chartSpec)" class="msg-chart">
                <ChartRenderer
                  :chartType="(msg._chartType || 'bar') as ChartType"
                  :data="msg._chartData || { columns: [], rows: [] }"
                  :chartSpec="msg._chartSpec"
                  :inline="true"
                />
                <button v-if="msg._chartData && msg._saved !== true" class="btn-save" @click="saveToDashboard(msg)">📥 保存</button>
                <span v-else-if="msg._saved === true" class="saved-hint">✅ 已保存</span>
              </div>

              <!-- 追问建议 -->
              <div v-if="msg._followups?.length && i === store.messages.length - 1 && msg.role === 'assistant'" class="followups">
                <div v-for="q in msg._followups" :key="q" class="followup-chip" @click="sendMessage(q)">
                  {{ q }}
                </div>
              </div>
            </div>
          </div>

          <!-- 加载状态 -->
          <div v-if="store.loading" class="thinking">
            <div class="msg-avatar">🤖</div>
            <div class="msg-body">
              <div class="thinking-text">{{ store.thinkingText || '思考中...' }}</div>
              <div v-for="(s, i) in store.thinkingSteps" :key="i" class="thinking-step" :class="'step-' + s.type">
                <span class="step-badge">{{ s.type === 'tool' ? '🔧' : s.type === 'sql' ? '📝' : '💭' }}</span>
                <span class="step-text">{{ s.message }}</span>
              </div>
              <div class="thinking-dots"><span>.</span><span>.</span><span>.</span></div>
            </div>
          </div>
        </div>

        <!-- 输入框 -->
        <div class="dialog-footer">
          <input v-model="query" type="text" class="msg-input" placeholder="输入自然语言查询..." @keyup.enter="sendMessage(query)" :disabled="store.loading" />
          <button class="btn-send" @click="sendMessage(query)" :disabled="!query.trim() || store.loading">发送</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted } from 'vue'
import { useChatStore } from '../../stores/chat'
import * as api from '../../api'
import ChartRenderer from './ChartRenderer.vue'
import type { ChartType } from './ChartRenderer.vue'

defineProps<{ visible: boolean }>()
defineEmits<{ close: [] }>()

const store = useChatStore()
const query = ref('')
const msgRef = ref<HTMLElement | null>(null)

const suggestions = [
  '按车型统计报警数量',
  '按规则类型查看平均持续时间',
  '按人员统计任务数量分布',
  '查看各时间段的报警趋势',
  '统计各车型的报警占比',
]

function renderMarkdown(text: string): string {
  if (!text) return ''
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

function toggleThinking(index: number) {
  const msg = store.messages[index]
  if (msg) msg._thinkingExpanded = !msg._thinkingExpanded
}

function sendMessage(text: string) {
  if (!text.trim() || store.loading) return
  query.value = ''
  store.sendMessage(text)
  nextTick(scrollBottom)
}

async function saveToDashboard(msg: any) {
  try {
    const cols = msg._chartData?.columns || []
    const rows = msg._chartData?.rows || msg._chartData?.data || []
    const firstRow = rows[0] || {}
    const inferredDims = cols.filter((c: string) => typeof firstRow[c] !== 'number') || []
    const inferredMeasures = cols.filter((c: string) => typeof firstRow[c] === 'number') || []

    const payload = {
      query: store.messages.slice(0, store.messages.indexOf(msg)).filter(m => m.role === 'user').pop()?.content || '',
      chart_type: msg._chartType || 'bar',
      chart_spec: msg._chartSpec ? (typeof msg._chartSpec === 'string' ? JSON.parse(msg._chartSpec) : msg._chartSpec) : null,
      data: rows,
      columns: cols,
      rowFields: msg.config?.rowFields?.length ? msg.config.rowFields : inferredDims,
      columnFields: msg.config?.columnFields || [],
      valueFields: msg.config?.valueFields?.length ? msg.config.valueFields : inferredMeasures,
      aggregations: msg.config?.aggregations?.length ? msg.config.aggregations : ['count'],
    }
    const { data: res } = await api.createChartFromAI(payload)
    if (res.success) msg._saved = true
  } catch (e: any) {
    console.error('保存失败:', e)
    alert('保存失败: ' + (e.message || '未知错误'))
  }
}

function scrollBottom() {
  requestAnimationFrame(() => {
    if (msgRef.value) msgRef.value.scrollTop = msgRef.value.scrollHeight
  })
}
</script>

<style scoped>
.chat-dialog-overlay {
  position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
}
.chat-dialog {
  width: 700px; height: 80vh;
  background: #fff; border-radius: 12px;
  display: flex; flex-direction: column;
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
  overflow: hidden;
}
.dialog-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border-color);
  background: #fff;
}
.dialog-header h3 { margin: 0; font-size: 16px; }
.dialog-close {
  padding: 4px 10px; border: none; background: transparent;
  font-size: 18px; cursor: pointer; border-radius: 4px;
}
.dialog-close:hover { background: #f0f2f5; }
.dialog-body {
  flex: 1; overflow-y: auto; padding: 16px;
  background: #f5f7fa;
}
.welcome { text-align: center; padding: 40px 20px; }
.welcome-icon { font-size: 48px; }
.welcome-title { font-size: 18px; font-weight: 600; margin: 12px 0 6px; }
.welcome-desc { font-size: 13px; color: #909399; margin-bottom: 20px; }
.suggestions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.suggestion-chip {
  padding: 8px 16px; background: #ecf5ff; color: var(--primary-color);
  border-radius: 20px; font-size: 13px; cursor: pointer;
}
.suggestion-chip:hover { background: #d9ecff; }
.message { display: flex; gap: 10px; margin-bottom: 16px; }
.msg-avatar { font-size: 20px; flex-shrink: 0; margin-top: 2px; }
.msg-body { flex: 1; min-width: 0; }
.msg-text { font-size: 13px; line-height: 1.6; }
.thinking-recap {
  font-size: 12px; color: #909399; cursor: pointer; margin-top: 6px;
  padding: 4px 8px; background: #f9f9f9; border-radius: 4px;
}
.thinking-steps { margin-top: 6px; }
.thinking-step { font-size: 12px; padding: 3px 6px; color: #606266; display: flex; gap: 4px; }
.step-badge { flex-shrink: 0; }
.msg-chart { margin-top: 8px; }
.btn-save {
  display: block; margin: 6px auto 0;
  padding: 4px 12px; background: #fff; border: 1px solid var(--border-color);
  border-radius: 4px; font-size: 12px; cursor: pointer; color: var(--primary-color);
}
.btn-save:hover { background: #ecf5ff; }
.saved-hint { display: block; text-align: center; font-size: 12px; color: #67c23a; margin-top: 4px; }
.followups { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.followup-chip {
  padding: 5px 12px; background: #fff; border: 1px solid var(--border-color);
  border-radius: 14px; font-size: 12px; cursor: pointer; color: #606266;
}
.followup-chip:hover { color: var(--primary-color); border-color: var(--primary-color); }
.thinking { display: flex; gap: 10px; max-height: 200px; overflow-y: auto;}
.thinking-text { font-size: 12px; color: #909399; }
.thinking-dots span {
  animation: dot-blink 1.4s infinite; font-size: 24px; line-height: 1; color: #909399;
}
.thinking-dots span:nth-child(2) { animation-delay: 0.2s; }
.thinking-dots span:nth-child(3) { animation-delay: 0.4s; }
@keyframes dot-blink { 0%, 80%, 100% { opacity: 0; } 40% { opacity: 1; } }
.dialog-footer {
  display: flex; gap: 8px; padding: 12px 16px;
  border-top: 1px solid var(--border-color); background: #fff;
}
.msg-input {
  flex: 1; padding: 8px 12px; border: 1px solid var(--border-color);
  border-radius: 6px; font-size: 13px; outline: none;
}
.msg-input:focus { border-color: var(--primary-color); }
.btn-send {
  padding: 8px 18px; background: var(--primary-color); color: #fff;
  border: none; border-radius: 6px; font-size: 13px; cursor: pointer;
}
.btn-send:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
