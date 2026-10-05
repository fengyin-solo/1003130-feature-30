<template>
  <section class="page" data-module="minearea">
    <header class="page-head">
      <div>
        <h2>矿区台账管理</h2>
        <p class="page-desc">维护矿区，围绕矿区编号、矿区名称、开采矿种、核定产能做登记、筛选与状态流转；支持从表格批量建档。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openBatch">批量建档</button>
        <button class="btn" type="button" @click="backfillSafety">存量安全等级回填</button>
        <button class="btn" type="button" @click="exportRows">导出矿区台账清单</button>
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
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
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
          <td :colspan="columns.length + 1" class="empty-state">暂无矿区台账数据，可先批量建档</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条矿区台账记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="batchOpen" class="batch-panel" @click.self="batchOpen = false">
      <div class="batch-dialog">
        <div class="batch-head">
          <h3>批量建档</h3>
          <button class="link" type="button" @click="batchOpen = false">关闭</button>
        </div>
        <p class="batch-tip">
          选择 CSV/TSV 文件，或直接粘贴表格文本。首行是表头时按列名对齐，没有表头时按
          矿区编号、矿区名称、开采矿种、核定产能、开采方式、服务年限、安全等级、矿区状态 的列序对齐。
          编号需为 MINE-0004 式格式；重复编号只留最早一条，缺矿种或编号格式不对的行整行退回。
        </p>
        <div class="batch-inputs">
          <input ref="fileInput" type="file" accept=".csv,.tsv,.txt" @change="onFileChange" />
          <textarea
            v-model="batchContent"
            rows="8"
            placeholder="也可以直接粘贴表格内容，例如：&#10;MINE-0101,南岭煤矿,煤矿,90万吨/年,地下开采,20年,,&#10;MINE-0102,东川铁矿,铁矿,30万吨/年,露天开采,15年,,"
          ></textarea>
        </div>
        <div class="batch-actions">
          <button class="btn primary" type="button" :disabled="submitting" @click="submitBatch">
            {{ submitting ? '提交中…' : '提交批量建档' }}
          </button>
          <button class="btn ghost" type="button" @click="batchContent = ''; batchResult = null">清空</button>
          <span v-if="batchError" class="error-text">{{ batchError }}</span>
        </div>

        <div v-if="batchResult" class="batch-result">
          <div class="stat-row">
            <article class="stat-card"><span class="stat-label">受理行数</span><strong class="stat-value">{{ batchResult.total }}</strong></article>
            <article class="stat-card"><span class="stat-label">建档成功</span><strong class="stat-value ok-text">{{ batchResult.created }}</strong></article>
            <article class="stat-card"><span class="stat-label">重复退回</span><strong class="stat-value dup-text">{{ batchResult.duplicated }}</strong></article>
            <article class="stat-card"><span class="stat-label">校验退回</span><strong class="stat-value err-text">{{ batchResult.rejected }}</strong></article>
            <article class="stat-card"><span class="stat-label">存量回填</span><strong class="stat-value">{{ batchResult.stock_backfilled }}</strong></article>
            <article class="stat-card"><span class="stat-label">同步入井待办</span><strong class="stat-value">{{ batchResult.shift_synced }}</strong></article>
          </div>
          <table class="data-table">
            <thead>
              <tr><th>行号</th><th>矿区编号</th><th>矿区名称</th><th>结果</th><th>说明</th></tr>
            </thead>
            <tbody>
              <tr v-for="receipt in batchResult.receipts" :key="receipt.line" :class="receiptClass(receipt.result)">
                <td>{{ receipt.line }}</td>
                <td>{{ receipt.code || '—' }}</td>
                <td>{{ receipt.name || '—' }}</td>
                <td>{{ resultLabel[receipt.result] ?? receipt.result }}</td>
                <td>
                  {{ receipt.message }}
                  <ul v-if="receipt.warnings?.length" class="warn-list">
                    <li v-for="warning in receipt.warnings" :key="warning">提示：{{ warning }}</li>
                  </ul>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

type Receipt = {
  line: number
  code: string | null
  name: string | null
  ok: boolean
  result: 'created' | 'duplicated' | 'rejected'
  message: string
  warnings: string[]
}

