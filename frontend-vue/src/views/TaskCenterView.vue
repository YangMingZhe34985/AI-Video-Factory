<template>
  <DefaultLayout :title="t('title')" :subtitle="t('subtitle')">
    <div class="task-center mx-auto max-w-[1600px] space-y-4" data-testid="task-center">
      <!-- scope strip -->
      <section class="strip">
        <span class="strip-item font-medium text-slate-700 dark:text-slate-200"><PhStack :size="15" />{{ t('scope') }}</span>
        <span v-if="result" class="strip-item"><span class="dot" :class="result.mq_admission_enabled ? 'bg-emerald-500' : 'bg-slate-400'" />{{ result.mq_admission_enabled ? t('mqOn') : t('mqOff') }}</span>
        <span class="strip-item"><span class="dot bg-slate-300 dark:bg-slate-600" />{{ t('health') }}</span>
        <span class="ml-auto flex items-center gap-3">
          <span v-if="result?.observed_at" class="text-xs tabular-nums text-slate-400" :title="t('note')">{{ t('observed', { time: time(result.observed_at) }) }}</span>
          <button class="icon-btn" type="button" :disabled="loading" :aria-label="t('refresh')" :title="t('refresh')" @click="poller.refresh()"><PhArrowClockwise :size="16" :class="loading ? 'animate-spin' : ''" /></button>
        </span>
      </section>

      <!-- state summary doubles as the state filter -->
      <div v-if="result" class="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7" role="group" :aria-label="t('stateLabel')">
        <button type="button" class="tile" :class="filters.state === 'all' ? 'tile-active' : ''" :aria-pressed="filters.state === 'all'" @click="chooseState('all')">
          <span class="tile-label"><span class="dot bg-slate-400" />{{ t('all') }}</span>
          <strong class="tile-count">{{ summaryTotal }}</strong>
        </button>
        <button v-for="state in states" :key="state" type="button" class="tile" :class="filters.state === state ? 'tile-active' : ''" :aria-pressed="filters.state === state" @click="chooseState(state)">
          <span class="tile-label"><span class="dot" :class="stateDot[state]" />{{ t('state.' + state) }}</span>
          <strong class="tile-count" :class="state === 'attention' && result.summary[state] ? 'text-red-600 dark:text-red-400' : ''">{{ result.summary[state] || 0 }}</strong>
        </button>
      </div>

      <!-- filters -->
      <form class="flex flex-wrap items-center gap-2.5" @submit.prevent="applySearch">
        <div class="segmented" role="radiogroup" :aria-label="t('source')">
          <button v-for="option in sourceOptions" :key="option.value" type="button" role="radio" :aria-checked="filters.source === option.value"
            :class="filters.source === option.value ? 'segment-active' : ''" @click="chooseSource(option.value)">
            <component :is="option.icon" v-if="option.icon" :size="14" />{{ t(option.label) }}
          </button>
        </div>
        <label class="search">
          <PhMagnifyingGlass :size="15" class="flex-none text-slate-400" />
          <input v-model="searchDraft" type="search" maxlength="200" :placeholder="t('search')" :aria-label="t('search')">
        </label>
        <button class="primary-btn" type="submit">{{ t('searchButton') }}</button>
        <span v-if="result" class="ml-auto text-xs text-slate-500">{{ t('total', { count: result.total }) }}</span>
      </form>

      <p v-if="listError" class="notice" role="status"><PhWarning :size="16" class="flex-none" />{{ result ? t('stale') : t('unavailable') }}</p>

      <div class="grid items-start gap-4" :class="selection ? 'xl:grid-cols-[minmax(0,1fr)_minmax(24rem,32rem)]' : ''">
        <!-- task list -->
        <section class="list" :aria-label="t('title')">
          <p v-if="result && !result.items.length" class="empty"><PhTray :size="28" class="text-slate-300 dark:text-slate-600" />{{ t('empty') }}</p>
          <p v-else-if="!result" class="empty">{{ listError ? t('unavailable') : t('loading') }}</p>
          <article v-for="item in result?.items || []" :key="item.source + ':' + item.id" class="row" :class="isSelected(item) ? 'row-selected' : ''">
            <span class="source-icon" :class="item.source === 'agent' ? 'bg-violet-50 text-violet-600 dark:bg-violet-950/50 dark:text-violet-300' : 'bg-sky-50 text-sky-600 dark:bg-sky-950/50 dark:text-sky-300'" :title="t(item.source)">
              <PhSparkle v-if="item.source === 'agent'" :size="16" /><PhFlowArrow v-else :size="16" />
            </span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2">
                <button type="button" class="min-w-0 truncate text-left text-sm font-semibold text-slate-900 hover:text-blue-700 dark:text-slate-100 dark:hover:text-blue-300" :title="item.title" @click="openDetail(item)">{{ displayTitle(item) }}</button>
                <span class="state-pill" :class="statePill[item.state]">{{ t('state.' + item.state) }}</span>
              </div>
              <p class="mt-0.5 truncate font-mono text-[11px] text-slate-400">{{ t(item.source) }} · {{ item.id }}</p>
              <p class="mt-1.5 text-xs text-slate-600 dark:text-slate-300">
                <span class="font-medium">{{ stageLabel(item.stage) }}</span>
                <span v-if="item.wait_reason" class="text-slate-500 dark:text-slate-400"> · {{ t('wait.' + item.wait_reason) }}</span>
              </p>
              <div v-if="activeQueues(item.queue_counts).length" class="mt-2 flex flex-wrap gap-1.5">
                <span v-for="queue in activeQueues(item.queue_counts)" :key="queue.key" class="queue-chip" :class="queue.key === 'unknown' ? 'queue-unknown' : ''">{{ stageLabel(queue.key) }} · {{ queue.count }}</span>
              </div>
            </div>
            <div class="hidden w-40 flex-none" :class="selection ? '2xl:block' : 'md:block'">
              <div class="flex items-baseline justify-between text-[11px] text-slate-500">
                <span class="tabular-nums">{{ item.progress.completed }} / {{ item.progress.total }} {{ t(item.progress.unit) }}</span>
                <span v-if="item.progress.failed" class="tabular-nums text-red-600 dark:text-red-400">{{ t('failedCount', { count: item.progress.failed }) }}</span>
              </div>
              <div class="progress" role="img" :aria-label="t('progress', { done: item.progress.completed, total: item.progress.total, failed: item.progress.failed, unit: t(item.progress.unit) })">
                <span class="bg-emerald-500" :style="{ width: percent(item.progress.completed, item.progress.total) }" />
                <span class="bg-red-500" :style="{ width: percent(item.progress.failed, item.progress.total) }" />
              </div>
              <p class="mt-1.5 text-[11px] tabular-nums text-slate-400">{{ t('updated', { time: time(item.updated_at) }) }}</p>
            </div>
            <div class="flex flex-none items-center gap-1">
              <button type="button" class="ghost-btn" :aria-pressed="isSelected(item)" @click="isSelected(item) ? closeDetail() : openDetail(item)"><PhListBullets :size="15" />{{ t('details') }}</button>
              <RouterLink v-if="taskRoute(item)" class="icon-btn" :to="taskRoute(item)" :aria-label="t('open')" :title="t('open')"><PhArrowSquareOut :size="16" /></RouterLink>
            </div>
          </article>
          <div v-if="result && pages > 1" class="pager">
            <button class="icon-btn" type="button" :disabled="filters.page <= 1" :aria-label="t('before')" @click="filters.page--"><PhCaretLeft :size="16" /></button>
            <span class="tabular-nums">{{ t('page', { page: filters.page, total: pages }) }}</span>
            <button class="icon-btn" type="button" :disabled="filters.page >= pages" :aria-label="t('after')" @click="filters.page++"><PhCaretRight :size="16" /></button>
          </div>
        </section>

        <TaskDetails v-if="selection" class="xl:sticky xl:top-4" :selection="selection" :detail="detail" :error="detailError" :page="childPage" @close="closeDetail" @page="setChildPage" />
      </div>
      <p class="text-[11px] text-slate-400">{{ t('note') }}</p>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { getTask, listTasks } from '@/api/task-center'
