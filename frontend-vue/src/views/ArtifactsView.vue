<template>
  <DefaultLayout :title="t('artifacts.title')" :subtitle="t('artifacts.subtitle')">
    <div class="max-w-7xl mx-auto space-y-6">

      <!-- Filter bar -->
      <div class="bg-white p-4 rounded-xl border border-gray-100 shadow-sm space-y-3">
        <div class="flex items-center gap-3 flex-wrap">
          <!-- Series -->
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">{{ t('series.title') }}</span>
            <AppSelect
              v-model="filterSeriesId"
              :options="seriesOptions"
              :placeholder="t('series.all')"
              class="min-w-[140px]"
              @change="onSeriesChange"
            />
          </div>

          <!-- Template (filtered by series) -->
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">{{ t('artifacts.template') }}</span>
            <AppSelect
              v-model="filterTemplateId"
              :options="templatesForSeries"
              :placeholder="t('artifacts.allTemplates')"
              class="min-w-[160px]"
              @change="onTemplateChange"
            />
          </div>

          <!-- Job (filtered by template) -->
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">{{ t('artifacts.job') }}</span>
            <AppSelect
              v-model="filterJobId"
              :options="jobOptions"
              :placeholder="t('artifacts.allJobs')"
              class="min-w-[160px]"
              @change="onJobChange"
            />
          </div>

          <!-- Artifact Type -->
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">{{ t('artifacts.type') }}</span>
            <AppSelect
              v-model="filterArtifactType"
              :options="artifactTypeOptions"
              :placeholder="t('artifacts.allTypes')"
              class="min-w-[120px]"
              @change="loadArtifacts"
            />
          </div>

          <!-- Branch -->
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">{{ t('artifacts.branch') }}</span>
            <AppSelect
              v-model="filterBranchKey"
              :options="branchOptions"
              :placeholder="t('artifacts.allBranches')"
              class="min-w-[120px]"
              @change="loadArtifacts"
            />
          </div>

          <!-- Search -->
          <SearchInput v-model="search" :placeholder="t('artifacts.searchPlaceholder')" class="w-48" />

          <button @click="loadArtifacts" class="p-2 bg-white border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50" :title="t('artifacts.refresh')">
            <PhArrowsClockwise class="text-lg" />
          </button>
        </div>

        <!-- Active filters summary -->
        <div v-if="hasActiveFilters" class="flex items-center gap-2 text-xs text-gray-500">
          <span>{{ t('artifacts.showing') }}:</span>
          <span v-if="filterSeriesId" class="px-2 py-0.5 bg-violet-50 text-violet-700 rounded border border-violet-100">{{ t('series.title') }}: {{ seriesLabel(filterSeriesId) }}</span>
          <span v-if="filterTemplateId" class="px-2 py-0.5 bg-blue-50 text-blue-700 rounded border border-blue-100">{{ t('artifacts.template') }}: {{ filterTemplateId }}</span>
          <span v-if="filterJobId" class="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded border border-indigo-100">{{ t('artifacts.job') }}: {{ filterJobId }}</span>
          <span v-if="filterArtifactType" class="px-2 py-0.5 bg-green-50 text-green-700 rounded border border-green-100">{{ t('artifacts.type') }}: {{ filterArtifactType }}</span>
          <span v-if="filterBranchKey" class="px-2 py-0.5 bg-orange-50 text-orange-700 rounded border border-orange-100">{{ t('artifacts.branch') }}: {{ filterBranchKey }}</span>
          <button @click="clearFilters" class="text-gray-400 hover:text-red-500 ml-1">{{ t('artifacts.clearAll') }}</button>
        </div>

        <div class="flex items-center gap-2 text-xs">
          <span class="text-gray-500">Group by</span>
          <button
            @click="groupMode = 'type'"
            class="px-3 py-1.5 rounded-lg border font-medium"
            :class="groupMode === 'type' ? 'bg-primary text-white border-primary' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'"
          >Type</button>
          <button
            @click="groupMode = 'job'"
            class="px-3 py-1.5 rounded-lg border font-medium"
            :class="groupMode === 'job' ? 'bg-primary text-white border-primary' : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'"
          >Job</button>
        </div>
      </div>

      <div v-if="loading" class="py-12"><LoadingSpinner :text="t('artifacts.loading')" /></div>

      <div v-else-if="filteredItems.length === 0" class="bg-white rounded-xl border border-gray-100 p-12">
        <EmptyState :text="t('artifacts.noArtifacts')" />
      </div>

      <div v-else class="space-y-6">
        <p class="text-xs text-gray-400 mb-3">{{ t('artifacts.found', { count: filteredItems.length }) }}</p>
        <section v-for="group in groupedItems" :key="group.key" class="space-y-3">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-bold text-gray-900">{{ group.label }}</h2>
            <span class="text-xs text-gray-400">{{ group.items.length }} item(s)</span>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          <div v-for="a in group.items" :key="a.id || a.artifact_id"
            class="bg-white rounded-xl border border-gray-100 p-4 shadow-sm hover:shadow transition-shadow">
            <!-- Preview area -->
            <div class="w-full h-36 bg-gray-900 rounded-lg mb-3 flex items-center justify-center overflow-hidden relative">
              <video
                v-if="isVideo(a)"
                :src="`/api/artifacts/${a.id || a.artifact_id}/preview`"
                class="w-full h-full object-cover"
                muted
                preload="none"
                @mouseenter="(e) => e.target.play()"
                @mouseleave="(e) => { e.target.pause(); e.target.currentTime = 0 }"
              />
              <img
                v-else-if="isImage(a)"
                :src="`/api/artifacts/${a.id || a.artifact_id}/preview`"
                class="w-full h-full object-cover"
                loading="lazy"
              />
              <div v-else class="flex flex-col items-center gap-2">
                <PhFile class="text-white text-3xl opacity-50" />
                <span class="text-white text-xs opacity-50">{{ a.artifact_type || 'file' }}</span>
              </div>
              <span v-if="a.branch_key" class="absolute top-2 right-2 text-[10px] px-1.5 py-0.5 rounded bg-black/60 text-white font-mono">{{ a.branch_key }}</span>
            </div>

            <h3 class="font-bold text-gray-900 text-sm mb-1 truncate" :title="a.file_name || a.filename">
              {{ a.file_name || a.filename || a.name || t('artifacts.artifact') }}
            </h3>
            <p class="text-xs text-gray-400 mb-0.5 truncate">
              <router-link v-if="a.job_id" :to="`/jobs/${a.job_id}`" class="text-primary hover:underline">{{ jobLabel(a) }}</router-link>
              <span v-else>--</span>
              <span v-if="a.template_name" class="text-gray-300"> / {{ a.template_name }}</span>
            </p>
            <p class="text-xs text-gray-500 mb-3">{{ a.mime_type || '--' }} · {{ formatSize(a.size) }}</p>

            <div class="flex items-center gap-2">
              <a :href="`/api/artifacts/${a.id || a.artifact_id}/download`"
                class="flex-1 px-3 py-1.5 bg-primary text-white rounded-lg text-xs font-medium text-center hover:bg-blue-700 flex items-center justify-center">
                <PhDownloadSimple class="mr-1" /> {{ t('artifacts.download') }}
              </a>
              <button @click="openArtifactPreview(a)"
                class="px-3 py-1.5 border border-gray-200 rounded-lg text-xs font-medium text-gray-600 hover:bg-gray-50 flex items-center justify-center">
                <PhEye class="mr-1" /> {{ t('artifacts.preview') }}
              </button>
            </div>
          </div>
        </div>
        </section>
      </div>

      <div v-if="previewOpen" class="fixed inset-0 z-50 flex justify-end">
        <div class="absolute inset-0 bg-black/30" @click="closeArtifactPreview"></div>
        <aside class="relative w-full max-w-4xl h-full bg-white shadow-2xl flex flex-col">
          <div class="px-5 py-4 border-b border-gray-100 flex items-start justify-between gap-4">
            <div class="min-w-0">
              <h2 class="text-base font-bold text-gray-900 truncate">
                {{ previewArtifact?.file_name || previewArtifact?.filename || previewArtifact?.name || t('artifacts.artifact') }}
              </h2>
              <p class="text-xs text-gray-400 mt-1 truncate">
                {{ previewArtifact?.artifact_type || '--' }} / {{ previewArtifact?.mime_type || '--' }}
              </p>
            </div>
            <div class="flex items-center gap-2 shrink-0">
              <button
                v-if="previewText"
                @click="copyPreviewContent"
                class="px-3 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50 flex items-center"
              >
                <PhCopy class="mr-1" /> Copy
              </button>
              <button
                v-if="previewFormat === 'json' && previewJsonCanCollapse"
                @click="previewJsonCollapsed = !previewJsonCollapsed"
                class="px-3 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50"
              >
                {{ previewJsonCollapsed ? 'Expand JSON' : 'Collapse JSON' }}
              </button>
              <a
                v-if="previewArtifact"
                :href="`/api/artifacts/${previewArtifact.id || previewArtifact.artifact_id}/download`"
                class="px-3 py-1.5 bg-primary text-white rounded-lg text-xs font-medium hover:bg-blue-700 flex items-center"
              >
                <PhDownloadSimple class="mr-1" /> {{ t('artifacts.download') }}
              </a>
              <button @click="closeArtifactPreview" class="p-2 border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50">
                <PhX />
              </button>
            </div>
          </div>

          <div class="flex-1 min-h-0 overflow-auto p-5 bg-gray-50">
            <div v-if="previewLoading" class="py-16">
              <LoadingSpinner :text="t('artifacts.loading')" />
            </div>
            <div v-else-if="previewError" class="bg-red-50 border border-red-100 text-red-600 rounded-xl p-4 text-sm">
              {{ previewError }}
            </div>
            <video
              v-else-if="previewArtifact && isVideo(previewArtifact)"
              :src="`/api/artifacts/${previewArtifact.id || previewArtifact.artifact_id}/preview`"
              class="w-full max-h-[calc(100vh-160px)] rounded-xl bg-black"
              controls
            />
            <img
              v-else-if="previewArtifact && isImage(previewArtifact)"
              :src="`/api/artifacts/${previewArtifact.id || previewArtifact.artifact_id}/preview`"
              class="max-w-full rounded-xl bg-white border border-gray-100 mx-auto"
            />
            <div
              v-else-if="previewFormat === 'markdown'"
              class="bg-white border border-gray-100 rounded-xl p-5 prose-lite"
              v-html="renderMarkdown(previewText)"
            ></div>
            <pre
              v-else-if="previewFormat === 'json'"
              class="bg-gray-950 text-gray-50 rounded-xl p-5 text-xs leading-5 overflow-auto"
              v-html="renderJsonHighlighted(displayedJsonText)"
            ></pre>
            <pre
              v-else-if="previewText"
              class="bg-white border border-gray-100 rounded-xl p-5 text-sm leading-6 font-mono whitespace-pre-wrap overflow-auto"
            >{{ previewText }}</pre>
            <div v-else class="bg-white border border-gray-100 rounded-xl p-8 text-center text-sm text-gray-400">
              Preview is not available for this artifact type. Use Download to open it locally.
            </div>
          </div>
        </aside>
      </div>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import SearchInput from '@/components/common/SearchInput.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import * as artifactsApi from '@/api/artifacts'
