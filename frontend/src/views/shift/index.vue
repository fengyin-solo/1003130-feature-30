<template>
  <section class="page" data-module="shift">
    <header class="page-head">
      <div>
        <h2>入井管理</h2>
        <p class="page-desc">维护入井记录与入井名单待办：矿区台账批量建档成功的新矿区会自动进入待编排清单，在册人数与台账建档回执同源。</p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" :class="{ ghost: rosterFilter !== '待编排' }" @click="toggleRosterFilter">
          {{ rosterFilter === '待编排' ? '查看全部记录' : '只看入井待办' }}
        </button>
        <button class="btn" type="button" @click="exportRows">导出入井管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

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
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-todo': row.status === '待编排' }">
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
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
          <td :colspan="columns.length + 1" class="empty-state">暂无入井管理数据，矿区批量建档后会自动生成待办</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条入井管理记录 · 待办 {{ roster?.roster_pending ?? 0 }} 条 · 在册人数 {{ roster?.roster_headcount ?? 0 }} 人（与矿区台账一致）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type RosterSummary = {
  roster_total: number
  roster_pending: number
  roster_headcount: number
  pending_total: number
  pending_items: Row[]
  status_counts: Record<string, number>
}

const ENDPOINT = '/api/shift'
const columns = ["记录编号", "入井人员", "所属班组", "入井时间", "升井时间", "携带设备", "出勤区域", "入井状态"]
const actions = ["登记入井", "登记升井", "超时联系"]
const statuses = ["待编排", "入井中", "已升井", "超时未升", "已联系"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const rosterFilter = ref('')
const roster = ref<RosterSummary | null>(null)

const stats = ref([
  { label: '在册人数（台账同步）', value: 0 },
  { label: '入井待办', value: 0 },
  { label: '入井中人数', value: 0 },
  { label: '已升井人数', value: 0 },
  { label: '超时人数', value: 0 },
])

function availableActions(row: Row) {
  // 台账同步过来的待办第一步是排班登记入井；其他记录沿用原动作
  return row.status === '待编排' ? ["登记入井"] : actions
}

function toggleRosterFilter() {
  rosterFilter.value = rosterFilter.value === '待编排' ? '' : '待编排'
  filters.value = {}
  void reload()
}

function resetFilters() {
  filters.value = {}
  rosterFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
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
    await Promise.all([reload(), loadRoster()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井管理操作失败'
  }
}

async function loadRoster() {
  try {
    const response = await request(`${ENDPOINT}/roster`)
    if (!response.ok) {
      throw new Error('入井名单读取失败')
    }
    roster.value = await response.json()
  } catch {
    // 名单汇总读不出来时保留上一次的值，不打断列表浏览
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams(filters.value as Record<string, string>)
  params.set('size', '200')
  if (rosterFilter.value) {
    params.set('status', rosterFilter.value)
  }
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) {
      throw new Error('入井记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (roster.value) {
      const counts = roster.value.status_counts ?? {}
      stats.value = [
        { label: '在册人数（台账同步）', value: roster.value.roster_headcount },
        { label: '入井待办', value: roster.value.roster_pending },
        { label: '入井中人数', value: counts['入井中'] ?? 0 },
        { label: '已升井人数', value: counts['已升井'] ?? 0 },
        { label: '超时人数', value: counts['超时未升'] ?? 0 },
      ]
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '入井管理列表读取失败'
  }
}

onMounted(async () => {
  await loadRoster()
  await reload()
})
</script>

<style scoped>
.row-todo td {
  background: #fffaeb;
}
</style>