import TaskDetails from '@/components/task-center/TaskDetails.vue'
import { PhArrowClockwise, PhArrowSquareOut, PhCaretLeft, PhCaretRight, PhFlowArrow, PhListBullets, PhMagnifyingGlass, PhSparkle, PhStack, PhTray, PhWarning } from '@phosphor-icons/vue'
import messages from '@/components/task-center/messages'
import { activeQueues, createTaskPoller, pageCount, states, taskRoute } from '@/components/task-center/task-center'

const { t, te } = useI18n({ useScope: 'local', messages })
const filters = reactive({ source: 'all', state: 'all', search: '', page: 1, per_page: 20 })
const searchDraft = ref(''), result = ref(null), detail = ref(null), selection = ref(null), childPage = ref(1)
const listError = ref(false), detailError = ref(false), loading = ref(false)
const pages = computed(() => pageCount(result.value?.total, filters.per_page))
const stageLabel = (key) => te('stage.' + key) ? t('stage.' + key) : key || '—'
const time = (value) => new Date(value).toLocaleString()
const poller = createTaskPoller({
  visible: () => !document.hidden,
  busy: (value) => { loading.value = value },
  read: async (signal) => {
    const selected = selection.value
    const reads = await Promise.allSettled([
      listTasks({ ...filters }, signal),
      selected ? getTask(selected.source, selected.id, { page: childPage.value, per_page: 20 }, signal) : Promise.resolve(null),
    ])
    return reads
  },
  accept: ([list, child]) => {
    listError.value = list.status !== 'fulfilled'
    if (!listError.value) result.value = list.value
    detailError.value = child.status !== 'fulfilled'
    if (!detailError.value) detail.value = child.value
    else if ([403, 404].includes(child.reason?.response?.status)) detail.value = null
  },
  fail: () => { listError.value = true; detailError.value = Boolean(selection.value) },
})
function resetPage() { filters.page = 1 }
function chooseSource(value) { filters.source = value; filters.page = 1 }
const sourceOptions = [{ value: 'all', label: 'all' }, { value: 'agent', label: 'agent', icon: PhSparkle }, { value: 'workflow', label: 'workflow', icon: PhFlowArrow }]
const stateDot = { queued: 'bg-sky-500', running: 'bg-blue-600', waiting: 'bg-amber-500', attention: 'bg-red-500', completed: 'bg-emerald-500', cancelled: 'bg-slate-400' }
const statePill = { queued: 'pill-sky', running: 'pill-blue', waiting: 'pill-amber', attention: 'pill-red', completed: 'pill-emerald', cancelled: 'pill-slate' }
const summaryTotal = computed(() => states.reduce((sum, state) => sum + (result.value?.summary?.[state] || 0), 0))
const percent = (value, total) => `${total > 0 ? Math.min(100, Math.max(0, (value / total) * 100)) : 0}%`
// The server never returns request text (private prompt); untitled runs show their ID.
const displayTitle = (item) => item.source === 'agent' && item.title === item.id ? t('untitled') : item.title
const isSelected = (item) => selection.value?.source === item.source && selection.value?.id === item.id
function applySearch() { filters.search = searchDraft.value.trim(); filters.page = 1; poller.refresh() }
function chooseState(state) { filters.state = filters.state === state && state !== 'all' ? 'all' : state; filters.page = 1 }
function openDetail(item) { selection.value = { source: item.source, id: item.id }; detail.value = null; detailError.value = false; childPage.value = 1; poller.refresh() }
function closeDetail() { selection.value = null; detail.value = null; poller.refresh() }
function setChildPage(page) { childPage.value = page; poller.refresh() }
watch(filters, () => poller.refresh())
const visibility = () => poller.visibilityChanged()
onMounted(() => { document.addEventListener('visibilitychange', visibility); poller.refresh() })
onUnmounted(() => { poller.stop(); document.removeEventListener('visibilitychange', visibility) })
</script>

