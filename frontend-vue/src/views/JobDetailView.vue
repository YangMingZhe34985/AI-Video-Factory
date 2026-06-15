<template>
  <DefaultLayout :title="t('jobDetail.title')" :subtitle="`${t('jobDetail.subtitle')} ${jobDisplayTitle}`">
    <div v-if="jobStore.loading" class="flex-1 flex items-center justify-center">
      <LoadingSpinner :text="t('jobs.loadingJobs')" />
    </div>
    <div v-else-if="!job" class="flex-1 flex items-center justify-center">
      <EmptyState :text="t('jobs.noJobs')" />
    </div>
    <div v-else class="max-w-[1800px] mx-auto space-y-4 pb-4">
      <!-- Job header -->
      <div class="bg-white rounded-xl border border-gray-100 p-5 shadow-sm">
        <div class="flex justify-between items-start mb-4">
          <div>
            <div v-if="editingName" class="flex items-center gap-2 mb-2">
              <input v-model="renameDraft" type="text" class="w-80 max-w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" placeholder="Job name" />
              <button @click="saveJobName" :disabled="renameSaving" class="px-3 py-2 bg-primary text-white rounded-lg text-xs font-medium disabled:opacity-50">
                {{ renameSaving ? 'Saving...' : 'Save' }}
              </button>
              <button @click="cancelRename" class="px-3 py-2 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50">Cancel</button>
            </div>
            <div v-else class="flex items-center text-xl font-bold text-gray-900 mb-2">
              {{ jobDisplayTitle }}
              <PhCopy class="ml-2 text-gray-400 text-base cursor-pointer hover:text-gray-600" @click="copyJobId" />
              <button @click="startRename" class="ml-2 p-1.5 text-gray-400 hover:text-primary border border-gray-200 rounded-lg bg-white">
                <PhPencilSimple class="text-base" />
              </button>
            </div>
            <div class="flex items-center space-x-3 text-xs text-gray-500 flex-wrap">
              <StatusBadge :status="job.status" />
              <span v-if="job.job_name">Job ID: <span class="font-mono text-gray-700">{{ job.job_id }}</span></span>
              <span>Template: <span class="font-mono text-gray-700">{{ job.template_id || '--' }}</span></span>
              <span>Created: {{ formatDate(job.created_at) }}</span>
              <span>Updated: {{ formatDate(job.updated_at) }}</span>
            </div>
          </div>
          <div class="flex items-center space-x-2">
            <button @click="packageCurrentJob" :disabled="packageLoading" class="px-4 py-2 border border-blue-200 text-blue-600 rounded-lg text-sm font-medium hover:bg-blue-50 flex items-center disabled:opacity-50">
              <PhDownloadSimple class="mr-1.5" /> {{ packageLoading ? packageText('packaging') : packageText('packageJob') }}
            </button>
            <button v-if="!['running', 'queued'].includes(job.status)" @click="openDeleteDialog" class="px-4 py-2 border border-red-200 text-red-600 rounded-lg text-sm font-medium hover:bg-red-50 flex items-center">
              <PhTrash class="mr-1.5" /> Delete
            </button>
            <button v-if="!['running', 'queued'].includes(job.status)" @click="runFresh" class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 flex items-center">
              <PhPlay class="mr-1.5" /> {{ t('jobs.runFresh') }}
            </button>
            <button v-if="['failed', 'partial_success'].includes(job.status)" @click="runRollback" class="px-4 py-2 border border-primary text-primary rounded-lg text-sm font-medium hover:bg-blue-50 flex items-center">
              <PhArrowCounterClockwise class="mr-1.5" /> {{ t('jobs.runRollback') }}
            </button>
            <button v-if="job.status === 'running'" @click="pauseJob" class="px-4 py-2 border border-orange-200 text-orange-600 rounded-lg text-sm font-medium hover:bg-orange-50 flex items-center">
              <PhPause class="mr-1.5" /> {{ t('jobs.paused') }}
            </button>
            <button v-if="['running', 'queued'].includes(job.status)" @click="cancelJob" class="px-4 py-2 border border-red-200 text-red-600 rounded-lg text-sm font-medium hover:bg-red-50 flex items-center">
              <PhStop class="mr-1.5" /> {{ t('jobs.cancelled') }}
            </button>
          </div>
        </div>

        <!-- Progress bar -->
        <div class="w-full bg-gray-200 rounded-full h-2.5 mb-2">
          <div class="h-2.5 rounded-full transition-all duration-500" :class="progressColor" :style="{ width: progressPct + '%' }"></div>
        </div>
        <div class="text-xs text-gray-500">{{ progressPct }}% complete ({{ completedNodes }}/{{ totalNodes }} nodes)</div>
        <div v-if="packageResult" class="mt-3 flex items-center justify-between gap-3 bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 text-sm">
          <div class="text-blue-700">
            {{ packageText('packageReady') }}
            <span class="text-xs text-blue-500 ml-2">
              {{ packageResult.package_status }} ·
              {{ packageResult.included_counts?.videos || 0 }} video(s),
              {{ packageResult.included_counts?.images || 0 }} image(s),
              {{ packageResult.included_counts?.prompts || 0 }} prompt(s)
            </span>
          </div>
          <a :href="packageResult.download_url" class="inline-flex items-center px-3 py-1.5 bg-white border border-blue-200 text-blue-700 rounded hover:bg-blue-50">
            <PhDownloadSimple class="mr-1" /> {{ packageText('downloadPackage') }}
          </a>
        </div>
      </div>

      <!-- Job events (SSE) -->
      <div class="bg-white rounded-xl border border-gray-100 p-5 shadow-sm">
        <div class="flex items-center justify-between mb-4">
          <h3 class="font-bold text-gray-900">Live Events</h3>
          <span class="text-xs inline-flex items-center" :class="liveEventsBadgeClass">
            <span class="w-1.5 h-1.5 rounded-full inline-block mr-1" :class="liveEventsDotClass"></span>
            {{ liveEventsStatusText }}
          </span>
        </div>
        <div class="max-h-64 overflow-y-auto bg-gray-50 rounded-lg p-3 font-mono text-xs space-y-1">
          <div v-if="sseEvents.length === 0" class="text-gray-400">No events yet. Run the job to see live updates.</div>
          <div v-for="evt in sseEvents" :key="eventKey(evt)" class="rounded-md px-2 py-1.5" :class="eventRowClass(evt)">
            <div class="flex items-start gap-2">
              <span class="text-gray-400 shrink-0">{{ formatDate(evt.created_at) }}</span>
              <span class="text-gray-300 shrink-0">|</span>
              <span class="font-semibold shrink-0" :class="eventTypeClass(evt)">{{ evt.node_key || evt.event_type || evt.type || 'event' }}</span>
              <span class="text-gray-300 shrink-0">|</span>
              <span class="flex-1 whitespace-pre-wrap break-words" :class="eventMessageClass(evt)">{{ evt.message || evt.status || '' }}</span>
              <button
                v-if="eventErrorDetail(evt)"
                @click="toggleEventDetails(evt)"
                class="shrink-0 px-2 py-0.5 rounded border border-red-100 bg-white text-[10px] text-red-600 hover:bg-red-50"
              >
                {{ isEventExpanded(evt) ? 'Hide' : 'Details' }}
              </button>
            </div>
            <div v-if="eventErrorDetail(evt) && isEventExpanded(evt)" class="mt-2 rounded-lg border border-red-100 bg-white p-3 text-[11px] text-gray-700 space-y-2 font-sans">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                <div><span class="text-gray-400">Code:</span> <span class="font-mono text-red-600">{{ eventErrorDetail(evt).code || '--' }}</span></div>
                <div><span class="text-gray-400">Node:</span> <span class="font-mono">{{ eventErrorDetail(evt).node_key || evt.node_key || '--' }}</span></div>
                <div><span class="text-gray-400">Run:</span> <span class="font-mono">{{ eventErrorDetail(evt).run_id || '--' }}</span></div>
                <div><span class="text-gray-400">Attempt:</span> <span class="font-mono">{{ eventErrorDetail(evt).attempt || '--' }}</span></div>
              </div>
              <div v-if="eventErrorDetail(evt).hint" class="rounded bg-amber-50 border border-amber-100 px-2 py-1 text-amber-800">{{ eventErrorDetail(evt).hint }}</div>
              <div v-if="eventErrorDetail(evt).technical_message">
                <div class="text-gray-400 mb-1">Technical message</div>
                <pre class="whitespace-pre-wrap break-words rounded bg-gray-50 border border-gray-100 p-2 font-mono text-[11px] text-gray-700">{{ eventErrorDetail(evt).technical_message }}</pre>
              </div>
              <div v-if="eventErrorDetail(evt).api_task">
                <div class="text-gray-400 mb-1">API task</div>
                <pre class="whitespace-pre-wrap break-words rounded bg-gray-50 border border-gray-100 p-2 font-mono text-[11px] text-gray-700">{{ formatDetailJson(eventErrorDetail(evt).api_task) }}</pre>
              </div>
              <div v-if="eventErrorDetail(evt).payload">
                <div class="text-gray-400 mb-1">Payload</div>
                <pre class="whitespace-pre-wrap break-words rounded bg-gray-50 border border-gray-100 p-2 font-mono text-[11px] text-gray-700">{{ formatDetailJson(eventErrorDetail(evt).payload) }}</pre>
              </div>
              <div v-if="eventErrorDetail(evt).traceback">
                <div class="text-gray-400 mb-1">Traceback</div>
                <pre class="whitespace-pre-wrap break-words rounded bg-red-50 border border-red-100 p-2 font-mono text-[11px] text-red-700">{{ eventErrorDetail(evt).traceback }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Node runs -->
      <div class="bg-white rounded-xl border border-gray-100 p-5 shadow-sm">
        <h3 class="font-bold text-gray-900 mb-4">Node Runs</h3>
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-3">
          <div v-for="nr in (job.node_runs || [])" :key="nr.node_key" class="border rounded-lg p-3 text-center" :class="nodeRunBorder(nr.status)">
            <div class="text-xs font-bold text-gray-800 truncate mb-1">{{ nr.node_key }}</div>
            <StatusBadge :status="nr.status || 'pending'" />
            <div class="text-[10px] text-gray-400 mt-1">{{ nr.started_at ? formatDate(nr.started_at) : 'Not started' }}</div>
          </div>
        </div>
        <div v-if="!job.node_runs?.length" class="text-center text-gray-400 text-sm py-4">No node runs yet</div>
      </div>

      <!-- I2I test results -->
      <div v-if="i2iTestGroups.length" class="bg-white rounded-xl border border-amber-100 p-5 shadow-sm">
        <div class="flex items-center justify-between mb-4">
          <h3 class="font-bold text-gray-900">I2I Test Results</h3>
          <span class="text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded px-2 py-0.5">{{ i2iTestGroups.length }} tests</span>
        </div>
        <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
          <div v-for="group in i2iTestGroups" :key="group.test_index" class="border border-amber-100 rounded-lg p-3 bg-amber-50/30">
            <div class="flex items-center justify-between mb-2">
              <div class="text-sm font-bold text-gray-900">Test #{{ group.test_index || '--' }}</div>
              <span class="text-[10px] px-1.5 py-0.5 rounded bg-white border border-amber-100 text-amber-700">{{ group.mode || 'i2i_test' }}</span>
            </div>
            <div class="grid grid-cols-3 gap-2">
              <div class="rounded-lg border border-amber-100 bg-white p-2 min-w-0">
                <div class="text-[10px] text-gray-400 mb-1">Source</div>
                <div class="text-xs text-gray-700 truncate">{{ group.sourceImages.length }} image(s)</div>
                <a
                  v-if="group.sourceImages[0]"
                  :href="`/api/artifacts/${group.sourceImages[0].id || group.sourceImages[0].artifact_id}/preview`"
                  target="_blank"
                  class="text-[10px] text-primary hover:underline"
                >Preview</a>
              </div>
              <div class="rounded-lg border border-amber-100 bg-white p-2 min-w-0">
                <div class="text-[10px] text-gray-400 mb-1">I2I First Frame</div>
                <div v-if="group.firstFrame" class="text-xs text-gray-700 truncate">{{ group.firstFrame.filename || group.firstFrame.name }}</div>
                <span v-else class="text-xs text-gray-400">Missing</span>
                <a
                  v-if="group.firstFrame"
                  :href="`/api/artifacts/${group.firstFrame.id || group.firstFrame.artifact_id}/preview`"
                  target="_blank"
                  class="text-[10px] text-primary hover:underline"
                >Preview</a>
              </div>
              <div class="rounded-lg border border-amber-100 bg-white p-2 min-w-0">
                <div class="text-[10px] text-gray-400 mb-1">Test Video</div>
                <div v-if="group.video" class="text-xs text-gray-700 truncate">{{ group.video.filename || group.video.name }}</div>
                <span v-else class="text-xs text-gray-400">Missing</span>
                <a
                  v-if="group.video"
                  :href="`/api/artifacts/${group.video.id || group.video.artifact_id}/download`"
                  class="text-[10px] text-primary hover:underline inline-flex items-center"
                ><PhDownloadSimple class="mr-0.5" /> Download</a>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Artifacts -->
      <div class="bg-white rounded-xl border border-gray-100 p-5 shadow-sm">
        <div class="flex items-center justify-between gap-3 mb-4">
          <div>
            <h3 class="font-bold text-gray-900">Artifacts</h3>
            <p class="text-xs text-gray-400 mt-0.5">
              {{ showArtifactHistory ? 'Showing current and historical artifacts' : 'Showing current run artifacts' }}
            </p>
          </div>
          <label class="inline-flex items-center gap-2 text-xs text-gray-500 select-none">
            <input
              v-model="showArtifactHistory"
              type="checkbox"
              class="rounded border-gray-300 text-primary focus:ring-primary"
              @change="loadArtifacts"
            />
            Show history
          </label>
        </div>
        <div v-if="artifacts.length === 0" class="text-center text-gray-400 text-sm py-4">No artifacts yet</div>
        <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div v-for="a in artifacts" :key="a.id || a.artifact_id" class="border border-gray-200 rounded-lg p-3 flex items-center">
            <div class="w-16 h-10 bg-gray-800 rounded mr-4 flex items-center justify-center shrink-0 overflow-hidden">
              <PhImage class="text-white" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-bold text-gray-900 truncate">{{ a.filename || a.name || 'artifact' }}</div>
              <div class="text-xs text-gray-500">{{ a.mime_type || '' }}</div>
              <div class="text-[10px] text-gray-400 mt-0.5">{{ formatDate(a.created_at) }}</div>
            </div>
            <a v-if="a.id || a.artifact_id" :href="`/api/artifacts/${a.id || a.artifact_id}/download`" class="p-1.5 text-gray-400 hover:text-primary border border-gray-200 rounded ml-2">
              <PhDownloadSimple />
            </a>
          </div>
        </div>
      </div>

      <div v-if="showDeleteDialog" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="closeDeleteDialog"></div>
        <div class="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-md mx-4 z-10">
          <h3 class="text-lg font-bold text-gray-900 mb-2">Delete Job</h3>
          <p class="text-sm text-gray-500 mb-4">
            This removes the Job record, node runs, events, artifacts and owned files. Type
            <span class="font-mono text-gray-800">{{ jobDisplayTitle }}</span>
            or <span class="font-mono text-gray-800">{{ job.job_id }}</span> to confirm.
          </p>
          <input v-model="deleteConfirm" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-red-400" />
          <div class="flex justify-end gap-3 mt-5">
            <button @click="closeDeleteDialog" class="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">Cancel</button>
            <button @click="deleteCurrentJob" :disabled="deletingJob" class="px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-medium hover:bg-red-700 disabled:opacity-50">
              {{ deletingJob ? 'Deleting...' : 'Delete Job' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useJobStore } from '@/stores/jobs'
import { useToast } from '@/composables/useToast'
import { formatDate } from '@/utils/format'
import * as artifactsApi from '@/api/artifacts'
import { deleteJob, packageJob, updateJob } from '@/api/jobs'
import { PhCopy, PhPlay, PhPause, PhStop, PhImage, PhDownloadSimple, PhPencilSimple, PhTrash, PhArrowCounterClockwise } from '@phosphor-icons/vue'
import { clearRecentJob, setRecentJob } from '@/composables/useRecentJob'

import { useI18n } from 'vue-i18n'

const route = useRoute()
const router = useRouter()
const jobStore = useJobStore()
const toast = useToast()
const { t, locale } = useI18n()

const jobId = computed(() => route.params.jobId)
const job = computed(() => jobStore.currentJob)
const jobDisplayTitle = computed(() => job.value?.job_name || job.value?.job_id || job.value?.id || jobId.value)
const artifacts = ref([])
const showArtifactHistory = ref(false)
const sseEvents = ref([])
const sseConnected = ref(false)
const expandedEventKeys = ref(new Set())
const packageLoading = ref(false)
const packageResult = ref(null)
const editingName = ref(false)
const renameDraft = ref('')
const renameSaving = ref(false)
const showDeleteDialog = ref(false)
const deleteConfirm = ref('')
const deletingJob = ref(false)

let eventSource = null
let refreshTimer = null
let pollingTimer = null

const terminalStatuses = new Set(['success', 'failed', 'paused', 'cancelled', 'partial_success'])
const maxVisibleEvents = 100

const totalNodes = computed(() => job.value?.total_nodes || 12)
const completedNodes = computed(() => {
  if (job.value?.status === 'success') return totalNodes.value
  if (Number.isFinite(Number(job.value?.completed_nodes))) return Number(job.value.completed_nodes)
  return latestRuns(job.value?.node_runs || []).filter((n) => n.status === 'success').length
})
const progressPct = computed(() => totalNodes.value > 0 ? Math.min(100, Math.max(0, Math.round(completedNodes.value / totalNodes.value * 100))) : 0)
const i2iTestGroups = computed(() => {
  const groups = new Map()
  const relevantTypes = new Set([
    'i2i_test_source_image',
    'i2i_test_first_frame_image',
    'i2i_test_video',
  ])
  artifacts.value
    .filter((a) => a.branch_key === 'i2i_test' && relevantTypes.has(a.artifact_type))
    .forEach((artifact) => {
      const meta = artifactMeta(artifact)
      const key = String(meta.test_index || '--')
      if (!groups.has(key)) {
        groups.set(key, {
          test_index: key,
          mode: meta.mode,
          sourceImages: [],
          firstFrame: null,
          video: null,
        })
      }
      const group = groups.get(key)
      if (!group.mode && meta.mode) group.mode = meta.mode
      if (artifact.artifact_type === 'i2i_test_source_image') group.sourceImages.push(artifact)
      if (artifact.artifact_type === 'i2i_test_first_frame_image') group.firstFrame = artifact
      if (artifact.artifact_type === 'i2i_test_video') group.video = artifact
    })
  return [...groups.values()].sort((a, b) => {
    const av = Number(a.test_index)
    const bv = Number(b.test_index)
    if (Number.isNaN(av) && Number.isNaN(bv)) return 0
    if (Number.isNaN(av)) return 1
    if (Number.isNaN(bv)) return -1
    return av - bv
  })
})
const progressColor = computed(() => {
  if (job.value?.status === 'success') return 'bg-green-500'
  if (job.value?.status === 'failed') return 'bg-red-500'
  return 'bg-primary'
})
const liveEventsStatusText = computed(() => {
  const status = job.value?.status
  if (status === 'running') return sseConnected.value ? 'Live' : 'Running'
  if (status === 'queued') return 'Queued'
  if (status === 'paused') return 'Paused'
  if (status === 'failed') return 'Failed'
  if (status === 'success') return 'Completed'
  if (status === 'partial_success') return 'Partial Success'
  if (status === 'cancelled') return 'Cancelled'
  return sseEvents.value.length ? 'History' : 'Idle'
})
const liveEventsBadgeClass = computed(() => {
  const status = job.value?.status
  if (status === 'running') return 'text-green-600'
  if (status === 'queued') return 'text-blue-600'
  if (status === 'paused') return 'text-orange-600'
  if (status === 'failed') return 'text-red-600'
  if (status === 'success' || status === 'partial_success') return 'text-green-600'
  if (status === 'cancelled') return 'text-gray-500'
  return 'text-gray-400'
})
const liveEventsDotClass = computed(() => {
  const status = job.value?.status
  if (status === 'running') return 'bg-green-500'
  if (status === 'queued') return 'bg-blue-500'
  if (status === 'paused') return 'bg-orange-500'
  if (status === 'failed') return 'bg-red-500'
  if (status === 'success' || status === 'partial_success') return 'bg-green-500'
  if (status === 'cancelled') return 'bg-gray-500'
  return 'bg-gray-400'
})

function nodeRunBorder(status) {
  const map = {
    success: 'border-green-200',
    failed: 'border-red-200',
    running: 'border-blue-200',
    retrying: 'border-blue-200',
    path_failed: 'border-amber-200',
    paused: 'border-orange-200',
  }
  return map[status] || 'border-gray-200'
}

function latestRuns(runs) {
  const byNode = new Map()
  runs.forEach((run) => {
    if (run?.node_key) byNode.set(run.node_key, run)
  })
  return [...byNode.values()]
}

function artifactMeta(artifact) {
  return artifact?.meta || artifact?.metadata || {}
}

function eventKey(evt) {
  return String(evt?.id || evt?.event_id || `${evt?.created_at || ''}-${evt?.event_type || evt?.type || ''}-${evt?.message || ''}`)
}

function eventNumericId(evt) {
  const value = Number(evt?.id)
  return Number.isFinite(value) ? value : 0
}

function compareEvents(a, b) {
  const aid = eventNumericId(a)
  const bid = eventNumericId(b)
  if (aid || bid) return aid - bid
  return new Date(a?.created_at || 0).getTime() - new Date(b?.created_at || 0).getTime()
}

function maxEventId() {
  return sseEvents.value.reduce((max, evt) => Math.max(max, eventNumericId(evt)), 0)
}

function mergeEvents(events = []) {
  if (!Array.isArray(events) || events.length === 0) return
  const merged = new Map()
  sseEvents.value.forEach((evt) => merged.set(eventKey(evt), evt))
  events.forEach((evt) => merged.set(eventKey(evt), evt))
  sseEvents.value = [...merged.values()].sort(compareEvents).slice(-maxVisibleEvents)
}

function eventErrorDetail(evt) {
  const payload = evt?.payload || {}
  if (payload?.error_detail) return payload.error_detail
  if (evt?.level === 'error') {
    return {
      code: payload?.code || 'ERROR',
      summary: evt?.message || '',
      technical_message: evt?.message || '',
      node_key: evt?.node_key,
      payload,
    }
  }
  return null
}

function toggleEventDetails(evt) {
  const key = eventKey(evt)
  const next = new Set(expandedEventKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expandedEventKeys.value = next
}

function isEventExpanded(evt) {
  return expandedEventKeys.value.has(eventKey(evt))
}

function eventRowClass(evt) {
  if (evt?.level === 'error') return 'bg-red-50 border border-red-100'
  if (evt?.level === 'warning') return 'bg-amber-50 border border-amber-100'
  if (job.value?.status === 'running') return 'text-green-700'
  if (job.value?.status === 'paused') return 'text-orange-700'
  if (job.value?.status === 'failed') return 'text-red-700'
  return 'text-gray-600'
}

function eventTypeClass(evt) {
  if (evt?.level === 'error') return 'text-red-600'
  if (evt?.level === 'warning') return 'text-amber-700'
  if (job.value?.status === 'running') return 'text-green-700'
  return 'text-gray-700'
}

function eventMessageClass(evt) {
  if (evt?.level === 'error') return 'text-red-700'
  if (evt?.level === 'warning') return 'text-amber-800'
  if (job.value?.status === 'running') return 'text-green-700'
  if (job.value?.status === 'paused') return 'text-orange-700'
  if (job.value?.status === 'failed') return 'text-red-700'
  return 'text-gray-600'
}

function formatDetailJson(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value || '')
  }
}

function copyJobId() {
  navigator.clipboard?.writeText(job.value?.job_id || job.value?.id || '')
  toast.success(t('jobDetail.copiedToClipboard'))
}

function startRename() {
  renameDraft.value = job.value?.job_name || ''
  editingName.value = true
}

function cancelRename() {
  editingName.value = false
  renameDraft.value = ''
  renameSaving.value = false
}

async function saveJobName() {
  renameSaving.value = true
  try {
    await updateJob(jobId.value, { job_name: renameDraft.value })
    toast.success('Job name updated')
    cancelRename()
    await loadJob()
  } catch (e) {
    toast.error(e?.response?.data?.error?.message || 'Failed to update Job name')
    renameSaving.value = false
  }
}

function openDeleteDialog() {
  deleteConfirm.value = ''
  showDeleteDialog.value = true
}

function closeDeleteDialog() {
  showDeleteDialog.value = false
  deleteConfirm.value = ''
  deletingJob.value = false
}

async function deleteCurrentJob() {
  deletingJob.value = true
  const id = job.value?.job_id || jobId.value
  try {
    await deleteJob(id, deleteConfirm.value)
    clearRecentJob(id)
    toast.success('Job deleted')
    closeDeleteDialog()
    router.push('/jobs')
  } catch (e) {
    toast.error(e?.response?.data?.error?.message || 'Failed to delete Job')
    deletingJob.value = false
  }
}

function packageText(key) {
  const zh = String(locale.value || '').startsWith('zh')
  const labels = {
    packageJob: zh ? '一键打包' : 'Package Job',
    packaging: zh ? '打包中...' : 'Packaging...',
    packageReady: zh ? '交付包已生成' : 'Package ready',
    downloadPackage: zh ? '下载交付包' : 'Download Package',
    packageFailed: zh ? '打包失败' : 'Failed to package job',
  }
  return labels[key] || key
}

function connectSSE() {
  if (eventSource) eventSource.close()
  const afterId = maxEventId()
  const suffix = afterId ? `?after_id=${afterId}` : ''
  eventSource = new EventSource(`/api/jobs/${jobId.value}/stream${suffix}`)
  sseConnected.value = false
  eventSource.onopen = () => {
    sseConnected.value = true
  }
  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.type === 'stream_closed') {
        eventSource?.close()
        eventSource = null
        sseConnected.value = false
        doFinalRefresh()
        return
      }
      mergeEvents([data])
      scheduleLiveRefresh()
    } catch {}
  }
  eventSource.onerror = () => {
    sseConnected.value = false
  }
}

