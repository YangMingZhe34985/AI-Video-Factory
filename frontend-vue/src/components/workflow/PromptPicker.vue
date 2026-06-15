<template>
  <div class="space-y-3">
    <div>
      <label class="text-xs text-gray-500 block mb-1">{{ t('series.select') }}</label>
      <select
        v-model="sel.series"
        @change="onSeriesChange"
        class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white focus:border-primary outline-none"
      >
        <option value="">{{ t('workflow.wizardSelectPlaceholder') }}</option>
        <option v-for="s in seriesList" :key="s.series_id" :value="s.series_id">
          {{ s.name }}{{ s.is_default ? ` (${t('series.default')})` : '' }}
        </option>
      </select>
    </div>

    <div>
      <label class="text-xs text-gray-500 block mb-1">{{ t('template.select') }}</label>
      <select
        v-model="sel.template"
        @change="onTemplateChange"
        :disabled="!sel.series"
        class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white focus:border-primary outline-none disabled:opacity-50"
      >
        <option value="">{{ t('workflow.wizardSelectPlaceholder') }}</option>
        <option v-for="tmpl in templates" :key="tmpl.template_id" :value="tmpl.template_id">
          {{ tmpl.name || tmpl.template_id }}
        </option>
      </select>
    </div>

    <div>
      <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.wizardSelectJob') }}</label>
      <select
        v-model="sel.job"
        @change="onJobChange"
        :disabled="!sel.template"
        class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white focus:border-primary outline-none disabled:opacity-50"
      >
        <option value="">{{ loadingJobs ? t('common.loading') : t('workflow.wizardSelectPlaceholder') }}</option>
        <option v-for="j in jobs" :key="j.job_id" :value="j.job_id">
          {{ j.job_name ? `${j.job_name} (${j.job_id})` : j.job_id }}
        </option>
      </select>
      <p v-if="sel.template && !jobs.length && !loadingJobs" class="text-xs text-gray-400 mt-1">
        {{ t('workflow.wizardNoJobsFound') }}
      </p>
    </div>

    <div>
      <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.wizardSelectPromptVersion') }}</label>
      <select
        v-model="sel.promptId"
        @change="onPromptChange"
        :disabled="!sel.job || !promptVersions.length"
        class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white focus:border-primary outline-none disabled:opacity-50"
      >
        <option value="">{{ loadingPrompts ? t('common.loading') : t('workflow.wizardSelectPlaceholder') }}</option>
        <option v-for="v in promptVersions" :key="v.uid" :value="v.uid">
          {{ v.version }}{{ v.prompt_key && v.prompt_key !== 'default' ? ` [${v.prompt_key}]` : '' }}
        </option>
      </select>
      <p v-if="sel.job && !promptVersions.length && !loadingPrompts" class="text-xs text-gray-400 mt-1">
        {{ t('workflow.wizardNoPromptsFound') }}
      </p>
    </div>

    <div v-if="previewContent" class="bg-gray-50 border border-gray-100 rounded-lg p-3">
      <div class="text-[10px] text-gray-400 uppercase tracking-wider mb-1.5">{{ t('workflow.wizardPromptPreview') }}</div>
      <div class="text-xs text-gray-700 font-mono whitespace-pre-wrap max-h-32 overflow-y-auto leading-relaxed">{{ previewContent }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSeriesStore } from '@/stores/series'
import { getTemplates } from '@/api/templates'
import { getJobs } from '@/api/jobs'
import { listPrompts } from '@/api/prompts'

const props = defineProps({
  promptType: { type: String, required: true },
  modelValue: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()
const seriesStore = useSeriesStore()

const sel = ref({ series: '', template: '', job: '', promptId: '' })
const templates = ref([])
const jobs = ref([])
const promptVersions = ref([])
const loadingJobs = ref(false)
const loadingPrompts = ref(false)
const previewContent = ref('')

const seriesList = computed(() => seriesStore.seriesList)

async function onSeriesChange() {
  sel.value.template = ''
  sel.value.job = ''
  sel.value.promptId = ''
  jobs.value = []
  promptVersions.value = []
  previewContent.value = ''
  emit('update:modelValue', '')
  templates.value = []
  if (!sel.value.series) return
  try {
    const data = await getTemplates({ series_id: sel.value.series })
    templates.value = data.templates || (Array.isArray(data) ? data : [])
  } catch { templates.value = [] }
}

async function onTemplateChange() {
  sel.value.job = ''
  sel.value.promptId = ''
  promptVersions.value = []
  previewContent.value = ''
  emit('update:modelValue', '')
  jobs.value = []
  if (!sel.value.template) return
  loadingJobs.value = true
  try {
    const data = await getJobs({ template_id: sel.value.template, limit: 50 })
    jobs.value = data.jobs || (Array.isArray(data) ? data : [])
  } catch { jobs.value = [] }
  finally { loadingJobs.value = false }
}

async function onJobChange() {
  sel.value.promptId = ''
  previewContent.value = ''
  emit('update:modelValue', '')
  promptVersions.value = []
  if (!sel.value.job) return
  loadingPrompts.value = true
  try {
    const assets = await listPrompts(sel.value.template, {
      job_id: sel.value.job,
      prompt_type: props.promptType,
    })
    const scopePriority = { job: 0, job_snapshot: 1, template: 2 }
    const dedup = new Map()
    ;(assets || []).forEach((asset) => {
      const scope = asset.scope || 'template'
      const priority = scopePriority[scope] ?? 9
      ;(asset.versions || []).forEach((v) => {
        const dedupKey = `${asset.prompt_key ?? 'default'}::${v.version}`
        const existing = dedup.get(dedupKey)
        if (!existing || priority < existing._priority) {
          dedup.set(dedupKey, {
            uid: v.id ?? v.prompt_id ?? `${asset.prompt_key}-${v.version}`,
            version: v.version,
            prompt_key: asset.prompt_key ?? 'default',
            content: v.content ?? '',
            _priority: priority,
          })
        }
      })
    })
    promptVersions.value = [...dedup.values()].map(({ _priority, ...rest }) => rest)
  } catch { promptVersions.value = [] }
  finally { loadingPrompts.value = false }
}

function onPromptChange() {
  const found = promptVersions.value.find((v) => v.uid === sel.value.promptId)
  previewContent.value = found?.content ?? ''
  emit('update:modelValue', previewContent.value)
}
</script>
