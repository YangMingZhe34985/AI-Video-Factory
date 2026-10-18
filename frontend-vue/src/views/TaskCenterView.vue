<template>
  <DefaultLayout :title="t('title')" :subtitle="t('subtitle')">
    <div class="task-center max-w-[1600px] mx-auto space-y-5" data-testid="task-center">
      <section class="surface space-y-2 text-sm">
        <p class="font-medium">{{ t('scope') }}</p>
        <div class="flex flex-wrap gap-x-5 gap-y-1 text-slate-600 dark:text-slate-300">
          <span v-if="result">{{ result.mq_admission_enabled ? t('mqOn') : t('mqOff') }}</span>
          <span>{{ t('health') }}</span>
        </div>
        <p class="text-xs text-slate-500">{{ t('note') }}</p>
        <p v-if="result?.observed_at" class="text-xs text-slate-500">{{ t('observed', { time: time(result.observed_at) }) }}</p>
      </section>
      <form class="surface flex flex-wrap items-end gap-3" @submit.prevent="applySearch">
        <label class="filter-label">{{ t('source') }}
          <select v-model="filters.source" @change="resetPage"><option value="all">{{ t('all') }}</option><option value="agent">{{ t('agent') }}</option><option value="workflow">{{ t('workflow') }}</option></select>
        </label>
        <label class="filter-label">{{ t('stateLabel') }}
          <select v-model="filters.state" @change="resetPage"><option value="all">{{ t('all') }}</option><option v-for="state in states" :key="state" :value="state">{{ t('state.' + state) }}</option></select>
        </label>
        <label class="filter-label grow">{{ t('search') }}
          <input v-model="searchDraft" type="search" maxlength="200" :placeholder="t('search')" />
        </label>
        <button class="primary-btn" type="submit">{{ t('searchButton') }}</button>
        <button class="secondary-btn" type="button" :disabled="loading" @click="poller.refresh()">{{ loading ? t('loading') : t('refresh') }}</button>
      </form>
      <div v-if="result" class="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <button v-for="state in states" :key="state" class="surface text-left" type="button" @click="chooseState(state)">
          <span class="block text-sm text-slate-500">{{ t('state.' + state) }}</span>
          <strong class="text-xl">{{ result.summary[state] || 0 }}</strong>
        </button>
      </div>
      <p v-if="listError" class="surface text-amber-700 dark:text-amber-300" role="status">{{ result ? t('stale') : t('unavailable') }}</p>
      <TaskDetails v-if="selection" :selection="selection" :detail="detail" :error="detailError" :page="childPage" @close="closeDetail" @page="setChildPage" />
      <p v-if="result" class="text-sm text-slate-500">{{ t('total', { count: result.total }) }}</p>
      <p v-if="result && !result.items.length" class="surface">{{ t('empty') }}</p>
      <article v-for="item in result?.items || []" :key="item.source + ':' + item.id" class="surface space-y-3">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0 flex-1">
            <p class="text-xs text-slate-500 mb-1">{{ t(item.source) }} · {{ item.id }}</p>
            <h2 class="font-semibold">{{ item.title }}</h2>
          </div>
          <span class="rounded-full px-3 py-1 bg-slate-100 text-sm dark:bg-slate-800">{{ t('state.' + item.state) }}</span>
        </div>
        <div class="text-sm space-y-1">
          <p class="font-medium">{{ stageLabel(item.stage) }}</p>
          <p v-if="item.wait_reason" class="text-slate-600 dark:text-slate-300">{{ t('wait.' + item.wait_reason) }}</p>
          <p class="text-slate-500">{{ t('progress', { done: item.progress.completed, total: item.progress.total, failed: item.progress.failed, unit: t(item.progress.unit) }) }}</p>
        </div>
        <div v-if="activeQueues(item.queue_counts).length" class="flex flex-wrap gap-2 text-xs">
          <span v-for="queue in activeQueues(item.queue_counts)" :key="queue.key" class="rounded bg-blue-50 px-2 py-1 text-blue-700 dark:bg-blue-950 dark:text-blue-200">{{ stageLabel(queue.key) }} {{ queue.count }}</span>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <button type="button" class="secondary-btn" @click="openDetail(item)">{{ t('details') }}</button>
          <RouterLink v-if="taskRoute(item)" class="text-sm text-blue-600 dark:text-blue-300 underline" :to="taskRoute(item)">{{ t('open') }}</RouterLink>
        </div>
      </article>
      <div v-if="result" class="flex flex-wrap items-center gap-3 text-sm">
        <button class="secondary-btn" type="button" :disabled="filters.page <= 1" @click="filters.page--">{{ t('before') }}</button>
        <span>{{ t('page', { page: filters.page, total: pages }) }}</span>
        <button class="secondary-btn" type="button" :disabled="filters.page >= pages" @click="filters.page++">{{ t('after') }}</button>
      </div>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { getTask, listTasks } from '@/api/task-center'
import TaskDetails from '@/components/task-center/TaskDetails.vue'
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
function applySearch() { filters.search = searchDraft.value.trim(); filters.page = 1; poller.refresh() }
function chooseState(state) { filters.state = state; filters.page = 1 }
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
.surface { @apply rounded-xl border border-slate-200 bg-white p-4 text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200; min-width: 0; }
.filter-label { @apply flex flex-col gap-1 text-xs text-slate-500; flex-basis: 160px; min-width: 0; }
input, select { @apply rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200; width: 100%; min-width: 0; }
.secondary-btn { @apply rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-40 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
.primary-btn { @apply rounded-lg bg-blue-600 px-3 py-2 text-sm text-white hover:bg-blue-700; }
</style>