function scheduleLiveRefresh(delay = 500) {
  if (refreshTimer) return
  refreshTimer = window.setTimeout(async () => {
    refreshTimer = null
    await refreshLiveData()
  }, delay)
}

async function doFinalRefresh() {
  await new Promise(resolve => setTimeout(resolve, 800))
  await Promise.all([loadJob({ silent: true }), loadArtifacts()])
  if (
    job.value?.status === 'success' &&
    Number.isFinite(Number(job.value?.completed_nodes)) &&
    Number.isFinite(Number(job.value?.total_nodes)) &&
    Number(job.value.completed_nodes) < Number(job.value.total_nodes)
  ) {
    await new Promise(resolve => setTimeout(resolve, 1500))
    await Promise.all([loadJob({ silent: true }), loadArtifacts()])
  }
}

async function refreshLiveData() {
  await Promise.all([loadJob({ silent: true }), loadArtifacts()])
  if (terminalStatuses.has(job.value?.status)) {
    stopRunningPoll()
    if (eventSource) {
      eventSource.close()
      eventSource = null
      sseConnected.value = false
    }
    doFinalRefresh()
  }
}

function startRunningPoll() {
  stopRunningPoll()
  pollingTimer = window.setInterval(async () => {
    if (terminalStatuses.has(job.value?.status)) {
      stopRunningPoll()
      await doFinalRefresh()
      return
    }
    refreshLiveData()
  }, 3000)
}