import * as jobsApi from '@/api/jobs'
import * as templatesApi from '@/api/templates'
import * as seriesApi from '@/api/series'
import AppSelect from '@/components/common/AppSelect.vue'
import { PhArrowsClockwise, PhFile, PhDownloadSimple, PhEye, PhX, PhCopy } from '@phosphor-icons/vue'
import { useI18n } from 'vue-i18n'
import { clearRecentJob, getRecentJob, setRecentJob } from '@/composables/useRecentJob'

const { t } = useI18n()
const route = useRoute()
const search = ref('')
const filterSeriesId = ref(route.query.series_id || route.query.series || '')
const filterTemplateId = ref(route.query.template_id || route.query.template || '')
const filterJobId = ref(route.query.job_id || '')
const filterArtifactType = ref(route.query.artifact_type || route.query.type || '')
const filterBranchKey = ref(route.query.branch_key || route.query.branch || '')
const items = ref([])
const loading = ref(false)
const allJobs = ref([])
const templates = ref([])
const seriesList = ref([])
const groupMode = ref('type')
const previewOpen = ref(false)
const previewArtifact = ref(null)
const previewText = ref('')
const previewFormat = ref('')
const previewLoading = ref(false)
const previewError = ref('')
const previewJsonCollapsed = ref(false)

