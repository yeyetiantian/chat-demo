<template>
  <div class="chat-page">
    <div class="chat-main">
      <div class="chat-header">
        <h2>AI 报表助手</h2>
        <span class="chat-hint">输入自然语言，AI 自动生成数据透视图表</span>
      </div>

      <div class="chat-messages" ref="msgRef">
        <div v-if="messages.length === 0" class="welcome">
          <div class="welcome-icon">📊</div>
          <div class="welcome-title">欢迎使用 DataPivot AI 助手</div>
          <div class="welcome-desc">试试下面的示例查询，或直接输入您的问题</div>
          <div class="suggestions">
            <div
              v-for="s in suggestions"
              :key="s"
              class="suggestion-chip"
              @click="sendMessage(s)"
            >
              {{ s }}
            </div>
          </div>
        </div>

        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="message"
          :class="msg.role"
        >
          <div class="message-avatar">{{ msg.role === 'user' ? '👤' : '🤖' }}</div>
          <div class="message-body" :class="{ 'has-chart': msg.chartType }">
            <!-- 文字回答（Markdown 渲染） -->
            <div class="message-text" v-html="renderMarkdown(msg.content)"></div>

            <!-- 思考过程（已完成的消息，可折叠） -->
            <div
              v-if="msg._thinkingSteps && msg._thinkingSteps.length > 0"
              class="thinking-recap"
              :class="{ expanded: msg._thinkingExpanded }"
            >
              <div class="thinking-recap-toggle" @click="toggleThinking(i)">
                <span class="toggle-icon">{{ msg._thinkingExpanded ? '▼' : '▶' }}</span>
                💭 思考过程 ({{ msg._thinkingSteps.length }}步)
                <span v-if="msg._thinkingStatus" class="recap-status">{{ msg._thinkingStatus }}</span>
              </div>
              <div v-if="msg._thinkingExpanded" class="thinking-recap-steps">
                <div
                  v-for="(step, si) in msg._thinkingSteps"
                  :key="si"
                  :class="['thinking-step', `step-${step.type}`]"
                >
                  <span v-if="step.type === 'tool'" class="step-badge">🔧</span>
                  <span v-else-if="step.type === 'sql'" class="step-badge">📝</span>
                  <span class="step-text">{{ step.message }}</span>
                </div>
              </div>
            </div>

            <!-- 图表嵌入在气泡内 -->
            <div v-if="msg.chartType && msg._chartData" class="message-chart">
              <ChartRenderer
                :chartType="(msg._chartType || 'bar') as ChartType"
                :data="msg._chartData"
                :chartSpec="msg._chartSpec"
                :inline="true"
              />
            </div>
            <!-- 追问建议（仅最后一条 assistant 消息） -->
            <div
              v-if="msg._followups && msg._followups.length > 0 && i === messages.length - 1 && msg.role === 'assistant'"
              class="followup-chips"
            >
              <div
                v-for="q in msg._followups"
                :key="q"
                class="followup-chip"
                @click="sendMessage(q)"
              >
                {{ q }}
              </div>
            </div>
          </div>
        </div>

        <div v-if="loading" class="message thinking">
          <div class="message-avatar">🤖</div>
          <div class="message-body thinking-body">
            <div class="thinking-status">{{ thinkingText || '正在思考...' }}</div>
            <div v-if="thinkingSteps.length > 0" class="thinking-steps">
              <div
                v-for="(step, i) in thinkingSteps"
                :key="i"
                :class="['thinking-step', `step-${step.type}`]"
              >
                <span v-if="step.type === 'tool'" class="step-badge">🔧</span>
                <span v-else-if="step.type === 'sql'" class="step-badge">📝</span>
                <span class="step-text">{{ step.message }}</span>
              </div>
            </div>
            <div class="typing-indicator"><span></span><span></span><span></span></div>
          </div>
        </div>
      </div>

      <div class="chat-input-area">
        <input
          ref="inputRef"
          v-model="query"
          type="text"
          class="chat-input"
          placeholder="输入查询，例如：按车型统计各规则类型的报警数量"
          :disabled="loading"
          @keyup.enter="sendMessage(query)"
        />
        <button
          class="send-btn"
          :disabled="loading || !query.trim()"
          @click="sendMessage(query)"
        >
          发送
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onUnmounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useChatStore } from '../stores/chat'
import ChartRenderer from '../components/charts/ChartRenderer.vue'
import type { ChartType } from '../components/charts/ChartRenderer.vue'

const store = useChatStore()
const { messages, loading, thinkingText, thinkingSteps } = storeToRefs(store)
const query = ref('')
const msgRef = ref<HTMLElement | null>(null)

const suggestions = [
  '按车型统计报警数量',
  '按规则类型查看平均持续时间',
  '按人员统计任务数量分布',
  '查看各时间段的报警趋势',
  '统计各车型的报警占比',
]