function stopRunningPoll() {
  if (pollingTimer) {
    window.clearInterval(pollingTimer)
    pollingTimer = null
  }
}

async function runFull() {
  try {
    setRecentJob(job.value?.job_id || jobId.value)
    await jobStore.runFull(jobId.value)
    toast.success(t('jobs.jobStarted'))
    connectSSE()
    await refreshLiveData()
    startRunningPoll()
  } catch (e) { toast.error(t('jobs.jobStartFailed')) }
}

async function runFresh() {
  try {
    setRecentJob(job.value?.job_id || jobId.value)
    artifacts.value = []
    showArtifactHistory.value = false
    packageResult.value = null
    await jobStore.runFull(jobId.value, true, { restart: true })
    toast.success(t('jobs.jobStarted'))
    connectSSE()
    await refreshLiveData()
    startRunningPoll()
  } catch (e) { toast.error(t('jobs.jobStartFailed')) }
}

async function runRollback() {
  try {
    setRecentJob(job.value?.job_id || jobId.value)
    await jobStore.runFull(jobId.value, false)
    toast.success(t('jobs.jobStarted'))
    connectSSE()
    await refreshLiveData()
    startRunningPoll()
  } catch (e) { toast.error(t('jobs.jobStartFailed')) }
}

async function pauseJob() {
  try {
    await jobStore.pauseJob(jobId.value)
    toast.success(t('jobs.jobPaused'))
    await refreshLiveData()
  } catch (e) { toast.error(t('jobs.jobPauseFailed')) }
}