// Computed option lists for AppSelect
const seriesOptions = computed(() =>
  seriesList.value.map((s) => ({ label: s.name, value: s.series_id }))
)

const templatesForSeries = computed(() => {
  const list = filterSeriesId.value
    ? templates.value.filter((t) => (t.series_id || t.series || 'default') === filterSeriesId.value)
    : templates.value
  return list.map((t) => ({ label: t.name || t.template_id, value: t.template_id }))
})

const jobsForTemplate = computed(() => {
  if (filterTemplateId.value) return allJobs.value.filter((j) => j.template_id === filterTemplateId.value)
  if (filterSeriesId.value) {
    const tmplIds = new Set(templatesForSeries.value.map((t) => t.value))
    return allJobs.value.filter((j) => tmplIds.has(j.template_id))
  }
  return allJobs.value
})

const jobOptions = computed(() =>
  jobsForTemplate.value.map((j) => ({ label: jobOptionLabel(j), value: j.job_id }))
)

const artifactTypeOptions = computed(() => [
  { label: t('artifacts.video'), value: 'video' },
  { label: t('artifacts.image'), value: 'image' },
  { label: t('artifacts.manifest'), value: 'manifest' },
  { label: 'JSON', value: 'json' },
  { label: 'I2I Test Source Image', value: 'i2i_test_source_image' },
  { label: 'I2I Test First Frame Image', value: 'i2i_test_first_frame_image' },
  { label: 'I2I Test Video', value: 'i2i_test_video' },
])

