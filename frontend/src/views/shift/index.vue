<template>
  <section class="page" data-module="shift">
    <header class="page-head">
      <div>
        <h2>入井管理管理</h2>
        <p class="page-desc">维护入井记录，围绕记录编号、入井人员、所属班组、入井时间做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记入井记录</button>
        <button class="btn" type="button" @click="exportRows">导出入井管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <section class="receipt-panel">
      <header class="receipt-head">
        <strong>待办清单</strong>
        <span>矿区批量建档结果会同步到这里，共 {{ todos.length }} 条待办</span>
      </header>
      <table class="data-table">
        <thead>
          <tr><th>记录编号</th><th>出勤区域</th><th>来源矿区</th><th>入井状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="todo in todos" :key="String(todo.id)">
            <td>{{ todo.记录编号 ?? '—' }}</td>
            <td>{{ todo.出勤区域 ?? '—' }}</td>
            <td>{{ todo.来源矿区 || '—' }}</td>
            <td>{{ todo.入井状态 ?? '—' }}</td>
          </tr>
          <tr v-if="!todos.length">
            <td colspan="4" class="empty-state">暂无待办，矿区批量建档后会自动出现在这里</td>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无入井管理数据，可先登记入井记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条入井管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type Stat = { label: string; value: number }
type Todo = { id: number; 记录编号: string; 出勤区域: string; 来源矿区: string; 入井状态: string }
type Summary = { 在册人数: number; 待办数: number; 状态分布: Record<string, number>; 待办清单: Todo[] }

const ENDPOINT = '/api/shift'
const columns = ["记录编号", "入井人员", "所属班组", "入井时间", "升井时间", "携带设备", "出勤区域", "入井状态"]
const actions = ["登记入井", "登记升井", "超时联系"]
const statuses = ["入井中", "已升井", "超时未升", "已联系"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const stats = ref<Stat[]>([
  { label: '在册人数', value: 0 },
  { label: '待办数', value: 0 },
  { label: '入井中人数', value: 0 },
  { label: '超时人数', value: 0 },
])
const todos = ref<Todo[]>([])

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '入井记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    if (!response.ok) {
      throw new Error('入井管理动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadSummary()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井管理操作失败'
  }
}

async function loadSummary() {
  try {
    const payload = await fetchJson<Summary>(`${ENDPOINT}/summary`)
    stats.value = [
      { label: '在册人数', value: payload.在册人数 ?? 0 },
      { label: '待办数', value: payload.待办数 ?? 0 },
      { label: '入井中人数', value: payload.状态分布?.['入井中'] ?? 0 },
      { label: '超时人数', value: payload.状态分布?.['超时未升'] ?? 0 },
    ]
    todos.value = payload.待办清单 ?? []
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
      throw new Error('入井记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井管理列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadSummary()
})
</script>
