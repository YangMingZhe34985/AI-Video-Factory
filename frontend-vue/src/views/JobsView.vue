<template>
  <DefaultLayout :title="t('jobs.title')" :subtitle="t('jobs.subtitle')">
    <div class="max-w-[1600px] mx-auto space-y-6">
      <!-- Filters -->
      <div class="flex flex-wrap gap-4 items-end bg-white p-5 rounded-xl border border-gray-100 shadow-sm">
        <div class="flex flex-col flex-1 min-w-[150px]">
          <label class="text-xs text-gray-500 mb-1.5">{{ t('series.title') }}</label>
          <AppSelect
            v-model="filters.series_id"
            :options="seriesOptions"
            :placeholder="t('series.all')"
            @change="onSeriesChange"
          />
        </div>
        <div class="flex flex-col flex-1 min-w-[150px]">
          <label class="text-xs text-gray-500 mb-1.5">{{ t('jobs.templateId') }}</label>
          <AppSelect
            v-model="filters.template"
            :options="templateOptions"
            :placeholder="t('jobs.allTemplates')"
            @change="loadJobs"
          />
        </div>
        <div class="flex flex-col flex-1 min-w-[150px]">
          <label class="text-xs text-gray-500 mb-1.5">{{ t('jobs.status') }}</label>
          <AppSelect
            v-model="filters.status"
            :options="statusOptions"
            :placeholder="t('jobs.allStatus')"
            @change="loadJobs"
          />
        </div>
        <div class="flex flex-col flex-1 min-w-[150px]">
          <label class="text-xs text-gray-500 mb-1.5">{{ t('jobs.currentNode') }}</label>
          <AppSelect
            v-model="filters.node"
            :options="nodeOptions"
            :placeholder="t('jobs.allNodes')"
            @change="loadJobs"
          />
        </div>
        <div class="flex flex-col flex-2 min-w-[200px]">
          <label class="text-xs text-gray-500 mb-1.5">{{ t('jobs.search') }}</label>
          <SearchInput v-model="filters.search" :placeholder="t('jobs.searchPlaceholder')" />
        </div>
        <div class="flex items-center space-x-2">
          <button @click="resetFilters" class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50 bg-white">{{ t('jobs.reset') }}</button>
          <button @click="showWizard = true" class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 flex items-center">
            <PhPlus class="mr-1.5" /> {{ t('jobs.createJob') }}
          </button>
          <button @click="loadJobs" class="px-3 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50 bg-white flex items-center">
            <PhArrowsClockwise class="mr-1.5" /> {{ t('jobs.refresh') }}
          </button>
        </div>
      </div>

      <!-- Stats row -->
      <div class="flex space-x-4 overflow-x-auto pb-2">
        <div v-for="stat in statsRow" :key="stat.label" @click="filterByStatus(stat.statusKey)" class="bg-white rounded-xl border border-gray-100 p-4 min-w-[160px] flex-1 shadow-sm flex items-center cursor-pointer hover:shadow-md hover:border-gray-200 transition-shadow">
          <div :class="stat.iconBg" class="w-12 h-12 rounded-lg flex items-center justify-center mr-4 shrink-0">
            <component :is="stat.icon" class="text-2xl" :class="stat.iconColor" />
          </div>
          <div>
            <div class="text-sm font-medium text-gray-500 mb-0.5">{{ stat.label }}</div>
            <div class="text-xl font-bold text-gray-900">{{ stat.value }}</div>
          </div>
        </div>
      </div>

      <!-- Jobs table -->
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="bg-white text-gray-500 text-xs font-semibold border-b border-gray-100">
                <th class="px-5 py-4 whitespace-nowrap">{{ t('jobs.jobId') }}</th>
                <th class="px-5 py-4 whitespace-nowrap">{{ t('series.title') }}</th>
                <th class="px-5 py-4 whitespace-nowrap">{{ t('jobs.templateId') }}</th>
                <th class="px-5 py-4 whitespace-nowrap">{{ t('jobs.status') }}</th>
                <th class="px-5 py-4 whitespace-nowrap">{{ t('jobs.currentNode') }}</th>
                <th class="px-5 py-4 whitespace-nowrap min-w-[120px]">{{ t('jobs.progress') }}</th>
                <th class="px-5 py-4 whitespace-nowrap">{{ t('jobs.error') }}</th>
                <th class="px-5 py-4 whitespace-nowrap">{{ t('jobs.createdAt') }}</th>
                <th class="px-5 py-4 whitespace-nowrap">{{ t('jobs.updatedAt') }}</th>
                <th class="px-5 py-4 whitespace-nowrap text-center">{{ t('jobs.actions') }}</th>
              </tr>
            </thead>
            <tbody class="text-sm text-gray-700 divide-y divide-gray-50">
              <tr v-if="jobStore.loading">
                <td colspan="10" class="px-5 py-12 text-center"><LoadingSpinner :text="t('jobs.loadingJobs')" /></td>
              </tr>
              <tr v-else-if="jobStore.jobs.length === 0">
                <td colspan="10" class="px-5 py-12 text-center"><EmptyState :text="t('jobs.noJobs')" /></td>
              </tr>
              <tr v-for="job in jobStore.jobs" :key="job.job_id || job.id" class="hover:bg-gray-50/50 transition-colors">
                <td class="px-5 py-4 whitespace-nowrap text-gray-800 font-medium">
                  <router-link :to="`/jobs/${jobKey(job)}`" @click="rememberJob(job)" class="hover:text-primary transition-colors flex items-center gap-2">
                    <span class="min-w-0">
                      <span class="block truncate">{{ displayJobName(job) }}</span>
                      <span v-if="job.job_name" class="block text-[11px] font-mono text-gray-400 truncate">{{ job.job_id }}</span>
                    </span>
                    <PhCopy class="text-gray-400 cursor-pointer hover:text-gray-600 shrink-0" @click.stop.prevent="copyToClipboard(jobKey(job))" />
                  </router-link>
                </td>
                <td class="px-5 py-4 whitespace-nowrap">
                  <span class="px-2 py-0.5 bg-violet-50 text-violet-600 border border-violet-100 rounded text-xs font-medium">{{ job.series_name || job.series_id || '--' }}</span>
                </td>
                <td class="px-5 py-4 whitespace-nowrap text-primary">{{ job.template_name || job.template_id || '--' }}</td>
                <td class="px-5 py-4 whitespace-nowrap"><StatusBadge :status="job.status" /></td>
                <td class="px-5 py-4 whitespace-nowrap text-gray-500">{{ job.current_node || '--' }}</td>
                <td class="px-5 py-4 whitespace-nowrap">
                  <JobProgressBar :job="job" />
                </td>
                <td class="px-5 py-4 text-xs max-w-[200px]">
                  <button
                    v-if="job.error_summary"
                    @click="toggleError(job.job_id || job.id)"
                    class="text-left text-red-500 hover:text-red-600"
                    :class="expandedErrors.has(job.job_id || job.id) ? '' : 'truncate block max-w-[200px]'"
                    :title="t('jobs.clickToExpand')"
                  >{{ job.error_summary }}</button>
                  <span v-else class="text-gray-400">-</span>
                </td>
                <td class="px-5 py-4 whitespace-nowrap text-gray-500">{{ formatDate(job.created_at) }}</td>
                <td class="px-5 py-4 whitespace-nowrap text-gray-500">{{ formatDate(job.updated_at) }}</td>
                <td class="px-5 py-4 whitespace-nowrap">
                  <div class="flex items-center justify-center space-x-1">
                    <router-link :to="`/jobs/${jobKey(job)}`" @click="rememberJob(job)" class="p-1.5 text-gray-400 hover:text-gray-600 border border-gray-200 rounded bg-white"><PhEye /></router-link>
                    <button v-if="!['running', 'queued'].includes(job.status)" @click="runJob(job)" class="p-1.5 text-gray-400 hover:text-gray-600 border border-gray-200 rounded bg-white"><PhPlay /></button>
                    <button v-if="job.status === 'running'" @click="pauseJob(job)" class="p-1.5 text-gray-400 hover:text-gray-600 border border-gray-200 rounded bg-white"><PhPause /></button>
                    <button v-if="['running', 'queued'].includes(job.status)" @click="cancelJob(job)" class="p-1.5 text-red-400 hover:text-red-600 border border-red-200 rounded bg-red-50"><PhStop /></button>
                    <button v-if="!['running', 'queued'].includes(job.status)" @click="openDeleteJob(job)" class="p-1.5 text-red-400 hover:text-red-600 border border-red-200 rounded bg-red-50"><PhTrash /></button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="p-4 border-t border-gray-100 flex justify-between items-center text-sm text-gray-500 bg-white">
          <div>{{ t('jobs.showing', { count: jobStore.jobs.length }) }}</div>
          <Pagination
            :current-page="jobStore.pagination.page"
            :total-pages="Math.ceil(jobStore.pagination.total / jobStore.pagination.perPage) || 1"
            @change="(p) => { jobStore.pagination.page = p; loadJobs() }"
          />
        </div>
      </div>

      <WorkflowJobWizard
        v-if="showWizard"
        @close="showWizard = false"
        @created="loadJobs"
      />

      <div v-if="deleteTarget" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="closeDeleteDialog"></div>
        <div class="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-md mx-4 z-10">
          <h3 class="text-lg font-bold text-gray-900 mb-2">Delete Job</h3>
          <p class="text-sm text-gray-500 mb-4">
            This removes the Job record, node runs, events, artifacts and owned files. Type
            <span class="font-mono text-gray-800">{{ displayJobName(deleteTarget) }}</span>
            or <span class="font-mono text-gray-800">{{ jobKey(deleteTarget) }}</span> to confirm.
          </p>
          <input v-model="deleteConfirm" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-red-400" />
          <div class="flex justify-end gap-3 mt-5">
            <button @click="closeDeleteDialog" class="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            <button @click="confirmDeleteJob" :disabled="deletingJob" class="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50">
              {{ deletingJob ? 'Deleting...' : 'Delete Job' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from 'vue'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import SearchInput from '@/components/common/SearchInput.vue'
import Pagination from '@/components/common/Pagination.vue'
import AppSelect from '@/components/common/AppSelect.vue'
import JobProgressBar from '@/components/jobs/JobProgressBar.vue'
import WorkflowJobWizard from '@/components/workflow/WorkflowJobWizard.vue'
import { useJobStore } from '@/stores/jobs'
import { useSeriesStore } from '@/stores/series'
import { useTemplateStore } from '@/stores/templates'
import { useWorkflowStore } from '@/stores/workflow'
import { useToast } from '@/composables/useToast'
import { formatDate } from '@/utils/format'
import { PhPlay, PhPause, PhStop, PhEye, PhCopy, PhPlus, PhArrowsClockwise, PhPlayCircle, PhCheckCircle, PhXCircle, PhBriefcase, PhStopCircle, PhTrash } from '@phosphor-icons/vue'
import { clearRecentJob, setRecentJob } from '@/composables/useRecentJob'

import { useI18n } from 'vue-i18n'

const jobStore = useJobStore()
const seriesStore = useSeriesStore()
const templateStore = useTemplateStore()
const workflowStore = useWorkflowStore()
const toast = useToast()
const { t } = useI18n()

const filters = reactive({ series_id: '', template: '', status: '', node: '', search: '' })
const expandedErrors = ref(new Set())
const showWizard = ref(false)
const deleteTarget = ref(null)
const deleteConfirm = ref('')
const deletingJob = ref(false)

const seriesOptions = computed(() =>
  seriesStore.seriesList.map((s) => ({ label: s.name, value: s.series_id }))
)

const templateOptions = computed(() => {
  const list = filters.series_id
    ? templateStore.templates.filter((t) => (t.series_id || t.series || 'default') === filters.series_id)
    : templateStore.templates
  return list.map((t) => ({ label: t.name || t.template_id, value: t.template_id }))
})

const statusOptions = computed(() => [
  { label: t('jobs.queued'), value: 'queued' },
  { label: t('jobs.running'), value: 'running' },
  { label: t('jobs.success'), value: 'success' },
  { label: t('jobs.failed'), value: 'failed' },
  { label: t('jobs.paused'), value: 'paused' },
  { label: t('jobs.cancelled'), value: 'cancelled' },
  { label: t('jobs.partialSuccess'), value: 'partial_success' },
])

const nodeOptions = computed(() =>
  workflowStore.nodes.map((n) => ({ label: n.display_name || n.node_key, value: n.node_key }))
)

function onSeriesChange() {
  filters.template = ''
  loadJobs()
}

function toggleError(id) {
  const next = new Set(expandedErrors.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedErrors.value = next
}

const statsRow = computed(() => {
  const counts = jobStore.statusCounts || {}
  return [
    { label: t('jobs.allJobs'), value: jobStore.pagination.total || jobStore.jobs.length, icon: PhBriefcase, iconBg: 'bg-white', iconColor: 'text-gray-500', statusKey: '' },
    { label: t('jobs.queued'), value: counts.queued || 0, icon: PhArrowsClockwise, iconBg: 'bg-indigo-50', iconColor: 'text-indigo-500', statusKey: 'queued' },
    { label: t('jobs.running'), value: counts.running || 0, icon: PhPlayCircle, iconBg: 'bg-blue-50', iconColor: 'text-blue-500', statusKey: 'running' },
    { label: t('jobs.success'), value: counts.success || 0, icon: PhCheckCircle, iconBg: 'bg-green-50', iconColor: 'text-green-500', statusKey: 'success' },
    { label: t('jobs.failed'), value: counts.failed || 0, icon: PhXCircle, iconBg: 'bg-red-50', iconColor: 'text-red-500', statusKey: 'failed' },
    { label: t('jobs.paused'), value: counts.paused || 0, icon: PhPause, iconBg: 'bg-orange-50', iconColor: 'text-orange-500', statusKey: 'paused' },
    { label: t('jobs.cancelled'), value: counts.cancelled || 0, icon: PhStopCircle, iconBg: 'bg-gray-100', iconColor: 'text-gray-500', statusKey: 'cancelled' },
    { label: t('jobs.partialSuccess'), value: counts.partial_success || 0, icon: PhCheckCircle, iconBg: 'bg-yellow-50', iconColor: 'text-yellow-500', statusKey: 'partial_success' },
  ]
})

function filterByStatus(status) {
  filters.status = status
  loadJobs()
}

async function loadJobs() {
  await jobStore.fetchJobs(filters)
}

function jobKey(job) {
  return job?.job_id || job?.id || ''
}

function displayJobName(job) {
  return job?.job_name || jobKey(job)
}

function rememberJob(job) {
  setRecentJob(jobKey(job))
}

function resetFilters() {
  filters.series_id = ''
  filters.template = ''
  filters.status = ''
  filters.node = ''
  filters.search = ''
  loadJobs()
}

async function runJob(job) {
  try {
    rememberJob(job)
    await jobStore.runFull(jobKey(job))
    toast.success(t('jobs.jobStarted'))
    loadJobs()
  } catch (e) { toast.error(t('jobs.jobStartFailed')) }
}

async function pauseJob(job) {
  try {
    await jobStore.pauseJob(job.job_id || job.id)
    toast.success(t('jobs.jobPaused'))
    loadJobs()
  } catch (e) { toast.error(t('jobs.jobPauseFailed')) }
}

async function cancelJob(job) {
  try {
    await jobStore.cancelJob(job.job_id || job.id)
    toast.success(t('jobs.jobCancelled'))
    loadJobs()
  } catch (e) { toast.error(t('jobs.jobCancelFailed')) }
}

function openDeleteJob(job) {
  deleteTarget.value = job
  deleteConfirm.value = ''
}

function closeDeleteDialog() {
  deleteTarget.value = null
  deleteConfirm.value = ''
  deletingJob.value = false
}

async function confirmDeleteJob() {
  if (!deleteTarget.value) return
  deletingJob.value = true
  const id = jobKey(deleteTarget.value)
  try {
    await jobStore.deleteJob(id, deleteConfirm.value)
    clearRecentJob(id)
    toast.success('Job deleted')
    closeDeleteDialog()
    await loadJobs()
  } catch (e) {
    toast.error(e?.response?.data?.error?.message || 'Failed to delete Job')
    deletingJob.value = false
  }
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(t('jobs.copiedToClipboard'))
  } catch {
    toast.error(t('jobs.copyFailed'))
  }
}

onMounted(async () => {
  await Promise.all([
    seriesStore.fetchSeries(),
    templateStore.fetchTemplates(),
    workflowStore.fetchNodes(),
  ])
  loadJobs()
})
</script>