const branchOptions = computed(() => [
  { label: 'T2V', value: 't2v' },
  { label: 'First Frame', value: 'first_frame_image' },
  { label: 'I2V', value: 'i2v' },
  { label: 'I2I Test', value: 'i2i_test' },
  { label: 'R2V Flash', value: 'r2v_flash' },
])

const hasActiveFilters = computed(() =>
  !!(filterSeriesId.value || filterTemplateId.value || filterJobId.value || filterArtifactType.value || filterBranchKey.value)
)

const filteredItems = computed(() => {
  if (!search.value) return items.value
  const q = search.value.toLowerCase()
  return items.value.filter((a) =>
    [a.file_name, a.filename, a.name, a.artifact_type, a.job_id, a.job_name, a.template_name]
      .filter(Boolean).join(' ').toLowerCase().includes(q)
  )
})

const groupOrder = ['video', 'image', 'prompt', 'manifest', 'package', 'process', 'other']
const groupLabels = {
  video: 'Video',
  image: 'Image',
  prompt: 'Prompt',
  manifest: 'Manifest',
  package: 'Package',
  process: 'Process',
  other: 'Other',
}

const groupedItems = computed(() => {
  const groups = new Map()
  filteredItems.value.forEach((artifact) => {
    const key = groupMode.value === 'job'
      ? (artifact.job_id || 'unknown_job')
      : artifactGroup(artifact)
    const label = groupMode.value === 'job'
      ? jobLabel(artifact)
      : (groupLabels[key] || key)
    if (!groups.has(key)) groups.set(key, { key, label, items: [] })
    groups.get(key).items.push(artifact)
  })
  const result = [...groups.values()]
  if (groupMode.value === 'type') {
    result.sort((a, b) => {
      const ai = groupOrder.includes(a.key) ? groupOrder.indexOf(a.key) : 999
      const bi = groupOrder.includes(b.key) ? groupOrder.indexOf(b.key) : 999
      return ai - bi
    })
  }
  return result
})

function isVideo(a) {
  return (a.mime_type || '').startsWith('video/')
}

function isImage(a) {
  return (a.mime_type || '').startsWith('image/')
}

function artifactGroup(a) {
  const group = a.artifact_group || ''
  if (groupOrder.includes(group)) return group
  if (isVideo(a)) return 'video'
  if (isImage(a)) return 'image'
  if (a.artifact_type === 'manifest') return 'manifest'
  if (a.artifact_type === 'job_package') return 'package'
  if (String(a.artifact_type || '').includes('prompt')) return 'prompt'
  return 'other'
}

