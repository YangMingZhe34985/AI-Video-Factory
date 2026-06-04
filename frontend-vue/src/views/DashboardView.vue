<template>
  <DefaultLayout :title="t('dashboard.title')" :subtitle="t('dashboard.subtitle')">
    <div class="max-w-7xl mx-auto space-y-6">
      <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <StatCard :icon="PhStack" icon-bg="bg-violet-500" :label="t('dashboard.series')" :value="summary.total_series ?? '--'" clickable to="/templates" />
        <StatCard :icon="PhFolder" icon-bg="bg-blue-500" :label="t('dashboard.templates')" :value="summary.total_templates ?? '--'" clickable to="/templates" />
        <StatCard :icon="PhBriefcase" icon-bg="bg-emerald-500" :label="t('dashboard.totalJobs')" :value="summary.total_jobs ?? '--'" clickable to="/jobs" />
        <StatCard :icon="PhPlayCircle" icon-bg="bg-sky-500" :value="summary.running ?? '--'" :label="t('dashboard.runningJobs')" clickable to="/jobs?status=running" />
        <StatCard :icon="PhCheckCircle" icon-bg="bg-green-500" :value="summary.success ?? '--'" :label="t('dashboard.successJobs')" clickable to="/jobs?status=success" />
        <StatCard :icon="PhXCircle" icon-bg="bg-red-500" :value="summary.failed ?? '--'" :label="t('dashboard.failedJobs')" clickable to="/jobs?status=failed" />
        <StatCard :icon="PhImage" icon-bg="bg-indigo-500" :label="t('dashboard.artifacts')" :value="summary.total_artifacts ?? '--'" clickable to="/artifacts" />
      </div>

      <div class="bg-white rounded-xl p-6 border border-gray-100 shadow-sm relative">
        <div class="flex justify-between items-center mb-6">
          <div>
            <h2 class="text-lg font-bold text-gray-900">{{ t('dashboard.quickStart') }}</h2>
            <p class="text-sm text-gray-500">{{ t('dashboard.quickStartDesc') }}</p>
          </div>
          <button @click="openCreateJobWizard" class="text-sm text-primary hover:underline flex items-center cursor-pointer">{{ t('dashboard.advancedOptions') }} <PhCaretRight class="ml-1" /></button>
        </div>

        <div class="flex flex-col md:flex-row justify-between items-start relative mt-4">
          <div class="hidden md:block absolute top-6 left-10 right-10 border-t-2 border-dashed border-gray-200 z-0"></div>

          <div v-for="(step, i) in quickSteps" :key="i" class="flex-1 flex flex-col items-center text-center relative z-10 bg-white px-2 mb-6 md:mb-0">
            <div class="w-8 h-8 rounded-full bg-blue-50 text-primary font-bold flex items-center justify-center mb-4">{{ i + 1 }}</div>
            <component :is="step.icon" class="text-3xl text-primary mb-3" />
            <h3 class="font-bold text-gray-900 text-sm mb-1">{{ step.title }}</h3>
            <p class="text-xs text-gray-500 mb-4 px-4 h-8">{{ step.desc }}</p>
            <component :is="step.actionType" :to="step.to" @click="step.onClick" :class="step.btnClass" class="rounded-lg px-4 py-2 text-sm font-medium transition-colors w-full max-w-[160px] flex justify-center items-center">
              <component :is="step.btnIcon" class="mr-2" /> {{ step.btnText }}
            </component>
          </div>
        </div>
      </div>

      <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div class="p-5 border-b border-gray-100 flex justify-between items-center bg-white">
          <h2 class="text-lg font-bold text-gray-900">{{ t('dashboard.recentJobs') }}</h2>
          <router-link to="/jobs" class="text-sm text-primary hover:underline flex items-center">{{ t('dashboard.viewAllJobs') }} <PhArrowRight class="ml-1" /></router-link>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-left border-collapse">
            <thead>
              <tr class="bg-gray-50/50 text-gray-500 text-xs uppercase tracking-wider border-b border-gray-100">
                <th class="px-5 py-3 font-medium">{{ t('dashboard.jobId') }}</th>
                <th class="px-5 py-3 font-medium">{{ t('dashboard.template') }}</th>
                <th class="px-5 py-3 font-medium">{{ t('dashboard.status') }}</th>
                <th class="px-5 py-3 font-medium">{{ t('dashboard.currentNode') }}</th>
                <th class="px-5 py-3 font-medium">{{ t('dashboard.progress') }}</th>
                <th class="px-5 py-3 font-medium">{{ t('dashboard.createdAt') }}</th>
                <th class="px-5 py-3 font-medium">{{ t('dashboard.updatedAt') }}</th>
                <th class="px-5 py-3 font-medium text-center">{{ t('dashboard.actions') }}</th>
              </tr>
            </thead>
            <tbody class="text-sm text-gray-700 divide-y divide-gray-50">
              <tr v-if="recentJobs.length === 0">
                <td colspan="8" class="px-5 py-12 text-center text-gray-400">
                  <LoadingSpinner v-if="loading" :text="t('jobs.loadingJobs')" />
                  <EmptyState v-else :text="t('jobs.noJobs')" />
                </td>
              </tr>
              <tr v-for="job in recentJobs" :key="job.job_id || job.id" class="hover:bg-gray-50/50 transition-colors">
                <td class="px-5 py-4 whitespace-nowrap">
                  <div class="flex items-center gap-2">
                    <span>
                      <span class="block">{{ jobDisplayName(job) }}</span>
                      <span v-if="job.job_name" class="block text-[11px] font-mono text-gray-400">{{ job.job_id }}</span>
                    </span>
                    <PhCopy class="text-gray-400 cursor-pointer hover:text-gray-600" @click.stop="copyToClipboard(job.job_id || job.id)" />
                  </div>
                </td>
                <td class="px-5 py-4 text-primary whitespace-nowrap">{{ job.template_id || '--' }}</td>
                <td class="px-5 py-4 whitespace-nowrap"><StatusBadge :status="job.status" /></td>
                <td class="px-5 py-4 text-gray-500 whitespace-nowrap">{{ job.current_node || '--' }}</td>
                <td class="px-5 py-4 whitespace-nowrap">
                  <div class="flex items-center">
                    <div class="w-24 bg-gray-200 rounded-full h-1.5 mr-3">
                      <div class="bg-primary h-1.5 rounded-full" :style="{ width: jobProgress(job) + '%' }"></div>
                    </div>
                    <span class="text-xs text-gray-500">{{ jobProgress(job) }}%</span>
                  </div>
                </td>
                <td class="px-5 py-4 text-gray-500 whitespace-nowrap">{{ formatDate(job.created_at) }}</td>
                <td class="px-5 py-4 text-gray-500 whitespace-nowrap">{{ formatDate(job.updated_at) }}</td>
                <td class="px-5 py-4 whitespace-nowrap">
                  <div class="flex items-center justify-center space-x-1">
                    <router-link :to="`/jobs/${job.job_id || job.id}`" class="p-1.5 text-gray-400 hover:text-gray-600 border border-gray-200 rounded">
                      <PhEye />
                    </router-link>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <WorkflowJobWizard
        v-if="showWizard"
        @close="showWizard = false"
        @created="handleJobCreated"
      />
    </div>
  </DefaultLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import StatCard from '@/components/common/StatCard.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import WorkflowJobWizard from '@/components/workflow/WorkflowJobWizard.vue'