type BatchResult = {
  ok: boolean
  message: string
  total: number
  created: number
  duplicated: number
  rejected: number
  stock_backfilled: number
  existing_completed: number
  shift_synced: number
  roster_pending: number
  roster_headcount: number
  receipts: Receipt[]
}

const ENDPOINT = '/api/minearea'
const columns = ["矿区编号", "矿区名称", "开采矿种", "核定产能", "开采方式", "服务年限", "安全等级", "矿区状态"]
const actions = ["停产整顿", "恢复生产", "闭坑登记"]
const resultLabel: Record<string, string> = { created: '建档成功', duplicated: '重复退回', rejected: '整行退回' }

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

const stats = ref([
  { label: '矿区总数', value: 0 },
  { label: '正常生产', value: 0 },
  { label: '停产/检修', value: 0 },
  { label: '已闭坑', value: 0 },
])

const batchOpen = ref(false)
const batchContent = ref('')
const submitting = ref(false)
const batchError = ref('')
const batchResult = ref<BatchResult | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
let pendingFilename = ''

function receiptClass(result: string) {
  return {
    'row-created': result === 'created',
    'row-duplicated': result === 'duplicated',
    'row-rejected': result === 'rejected',
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openBatch() {
  batchOpen.value = true
  batchError.value = ''
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) {
    return
  }
  pendingFilename = file.name
  const reader = new FileReader()
  reader.onload = () => {
    batchContent.value = String(reader.result ?? '')
  }
  reader.onerror = () => {
    batchError.value = '文件读取失败，请换一个文件再试'
  }
  reader.readAsText(file, 'utf-8')
}

async function submitBatch() {
  batchError.value = ''
  if (!batchContent.value.trim()) {
    batchError.value = '请先选择文件或粘贴表格内容'
    return
  }
  submitting.value = true
  try {
    const response = await request(`${ENDPOINT}/batch`, {
      method: 'POST',
      body: JSON.stringify({ content: batchContent.value, filename: pendingFilename }),
    })
    if (!response.ok) {
      throw new Error(`批量建档未被受理（${response.status}）`)
    }
    const result: BatchResult = await response.json()
    batchResult.value = result
    if (!result.ok) {
      batchError.value = result.message
    }
    await reload()
  } catch (error) {
    batchError.value = error instanceof Error ? error.message : '批量建档提交失败'
  } finally {
    submitting.value = false
  }
}

async function backfillSafety() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/backfill-safety`, { method: 'POST' })
    if (!response.ok) {
      throw new Error('存量回填未生效，请稍后重试')
    }
    const payload = await response.json()
    errorMessage.value = ''
    window.alert(payload.message ?? '存量安全等级回填完成')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '存量回填失败'
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
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '矿区台账操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?size=200${query ? `&${query}` : ''}`)
    if (!response.ok) {
      throw new Error('矿区列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    stats.value = [
      { label: '矿区总数', value: total.value },
      { label: '正常生产', value: rows.value.filter((r) => r.status === '正常生产').length },
      { label: '停产/检修', value: rows.value.filter((r) => r.status === '停产整顿' || r.status === '检修中').length },
      { label: '已闭坑', value: rows.value.filter((r) => r.status === '已闭坑').length },
    ]
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '矿区台账列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.batch-panel {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 32px 16px;
  overflow-y: auto;
  z-index: 20;
}
.batch-dialog {
  background: #fff;
  border-radius: 10px;
  width: min(960px, 100%);
  padding: 18px 20px;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.2);
}
.batch-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.batch-head h3 {
  margin: 0;
  font-size: 16px;
}
.batch-tip {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.7;
  margin: 8px 0 12px;
}
.batch-inputs {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.batch-inputs textarea {
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 10px;
  font: inherit;
  font-size: 13px;
  resize: vertical;
}
.batch-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  margin: 12px 0;
}
.batch-result {
  margin-top: 8px;
}
.batch-result .stat-card {
  padding: 8px 10px;
}
.batch-result .stat-value {
  font-size: 18px;
}
.ok-text { color: #067647; }
.dup-text { color: #b54708; }
.err-text { color: #b42318; }
.row-created td { background: #f0fdf4; }
.row-duplicated td { background: #fffaeb; }
.row-rejected td { background: #fef3f2; }
.warn-list {
  margin: 4px 0 0;
  padding-left: 16px;
  color: #b54708;
}
</style>