function artifactId(a) {
  return a?.id || a?.artifact_id
}

function fileName(a) {
  return String(a?.file_name || a?.filename || a?.name || '')
}

function artifactFormat(a) {
  const name = fileName(a).toLowerCase()
  const type = String(a?.artifact_type || '').toLowerCase()
  const mime = String(a?.mime_type || '').toLowerCase()
  if (name.endsWith('.md') || type === 'prompt_markdown') return 'markdown'
  if (name.endsWith('.json') || mime === 'application/json' || ['prompt_summary', 'manifest', 'request_payload', 'api_response'].includes(type)) return 'json'
  if (name.endsWith('.txt') || mime.startsWith('text/')) return 'text'
  return ''
}

function isTextPreview(a) {
  return !!artifactFormat(a)
}

async function openArtifactPreview(artifact) {
  previewArtifact.value = artifact
  previewOpen.value = true
  previewText.value = ''
  previewError.value = ''
  previewLoading.value = false
  previewJsonCollapsed.value = false
  previewFormat.value = artifactFormat(artifact)
  if (!isTextPreview(artifact)) return
  previewLoading.value = true
  try {
    const response = await fetch(`/api/artifacts/${artifactId(artifact)}/preview`)
    if (!response.ok) throw new Error(`Preview failed: ${response.status}`)
    const raw = await response.text()
    previewText.value = previewFormat.value === 'json' ? formatJsonText(raw) : raw
    previewJsonCollapsed.value = previewFormat.value === 'json' && previewText.value.split('\n').length > 160
  } catch (error) {
    previewError.value = error?.message || 'Failed to load preview'
  } finally {
    previewLoading.value = false
  }
}

function closeArtifactPreview() {
  previewOpen.value = false
  previewArtifact.value = null
  previewText.value = ''
  previewFormat.value = ''
  previewError.value = ''
  previewLoading.value = false
  previewJsonCollapsed.value = false
}

const previewJsonCanCollapse = computed(() =>
  previewFormat.value === 'json' && previewText.value.split('\n').length > 160
)

const displayedJsonText = computed(() => {
  if (!previewJsonCollapsed.value) return previewText.value
  const lines = previewText.value.split('\n')
  return [
    ...lines.slice(0, 120),
    '',
    `... ${Math.max(0, lines.length - 120)} more line(s). Click Expand JSON to view all.`,
  ].join('\n')
})

function formatJsonText(raw) {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

function copyPreviewContent() {
  navigator.clipboard?.writeText(previewText.value || '')
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderInline(value) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-gray-100 rounded text-xs">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
}

function renderJsonHighlighted(source) {
  return escapeHtml(source).replace(
    /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\b\d+(?:\.\d+)?(?:e[+-]?\d+)?\b/gi,
    (match, stringValue, colon, keyword) => {
      if (stringValue) {
        const cls = colon ? 'text-sky-300' : 'text-emerald-300'
        return `<span class="${cls}">${stringValue}</span>${colon || ''}`
      }
      if (keyword) return `<span class="text-purple-300">${keyword}</span>`
      return `<span class="text-amber-300">${match}</span>`
    }
  )
}

function renderMarkdown(source) {
  const lines = String(source || '').replace(/\r\n/g, '\n').split('\n')
  const html = []
  let inCode = false
  let codeLines = []
  let listItems = []

  function flushList() {
    if (!listItems.length) return
    html.push(`<ul class="list-disc pl-5 space-y-1">${listItems.join('')}</ul>`)
    listItems = []
  }

  function flushCode() {
    if (!inCode) return
    html.push(`<pre class="bg-gray-950 text-gray-50 rounded-lg p-3 overflow-auto text-xs"><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
    inCode = false
    codeLines = []
  }

  lines.forEach((rawLine) => {
    const line = rawLine || ''
    if (line.trim().startsWith('```')) {
      if (inCode) flushCode()
      else {
        flushList()
        inCode = true
        codeLines = []
      }
      return
    }
    if (inCode) {
      codeLines.push(line)
      return
    }
    const trimmed = line.trim()
    if (!trimmed) {
      flushList()
      html.push('<div class="h-3"></div>')
      return
    }
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      flushList()
      const level = heading[1].length
      const cls = level === 1 ? 'text-xl' : level === 2 ? 'text-lg' : 'text-base'
      html.push(`<h${level} class="${cls} font-bold text-gray-900 mt-3 mb-2">${renderInline(heading[2])}</h${level}>`)
      return
    }
    const list = trimmed.match(/^[-*]\s+(.+)$/)
    if (list) {
      listItems.push(`<li>${renderInline(list[1])}</li>`)
      return
    }
    flushList()
    html.push(`<p class="text-sm leading-6 text-gray-700">${renderInline(trimmed)}</p>`)
  })
  flushCode()
  flushList()
  return html.join('\n')
}

