<template>
  <div class="trace-page">
    <!-- 左侧：Trace 列表 -->
    <aside class="trace-sidebar">
      <div class="sidebar-header">
        <h3>🔍 链路追踪</h3>
        <span class="trace-count" v-if="stats">{{ stats.total_traces }} 条记录</span>
      </div>

      <!-- 统计概览 -->
      <div class="stats-bar" v-if="stats">
        <div class="stat-item">
          <span class="stat-val">{{ stats.total_llm_calls }}</span>
          <span class="stat-label">LLM</span>
        </div>
        <div class="stat-item">
          <span class="stat-val">{{ stats.total_tool_calls }}</span>
          <span class="stat-label">工具</span>
        </div>
        <div class="stat-item">
          <span class="stat-val">{{ stats.avg_duration_ms }}ms</span>
          <span class="stat-label">均耗时</span>
        </div>
      </div>

      <div class="trace-list" v-if="traces.length > 0">
        <div
          v-for="t in traces"
          :key="t.trace_id"
          class="trace-item"
          :class="{ active: selectedId === t.trace_id, error: t.status === 'error' }"
          @click="selectTrace(t.trace_id)"
        >
          <div class="trace-item-top">
            <span class="trace-badge" :class="t.status">{{ t.status === 'error' ? '❌' : '✅' }}</span>
            <span class="trace-query">{{ truncate(t.query, 50) }}</span>
          </div>
          <div class="trace-item-meta">
            <span>{{ formatTime(t.start_iso) }}</span>
            <span>{{ t.duration_ms }}ms</span>
            <span>{{ t.llm_calls }} LLM</span>
            <span>{{ t.tool_calls }} 工具</span>
          </div>
        </div>
      </div>

      <div class="empty-list" v-else-if="!loading">
        <p>暂无追踪记录</p>
        <p class="empty-hint">发送一条 AI 对话后，这里将显示完整的执行链路</p>
      </div>
    </aside>

    <!-- 右侧：Trace 详情 -->
    <main class="trace-detail">
      <!-- 空状态 -->
      <div class="detail-empty" v-if="!selectedTrace">
        <div class="empty-icon">📡</div>
        <h2>Chat Demo 全链路追踪</h2>
        <p>选择一个 trace 查看从用户输入到最终输出的完整执行过程</p>
        <div class="pipeline-overview">
          <div class="pipeline-step-demo">
            <div class="demo-node user">👤 用户输入</div>
            <div class="demo-arrow">→</div>
            <div class="demo-node agent">🤖 Agent 规划</div>
            <div class="demo-arrow">→</div>
            <div class="demo-node llm">🧠 LLM 推理</div>
            <div class="demo-arrow">→</div>
            <div class="demo-node tool">🔧 工具调用</div>
            <div class="demo-arrow">→</div>
            <div class="demo-node output">📊 最终输出</div>
          </div>
          <div class="demo-loop">⟲ ReAct 循环（LLM → 工具 → LLM → ...）</div>
        </div>
      </div>

      <!-- 选中 Trace 详情 -->
      <template v-if="selectedTrace">
        <!-- Trace 头部 -->
        <div class="detail-header">
          <div class="detail-header-left">
            <h3>
              <span class="status-dot" :class="selectedTrace.status"></span>
              {{ truncate(selectedTrace.query, 80) }}
            </h3>
            <div class="header-meta">
              <span>ID: {{ selectedTrace.trace_id }}</span>
              <span>🕐 {{ formatTime(selectedTrace.start_iso) }}</span>
              <span>⏱️ {{ selectedTrace.duration_ms }}ms</span>
              <span>📋 {{ selectedTrace.events?.length || 0 }} 事件</span>
              <span v-if="selectedTrace.summary?.total_tokens">🪙 {{ selectedTrace.summary.total_tokens }} tokens</span>
            </div>
          </div>
          <button class="btn-close" @click="selectedId = null; selectedTrace = null">✕</button>
        </div>

        <!-- 摘要卡片 -->
        <div class="summary-cards">
          <div class="sum-card">
            <div class="sum-val">{{ summary.llmCalls }}</div>
            <div class="sum-label">LLM 调用</div>
          </div>
          <div class="sum-card">
            <div class="sum-val">{{ summary.toolCalls }}</div>
            <div class="sum-label">工具调用</div>
          </div>
          <div class="sum-card">
            <div class="sum-val">{{ summary.iterations }}</div>
            <div class="sum-label">ReAct 循环</div>
          </div>
          <div class="sum-card">
            <div class="sum-val">{{ summary.totalTokens || 0 }}</div>
            <div class="sum-label">总 Tokens</div>
          </div>
          <div class="sum-card">
            <div class="sum-val">{{ selectedTrace.duration_ms }}ms</div>
            <div class="sum-label">总耗时</div>
          </div>
        </div>

        <!-- 时间线视图 -->
        <div class="timeline-section">
          <h4>📋 执行时间线</h4>
          <div class="timeline">
            <div
              v-for="(evt, i) in selectedTrace.events"
              :key="i"
              class="timeline-item"
              :class="'type-' + evt.type"
            >
              <!-- 时间线节点 -->
              <div class="tl-marker">
                <span class="tl-dot" :class="'dot-' + evt.type"></span>
                <span class="tl-time">{{ evt.elapsed_ms }}ms</span>
              </div>

              <!-- 事件内容 -->
              <div class="tl-content" :class="{ expanded: expandedEvents.has(i) }">
                <!-- 事件头部 — 可点击展开 -->
                <div class="tl-header" @click="toggleEvent(i)">
                  <span class="tl-type-badge" :class="'badge-' + evt.type">
                    {{ typeLabel(evt.type) }}
                  </span>
                  <span class="tl-phase" v-if="evt.phase">[{{ phaseLabel(evt.phase) }}]</span>
                  <span class="tl-title">{{ eventTitle(evt) }}</span>
                  <span class="tl-expand">{{ expandedEvents.has(i) ? '▼' : '▶' }}</span>
                </div>

                <!-- 展开的详情 -->
                <div class="tl-detail" v-if="expandedEvents.has(i)">
                  <!-- 用户输入 -->
                  <div v-if="evt.type === 'user_input'" class="detail-block">
                    <div class="detail-label">📝 用户查询</div>
                    <pre class="detail-pre">{{ evt.data?.query }}</pre>
                  </div>

                  <!-- 阶段切换 -->
                  <div v-if="evt.type === 'phase'" class="detail-block">
                    <div class="detail-label">📌 进入阶段: {{ phaseLabel(evt.data?.phase) }}</div>
                  </div>

                  <!-- LLM 调用 -->
                  <div v-if="evt.type === 'llm_call'" class="detail-block">
                    <div class="detail-label">
                      🤖 LLM 调用 #{{ evt.data?.iteration }}
                      <span class="detail-sub">模型: {{ evt.data?.model }}</span>
                      <span class="detail-sub">耗时: {{ evt.data?.duration_ms }}ms</span>
                      <span v-if="evt.data?.usage" class="detail-sub">
                        Tokens: in={{ evt.data.usage.prompt_tokens }} out={{ evt.data.usage.completion_tokens }}
                      </span>
                    </div>

                    <!-- 输入 Messages -->
                    <div class="subsection">
                      <div class="subsection-title" @click="toggleSub(i, 'input')">
                        {{ expandedSubs.has(i + '-input') ? '▼' : '▶' }} 📥 完整 Prompt ({{ evt.data?.input_messages?.length || 0 }} 条消息)
                      </div>
                      <div v-if="expandedSubs.has(i + '-input')" class="subsection-body">
                        <div
                          v-for="(msg, mi) in (evt.data?.input_messages || [])"
                          :key="mi"
                          class="msg-block"
                        >
                          <div class="msg-role" :class="'role-' + (msg.role || 'unknown')">
                            {{ msg.role?.toUpperCase() }}
                            <span v-if="msg.name" class="msg-name">({{ msg.name }})</span>
                          </div>
                          <pre class="msg-content">{{ msg.content }}</pre>
                          <div v-if="msg.tool_calls" class="msg-toolcalls">
                            <div class="tc-label">🔧 Tool Calls:</div>
                            <div v-for="tc in msg.tool_calls" :key="tc.id" class="tc-item">
                              <code>{{ tc.name }}</code>
                              <pre class="tc-args">{{ formatJson(tc.args) }}</pre>
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- 输出响应 -->
                    <div class="subsection">
                      <div class="subsection-title" @click="toggleSub(i, 'output')">
                        {{ expandedSubs.has(i + '-output') ? '▼' : '▶' }} 📤 原始响应
                      </div>
                      <div v-if="expandedSubs.has(i + '-output')" class="subsection-body">
                        <div class="output-block">
                          <div class="output-content">
                            <pre>{{ evt.data?.output?.content || '(无文本内容)' }}</pre>
                          </div>
                          <div v-if="evt.data?.output?.tool_calls" class="output-toolcalls">
                            <div class="tc-label">🔧 决定调用的工具:</div>
                            <div v-for="tc in evt.data.output.tool_calls" :key="tc.id" class="tc-item">
                              <code>{{ tc.name }}</code>
                              <pre class="tc-args">{{ formatJson(tc.args) }}</pre>
                            </div>
                          </div>
                          <div v-if="evt.data?.output?.finish_reason" class="output-meta">
                            finish_reason: {{ evt.data.output.finish_reason }}
                          </div>
                          <div v-if="evt.data?.output?.usage" class="output-meta">
                            usage: {{ formatJson(evt.data.output.usage) }}
                          </div>
                        </div>
                      </div>
                    </div>

                    <!-- 错误 -->
                    <div v-if="evt.error" class="detail-error">
                      ❌ {{ evt.data?.output?.error || '调用失败' }}
                    </div>
                  </div>

                  <!-- 工具调用 -->
                  <div v-if="evt.type === 'tool_call'" class="detail-block">
                    <div class="detail-label">
                      🔧 {{ evt.data?.name }}
                      <span class="detail-sub">耗时: {{ evt.data?.duration_ms }}ms</span>
                      <span v-if="evt.error" class="detail-error-sub">❌ 失败</span>
                    </div>
                    <div class="detail-desc" v-if="evt.data?.description">{{ evt.data.description }}</div>

                    <!-- 输入参数 -->
                    <div class="subsection">
                      <div class="subsection-title" @click="toggleSub(i, 'args')">
                        {{ expandedSubs.has(i + '-args') ? '▼' : '▶' }} 📥 输入参数
                      </div>
                      <pre v-if="expandedSubs.has(i + '-args')" class="detail-pre">{{ formatJson(evt.data?.args) }}</pre>
                    </div>

                    <!-- 输出结果 -->
                    <div class="subsection">
                      <div class="subsection-title" @click="toggleSub(i, 'output')">
                        {{ expandedSubs.has(i + '-output') ? '▼' : '▶' }} 📤 输出结果
                      </div>
                      <pre v-if="expandedSubs.has(i + '-output')" class="detail-pre">{{ formatJson(evt.data?.output) }}</pre>
                    </div>

                    <div v-if="evt.data?.error" class="detail-error">
                      ❌ {{ evt.data.error }}
                    </div>
                  </div>

                  <!-- 最终输出 -->
                  <div v-if="evt.type === 'final'" class="detail-block">
                    <div class="detail-label">✅ 执行完成</div>
                    <pre class="detail-pre">{{ formatJson(evt.data) }}</pre>
                  </div>

                  <!-- 错误 -->
                  <div v-if="evt.type === 'error'" class="detail-block error-block">
                    <div class="detail-label">❌ 错误</div>
                    <pre class="detail-pre">{{ evt.data?.error }}</pre>
                  </div>

                  <!-- 时间戳 -->
                  <div class="detail-ts">{{ evt.timestamp }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 循环流程图 -->
        <div class="flow-section" v-if="hasEvents">
          <h4>🔄 ReAct 循环流程</h4>
          <div class="flow-diagram">
            <template v-for="(evt, i) in selectedTrace.events" :key="i">
              <!-- Phase 分隔 -->
              <div v-if="evt.type === 'phase'" class="flow-phase-sep">
                <span class="flow-phase-label">{{ phaseLabel(evt.data?.phase) }}</span>
              </div>

              <!-- LLM 调用 -->
              <div v-if="evt.type === 'llm_call'" class="flow-node-wrap">
                <div class="flow-node llm" :class="{ error: evt.error }">
                  <div class="flow-node-icon">🧠</div>
                  <div class="flow-node-title">LLM #{{ evt.data?.iteration }}</div>
                  <div class="flow-node-detail">{{ evt.data?.model }}</div>
                  <div class="flow-node-detail">{{ evt.data?.duration_ms }}ms</div>
                  <div class="flow-node-detail" v-if="evt.data?.output?.tool_calls?.length">
                    → 调用 {{ evt.data.output.tool_calls.length }} 个工具
                  </div>
                  <div class="flow-node-detail" v-else-if="evt.data?.output?.content">
                    → 返回文本
                  </div>
                </div>
                <div class="flow-arrow">↓</div>
              </div>

              <!-- 工具调用 -->
              <div v-if="evt.type === 'tool_call'" class="flow-node-wrap">
                <div class="flow-node tool" :class="{ error: evt.error }">
                  <div class="flow-node-icon">🔧</div>
                  <div class="flow-node-title">{{ evt.data?.name }}</div>
                  <div class="flow-node-detail">{{ evt.data?.duration_ms }}ms</div>
                </div>
                <div class="flow-arrow">↓</div>
              </div>
            </template>

            <!-- 最终输出 -->
            <div class="flow-node-wrap">
              <div class="flow-node output" :class="{ error: selectedTrace.status === 'error' }">
                <div class="flow-node-icon">{{ selectedTrace.status === 'error' ? '❌' : '✅' }}</div>
                <div class="flow-node-title">{{ selectedTrace.status === 'error' ? '失败' : '完成' }}</div>
                <div class="flow-node-detail">{{ selectedTrace.duration_ms }}ms 总耗时</div>
                <div class="flow-node-detail" v-if="selectedTrace.summary?.total_tokens">
                  {{ selectedTrace.summary.total_tokens }} tokens
                </div>
              </div>
            </div>
          </div>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { getTraceList, getTraceDetail, getTraceStats } from '../api'

// ---- 类型 ----
interface TraceSummary {
  trace_id: string
  timestamp: string
  session_id: string
  user_query: string
  total_duration_ms: number
  step_count: number
  llm_call_count: number
  tool_call_count: number
  chart_type: string
  has_error: boolean
  status: string
  file_name: string
}

interface TraceEvent {
  seq: number
  type: string
  phase: string
  timestamp: string
  elapsed_ms: number
  data: any
  error?: boolean
}

interface TraceDetail {
  trace_id: string
  query: string
  session_id: string
  endpoint: string
  start_iso: string
  duration_ms: number
  status: string
  summary: any
  events: TraceEvent[]
}

// ---- 状态 ----
const loading = ref(false)
const traces = ref<TraceSummary[]>([])
const stats = ref<any>(null)
const selectedId = ref<string | null>(null)
const selectedTrace = ref<TraceDetail | null>(null)
const expandedEvents = ref<Set<number>>(new Set())
const expandedSubs = ref<Set<string>>(new Set())

// ---- 计算属性 ----
const summary = computed(() => {
  if (!selectedTrace.value) return { llmCalls: 0, toolCalls: 0, iterations: 0, totalTokens: 0 }
  const events = selectedTrace.value.events || []
  return {
    llmCalls: events.filter(e => e.type === 'llm_call').length,
    toolCalls: events.filter(e => e.type === 'tool_call').length,
    iterations: selectedTrace.value.summary?.iterations || 0,
    totalTokens: selectedTrace.value.summary?.total_tokens || 0,
  }
})

const hasEvents = computed(() => {
  return selectedTrace.value && (selectedTrace.value.events?.length || 0) > 0
})

// ---- 方法 ----
async function loadTraces() {
  loading.value = true
  try {
    const [listRes, statsRes] = await Promise.all([
      getTraceList(100),
      getTraceStats(),
    ])
    traces.value = listRes.data.traces || []
    stats.value = statsRes.data
  } catch (e) {
    console.error('加载 trace 列表失败', e)
  } finally {
    loading.value = false
  }
}

async function selectTrace(traceId: string) {
  selectedId.value = traceId
  expandedEvents.value.clear()
  expandedSubs.value.clear()
  try {
    const res = await getTraceDetail(traceId)
    selectedTrace.value = res.data.trace
  } catch (e) {
    console.error('加载 trace 详情失败', e)
    selectedTrace.value = null
  }
}

function toggleEvent(index: number) {
  const s = new Set(expandedEvents.value)
  if (s.has(index)) s.delete(index)
  else s.add(index)
  expandedEvents.value = s
}

function toggleSub(eventIdx: number, key: string) {
  const s = new Set(expandedSubs.value)
  const fullKey = `${eventIdx}-${key}`
  if (s.has(fullKey)) s.delete(fullKey)
  else s.add(fullKey)
  expandedSubs.value = s
}

function typeLabel(type: string): string {
  const map: Record<string, string> = {
    user_input: '👤 输入',
    phase: '📌 阶段',
    llm_call: '🤖 LLM',
    tool_call: '🔧 工具',
    final: '✅ 输出',
    error: '❌ 错误',
  }
  return map[type] || type
}

function phaseLabel(phase: string): string {
  const map: Record<string, string> = {
    ask: '查询执行',
    plot: '图表生成',
    followup: '追问生成',
  }
  return map[phase] || phase
}

function eventTitle(evt: TraceEvent): string {
  switch (evt.type) {
    case 'user_input':
      return `用户查询: ${truncate(evt.data?.query || '', 60)}`
    case 'llm_call':
      const tc = evt.data?.output?.tool_calls?.length || 0
      const content = evt.data?.output?.content
      return tc > 0
        ? `决定调用 ${tc} 个工具`
        : `返回文本: ${truncate(content || '', 80)}`
    case 'tool_call':
      return `${evt.data?.name || ''} (${evt.data?.duration_ms}ms)`
    case 'final':
      return '执行完成'
    case 'error':
      return `错误: ${truncate(evt.data?.error || '', 60)}`
    default:
      return ''
  }
}

function truncate(s: string, n: number): string {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '...' : s
}

function formatTime(iso: string): string {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

function formatJson(obj: any): string {
  if (!obj) return '(无)'
  try {
    if (typeof obj === 'string') {
      // 尝试解析 JSON 字符串
      try { return JSON.stringify(JSON.parse(obj), null, 2) } catch { return obj }
    }
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

// ---- 初始加载 ----
onMounted(loadTraces)
</script>

<style scoped>
.trace-page {
  display: flex;
  height: calc(100vh - 60px);
  background: #f5f7fa;
}

/* ====== 侧边栏 ====== */
.trace-sidebar {
  width: 340px;
  flex-shrink: 0;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sidebar-header {
  padding: 16px 20px;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.sidebar-header h3 { font-size: 16px; margin: 0; }
.trace-count { font-size: 12px; color: #909399; }

.stats-bar {
  display: flex;
  gap: 0;
  padding: 10px 16px;
  border-bottom: 1px solid #ebeef5;
  background: #fafbfc;
}
.stat-item {
  flex: 1;
  text-align: center;
}
.stat-val { display: block; font-size: 16px; font-weight: 600; color: #303133; }
.stat-label { display: block; font-size: 11px; color: #909399; margin-top: 2px; }

.trace-list {
  flex: 1;
  overflow-y: auto;
}
.trace-item {
  padding: 10px 16px;
  border-bottom: 1px solid #f0f0f0;
  cursor: pointer;
  transition: background 0.15s;
}
.trace-item:hover { background: #f5f7fa; }
.trace-item.active { background: #ecf5ff; border-left: 3px solid #409eff; }
.trace-item.error .trace-badge { color: #f56c6c; }

.trace-item-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}
.trace-badge { font-size: 14px; flex-shrink: 0; }
.trace-query {
  font-size: 13px;
  color: #303133;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trace-item-meta {
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: #909399;
}

.empty-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #909399;
  padding: 40px 20px;
  text-align: center;
}
.empty-hint { font-size: 12px; margin-top: 8px; }

/* ====== 详情区 ====== */
.trace-detail {
  flex: 1;
  overflow-y: auto;
  padding: 0;
}

.detail-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  text-align: center;
  color: #909399;
}
.empty-icon { font-size: 64px; margin-bottom: 16px; }
.detail-empty h2 { font-size: 20px; color: #303133; margin-bottom: 8px; }
.detail-empty p { font-size: 14px; }

.pipeline-overview {
  margin-top: 30px;
  padding: 20px;
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
}
.pipeline-step-demo {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
}
.demo-node {
  padding: 8px 16px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 500;
}
.demo-node.user { background: #ecf5ff; color: #409eff; }
.demo-node.agent { background: #fef0f0; color: #f56c6c; }
.demo-node.llm { background: #fdf6ec; color: #e6a23c; }
.demo-node.tool { background: #e8f5e9; color: #67c23a; }
.demo-node.output { background: #f5f3ff; color: #8b5cf6; }
.demo-arrow { font-size: 18px; color: #c0c4cc; }
.demo-loop {
  margin-top: 12px;
  font-size: 13px;
  color: #e6a23c;
  font-style: italic;
}

/* ---- Trace 头部 ---- */
.detail-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 16px 24px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
  position: sticky;
  top: 0;
  z-index: 10;
}
.detail-header-left h3 {
  margin: 0 0 6px;
  font-size: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.status-dot {
  width: 8px; height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.status-dot.success { background: #67c23a; }
.status-dot.error { background: #f56c6c; }
.header-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #909399;
}
.btn-close {
  background: none;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 14px;
  color: #909399;
}
.btn-close:hover { background: #f5f7fa; }

/* ---- 摘要卡片 ---- */
.summary-cards {
  display: flex;
  gap: 12px;
  padding: 16px 24px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}
.sum-card {
  flex: 1;
  text-align: center;
  padding: 10px;
  background: #fafbfc;
  border-radius: 8px;
}
.sum-val { font-size: 22px; font-weight: 700; color: #303133; }
.sum-label { font-size: 11px; color: #909399; margin-top: 4px; }

/* ---- 时间线 ---- */
.timeline-section {
  padding: 16px 24px;
}
.timeline-section h4 {
  margin: 0 0 12px;
  font-size: 15px;
}
.timeline {
  position: relative;
}
.timeline::before {
  content: '';
  position: absolute;
  left: 60px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: #e4e7ed;
}

.timeline-item {
  display: flex;
  gap: 16px;
  margin-bottom: 4px;
  position: relative;
}
.tl-marker {
  width: 70px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 8px;
  position: relative;
  z-index: 1;
}
.tl-dot {
  width: 12px; height: 12px;
  border-radius: 50%;
  display: block;
  border: 2px solid #fff;
  box-shadow: 0 0 0 2px #dcdfe6;
}
.dot-user_input { background: #409eff; box-shadow: 0 0 0 2px #409eff; }
.dot-llm_call { background: #e6a23c; box-shadow: 0 0 0 2px #e6a23c; }
.dot-tool_call { background: #67c23a; box-shadow: 0 0 0 2px #67c23a; }
.dot-phase { background: #909399; box-shadow: 0 0 0 2px #909399; }
.dot-final { background: #8b5cf6; box-shadow: 0 0 0 2px #8b5cf6; }
.dot-error { background: #f56c6c; box-shadow: 0 0 0 2px #f56c6c; }

.tl-time {
  font-size: 10px;
  color: #c0c4cc;
  margin-top: 4px;
}

.tl-content {
  flex: 1;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  margin-bottom: 8px;
  overflow: hidden;
  transition: box-shadow 0.15s;
}
.tl-content.expanded { box-shadow: 0 2px 8px rgba(0,0,0,0.06); }

.tl-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  font-size: 13px;
}
.tl-header:hover { background: #fafbfc; }
.tl-expand { margin-left: auto; font-size: 10px; color: #c0c4cc; }

.tl-type-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 500;
  flex-shrink: 0;
}
.badge-user_input { background: #ecf5ff; color: #409eff; }
.badge-llm_call { background: #fdf6ec; color: #e6a23c; }
.badge-tool_call { background: #e8f5e9; color: #67c23a; }
.badge-phase { background: #f4f4f5; color: #909399; }
.badge-final { background: #f5f3ff; color: #8b5cf6; }
.badge-error { background: #fef0f0; color: #f56c6c; }

.tl-phase { font-size: 11px; color: #909399; flex-shrink: 0; }
.tl-title { color: #606266; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ---- 事件详情 ---- */
.tl-detail {
  padding: 0 12px 12px;
  border-top: 1px solid #f0f0f0;
}

.detail-block { margin-top: 8px; }
.detail-label {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.detail-sub { font-size: 11px; font-weight: 400; color: #909399; }
.detail-error-sub { color: #f56c6c; font-weight: 500; }
.detail-desc { font-size: 12px; color: #909399; margin-bottom: 8px; font-style: italic; }
.detail-ts { font-size: 10px; color: #c0c4cc; text-align: right; margin-top: 8px; }

.detail-pre {
  background: #fafbfc;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 10px;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 500px;
  overflow-y: auto;
  margin: 0;
  color: #303133;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
}

.detail-error {
  margin-top: 8px;
  padding: 8px 12px;
  background: #fef0f0;
  border: 1px solid #fde2e2;
  border-radius: 4px;
  color: #f56c6c;
  font-size: 13px;
}
.error-block .detail-pre { border-color: #fde2e2; background: #fef0f0; color: #f56c6c; }

/* ---- 子展开区域 ---- */
.subsection {
  margin-top: 6px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  overflow: hidden;
}
.subsection-title {
  padding: 6px 10px;
  background: #fafbfc;
  font-size: 12px;
  color: #606266;
  cursor: pointer;
  user-select: none;
}
.subsection-title:hover { background: #f0f2f5; }
.subsection-body { padding: 8px; }

/* ---- 消息块 ---- */
.msg-block {
  margin-bottom: 10px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  overflow: hidden;
}
.msg-role {
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 700;
  color: #fff;
}
.role-system { background: #909399; }
.role-user { background: #409eff; }
.role-assistant { background: #e6a23c; }
.role-tool { background: #67c23a; }
.role-ai { background: #e6a23c; }
.role-human { background: #409eff; }
.msg-name { font-weight: 400; opacity: 0.8; }
.msg-content {
  padding: 8px 10px;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
  margin: 0;
  background: #fff;
  color: #303133;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
}
.msg-toolcalls {
  padding: 6px 10px;
  background: #fdf6ec;
  border-top: 1px solid #faecd8;
}
.tc-label { font-size: 12px; font-weight: 600; color: #e6a23c; margin-bottom: 4px; }
.tc-item {
  margin-bottom: 6px;
  padding: 4px 8px;
  background: #fff;
  border-radius: 4px;
}
.tc-item code {
  font-size: 12px;
  color: #303133;
  background: #f5f7fa;
  padding: 2px 6px;
  border-radius: 3px;
}
.tc-args {
  font-size: 11px;
  margin: 4px 0 0;
  padding: 6px;
  background: #fafbfc;
  border-radius: 3px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow-y: auto;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
}

/* ---- 输出块 ---- */
.output-block {
  padding: 0;
}
.output-content pre {
  padding: 8px 10px;
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  color: #303133;
}
.output-toolcalls {
  padding: 6px 10px;
  background: #fdf6ec;
  border-top: 1px solid #faecd8;
}
.output-meta {
  padding: 4px 10px;
  font-size: 11px;
  color: #909399;
  border-top: 1px solid #f0f0f0;
}

/* ====== 流程图 ====== */
.flow-section {
  padding: 16px 24px 40px;
}
.flow-section h4 { margin: 0 0 16px; font-size: 15px; }
.flow-diagram {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0;
}
.flow-phase-sep {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
}
.flow-phase-label {
  font-size: 13px;
  font-weight: 600;
  color: #909399;
  background: #f4f4f5;
  padding: 4px 16px;
  border-radius: 12px;
}
.flow-node-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.flow-node {
  padding: 12px 20px;
  border-radius: 8px;
  text-align: center;
  min-width: 200px;
  border: 2px solid #e4e7ed;
  background: #fff;
  transition: box-shadow 0.15s;
}
.flow-node:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.flow-node.llm { border-color: #e6a23c; background: #fdf6ec; }
.flow-node.tool { border-color: #67c23a; background: #e8f5e9; }
.flow-node.output { border-color: #8b5cf6; background: #f5f3ff; }
.flow-node.error { border-color: #f56c6c; background: #fef0f0; }

.flow-node-icon { font-size: 20px; }
.flow-node-title { font-size: 14px; font-weight: 600; color: #303133; margin: 4px 0; }
.flow-node-detail { font-size: 11px; color: #909399; }

.flow-arrow {
  font-size: 20px;
  color: #c0c4cc;
  padding: 4px 0;
}
</style>
