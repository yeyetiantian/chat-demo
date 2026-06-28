<template>
  <div class="pivot-table-wrapper">
    <div v-if="!hasData" class="pivot-empty">暂无透视数据</div>
    <div v-else class="pivot-table-scroll">
      <table class="pivot-table">
        <thead>
          <tr>
            <th v-for="col in columns" :key="col" class="pivot-th">
              {{ col }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, ri) in rows" :key="ri" class="pivot-tr">
            <td v-for="col in columns" :key="col" class="pivot-td">
              {{ formatValue(row[col]) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="hasData" class="pivot-footer">
      共 {{ rows.length }} 行 × {{ columns.length }} 列
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  data: any
}>()

const hasData = computed(() => {
  const rows = props.data?.rows || props.data?.data || []
  return rows.length > 0
})

const columns = computed(() => {
  return props.data?.columns || (props.data?.rows?.[0] ? Object.keys(props.data.rows[0]) : [])
})

const rows = computed(() => {
  return props.data?.rows || props.data?.data || []
})

function formatValue(val: any): string {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'number') {
    return Number.isInteger(val) ? val.toLocaleString() : val.toFixed(2)
  }
  // 截断时间戳显示
  const str = String(val)
  if (str.length > 25 && (str.includes('T') || str.includes(':'))) {
    return str.substring(0, 19)
  }
  return str.length > 30 ? str.substring(0, 30) + '...' : str
}
</script>

<style scoped>
.pivot-table-wrapper {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
}
.pivot-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: #909399;
}
.pivot-table-scroll {
  flex: 1;
  overflow: auto;
}
.pivot-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.pivot-th {
  position: sticky;
  top: 0;
  background: #f5f7fa;
  padding: 10px 12px;
  text-align: left;
  border-bottom: 2px solid #dcdfe6;
  white-space: nowrap;
  font-weight: 600;
  z-index: 1;
}
.pivot-td {
  padding: 8px 12px;
  border-bottom: 1px solid #ebeef5;
  white-space: nowrap;
}
.pivot-tr:hover .pivot-td {
  background: #f5f7fa;
}
.pivot-footer {
  padding: 8px 12px;
  font-size: 12px;
  color: #909399;
  border-top: 1px solid #dcdfe6;
}
</style>