async function cancelJob() {
  try {
    await jobStore.cancelJob(jobId.value)
    toast.success(t('jobs.jobCancelled'))
    await refreshLiveData()
  } catch (e) { toast.error(t('jobs.jobCancelFailed')) }
}

async function packageCurrentJob() {
  packageLoading.value = true
  packageResult.value = null
  try {
    packageResult.value = await packageJob(jobId.value)
    toast.success(packageText('packageReady'))
    await loadArtifacts()
    await loadJob()
  } catch (e) {
    toast.error(e?.response?.data?.error?.message || packageText('packageFailed'))
  } finally {
    packageLoading.value = false
  }
}

async function loadJob(options = {}) {
  await jobStore.fetchJob(jobId.value, options)
  mergeEvents(job.value?.recent_events || [])
  if (job.value?.job_id) {
    setRecentJob(job.value.job_id)
  }
}

async function loadArtifacts() {
  try {
    artifacts.value = await artifactsApi.getArtifacts(jobId.value, {
      includeHistory: showArtifactHistory.value,
    })
    if (!Array.isArray(artifacts.value)) artifacts.value = []
  } catch { artifacts.value = [] }
}

onMounted(async () => {
  await loadJob()
  await loadArtifacts()
  if (['running', 'queued'].includes(job.value?.status)) {
    connectSSE()
    startRunningPoll()
  }
})

onUnmounted(() => {
  if (eventSource) eventSource.close()
  if (refreshTimer) window.clearTimeout(refreshTimer)
  stopRunningPoll()
})
</script>
