<template>
  <section class="page" data-module="minearea">
    <header class="page-head">
      <div>
        <h2>矿区台账管理</h2>
        <p class="page-desc">维护矿区，围绕矿区编号、矿区名称、开采矿种、核定产能做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记矿区</button>
        <button class="btn primary" type="button" title="从 CSV 文件一次提交一批矿区" @click="pickBatchFile">批量建档</button>
        <button class="btn" type="button" @click="downloadTemplate">下载模板</button>
        <button class="btn" type="button" @click="exportRows">导出矿区台账清单</button>
        <input ref="fileInput" class="hidden-input" type="file" accept=".csv,text/csv" @change="onBatchFile" />
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section v-if="receipt" class="receipt-panel">
      <header class="receipt-head">
        <strong>批量建档回执</strong>
        <span>{{ receipt.message }}</span>
      </header>
      <table class="data-table">
        <thead>
          <tr><th>行号</th><th>矿区编号</th><th>矿区名称</th><th>结果</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in receipt.results" :key="item.line">
            <td>{{ item.line }}</td>
            <td>{{ item.code || '—' }}</td>
            <td>{{ item.name || '—' }}</td>
            <td :class="{ 'ok-text': item.result === '已入库', 'error-text': item.result === '整行退回' }">{{ item.result }}</td>
            <td>{{ item.message }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无矿区台账数据，可先登记矿区</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条矿区台账记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type Stat = { label: string; value: number }
type ReceiptItem = { line: number; code: string; name: string; result: string; message: string }
type Receipt = { message: string; results: ReceiptItem[] }
type Summary = { 在册矿区数: number; 待办数: number; 状态分布: Record<string, number> }

const ENDPOINT = '/api/minearea'
const columns = ["矿区编号", "矿区名称", "开采矿种", "核定产能", "开采方式", "服务年限", "安全等级", "矿区状态"]
const actions = ["停产整顿", "恢复生产", "闭坑登记"]
const statuses = ["正常生产", "停产整顿", "检修中", "已闭坑"]
// 批量建档的 CSV 列顺序，与下载模板一致
const CSV_FIELDS = ["矿区编号", "矿区名称", "开采矿种", "核定产能", "开采方式", "服务年限", "安全等级", "矿区状态"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref<Stat[]>([
  { label: '在册矿区数', value: 0 },
  { label: '正常矿区', value: 0 },
  { label: '整顿矿区', value: 0 },
  { label: '闭坑矿区', value: 0 },
])
const receipt = ref<Receipt | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '矿区登记入口尚未接入审批流'
}

function pickBatchFile() {
  fileInput.value?.click()
}

function downloadTemplate() {
  const sample = ['MINE-0004,北坡煤矿,煤矿,90万吨/年,井工开采,25年,,']
  const text = `\uFEFF${CSV_FIELDS.join(',')}\n${sample.join('\n')}\n`

  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = '矿区批量建档模板.csv'
  link.click()
  URL.revokeObjectURL(url)
}

function splitCsvLine(line: string): string[] {
  const cells: string[] = []
  let current = ''
  let inQuotes = false
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index]
    if (inQuotes) {
      if (char === '"') {
        if (line[index + 1] === '"') {
          current += '"'
          index += 1
        } else {
          inQuotes = false
        }
      } else {
        current += char
      }
    } else if (char === '"') {
      inQuotes = true
    } else if (char === ',') {
      cells.push(current)
      current = ''
    } else {
      current += char
    }
  }
  cells.push(current)
  return cells.map((cell) => cell.trim())
}

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/).filter((line) => line.trim())
  if (!lines.length) return []
  const first = splitCsvLine(lines[0])
  const hasHeader = first[0] === '矿区编号'
  const keys = hasHeader ? first : CSV_FIELDS
  return lines.slice(hasHeader ? 1 : 0).map((line) => {
    const cells = splitCsvLine(line)
    const row: Record<string, string> = {}
    keys.forEach((key, index) => {
      row[key] = cells[index] ?? ''
    })
    return row
  })
}

async function onBatchFile(event: Event) {
  errorMessage.value = ''
  receipt.value = null
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  try {
    const batchRows = parseCsv(await file.text())
    if (!batchRows.length) {
      throw new Error('文件里没有可建档的行')
    }
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({ rows: batchRows }),
    })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '批量建档请求未生效，请稍后重试')
    }
    receipt.value = { message: payload.message, results: payload.results ?? [] }
    if (!payload.ok) {
      errorMessage.value = payload.message
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量建档失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('矿区台账动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '矿区台账操作失败'
  }
}

async function loadSummary() {
  try {
    const payload = await fetchJson<Summary>(`${ENDPOINT}/summary`)
    stats.value = [
      { label: '在册矿区数', value: payload.在册矿区数 ?? 0 },
      { label: '正常矿区', value: payload.状态分布?.['正常生产'] ?? 0 },
      { label: '整顿矿区', value: payload.状态分布?.['停产整顿'] ?? 0 },
      { label: '闭坑矿区', value: payload.状态分布?.['已闭坑'] ?? 0 },
    ]
  } catch {
    // 概览读取失败时保留旧值，列表页照常可用
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('矿区列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '矿区台账列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