// 组件卸载时取消进行中的请求（但保留 store 中的消息）
onUnmounted(() => {
  store.cancelRequest()
})

// streaming 过程中自动滚动：思考步骤数量变化
watch(
  () => thinkingSteps.value.length,
  () => {
    scrollBottom()
    nextTick(() => {
      const stepsEl = msgRef.value?.querySelector('.thinking-steps') as HTMLElement | null
      if (stepsEl) stepsEl.scrollTop = stepsEl.scrollHeight
    })
  }
)

// streaming 过程中自动滚动：状态文字变化
watch(thinkingText, () => scrollBottom())

// 新消息添加或任意消息内容变化时自动滚动
watch(
  () => messages.value.length,
  () => nextTick(() => scrollBottom())
)

// 最后一条 assistant 消息内容增长时滚动（Markdown 渲染撑开高度）
watch(
  () => {
    const msgs = messages.value
    if (msgs.length === 0) return ''
    const last = msgs[msgs.length - 1]
    return last.role === 'assistant' ? last.content : ''
  },
  () => nextTick(() => scrollBottom())
)

/** 切换已完成消息的思考过程展开/收起 */
function toggleThinking(index: number) {
  const msg = messages.value[index]
  if (msg) {
    msg._thinkingExpanded = !msg._thinkingExpanded
  }
}

/** 简易 Markdown → HTML */
function renderMarkdown(text: string): string {
  if (!text) return ''
  let html = text
    // 1. 转义 HTML 特殊字符
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 2. 标题
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')

  // 3. 行内加粗
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  // 4. Markdown 表格：匹配连续的 |...| 行
  html = html.replace(/(?:^\|.+\|$\n?)+/gm, (match) => {
    const lines = match.trim().split('\n')
    const rows = lines
      .filter(l => !/^\|[-:\s]+\|$/.test(l))  // 跳过分割行 |---|
      .map((l, i) => {
        const cells = l.replace(/^\||\|$/g, '').split('|').map(c => c.trim())
        const tag = i === 0 ? 'th' : 'td'
        return '<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>'
      })
    return '<table class="md-table">' + rows.join('') + '</table>'
  })

  // 5. 无序列表：匹配连续的 - ... 行
  html = html.replace(/(?:^- .+$\n?)+/gm, (match) => {
    const items = match.trim().split('\n').map(l => '<li>' + l.replace(/^- /, '') + '</li>')
    return '<ul class="md-list">' + items.join('') + '</ul>'
  })

  // 6. 有序列表：匹配连续的 1. ... 行
  html = html.replace(/(?:^\d+\.\s.+$\n?)+/gm, (match) => {
    const items = match.trim().split('\n').map(l => '<li>' + l.replace(/^\d+\.\s/, '') + '</li>')
    return '<ul class="md-list">' + items.join('') + '</ul>'
  })

  // 7. 按双换行分段，每段包 <p>，段内单换行转 <br>
  const paragraphs = html.split(/\n\n+/)
  html = paragraphs.map(p => {
    const trimmed = p.trim()
    if (!trimmed) return ''
    // 已经是块级标签的跳过
    if (/^<(h[34]|table|ul)[ >]/.test(trimmed)) return trimmed
    return '<p>' + trimmed.split('\n').join('<br>') + '</p>'
  }).filter(Boolean).join('\n')

  return html
}

function sendMessage(text: string) {
  if (!text.trim() || loading.value) return
  query.value = ''
  store.sendMessage(text)
  scrollBottom()
}

function scrollBottom() {
  // requestAnimationFrame 确保在浏览器完成布局后再读取 scrollHeight
  requestAnimationFrame(() => {
    if (msgRef.value) {
      msgRef.value.scrollTop = msgRef.value.scrollHeight
    }
  })
}
</script>