import { useDashboardStore } from '@/stores/dashboard'
import { formatDate } from '@/utils/format'
import * as jobsApi from '@/api/jobs'
import {
  PhFolder, PhBriefcase, PhPlayCircle, PhCheckCircle, PhXCircle, PhImage,
  PhCaretRight, PhArrowRight, PhCopy, PhEye,
  PhCube, PhCloudArrowUp, PhGitBranch, PhFaders,
  PhUploadSimple, PhGear, PhPlay, PhStack,
} from '@phosphor-icons/vue'

import { useToast } from '@/composables/useToast'

import { useI18n } from 'vue-i18n'

const dashboardStore = useDashboardStore()
const toast = useToast()
const { t } = useI18n()
const summary = ref({})
const recentJobs = ref([])
const loading = ref(false)
const showWizard = ref(false)

const quickSteps = computed(() => [
  { icon: PhStack,      title: t('dashboard.qs1Title'), desc: t('dashboard.qs1Desc'), btnText: t('dashboard.qs1Btn'), actionType: 'router-link', to: '/templates', btnClass: 'border border-gray-200 text-primary hover:bg-blue-50', btnIcon: PhStack },
  { icon: PhFolder,     title: t('dashboard.qs2Title'), desc: t('dashboard.qs2Desc'), btnText: t('dashboard.qs2Btn'), actionType: 'router-link', to: '/templates', btnClass: 'border border-gray-200 text-primary hover:bg-blue-50', btnIcon: PhFolder },
  { icon: PhCloudArrowUp, title: t('dashboard.qs3Title'), desc: t('dashboard.qs3Desc'), btnText: t('dashboard.qs3Btn'), actionType: 'button', onClick: openCreateJobWizard, btnClass: 'border border-gray-200 text-primary hover:bg-blue-50', btnIcon: PhCloudArrowUp },
  { icon: PhImage,      title: t('dashboard.qs4Title'), desc: t('dashboard.qs4Desc'), btnText: t('dashboard.qs4Btn'), actionType: 'router-link', to: '/artifacts', btnClass: 'bg-primary text-white hover:bg-blue-700', btnIcon: PhImage },
])

function openCreateJobWizard() {
  showWizard.value = true
}

function jobProgress(job) {
  const total = job.total_nodes || 12
  const done = Number.isFinite(Number(job.completed_nodes))
    ? Number(job.completed_nodes)
    : latestRuns(job.node_runs || []).filter((n) => n.status === 'success').length
  return total > 0 ? Math.min(100, Math.max(0, Math.round(done / total * 100))) : 0
}

function latestRuns(runs) {
  const byNode = new Map()
  runs.forEach((run) => {
    if (run?.node_key) byNode.set(run.node_key, run)
  })
  return [...byNode.values()]
}

function jobDisplayName(job) {
  return job?.job_name || job?.job_id || job?.id || ''
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(t('dashboard.copiedToClipboard'))
  } catch {
    toast.error(t('dashboard.copyFailed'))
  }
}

async function loadRecentJobs() {
  loading.value = true
  try {
    const data = await jobsApi.getJobs({ limit: '5' })
    const jobs = Array.isArray(data) ? data : (data.jobs || [])
    recentJobs.value = jobs.slice(0, 5)
  } catch {
    recentJobs.value = []
  } finally {
    loading.value = false
  }
}

async function handleJobCreated() {
  showWizard.value = false
  await dashboardStore.fetchSummary()
  summary.value = dashboardStore.summary
  await loadRecentJobs()
}

onMounted(async () => {
  await dashboardStore.fetchSummary()
  summary.value = dashboardStore.summary
  await loadRecentJobs()
})
</script>
