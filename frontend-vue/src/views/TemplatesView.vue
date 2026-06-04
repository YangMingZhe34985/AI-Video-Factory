<template>
  <DefaultLayout :title="t('templates.title')" :subtitle="t('templates.subtitle')">
    <div class="max-w-7xl mx-auto space-y-6">

      <!-- Series filter bar + actions -->
      <div class="flex flex-col lg:flex-row justify-between items-start gap-4">
        <div class="flex items-center gap-3 flex-wrap">
          <!-- Series tabs -->
          <button
            @click="selectSeries('')"
            :class="selectedSeriesId === '' ? 'bg-primary text-white' : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'"
            class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors"
          >
            {{ t('series.all') }}
          </button>
          <button
            v-for="s in seriesStore.seriesList"
            :key="s.series_id"
            @click="selectSeries(s.series_id)"
            :class="selectedSeriesId === s.series_id ? 'bg-primary text-white' : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'"
            class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors"
          >
            {{ s.name }}
            <span v-if="s.is_default" class="ml-1 text-xs opacity-70">({{ t('series.default') }})</span>
          </button>
        </div>
        <div class="flex items-center gap-2 shrink-0">
          <SearchInput v-model="search" :placeholder="t('templates.searchPlaceholder')" class="w-52" />
          <button @click="openSeriesDialog" class="px-3 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 bg-white hover:bg-gray-50 flex items-center">
            <PhFolderPlus class="mr-1.5" /> {{ t('series.manage') }}
          </button>
          <button @click="openCreateDialog" class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 flex items-center">
            <PhPlus class="mr-1.5" /> {{ t('templates.createTemplate') }}
          </button>
          <button @click="refresh" class="p-2 bg-white border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50">
            <PhArrowsClockwise class="text-lg" />
          </button>
        </div>
      </div>

      <LoadingSpinner v-if="store.loading" :text="t('templates.loading')" />

      <div v-else-if="paginatedTemplates.length === 0" class="bg-white rounded-xl border border-gray-100 p-12">
        <EmptyState text="No templates found" />
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="tpl in paginatedTemplates"
          :key="tpl.id || tpl.template_id"
          class="bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-xl p-5 flex flex-col md:flex-row items-center justify-between shadow-sm hover:shadow transition-shadow"
        >
          <div class="flex items-start flex-1 mb-4 md:mb-0">
            <div class="w-11 h-11 rounded-lg bg-blue-50 text-primary flex items-center justify-center mr-4 shrink-0">
              <PhFilmSlate class="text-xl" />
            </div>
            <div class="min-w-0">
              <div class="flex items-center mb-1 gap-2 flex-wrap">
                <h3 class="text-sm font-bold text-gray-900 dark:text-gray-100">{{ tpl.name || tpl.template_id || t('templates.unnamed') }}</h3>
                <span v-if="tpl.series_name || tpl.series_id" class="bg-purple-50 text-purple-600 border border-purple-100 px-2 py-0.5 text-xs rounded font-medium">
                  {{ tpl.series_name || tpl.series_id }}
                </span>
              </div>
              <p class="text-xs text-gray-400 font-mono">{{ tpl.template_id }}</p>
              <p class="text-sm text-gray-500 mt-0.5">{{ tpl.description || t('templates.noDescription') }}</p>
            </div>
          </div>
          <div class="flex items-center gap-2 flex-wrap">
            <router-link :to="`/prompts?template=${tpl.template_id || tpl.id}`" class="border border-gray-200 text-gray-600 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-xs font-medium">{{ t('templates.viewDetails') }}</router-link>
            <button @click="openJobWizard(tpl)" class="border border-gray-200 text-gray-600 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-xs font-medium">{{ t('templates.createJob') }}</button>
            <button @click="openMoveDialog(tpl)" class="border border-gray-200 text-gray-600 hover:bg-gray-50 px-3 py-1.5 rounded-lg text-xs font-medium">{{ t('series.moveTo') }}</button>
          </div>
        </div>
      </div>

      <div v-if="!store.loading" class="flex justify-between items-center text-sm text-gray-500 pt-2">
        <div>{{ t('templates.showing', { count: filteredTemplates.length }) }}</div>
        <Pagination :current-page="currentPage" :total-pages="totalPages" @change="changePage" />
      </div>

      <!-- Create Template Dialog -->
      <div v-if="showCreateDialog" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showCreateDialog = false"></div>
        <div class="relative bg-white dark:bg-gray-800 rounded-xl shadow-xl p-6 w-full max-w-lg mx-4 z-10">
          <h3 class="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">{{ t('templates.createTitle') }}</h3>
          <div class="space-y-4">
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ t('series.select') }}</label>
              <select v-model="newTemplate.series_id" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary bg-white">
                <option v-for="s in seriesStore.seriesList" :key="s.series_id" :value="s.series_id">
                  {{ s.name }}{{ s.is_default ? ` (${t('series.default')})` : '' }}
                </option>
              </select>
              <p class="text-xs text-gray-400 mt-1">{{ t('series.templateBelongsTo') }}</p>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ t('templates.templateName') }} <span class="text-red-500">*</span></label>
              <input v-model="newTemplate.name" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" :placeholder="t('templates.templateNamePlaceholder')" />
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ t('templates.description') }}</label>
              <textarea v-model="newTemplate.description" rows="2" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" :placeholder="t('templates.descriptionPlaceholder')"></textarea>
            </div>
          </div>
          <div class="flex justify-end gap-3 mt-6">
            <button @click="showCreateDialog = false" class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50">{{ t('templates.cancel') }}</button>
            <button @click="handleCreateTemplate" :disabled="creating" class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {{ creating ? t('templates.creating') : t('templates.submit') }}
            </button>
          </div>
        </div>
      </div>

      <!-- Series Management Dialog -->
      <div v-if="showSeriesDialog" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showSeriesDialog = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 z-10 max-h-[80vh] flex flex-col">
          <div class="p-5 border-b border-gray-100 flex items-center justify-between">
            <h3 class="text-lg font-bold text-gray-900">{{ t('series.manage') }}</h3>
            <button @click="showSeriesDialog = false" class="text-gray-400 hover:text-gray-600 text-xl">&times;</button>
          </div>
          <div class="flex-1 overflow-y-auto p-4 space-y-3">
            <div v-for="s in seriesStore.seriesList" :key="s.series_id" class="flex items-center justify-between p-3 border border-gray-100 rounded-lg">
              <div>
                <div class="text-sm font-bold text-gray-900">{{ s.name }}</div>
                <div class="text-xs font-mono text-gray-400">{{ s.series_id }}</div>
                <div v-if="s.description" class="text-xs text-gray-500 mt-0.5">{{ s.description }}</div>
              </div>
              <div class="flex items-center gap-2">
                <span v-if="s.is_default" class="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded">Default</span>
                <button v-if="!s.is_default" @click="confirmDeleteSeries(s)" class="text-xs text-red-500 hover:text-red-700 px-2 py-1 border border-red-200 rounded hover:bg-red-50">{{ t('common.delete') }}</button>
              </div>
            </div>
          </div>
          <!-- Create new series -->
          <div class="p-4 border-t border-gray-100 space-y-3">
            <div class="text-xs text-gray-500 font-semibold uppercase tracking-wide">{{ t('series.create') }}</div>
            <div class="flex gap-2">
              <input v-model="newSeries.series_id" type="text" class="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" :placeholder="t('series.idPlaceholder')" />
              <input v-model="newSeries.name" type="text" class="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" :placeholder="t('series.namePlaceholder')" />
            </div>
            <input v-model="newSeries.description" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" :placeholder="t('series.descriptionPlaceholder')" />
            <button @click="handleCreateSeries" :disabled="creatingSeries" class="w-full py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {{ creatingSeries ? t('series.creating') : t('series.create') }}
            </button>
          </div>
        </div>
      </div>

      <!-- Move Template Dialog -->
      <div v-if="showMoveDialog && movingTemplate" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showMoveDialog = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-md mx-4 z-10">
          <h3 class="text-lg font-bold text-gray-900 mb-4">{{ t('series.moveTemplate') }}</h3>
          <p class="text-sm text-gray-500 mb-4">
            {{ t('series.movingTemplate') }}: <span class="font-mono font-bold text-primary">{{ movingTemplate.name || movingTemplate.template_id }}</span>
          </p>
          <div>
            <label class="block text-xs text-gray-500 mb-1">{{ t('series.targetSeries') }}</label>
            <select v-model="moveTargetSeriesId" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary bg-white">
              <option v-for="s in seriesStore.seriesList" :key="s.series_id" :value="s.series_id">{{ s.name }}</option>
            </select>
          </div>
          <div class="flex justify-end gap-3 mt-6">
            <button @click="showMoveDialog = false" class="px-4 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">{{ t('common.cancel') }}</button>
            <button @click="handleMoveTemplate" :disabled="moving" class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {{ moving ? t('series.moving') : t('series.moveConfirm') }}
            </button>
          </div>
        </div>
      </div>

      <WorkflowJobWizard
        v-if="showWizard"
        :default-template-id="wizardTemplateId"
        :default-series-id="wizardSeriesId"
        @close="showWizard = false"
      />

    </div>
  </DefaultLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import SearchInput from '@/components/common/SearchInput.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Pagination from '@/components/common/Pagination.vue'
