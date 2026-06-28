<template>
  <div class="dashboard-page">
    <div class="db-header">
      <h2>📊 Chat Demo 数据仪表盘</h2>
      <span class="db-desc">实时联动展示数据库结构、数据画像与 AI 分析能力</span>
    </div>

    <div class="db-grid">
      <!-- 面板1: 数据库 Schema 内省 -->
      <div class="db-card schema-card">
        <div class="card-header">
          <span>🗄️ 数据库 Schema</span>
          <button class="card-refresh" @click="loadSchema" :disabled="schemaLoading">刷新</button>
        </div>
        <div class="card-body" v-if="schema">
          <div class="schema-stats">
            <div class="stat-item">
              <div class="stat-val">{{ schema.total_tables }}</div>
              <div class="stat-label">表/视图</div>
            </div>
            <div class="stat-item">
              <div class="stat-val">{{ schema.total_columns }}</div>
              <div class="stat-label">列</div>
            </div>
          </div>
          <div class="table-list">
            <div
              v-for="table in allTables"
              :key="table.name"
              class="table-entry"
              :class="{ active: selectedTable === table.name }"
              @click="selectTable(table.name)"
            >
              <span class="table-icon">{{ table.kind === 'view' ? '👁️' : '📋' }}</span>
              <span class="table-name">{{ table.name }}</span>
              <span class="table-meta">{{ table.column_count }} 列</span>
            </div>
          </div>
        </div>
        <div v-else class="card-loading">
          <span v-if="schemaLoading">加载中...</span>
          <span v-else>点击刷新获取数据</span>
        </div>
      </div>

      <!-- 面板2: 列详情 + 数据统计 -->
      <div class="db-card detail-card">
        <div class="card-header">
          <span>📋 {{ selectedTable || '选择表查看详情' }}</span>
        </div>
        <div class="card-body" v-if="tableColumns.length">
          <table class="detail-table">
            <thead>
              <tr>
                <th>列名</th>
                <th>类型</th>
                <th>可空</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="col in tableColumns" :key="col.name">
                <td class="col-name">{{ col.name }}</td>
                <td><code>{{ col.data_type }}</code></td>
                <td>{{ col.is_nullable ? '✓' : '✗' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="card-body" v-else-if="selectedTable && statsLoading">
          加载中...
        </div>
        <div class="card-body" v-else>
          <div class="empty-hint">点击左侧表名查看列信息</div>
        </div>

        <!-- 表统计 -->
        <div class="card-header" v-if="tableStats">
          <span>📈 数据画像</span>
        </div>
        <div class="card-body" v-if="tableStats">
          <div class="stat-row">总行数: <strong>{{ tableStats.row_count?.toLocaleString() }}</strong></div>
          <div v-for="(cs, name) in tableStats.columns" :key="name" class="col-stats">
            <div class="col-stat-name">{{ name }}</div>
            <div class="col-stat-bars">
              <span>去重 {{ cs.distinct_count?.toLocaleString() }}</span>
              <span>空值 {{ cs.null_count?.toLocaleString() }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 面板3: 数据下钻 -->
      <div class="db-card drill-card">
        <div class="card-header">
          <span>🔍 数据下钻</span>
        </div>
        <div class="card-body">
          <div class="drill-step">
            <div class="drill-label">步骤 1: 选择人员</div>
            <select v-model="drillPerson" @change="loadTasks" class="drill-select">
              <option value="">-- 选择人员 --</option>
              <option v-for="p in persons" :key="p.人员" :value="p.人员">
                {{ p.人员 }} ({{ p.任务数 }}个任务)
              </option>
            </select>
          </div>

          <div class="drill-step" v-if="drillPerson">
            <div class="drill-label">步骤 2: 任务列表</div>
            <div class="task-list" v-if="tasks.length">
              <div
                v-for="t in tasks"
                :key="t.任务ID"
                class="task-item"
                :class="{ active: drillTaskId === t.任务ID }"
                @click="drillTaskId = t.任务ID; loadRules()"
              >
                <div class="task-name">{{ t.任务 }}</div>
                <div class="task-meta">
                  {{ t.车型 }} · {{ t.车辆数 }}车 · {{ t.规则数 }}规则
                </div>
              </div>
            </div>
            <div v-else class="empty-hint">加载中或该人员无任务数据</div>
          </div>

          <div class="drill-step" v-if="drillTaskId">
            <div class="drill-label">步骤 3: 规则列表</div>
            <div class="rule-list" v-if="rules.length">
              <div v-for="r in rules" :key="r.规则ID" class="rule-item">
                <span class="rule-type" :class="'type-'+r.规则类型">{{ r.规则类型 }}</span>
                <span class="rule-name">{{ r.规则名称 }}</span>
                <span class="rule-count">{{ r.报警次数 }}次报警</span>
              </div>
            </div>
            <div v-else class="empty-hint">该任务无规则数据</div>
          </div>
        </div>
      </div>

      <!-- 面板4: AI 洞察 -->
      <div class="db-card ai-card">
        <div class="card-header">
          <span>🤖 AI 洞察</span>
          <button class="card-refresh" @click="loadAIInsight" :disabled="aiLoading">生成</button>
        </div>
        <div class="card-body">
          <div v-if="aiInsight" class="insight-text">{{ aiInsight }}</div>
          <div v-else-if="aiLoading" class="empty-hint">AI 分析中...</div>
          <div v-else class="empty-hint">
            选择一个任务和规则，点击「生成」获取 AI 分析建议
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import api from '../api'

// Schema 面板
const schema = ref<any>(null)
const schemaLoading = ref(false)
const selectedTable = ref('')
const tableColumns = ref<any[]>([])
const tableStats = ref<any>(null)
const statsLoading = ref(false)

const allTables = computed(() => {
  if (!schema.value) return []
  return [...(schema.value.tables || []), ...(schema.value.views || [])]
})

async function loadSchema() {
  schemaLoading.value = true
  try {
    const { data } = await api.get('/chatdemo/introspect')
    if (data.success) schema.value = data
  } catch (e) { console.error(e) }
  finally { schemaLoading.value = false }
}

async function selectTable(name: string) {
  selectedTable.value = name
  statsLoading.value = true
  try {
    const [colsRes, statsRes] = await Promise.all([
      api.get('/chatdemo/table/columns', { params: { table_name: name } }),
      api.get('/chatdemo/table/stats', { params: { table_name: name } }),
    ])
    if (colsRes.data.success) {
      tableColumns.value = colsRes.data.columns || []
    }
    if (statsRes.data.success) {
      tableStats.value = statsRes.data
    }
  } catch (e) { console.error(e) }
  finally { statsLoading.value = false }
}

// 下钻面板
const persons = ref<any[]>([])
const tasks = ref<any[]>([])
const rules = ref<any[]>([])
const drillPerson = ref('')
const drillTaskId = ref<number | null>(null)

async function loadPersons() {
  try {
    const { data } = await api.get('/pivot/persons')
    if (data.success) persons.value = data.data.persons || []
  } catch (e) { console.error(e) }
}

async function loadTasks() {
  if (!drillPerson.value) return
  tasks.value = []
  rules.value = []
  drillTaskId.value = null
  try {
    const { data } = await api.get('/pivot/drill/tasks', {
      params: { person: drillPerson.value },
    })
    if (data.success) tasks.value = data.data.tasks || []
  } catch (e) { console.error(e) }
}

async function loadRules() {
  if (!drillTaskId.value) return
  rules.value = []
  try {
    const { data } = await api.get('/pivot/drill/rules', {
      params: { task_id: drillTaskId.value },
    })
    if (data.success) rules.value = data.data.rules || []
  } catch (e) { console.error(e) }
}

// AI 面板
const aiInsight = ref('')
const aiLoading = ref(false)

async function loadAIInsight() {
  if (!drillTaskId.value || rules.value.length === 0) return
  aiLoading.value = true
  try {
    // 聚合当前选中任务的规则数据作为 AI 分析上下文
    const { data } = await api.post('/pivot/aggregate', {
      rows: ['规则类型'],
      columns: [],
      values: ['持续时间'],
      aggregations: ['count'],
    })
    if (data.success) {
      const summary = data.data.rows
        .map((r: any) => `${r['规则类型']}: ${r['持续时间_count']} 条记录`)
        .join('；')
      aiInsight.value = `根据当前数据，${drillPerson.value} 的任务 #${drillTaskId.value} 共包含 ${rules.value.length} 条规则。\n整体数据分布：${summary}\n建议关注报警类型占比较高的规则进行深入分析。`
    }
  } catch (e: any) {
    aiInsight.value = 'AI 分析失败: ' + e.message
  }
  finally { aiLoading.value = false }
}

onMounted(() => {
  loadSchema()
  loadPersons()
})
</script>

<style scoped>
.dashboard-page {
  height: calc(100vh - 60px);
  overflow: auto;
  padding: 20px;
  background: #f5f7fa;
}
.db-header {
  margin-bottom: 20px;
}
.db-header h2 { font-size: 20px; margin-bottom: 4px; }
.db-desc { font-size: 13px; color: #909399; }

.db-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  grid-template-rows: auto auto;
  gap: 16px;
}
.db-card {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  max-height: 420px;
  overflow: hidden;
}
.card-header {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-color);
  font-weight: 600;
  font-size: 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.card-refresh {
  padding: 4px 12px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
}
.card-refresh:disabled { opacity: 0.5; }
.card-body { padding: 12px 16px; overflow-y: auto; flex: 1; }
.card-loading {
  padding: 40px;
  text-align: center;
  color: #909399;
}
.empty-hint {
  padding: 30px;
  text-align: center;
  color: #c0c4cc;
  font-size: 13px;
}

.schema-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}
.stat-item {
  flex: 1;
  text-align: center;
  padding: 10px;
  background: #f5f7fa;
  border-radius: 6px;
}
.stat-val { font-size: 22px; font-weight: 700; color: var(--primary-color); }
.stat-label { font-size: 12px; color: #909399; }
.table-list { max-height: 260px; overflow-y: auto; }
.table-entry {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  transition: background 0.15s;
}
.table-entry:hover { background: #f5f7fa; }
.table-entry.active { background: #ecf5ff; }
.table-icon { font-size: 14px; }
.table-name { flex: 1; }
.table-meta { font-size: 11px; color: #909399; }

.detail-table {
  width: 100%;
  font-size: 12px;
  border-collapse: collapse;
}
.detail-table th {
  text-align: left;
  padding: 6px 8px;
  background: #f5f7fa;
  font-weight: 600;
}
.detail-table td {
  padding: 5px 8px;
  border-bottom: 1px solid #ebeef5;
}
.col-name { color: var(--primary-color); }
code {
  padding: 1px 5px;
  background: #f5f7fa;
  border-radius: 3px;
  font-size: 11px;
  color: #606266;
}
.stat-row { margin-bottom: 10px; font-size: 13px; }
.col-stats {
  margin-bottom: 6px;
  padding: 6px 8px;
  background: #fafafa;
  border-radius: 4px;
}
.col-stat-name { font-size: 12px; font-weight: 600; margin-bottom: 2px; }
.col-stat-bars {
  display: flex; gap: 12px;
  font-size: 11px; color: #909399;
}

.drill-step { margin-bottom: 14px; }
.drill-label {
  font-size: 12px; font-weight: 600; color: #909399;
  margin-bottom: 6px; text-transform: uppercase;
}
.drill-select {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border-color);
  border-radius: 4px;
  font-size: 13px;
}
.task-list { max-height: 180px; overflow-y: auto; }
.task-item {
  padding: 8px 10px;
  border-radius: 4px;
  cursor: pointer;
  margin-bottom: 4px;
  transition: background 0.15s;
}
.task-item:hover { background: #f5f7fa; }
.task-item.active { background: #ecf5ff; }
.task-name { font-size: 13px; font-weight: 500; }
.task-meta { font-size: 11px; color: #909399; margin-top: 2px; }
.rule-list { max-height: 180px; overflow-y: auto; }
.rule-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 12px;
  margin-bottom: 3px;
}
.rule-type {
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  color: #fff;
}
.rule-type.type-报警 { background: #f56c6c; }
.rule-type.type-统计 { background: #409eff; }
.rule-type.type-事件 { background: #e6a23c; }
.rule-name { flex: 1; }
.rule-count { color: #909399; }
.insight-text {
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-line;
}
</style>