<style scoped>
.task-center { min-width: 0; overflow-wrap: anywhere; }
.strip { @apply flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-xs text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-400; }
.strip-item { @apply inline-flex items-center gap-1.5; }
.dot { @apply inline-block h-2 w-2 flex-none rounded-full; }
.tile { @apply flex flex-col gap-1.5 rounded-xl border border-slate-200 bg-white px-3.5 py-3 text-left transition hover:border-slate-300 hover:shadow-sm dark:border-slate-700 dark:bg-slate-900 dark:hover:border-slate-600; }
.tile-active { @apply border-blue-500 ring-2 ring-blue-500/15 dark:border-blue-400; }
.tile-label { @apply flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400; }
.tile-count { @apply text-2xl font-semibold leading-none tabular-nums text-slate-900 dark:text-white; }
.segmented { @apply inline-flex rounded-xl border border-slate-200 bg-slate-100 p-0.5 dark:border-slate-700 dark:bg-slate-800; }
.segmented button { @apply inline-flex items-center gap-1.5 rounded-[10px] px-3 py-1.5 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white; }
.segmented .segment-active { @apply bg-white font-medium text-slate-900 shadow-sm dark:bg-slate-950 dark:text-white; }
.search { @apply flex min-w-[14rem] flex-1 items-center gap-2 rounded-xl border border-slate-300 bg-white px-3 focus-within:ring-2 focus-within:ring-blue-500 dark:border-slate-600 dark:bg-slate-900; }
.search input { @apply w-full min-w-0 border-0 bg-transparent py-2 text-sm text-slate-800 outline-none placeholder:text-slate-400 dark:text-slate-100; }
.notice { @apply flex items-center gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200; }
.list { @apply min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900; }
.row { @apply flex items-start gap-3 border-b border-slate-100 px-4 py-3.5 transition last:border-b-0 hover:bg-slate-50/70 dark:border-slate-800 dark:hover:bg-slate-800/40; }
.row-selected { @apply bg-blue-50/60 dark:bg-blue-950/30; box-shadow: inset 3px 0 0 #2563eb; }
.source-icon { @apply mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-lg; }
.state-pill { @apply inline-flex flex-none items-center rounded-full px-2 py-0.5 text-[11px] font-medium; }
.pill-sky { @apply bg-sky-50 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300; }
.pill-blue { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.pill-amber { @apply bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300; }
.pill-red { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.pill-emerald { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.pill-slate { @apply bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.queue-chip { @apply rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.queue-unknown { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.progress { @apply mt-1 flex h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800; }
.empty { @apply flex flex-col items-center gap-2 px-4 py-12 text-sm text-slate-500; }
.pager { @apply flex items-center justify-center gap-3 border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500 dark:border-slate-800; }
.primary-btn { @apply rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700; }
.ghost-btn { @apply inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white; }
.ghost-btn[aria-pressed='true'] { @apply bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300; }
.icon-btn { @apply inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900 disabled:opacity-40 dark:hover:bg-slate-800 dark:hover:text-white; }
</style>