function jobLabel(a) {
  if (!a?.job_id) return 'No Job'
  return a.job_name ? `${a.job_name} (${a.job_id})` : a.job_id
}

function jobOptionLabel(job) {
  if (!job?.job_id) return ''
  return job.job_name ? `${job.job_name} (${job.job_id})` : job.job_id
}

function formatSize(bytes) {
  if (!bytes) return '--'
  const mb = bytes / 1024 / 1024
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${(bytes / 1024).toFixed(1)} KB`
}

function onSeriesChange() {
  filterTemplateId.value = ''
  filterJobId.value = ''
  loadArtifacts()
}

async function onTemplateChange() {
  filterJobId.value = ''
  await loadArtifacts()
}

async function onJobChange() {
  if (filterJobId.value) {
    setRecentJob(filterJobId.value)
  }
  await loadArtifacts()
}

async function loadArtifacts() {
  loading.value = true
  try {
    const params = {}
    if (filterTemplateId.value) params.template_id = filterTemplateId.value
    if (filterJobId.value) params.job_id = filterJobId.value
    if (filterArtifactType.value) params.artifact_type = filterArtifactType.value
    if (filterBranchKey.value) params.branch_key = filterBranchKey.value
    if (filterSeriesId.value) params.series_id = filterSeriesId.value
    const data = await artifactsApi.searchArtifacts(params)
    items.value = Array.isArray(data) ? data : (data?.artifacts || data || [])
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

function seriesLabel(seriesId) {
  return seriesList.value.find((s) => s.series_id === seriesId)?.name || seriesId
}

function clearFilters() {
  filterSeriesId.value = ''
  filterTemplateId.value = ''
  filterJobId.value = ''
  filterArtifactType.value = ''
  filterBranchKey.value = ''
  loadArtifacts()
}

function hasExplicitInitialFilters() {
  return !!(
    route.query.series_id ||
    route.query.series ||
    route.query.template_id ||
    route.query.template ||
    route.query.job_id ||
    route.query.artifact_type ||
    route.query.type ||
    route.query.branch_key ||
    route.query.branch
  )
}

async function applyRecentJobDefault() {
  if (hasExplicitInitialFilters()) return
  const recentJobId = getRecentJob()
  if (!recentJobId) return

  let recentJob = allJobs.value.find((item) => item.job_id === recentJobId)
  if (!recentJob) {
    try {
      recentJob = await jobsApi.getJob(recentJobId)
      if (recentJob?.job_id && !allJobs.value.some((item) => item.job_id === recentJob.job_id)) {
        allJobs.value = [recentJob, ...allJobs.value]
      }
    } catch {
      clearRecentJob(recentJobId)
      return
    }
  }

  if (!recentJob?.job_id) {
    clearRecentJob(recentJobId)
    return
  }

  filterJobId.value = recentJob.job_id
  filterTemplateId.value = recentJob.template_id || ''
  const template = templates.value.find((item) => item.template_id === filterTemplateId.value)
  filterSeriesId.value = template?.series_id || template?.series || recentJob.series_id || ''
}

onMounted(async () => {
  try {
    seriesList.value = await seriesApi.getSeries()
  } catch { seriesList.value = [] }
  try {
    const tData = await templatesApi.getTemplates()
    templates.value = Array.isArray(tData) ? tData : (tData.templates || [])
  } catch { templates.value = [] }
  try {
    const jData = await jobsApi.getJobs({ perPage: 500 })
    allJobs.value = Array.isArray(jData) ? jData : (jData.jobs || [])
  } catch { allJobs.value = [] }
  await applyRecentJobDefault()
  await loadArtifacts()
})
</script>