import WorkflowJobWizard from '@/components/workflow/WorkflowJobWizard.vue'
import { useTemplateStore } from '@/stores/templates'
import { useSeriesStore } from '@/stores/series'
import { useToast } from '@/composables/useToast'
import { PhArrowsClockwise, PhFilmSlate, PhPlus, PhFolderPlus } from '@phosphor-icons/vue'

const { t } = useI18n()
const store = useTemplateStore()
const seriesStore = useSeriesStore()
const toast = useToast()
const search = ref('')
const currentPage = ref(1)
const perPage = ref(10)
const showCreateDialog = ref(false)
const showSeriesDialog = ref(false)
const showMoveDialog = ref(false)
const showWizard = ref(false)
const wizardTemplateId = ref('')
const wizardSeriesId = ref('')
const creating = ref(false)
const creatingSeries = ref(false)
const moving = ref(false)
const selectedSeriesId = ref('')
const movingTemplate = ref(null)
const moveTargetSeriesId = ref('default')
const newTemplate = ref({ series_id: 'default', name: '', description: '' })
const newSeries = ref({ series_id: '', name: '', description: '' })

const filteredTemplates = computed(() => {
  let list = store.templates
  if (selectedSeriesId.value) {
    list = list.filter((t) => (t.series_id || t.series || 'default') === selectedSeriesId.value)
  }
  if (search.value) {
    const q = search.value.toLowerCase()
    list = list.filter((t) => (t.name || t.template_id || '').toLowerCase().includes(q))
  }
  return list
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredTemplates.value.length / perPage.value)))