<style scoped>
.chat-page {
  display: flex;
  justify-content: center;
  height: calc(100vh - 60px);
}
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  max-width: 860px;
  background: #fff;
}
.chat-header {
  padding: 20px;
  border-bottom: 1px solid var(--border-color);
}
.chat-header h2 {
  font-size: 18px;
  margin-bottom: 4px;
}
.chat-hint {
  font-size: 12px;
  color: #909399;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
}
.welcome {
  text-align: center;
  padding: 40px 20px;
}
.welcome-icon { font-size: 48px; margin-bottom: 16px; }
.welcome-title { font-size: 18px; font-weight: 600; margin-bottom: 8px; }
.welcome-desc { font-size: 13px; color: #909399; margin-bottom: 20px; }
.suggestions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.suggestion-chip {
  padding: 6px 14px;
  background: #ecf5ff;
  color: var(--primary-color);
  border-radius: 16px;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s;
}
.suggestion-chip:hover { background: #d9ecff; }

.message {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}
.message.user { justify-content: flex-end; }
.message-avatar {
  width: 32px; height: 32px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px;
  flex-shrink: 0;
}
.message-body {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
}
.message-body.has-chart {
  max-width: 92%;
  padding: 14px 18px;
}
.message.user .message-body { background: #ecf5ff; }
.message.assistant .message-body { background: #f5f7fa; }
.message.assistant .message-body.has-chart { background: #f8fafc; }
.message-text { word-break: break-word; }
.thinking-body {
  min-width: 240px;
  background: #f0f9ff !important;
  border: 1px solid #e0f2fe;
}
.thinking-status {
  font-size: 13px;
  color: #0284c7;
  margin-bottom: 8px;
  font-weight: 500;
}
.thinking-steps {
  margin-bottom: 8px;
  max-height: 240px;
  overflow-y: auto;
  scroll-behavior: smooth;
}
.thinking-step {
  font-size: 12px;
  padding: 4px 0 4px 16px;
  border-left: 2px solid #bae6fd;
  margin-bottom: 4px;
  line-height: 1.5;
  word-break: break-word;
}
.step-text { color: #606266; }
.step-tool {
  border-left-color: #f59e0b;
  background: #fffbeb;
}
.step-tool .step-text { color: #92400e; font-weight: 500; }
.step-sql {
  border-left-color: #8b5cf6;
  background: #f5f3ff;
  font-family: 'Menlo', 'Monaco', monospace;
  font-size: 11px;
  white-space: pre-wrap;
  max-height: 200px;
  overflow-y: auto;
}
.step-sql .step-text { color: #5b21b6; }
.step-badge { margin-right: 4px; flex-shrink: 0; }

/* 已完成消息中的思考回顾 — 默认收起 */
.thinking-recap {
  margin-top: 8px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  overflow: hidden;
}
.thinking-recap-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  font-size: 12px;
  color: #64748b;
  cursor: pointer;
  user-select: none;
  background: #f8fafc;
  transition: background 0.15s;
}
.thinking-recap-toggle:hover {
  background: #f1f5f9;
}
.thinking-recap-toggle .toggle-icon {
  font-size: 10px;
  width: 14px;
  text-align: center;
}
.thinking-recap .recap-status {
  margin-left: auto;
  font-size: 11px;
  color: #94a3b8;
}
.thinking-recap-steps {
  padding: 6px 10px;
  max-height: 200px;
  overflow-y: auto;
  background: #fafbfc;
}
.thinking-recap-steps .thinking-step {
  font-size: 11px;
  padding: 2px 0 2px 12px;
  margin-bottom: 2px;
}
.typing-indicator {
  display: flex; gap: 4px; padding: 4px 0;
}
.typing-indicator span {
  width: 6px; height: 6px;
  background: #c0c4cc; border-radius: 50%;
  animation: typing 1.4s infinite alternate;
}
.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing {
  from { opacity: 0.3; transform: translateY(0); }
  to { opacity: 1; transform: translateY(-4px); }
}
.chat-input-area {
  padding: 16px 20px;
  border-top: 1px solid var(--border-color);
  display: flex; gap: 10px;
}
.chat-input {
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  font-size: 14px;
  outline: none;
}
.chat-input:focus { border-color: var(--primary-color); }
.send-btn {
  padding: 10px 20px;
  background: var(--primary-color);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
}
.send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.send-btn:not(:disabled):hover { background: #66b1ff; }

/* 气泡内嵌图表 */
.message-chart {
  margin-top: 12px;
  width: 100%;
  min-width: 360px;
  min-height: 300px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 8px;
  background: #fff;
}
/* Markdown 渲染样式 */
.message-text :deep(.md-h3) {
  font-size: 16px; font-weight: 600; color: #303133;
  margin: 16px 0 8px; padding-bottom: 4px;
  border-bottom: 1px solid #ebeef5;
}
.message-text :deep(.md-h4) {
  font-size: 14px; font-weight: 600; color: #303133;
  margin: 12px 0 6px;
}
.message-text :deep(.md-table) {
  width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 13px;
}
.message-text :deep(.md-table td),
.message-text :deep(.md-table th) {
  padding: 6px 12px; border: 1px solid #dcdfe6; text-align: left;
}
.message-text :deep(.md-table th) {
  background: #f5f7fa; font-weight: 600;
}
.message-text :deep(.md-list) {
  padding-left: 20px; margin: 8px 0;
}
.message-text :deep(.md-list li) {
  margin: 4px 0; line-height: 1.6;
}
.message-text :deep(strong) {
  color: #303133; font-weight: 600;
}
.message-text :deep(p) {
  margin: 6px 0; line-height: 1.6;
}
/* 追问建议 */
.followup-chips {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.followup-chip {
  display: inline-block;
  padding: 5px 12px;
  background: #ecf5ff;
  color: #409eff;
  border: 1px solid #d9ecff;
  border-radius: 16px;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
  max-width: 100%;
  word-break: break-word;
}
.followup-chip:hover {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
}
</style>