const paginatedTemplates = computed(() => {
  const start = (currentPage.value - 1) * perPage.value
  return filteredTemplates.value.slice(start, start + perPage.value)
})

function changePage(page) { currentPage.value = page }

function selectSeries(id) {
  selectedSeriesId.value = id
  currentPage.value = 1
}

function openCreateDialog() {
  newTemplate.value = { series_id: selectedSeriesId.value || 'default', name: '', description: '' }
  showCreateDialog.value = true
}

function openSeriesDialog() {
  newSeries.value = { series_id: '', name: '', description: '' }
  showSeriesDialog.value = true
}

function openMoveDialog(tpl) {
  movingTemplate.value = tpl
  moveTargetSeriesId.value = tpl.series_id || tpl.series || 'default'
  showMoveDialog.value = true
}

function openJobWizard(tpl) {
  wizardTemplateId.value = tpl.template_id || tpl.id || ''
  wizardSeriesId.value = tpl.series_id || tpl.series || 'default'
  showWizard.value = true
}

async function refresh() {
  await Promise.all([store.fetchTemplates(), seriesStore.fetchSeries()])
}

async function handleCreateTemplate() {
  if (!newTemplate.value.name.trim()) {
    toast.error(t('templates.createFailed'))
    return
  }
  creating.value = true
  try {
    await store.createTemplate({
      name: newTemplate.value.name.trim(),
      series_id: newTemplate.value.series_id || 'default',
      description: newTemplate.value.description.trim() || undefined,
    })
    toast.success(t('templates.created'))
    showCreateDialog.value = false
    await store.fetchTemplates()
  } catch {
    toast.error(t('templates.createFailed'))
  } finally {
    creating.value = false
  }
}

async function handleCreateSeries() {
  if (!newSeries.value.series_id.trim() || !newSeries.value.name.trim()) {
    toast.error(t('series.idAndNameRequired'))
    return
  }
  creatingSeries.value = true
  try {
    await seriesStore.createSeries({
      series_id: newSeries.value.series_id.trim(),
      name: newSeries.value.name.trim(),
      description: newSeries.value.description.trim() || undefined,
    })
    toast.success(t('series.created'))
    newSeries.value = { series_id: '', name: '', description: '' }
  } catch (e) {
    toast.error(e?.response?.data?.error?.message || t('series.createFailed'))
  } finally {
    creatingSeries.value = false
  }
}

async function handleMoveTemplate() {
  if (!movingTemplate.value) return
  moving.value = true
  try {
    await seriesStore.moveTemplate(movingTemplate.value.template_id, moveTargetSeriesId.value)
    toast.success(t('series.moved'))
    showMoveDialog.value = false
    await store.fetchTemplates()
  } catch (e) {
    toast.error(e?.response?.data?.error?.message || t('series.moveFailed'))
  } finally {
    moving.value = false
  }
}

async function confirmDeleteSeries(s) {
  if (!confirm(`Delete series "${s.name}"? This cannot be undone.`)) return
  try {
    await seriesStore.deleteSeries(s.series_id)
    toast.success(t('series.deleted'))
  } catch (e) {
    toast.error(e?.response?.data?.error?.message || t('series.deleteFailed'))
  }
}

onMounted(async () => {
  await Promise.all([store.fetchTemplates(), seriesStore.fetchSeries()])
  // Set default series in create form
  const def = seriesStore.seriesList.find((s) => s.is_default)
  if (def) newTemplate.value.series_id = def.series_id
})
</script>
