<template>
  <DefaultLayout :title="t('prompts.title')" :subtitle="t('prompts.subtitle')">
    <div class="max-w-7xl mx-auto space-y-6">
      <div class="bg-white rounded-xl border border-gray-100 p-4 shadow-sm space-y-3">
        <div class="flex items-center gap-3 flex-wrap">
          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">{{ t('series.title') }}</span>
            <AppSelect
              v-model="selectedSeriesId"
              :options="seriesOptions"
              :placeholder="t('series.all')"
              clearable
              searchable
              class="min-w-[130px]"
              @change="onSeriesChange"
            />
          </div>

          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">{{ t('template.select') }}</span>
            <AppSelect
              v-model="selectedTemplateId"
              :options="templatesForSeries"
              :placeholder="t('prompts.selectTemplate')"
              clearable
              searchable
              class="min-w-[170px]"
              @change="onTemplateChange"
            />
          </div>

          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">Job</span>
            <AppSelect
              v-model="selectedJobId"
              :options="jobOptions"
              :placeholder="label('selectJob')"
              clearable
              searchable
              class="min-w-[170px]"
              @change="onJobChange"
            />
          </div>

          <div class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">{{ t('prompts.type') }}</span>
            <AppSelect
              v-model="selectedPromptType"
              :options="promptTypeOptions"
              :placeholder="t('prompts.allTypes')"
              clearable
              searchable
              class="min-w-[190px]"
              @change="onPromptTypeChange"
            />
          </div>

          <div v-if="availablePromptKeys.length > 0" class="flex items-center gap-2">
            <span class="text-xs text-gray-500 whitespace-nowrap">{{ t('prompts.key') }}</span>
            <AppSelect
              v-model="selectedPromptKey"
              :options="promptKeyOptions"
              :placeholder="label('allKeys')"
              clearable
              searchable
              class="min-w-[150px]"
              @change="onPromptKeyChange"
            />
          </div>

          <div class="ml-auto flex items-center gap-2">
            <button
              v-if="selectedJobId"
              class="px-3 py-1.5 rounded-lg text-xs border"
              :class="simplifiedView ? 'bg-blue-50 text-blue-700 border-blue-200' : 'border-gray-200 text-gray-500 hover:bg-gray-50'"
              @click="simplifiedView = !simplifiedView"
            >{{ simplifiedView ? label('simplifiedView') : label('fullView') }}</button>
            <button @click="clearFilters" class="px-3 py-2 border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50">
              {{ label('clearFilters') }}
            </button>
            <button @click="openCreateDialog" class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 flex items-center gap-1.5">
              <PhPlus class="text-base" /> {{ t('prompts.newPrompt') }}
            </button>
          </div>
        </div>

        <div class="flex items-center gap-2 flex-wrap text-xs text-gray-400">
          <span>{{ label('filterHint') }}</span>
          <span v-if="selectedPromptType" class="px-2 py-0.5 bg-blue-50 text-blue-700 border border-blue-100 rounded">{{ promptTypeLabel(selectedPromptType) }}</span>
          <span v-if="selectedTemplateId" class="px-2 py-0.5 bg-indigo-50 text-indigo-700 border border-indigo-100 rounded">{{ selectedTemplateId }}</span>
          <span v-if="selectedJobId" class="px-2 py-0.5 bg-purple-50 text-purple-700 border border-purple-100 rounded">{{ selectedJobId }}</span>
          <span v-if="selectedPromptKey" class="px-2 py-0.5 bg-gray-50 text-gray-700 border border-gray-100 rounded">{{ selectedPromptKey }}</span>
        </div>
      </div>

      <div v-if="promptStore.loading" class="bg-white rounded-xl border border-gray-100 p-10 text-center">
        <LoadingSpinner :text="t('common.loading')" />
      </div>

      <template v-else>
        <div v-if="!selectedAsset" class="space-y-4">
          <PromptAssetTable
            :title="label('businessPrompts')"
            :assets="businessAssets"
            :type-label="promptTypeLabel"
            :scope-label="scopeLabel"
            :job-label="assetJobLabel"
            @view="drillIntoAsset"
          />

          <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
            <button
              class="w-full px-5 py-4 flex items-center justify-between text-left hover:bg-gray-50"
              @click="showSystemPrompts = !showSystemPrompts"
            >
              <div>
                <h2 class="text-base font-bold text-gray-900">{{ label('systemPrompts') }}</h2>
                <p class="text-xs text-gray-400 mt-0.5">{{ label('systemPromptHint') }}</p>
              </div>
              <span class="text-xs text-gray-500">{{ showSystemPrompts ? label('collapse') : label('expand') }} · {{ systemAssets.length }}</span>
            </button>
            <PromptAssetTable
              v-if="showSystemPrompts"
              :assets="systemAssets"
              :type-label="promptTypeLabel"
              :scope-label="scopeLabel"
              :job-label="assetJobLabel"
              compact
              @view="drillIntoAsset"
            />
          </div>

          <div v-if="promptStore.jobPrompts.length === 0" class="bg-white rounded-xl border border-gray-100 p-12 text-center">
            <EmptyState :text="t('prompts.noPromptsForSelection')" />
          </div>
        </div>

        <div v-else class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div class="p-5 border-b border-gray-100 flex justify-between items-center gap-3">
            <div>
              <h2 class="text-base font-bold text-gray-900">{{ t('prompts.versions') }}</h2>
              <p class="text-xs text-gray-400 mt-0.5">
                <span>{{ promptTypeLabel(selectedAsset.prompt_type) }}</span>
                <span class="font-mono text-blue-600"> / {{ selectedAsset.prompt_key }}</span>
                <span v-if="selectedAsset.template_id" class="font-mono text-indigo-600"> / {{ selectedAsset.template_id }}</span>
                <span v-if="selectedAsset.job_id" class="font-mono text-purple-600"> / {{ selectedAsset.job_id }}</span>
              </p>
            </div>
            <button @click="backToAssets" class="px-3 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50">
              {{ t('common.back') }}
            </button>
          </div>
          <table class="w-full text-left">
            <thead>
              <tr class="bg-gray-50/50 text-gray-500 text-xs uppercase border-b">
                <th class="px-5 py-3">{{ t('prompts.version') }}</th>
                <th class="px-5 py-3">{{ t('prompts.status') }}</th>
                <th class="px-5 py-3">{{ t('prompts.createdAt') }}</th>
                <th class="px-5 py-3">{{ t('prompts.actions') }}</th>
              </tr>
            </thead>
            <tbody class="text-sm divide-y divide-gray-50">
              <tr v-if="currentVersions.length === 0">
                <td colspan="4" class="px-5 py-8 text-center"><EmptyState :text="t('common.noData')" /></td>
              </tr>
              <tr v-for="v in currentVersions" :key="versionKey(v)" class="hover:bg-gray-50/50 cursor-pointer" @click="previewVersion(v)">
                <td class="px-5 py-4 font-mono text-gray-800">{{ v.version }}</td>
                <td class="px-5 py-4">
                  <span :class="v.is_active ? 'bg-green-50 text-green-600 border-green-100' : 'bg-gray-50 text-gray-500 border-gray-100'" class="px-2 py-0.5 rounded text-xs font-medium border">
                    {{ v.is_active ? t('prompts.active') : t('prompts.inactive') }}
                  </span>
                  <span v-if="v.source" class="ml-2 px-2 py-0.5 rounded bg-gray-50 text-gray-500 text-xs border border-gray-100">{{ v.source }}</span>
                </td>
                <td class="px-5 py-4 text-gray-500">{{ formatDate(v.created_at) }}</td>
                <td class="px-5 py-4 space-x-1">
                  <button @click.stop="openEditVersion(v)" v-if="!v.read_only && selectedAsset.scope !== 'job_snapshot'" class="text-xs px-3 py-1 border border-blue-200 text-blue-600 rounded hover:bg-blue-50">{{ label('edit') }}</button>
                  <button @click.stop="activateVersion(v.version)" v-if="!v.is_active && !v.read_only && selectedAsset.scope !== 'job_snapshot'" class="text-xs px-3 py-1 border border-green-200 text-green-600 rounded hover:bg-green-50">{{ t('prompts.activate') }}</button>
                  <button @click.stop="rollbackVersion(v.version)" v-if="!v.read_only && selectedAsset.scope !== 'job_snapshot'" class="text-xs px-3 py-1 border border-gray-200 rounded hover:bg-gray-50">{{ t('prompts.rollback') }}</button>
                  <span v-if="v.read_only || selectedAsset.scope === 'job_snapshot'" class="text-xs text-gray-400">{{ t('prompts.snapshot') }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="previewContent" class="bg-white rounded-xl border border-gray-100 p-6 shadow-sm">
          <div class="flex items-center justify-between mb-3">
            <h3 class="font-bold text-gray-900">{{ previewTitle }}</h3>
            <button @click="previewContent = ''; previewTitle = ''" class="text-xs text-gray-400 hover:text-gray-600">x</button>
          </div>
          <pre class="bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm font-mono text-gray-700 whitespace-pre-wrap overflow-x-auto max-h-96 overflow-y-auto">{{ previewContent }}</pre>
        </div>
      </template>

      <div v-if="showEditDialog" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="closeEditDialog"></div>
        <div class="relative bg-white rounded-xl shadow-xl w-[min(1440px,calc(100vw-32px))] h-[calc(100vh-32px)] z-10 flex flex-col overflow-hidden">
          <div class="px-6 py-4 border-b border-gray-100 flex items-start justify-between gap-4">
            <div class="min-w-0">
              <h3 class="text-lg font-bold text-gray-900">{{ label('editPrompt') }}</h3>
              <p class="text-xs text-gray-400 mt-1 truncate">
                {{ selectedAsset?.template_id || '--' }}
                <template v-if="selectedAsset?.job_id"> / {{ selectedAsset.job_id }}</template>
                / {{ selectedAsset?.prompt_type }} / {{ selectedAsset?.prompt_key || 'default' }} / {{ editingVersion?.version }}
              </p>
            </div>
            <div class="flex items-center gap-2">
              <button
                class="px-3 py-1.5 rounded-lg text-xs border"
                :class="editViewMode === 'text' ? 'bg-blue-50 text-blue-700 border-blue-200' : 'border-gray-200 text-gray-500 hover:bg-gray-50'"
                @click="editViewMode = 'text'"
              >{{ label('textMode') }}</button>
              <button
                class="px-3 py-1.5 rounded-lg text-xs border"
                :class="editViewMode === 'markdown' ? 'bg-blue-50 text-blue-700 border-blue-200' : 'border-gray-200 text-gray-500 hover:bg-gray-50'"
                @click="editViewMode = 'markdown'"
              >{{ label('markdownMode') }}</button>
              <button @click="closeEditDialog" class="px-3 py-1.5 border border-gray-200 rounded-lg text-xs text-gray-600 hover:bg-gray-50">x</button>
            </div>
          </div>

          <div class="px-6 py-3 border-b border-gray-100 grid grid-cols-1 lg:grid-cols-[1fr_1fr_auto] gap-3 items-end">
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ label('editTitle') }}</label>
              <input v-model="editDraft.title" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" />
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ label('editNote') }}</label>
              <input v-model="editDraft.note" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" />
            </div>
            <label class="flex items-center gap-2 h-10 cursor-pointer text-sm text-gray-700">
              <input v-model="editDraft.activate" type="checkbox" class="rounded border-gray-300" />
              <span>{{ label('activeAfterEdit') }}</span>
            </label>
          </div>

          <div class="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-2">
            <div class="border-r border-gray-100 min-h-0 flex flex-col">
              <div class="px-5 py-3 border-b border-gray-100 bg-gray-50/60">
                <h4 class="text-sm font-bold text-gray-900">{{ label('before') }}</h4>
              </div>
              <div class="flex-1 overflow-auto p-5">
                <div v-if="editViewMode === 'markdown'" class="prose-lite" v-html="renderMarkdown(originalEditContent)"></div>
                <pre v-else class="text-sm font-mono whitespace-pre-wrap leading-6">
<template v-for="(line, index) in diffLines" :key="`before:${index}`"><span v-if="line.type === 'change'" :class="diffClass('equal', 'before')"><template v-for="(part, pIndex) in line.beforeParts" :key="`before:${index}:${pIndex}`"><span :class="diffPartClass(part.type, 'before')">{{ part.text }}</span></template></span><span v-else-if="line.type !== 'add'" :class="diffClass(line.type, 'before')">{{ line.text || ' ' }}</span><br v-if="line.type !== 'add'" /></template></pre>
              </div>
            </div>

            <div class="min-h-0 flex flex-col">
              <div class="px-5 py-3 border-b border-gray-100 bg-gray-50/60 flex items-center justify-between">
                <h4 class="text-sm font-bold text-gray-900">{{ label('after') }}</h4>
                <span v-if="editViewMode === 'text'" class="text-xs text-gray-400">{{ label('diffPreview') }}</span>
              </div>
              <div class="flex-1 overflow-auto p-5 space-y-4">
                <template v-if="editViewMode === 'markdown'">
                  <textarea v-model="editDraft.content" rows="8" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary font-mono" />
                  <div class="prose-lite border border-gray-100 rounded-lg p-4 bg-gray-50/40" v-html="renderMarkdown(editDraft.content)"></div>
                </template>
                <template v-else>
                  <textarea v-model="editDraft.content" class="w-full min-h-[260px] border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary font-mono" />
                  <div v-if="!hasDiff" class="border border-gray-100 rounded-lg p-4 bg-gray-50/30 text-sm text-gray-400 text-center py-8">{{ label('noChange') }}</div>
                  <pre v-else class="text-sm font-mono whitespace-pre-wrap leading-6 border border-gray-100 rounded-lg p-4 bg-gray-50/30">
<template v-for="(line, index) in diffLines" :key="`after:${index}`"><span v-if="line.type === 'change'" :class="diffClass('equal', 'after')"><template v-for="(part, pIndex) in line.afterParts" :key="`after:${index}:${pIndex}`"><span :class="diffPartClass(part.type, 'after')">{{ part.text }}</span></template></span><span v-else-if="line.type !== 'del'" :class="diffClass(line.type, 'after')">{{ line.text || ' ' }}</span><br v-if="line.type !== 'del'" /></template></pre>
                </template>
              </div>
            </div>
          </div>

          <div class="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
            <button @click="closeEditDialog" class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50">{{ t('common.cancel') }}</button>
            <button @click="saveEditedPrompt" :disabled="editSaving" class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {{ editSaving ? label('saving') : label('saveEdit') }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="showCreateDialog" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/50" @click="showCreateDialog = false"></div>
        <div class="relative bg-white rounded-xl shadow-xl p-6 w-full max-w-lg mx-4 z-10 max-h-[90vh] overflow-y-auto">
          <h3 class="text-lg font-bold text-gray-900 mb-4">{{ t('prompts.newPrompt') }}</h3>
          <div class="space-y-4">
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ t('template.select') }} <span class="text-red-400">*</span></label>
              <AppSelect
                v-model="newPrompt.template_id"
                :options="newPromptTemplateOptions"
                :placeholder="t('prompts.selectTemplate')"
                searchable
                @change="newPrompt.job_id = ''"
              />
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">Job <span class="text-gray-400">({{ t('common.optional') }})</span></label>
              <AppSelect
                v-model="newPrompt.job_id"
                :options="newPromptJobOptions"
                :placeholder="label('selectJob')"
                :disabled="!newPrompt.template_id"
                clearable
                searchable
              />
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ t('prompts.promptType') }} <span class="text-red-400">*</span></label>
              <AppSelect
                v-model="newPrompt.prompt_type"
                :options="promptTypeOptions"
                :placeholder="t('prompts.selectType')"
                searchable
              />
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ t('prompts.promptKey') }}</label>
              <input v-model="newPrompt.prompt_key" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" placeholder="default" />
              <p class="text-xs text-gray-400 mt-1">{{ t('prompts.autoKeyHint') }}</p>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ t('prompts.title_field') }} <span class="text-red-400">*</span></label>
              <input v-model="newPrompt.title" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" placeholder="Enter a title..." />
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ t('prompts.content') }} <span class="text-red-400">*</span></label>
              <textarea v-model="newPrompt.content" rows="6" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary font-mono" :placeholder="t('prompts.contentPlaceholder')"></textarea>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">{{ t('prompts.note') }} <span class="text-gray-400">({{ t('common.optional') }})</span></label>
              <input v-model="newPrompt.note" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" :placeholder="t('prompts.notePlaceholder')" />
            </div>
            <label class="flex items-center gap-2 cursor-pointer">
              <input v-model="newPrompt.activate" type="checkbox" class="rounded border-gray-300" />
              <span class="text-sm text-gray-700">{{ t('prompts.setActive') }}</span>
            </label>
          </div>
          <div class="flex justify-end gap-3 mt-6">
            <button @click="showCreateDialog = false" class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50">{{ t('prompts.cancel') }}</button>
            <button @click="createNewPrompt" :disabled="creating" class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {{ creating ? t('prompts.creating') : t('prompts.createPrompt') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import AppSelect from '@/components/common/AppSelect.vue'
import { useTemplateStore } from '@/stores/templates'
import { usePromptStore } from '@/stores/prompts'
import { useSeriesStore } from '@/stores/series'
import { useToast } from '@/composables/useToast'
import { formatDate } from '@/utils/format'
import { getJob, getJobs } from '@/api/jobs'
import { clearRecentJob, getRecentJob, setRecentJob } from '@/composables/useRecentJob'
import { PhPlus } from '@phosphor-icons/vue'
import { useI18n } from 'vue-i18n'

const PromptAssetTable = defineComponent({
  name: 'PromptAssetTable',
  props: {
    title: { type: String, default: '' },
    assets: { type: Array, default: () => [] },
    typeLabel: { type: Function, required: true },
    scopeLabel: { type: Function, required: true },
    jobLabel: { type: Function, required: true },
    compact: { type: Boolean, default: false },
  },
  emits: ['view'],
  setup(props, { emit }) {
    return () => h('div', { class: props.compact ? '' : 'bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden' }, [
      props.title ? h('div', { class: 'p-5 border-b border-gray-100' }, [
        h('h2', { class: 'text-base font-bold text-gray-900' }, props.title),
      ]) : null,
      props.assets.length === 0
        ? h('div', { class: 'p-8 text-center text-sm text-gray-400' }, 'No prompts for this group')
        : h('table', { class: 'w-full text-left' }, [
          h('thead', [
            h('tr', { class: 'bg-gray-50/50 text-gray-500 text-xs uppercase border-b' }, [
              h('th', { class: 'px-5 py-3' }, 'Scope'),
              h('th', { class: 'px-5 py-3' }, 'Type'),
              h('th', { class: 'px-5 py-3' }, 'Key'),
              h('th', { class: 'px-5 py-3' }, 'Template / Job'),
              h('th', { class: 'px-5 py-3' }, 'Active'),
              h('th', { class: 'px-5 py-3' }, 'Versions'),
              h('th', { class: 'px-5 py-3' }, 'Actions'),
            ]),
          ]),
          h('tbody', { class: 'text-sm divide-y divide-gray-50' }, props.assets.map((asset) =>
            h('tr', { key: `${asset.scope}:${asset.template_id}:${asset.job_id || ''}:${asset.prompt_type}:${asset.prompt_key}`, class: 'hover:bg-gray-50/50' }, [
              h('td', { class: 'px-5 py-4' }, [
                h('span', { class: 'px-2 py-0.5 bg-gray-50 text-gray-600 rounded text-xs font-mono' }, props.scopeLabel(asset.scope)),
              ]),
              h('td', { class: 'px-5 py-4 text-xs text-gray-700' }, props.typeLabel(asset.prompt_type)),
              h('td', { class: 'px-5 py-4' }, [
                h('span', { class: 'px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-xs font-mono' }, asset.prompt_key || 'default'),
              ]),
              h('td', { class: 'px-5 py-4 text-xs text-gray-500' }, [
                h('div', { class: 'font-mono text-gray-700' }, asset.template_id || '--'),
                asset.job_id ? h('div', { class: 'text-purple-600 mt-0.5' }, props.jobLabel(asset)) : null,
              ]),
              h('td', { class: 'px-5 py-4 font-mono text-gray-800' }, asset.active_version || '--'),
              h('td', { class: 'px-5 py-4 text-gray-500' }, String(asset.versions?.length || 0)),
              h('td', { class: 'px-5 py-4' }, [
                h('button', {
                  class: 'text-xs px-3 py-1 border border-primary text-primary rounded hover:bg-blue-50',
                  onClick: () => emit('view', asset),
                }, 'View Versions'),
              ]),
            ])
          )),
        ]),
    ])
  },
})

const route = useRoute()
const templateStore = useTemplateStore()
const promptStore = usePromptStore()
const seriesStore = useSeriesStore()
const toast = useToast()
const { t, locale } = useI18n()

const selectedSeriesId = ref('')
const selectedTemplateId = ref(route.query.template || '')
const selectedJobId = ref(route.query.job_id || '')
const selectedPromptType = ref(route.query.prompt_type || '')
const selectedPromptKey = ref('')
const selectedAsset = ref(null)
const showSystemPrompts = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)
const previewContent = ref('')
const previewTitle = ref('')
const localJobs = ref([])
const showEditDialog = ref(false)
const editingVersion = ref(null)
const editSaving = ref(false)
const editViewMode = ref('text')
const editDraft = ref({
  title: '',
  content: '',
  note: '',
  activate: true,
})

const newPrompt = ref({
  template_id: '',
  job_id: '',
  prompt_type: '',
  prompt_key: 'default',
  title: '',
  content: '',
  note: '',
  activate: true,
})

const text = {
  en: {
    clearFilters: 'Clear filters',
    selectJob: 'Select Job',
    allKeys: 'All keys',
    filterHint: 'Filters are optional. Select a type directly, then narrow by template, job, or key.',
    businessPrompts: 'Business Prompts',
    systemPrompts: 'Advanced / System Prompts',
    systemPromptHint: 'System and legacy prompts are kept for compatibility.',
    expand: 'Expand',
    collapse: 'Collapse',
    created: 'Prompt created',
    edit: 'Edit',
    editPrompt: 'Edit Prompt',
    before: 'Before',
    after: 'After',
    textMode: 'Text diff',
    markdownMode: 'Markdown',
    editTitle: 'New version title',
    editNote: 'Edit note',
    activeAfterEdit: 'Set new version active',
    diffPreview: 'Diff preview',
    saveEdit: 'Save as new version',
    saving: 'Saving...',
    editCreated: 'Edited prompt version created',
    editFailed: 'Failed to edit prompt',
    noChange: 'No changes — content is identical to the original.',
    simplifiedView: 'Simplified',
    fullView: 'Full view',
  },
  zh: {
    clearFilters: '清除筛选',
    selectJob: '选择 Job',
    allKeys: '全部 Key',
    filterHint: '筛选条件都是可选的。可以直接选择类型，再按模板、Job 或 Key 缩小范围。',
    businessPrompts: '业务提示词',
    systemPrompts: '高级 / 系统提示词',
    systemPromptHint: '系统提示词和历史兼容提示词仍然保留。',
    expand: '展开',
    collapse: '收起',
    created: '提示词已创建',
    edit: '修改',
    editPrompt: '修改提示词',
    before: '修改前',
    after: '修改后',
    textMode: '文本对比',
    markdownMode: 'Markdown',
    editTitle: '新版本标题',
    editNote: '修改备注',
    activeAfterEdit: '设为 active',
    diffPreview: '差异预览',
    saveEdit: '保存为新版本',
    saving: '保存中...',
    editCreated: '已创建修改后的新版本',
    editFailed: '修改提示词失败',
    noChange: '内容无变化，与原版本相同。',
    simplifiedView: '简洁视图',
    fullView: '完整视图',
  },
}

const PROMPT_TYPE_META = [
  { key: 't2v', group: 'business', zh: '文生视频提示词', en: 'T2V Prompt' },
  { key: 'first_frame_image', group: 'business', zh: '首帧图提示词', en: 'First Frame Prompt' },
  { key: 'i2v', group: 'business', zh: '图生视频提示词', en: 'I2V Prompt' },
  { key: 'r2v_flash', group: 'business', zh: '参考图生视频提示词', en: 'R2V Flash Prompt' },
  { key: 'i2i', group: 'business', zh: '图生图测试提示词', en: 'I2I Prompt' },
  { key: 'negative', group: 'business', zh: '负向提示词', en: 'Negative Prompt' },
  { key: 'video_understanding_system', group: 'system', zh: '视频理解系统提示词', en: 'Video Understanding System' },
  { key: 'video_understanding_user', group: 'system', zh: '视频理解用户提示词', en: 'Video Understanding User' },
  { key: 'prompt_rewrite_system', group: 'system', zh: '提示词改写系统提示词', en: 'Prompt Rewrite System' },
  { key: 'prompt_rewrite_user', group: 'system', zh: '提示词改写用户提示词', en: 'Prompt Rewrite User' },
  { key: 'reverse_prompts4r2v_system', group: 'system', zh: 'R2V 反推系统提示词', en: 'R2V Reverse System' },
  { key: 'rewrite_t2i_to_i2i_system', group: 'system', zh: 'T2I 转 I2I 系统提示词', en: 'Rewrite T2I to I2I System' },
  { key: 'failure_agent_system', group: 'system', zh: '错误处理系统提示词', en: 'Failure Agent System' },
  { key: 'failure_agent_user', group: 'system', zh: '错误处理用户提示词', en: 'Failure Agent User' },
]

const metaByType = computed(() => new Map(PROMPT_TYPE_META.map((item) => [item.key, item])))
const seriesOptions = computed(() => seriesStore.seriesList.map((s) => ({ label: s.name, value: s.series_id })))
const templatesForSeries = computed(() => {
  const list = selectedSeriesId.value
    ? templateStore.templates.filter((item) => (item.series_id || item.series || 'default') === selectedSeriesId.value)
    : templateStore.templates
  return list.map((item) => ({ label: item.name || item.template_id, value: item.template_id || item.id }))
})
const newPromptTemplateOptions = computed(() =>
  templateStore.templates.map((item) => ({ label: item.name || item.template_id, value: item.template_id || item.id }))
)
const jobOptions = computed(() => {
  let list = localJobs.value
  if (selectedSeriesId.value) {
    const allowedTemplates = new Set(
      templateStore.templates
        .filter((item) => (item.series_id || item.series || 'default') === selectedSeriesId.value)
        .map((item) => item.template_id || item.id)
    )
    list = list.filter((job) => allowedTemplates.has(job.template_id))
  }
  if (selectedTemplateId.value) list = list.filter((job) => job.template_id === selectedTemplateId.value)
  return list.map((job) => ({ label: jobOptionLabel(job), value: job.job_id }))
})
const newPromptJobOptions = computed(() =>
  localJobs.value
    .filter((job) => job.template_id === newPrompt.value.template_id)
    .map((job) => ({ label: jobOptionLabel(job), value: job.job_id }))
)
const promptTypeOptions = computed(() => PROMPT_TYPE_META.map((item) => ({ label: promptTypeLabel(item.key), value: item.key })))
const promptKeyOptions = computed(() => availablePromptKeys.value.map((key) => ({ label: key, value: key })))
const availablePromptKeys = computed(() => {
  if (!selectedPromptType.value) return []
  return [...new Set(promptStore.jobPrompts
    .filter((asset) => asset.prompt_type === selectedPromptType.value)
    .map((asset) => asset.prompt_key || 'default'))]
})
const simplifiedView = ref(true)

function deduplicatedAssets(assets) {
  if (!simplifiedView.value || !selectedJobId.value) return assets
  const PRIORITY = { job: 3, template: 2, job_snapshot: 1 }
  const map = new Map()
  for (const asset of assets) {
    const key = `${asset.prompt_type}:${asset.prompt_key || 'default'}`
    const existing = map.get(key)
    if (!existing || (PRIORITY[asset.scope] || 0) > (PRIORITY[existing.scope] || 0)) {
      map.set(key, asset)
    }
  }
  return Array.from(map.values())
}

const businessAssets = computed(() => sortedAssets(deduplicatedAssets(promptStore.jobPrompts.filter((asset) => typeGroup(asset.prompt_type) !== 'system'))))
const systemAssets = computed(() => sortedAssets(deduplicatedAssets(promptStore.jobPrompts.filter((asset) => typeGroup(asset.prompt_type) === 'system'))))
const currentVersions = computed(() => selectedAsset.value?.versions || [])
const originalEditContent = computed(() => editingVersion.value?.content || editingVersion.value?.content_snapshot || '')
const diffLines = computed(() => buildLineDiff(originalEditContent.value, editDraft.value.content || ''))
const hasDiff = computed(() => diffLines.value.some((l) => l.type !== 'equal'))

function label(key) {
  const lang = String(locale.value || 'en').startsWith('zh') ? 'zh' : 'en'
  return text[lang][key] || text.en[key] || key
}

function promptTypeLabel(key) {
  const lang = String(locale.value || 'en').startsWith('zh') ? 'zh' : 'en'
  const meta = metaByType.value.get(key)
  if (!meta) return key
  return `${meta[lang]} (${key})`
}

function typeGroup(key) {
  return metaByType.value.get(key)?.group || (String(key).includes('system') || String(key).includes('user') ? 'system' : 'business')
}

function scopeLabel(scope) {
  const labels = {
    template: 'Template',
    job: 'Job',
    job_snapshot: 'Snapshot',
  }
  return labels[scope] || scope || 'Template'
}

function jobOptionLabel(job) {
  if (!job) return ''
  return job.job_name ? `${job.job_name} (${job.job_id})` : job.job_id
}

function assetJobLabel(asset) {
  const job = localJobs.value.find((item) => item.job_id === asset.job_id)
  return job ? jobOptionLabel(job) : asset.job_id
}

function sortedAssets(list) {
  const order = new Map(PROMPT_TYPE_META.map((item, index) => [item.key, index]))
  return [...list].sort((a, b) => {
    const ao = order.get(a.prompt_type) ?? 999
    const bo = order.get(b.prompt_type) ?? 999
    if (ao !== bo) return ao - bo
    return `${a.template_id || ''}:${a.job_id || ''}:${a.prompt_key || ''}`.localeCompare(`${b.template_id || ''}:${b.job_id || ''}:${b.prompt_key || ''}`)
  })
}

function buildLineDiff(before, after) {
  const a = splitLines(before)
  const b = splitLines(after)
  const base = lcsDiff(a, b, (left, right) => left === right)
  if ((String(before || '').length + String(after || '').length) > 60000) return base
  return refineChangedLines(base)
}

function lcsDiff(a, b, equals) {
  const rows = a.length + 1
  const cols = b.length + 1
  const dp = Array.from({ length: rows }, () => Array(cols).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = equals(a[i], b[j])
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const result = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (equals(a[i], b[j])) {
      result.push({ type: 'equal', text: a[i] })
      i += 1
      j += 1
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: 'del', text: a[i] })
      i += 1
    } else {
      result.push({ type: 'add', text: b[j] })
      j += 1
    }
  }
  while (i < a.length) {
    result.push({ type: 'del', text: a[i] })
    i += 1
  }
  while (j < b.length) {
    result.push({ type: 'add', text: b[j] })
    j += 1
  }
  return result
}

function refineChangedLines(lines) {
  const result = []
  let i = 0
  while (i < lines.length) {
    if (lines[i]?.type !== 'del') {
      result.push(lines[i])
      i += 1
      continue
    }
    const dels = []
    const adds = []
    while (lines[i]?.type === 'del') {
      dels.push(lines[i])
      i += 1
    }
    while (lines[i]?.type === 'add') {
      adds.push(lines[i])
      i += 1
    }
    const pairs = Math.min(dels.length, adds.length)
    for (let index = 0; index < pairs; index += 1) {
      result.push(buildChangedLine(dels[index].text, adds[index].text))
    }
    for (let index = pairs; index < dels.length; index += 1) result.push(dels[index])
    for (let index = pairs; index < adds.length; index += 1) result.push(adds[index])
  }
  return result
}

function buildChangedLine(before, after) {
  const segsB = splitIntoSegments(before)
  const segsA = splitIntoSegments(after)

  // Fast path: both sides are a single short segment — go straight to token diff
  if (segsB.length === 1 && segsA.length === 1) {
    const r = buildTokenDiff(before, after)
    return { type: 'change', beforeParts: r.beforeParts, afterParts: r.afterParts }
  }

  // Multi-segment path: segment-level LCS (exact match), then token diff per changed segment pair
  const segDiff = lcsDiff(segsB, segsA, (a, b) => a === b)
  const beforeParts = []
  const afterParts = []
  let i = 0
  while (i < segDiff.length) {
    if (segDiff[i].type === 'equal') {
      beforeParts.push({ type: 'equal', text: segDiff[i].text })
      afterParts.push({ type: 'equal', text: segDiff[i].text })
      i += 1
      continue
    }
    const dels = []
    const adds = []
    while (i < segDiff.length && segDiff[i].type === 'del') { dels.push(segDiff[i].text); i += 1 }
    while (i < segDiff.length && segDiff[i].type === 'add') { adds.push(segDiff[i].text); i += 1 }
    const pairs = Math.min(dels.length, adds.length)
    for (let p = 0; p < pairs; p++) {
      const r = buildTokenDiff(dels[p], adds[p])
      beforeParts.push(...r.beforeParts)
      afterParts.push(...r.afterParts)
    }
    for (let p = pairs; p < dels.length; p++) beforeParts.push({ type: 'del', text: dels[p] })
    for (let p = pairs; p < adds.length; p++) afterParts.push({ type: 'add', text: adds[p] })
  }
  return { type: 'change', beforeParts: mergeDiffParts(beforeParts), afterParts: mergeDiffParts(afterParts) }
}

function tokenizeDiffText(value) {
  const tokens = []
  const source = String(value || '')
  const pattern = /[\u4e00-\u9fff]|[A-Za-z0-9_]+|\s+|./gu
  for (const match of source.matchAll(pattern)) tokens.push(match[0])
  return tokens
}

function buildTokenDiff(before, after) {
  const bt = tokenizeDiffText(before)
  const at = tokenizeDiffText(after)
  if (bt.length * at.length > 200000) {
    return { beforeParts: [{ type: 'del', text: before }], afterParts: [{ type: 'add', text: after }] }
  }
  const d = lcsDiff(bt, at, (l, r) => l === r)
  return {
    beforeParts: mergeDiffParts(d.filter((p) => p.type !== 'add')),
    afterParts: mergeDiffParts(d.filter((p) => p.type !== 'del')),
  }
}

function splitIntoSegments(text) {
  if (!text) return ['']
  const result = []
  let current = ''
  for (const ch of String(text)) {
    current += ch
    if (/[\u3002\uff01\uff1f!?\n]/.test(ch)) {
      result.push(current)
      current = ''
    } else if (current.length > 60 && /[\uff0c,\u3001\uff1b;]/.test(ch)) {
      result.push(current)
      current = ''
    }
  }
  if (current) result.push(current)
  return result.length ? result : [String(text)]
}

function mergeDiffParts(parts) {
  const result = []
  parts.forEach((part) => {
    if (!part.text) return
    const current = result[result.length - 1]
    if (current?.type === part.type) current.text += part.text
    else result.push({ type: part.type, text: part.text })
  })
  return result.length ? result : [{ type: 'equal', text: '' }]
}

function splitLines(value) {
  if (!value) return []
  return String(value).replace(/\r\n/g, '\n').split('\n')
}

function diffClass(type, side) {
  if (type === 'add') return 'block bg-emerald-50/70 text-emerald-700 px-2 rounded'
  if (type === 'del') return 'block bg-rose-50/70 text-rose-700 px-2 rounded line-through decoration-rose-400'
  return 'block text-gray-700 px-2'
}

function diffPartClass(type, side) {
  if (type === 'add') return side === 'after' ? 'bg-emerald-100 text-emerald-700 rounded px-0.5' : ''
  if (type === 'del') return side === 'before' ? 'bg-rose-100 text-rose-700 line-through decoration-rose-400 rounded px-0.5' : ''
  return ''
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
    html.push(`<pre class="bg-gray-900 text-gray-50 rounded-lg p-3 overflow-auto text-xs"><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`)
    inCode = false
    codeLines = []
  }

  for (const rawLine of lines) {
    const line = rawLine || ''
    if (line.trim().startsWith('```')) {
      if (inCode) {
        flushCode()
      } else {
        flushList()
        inCode = true
        codeLines = []
      }
      continue
    }
    if (inCode) {
      codeLines.push(line)
      continue
    }
    const trimmed = line.trim()
    if (!trimmed) {
      flushList()
      html.push('<div class="h-3"></div>')
      continue
    }
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      flushList()
      const level = heading[1].length
      const cls = level === 1 ? 'text-xl' : level === 2 ? 'text-lg' : 'text-base'
      html.push(`<h${level} class="${cls} font-bold text-gray-900 mt-3 mb-2">${renderInline(heading[2])}</h${level}>`)
      continue
    }
    const list = trimmed.match(/^[-*]\s+(.+)$/)
    if (list) {
      listItems.push(`<li>${renderInline(list[1])}</li>`)
      continue
    }
    flushList()
    html.push(`<p class="text-sm leading-6 text-gray-700">${renderInline(trimmed)}</p>`)
  }
  flushCode()
  flushList()
  return html.join('\n')
}

function renderInline(value) {
  return escapeHtml(value)
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-gray-900">$1</strong>')
    .replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 rounded bg-gray-100 text-gray-800">$1</code>')
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function queryParams() {
  return {
    ...(selectedSeriesId.value ? { series_id: selectedSeriesId.value } : {}),
    ...(selectedTemplateId.value ? { template_id: selectedTemplateId.value } : {}),
    ...(selectedJobId.value ? { job_id: selectedJobId.value } : {}),
    ...(selectedPromptType.value ? { prompt_type: selectedPromptType.value } : {}),
    ...(selectedPromptKey.value ? { prompt_key: selectedPromptKey.value } : {}),
  }
}

async function loadPrompts() {
  selectedAsset.value = null
  previewContent.value = ''
  await promptStore.fetchGlobalPrompts(queryParams())
}

async function loadLocalJobs() {
  try {
    const data = await getJobs({ perPage: 500 })
    localJobs.value = Array.isArray(data) ? data : (data.jobs || [])
  } catch {
    localJobs.value = []
  }
}

async function onSeriesChange() {
  selectedTemplateId.value = ''
  selectedJobId.value = ''
  selectedPromptKey.value = ''
  await loadPrompts()
}

async function onTemplateChange() {
  selectedJobId.value = ''
  selectedPromptKey.value = ''
  await loadPrompts()
}

async function onJobChange() {
  if (selectedJobId.value) {
    setRecentJob(selectedJobId.value)
  }
  selectedPromptKey.value = ''
  await loadPrompts()
}

async function onPromptTypeChange() {
  selectedPromptKey.value = ''
  await loadPrompts()
}

async function onPromptKeyChange() {
  await loadPrompts()
}

async function clearFilters() {
  selectedSeriesId.value = ''
  selectedTemplateId.value = ''
  selectedJobId.value = ''
  selectedPromptType.value = ''
  selectedPromptKey.value = ''
  selectedAsset.value = null
  await loadPrompts()
}

function drillIntoAsset(asset) {
  selectedAsset.value = asset
  selectedPromptType.value = asset.prompt_type
  selectedPromptKey.value = asset.prompt_key || 'default'
}

function backToAssets() {
  selectedAsset.value = null
  previewContent.value = ''
}

function versionKey(version) {
  return `${selectedAsset.value?.scope}:${selectedAsset.value?.template_id}:${selectedAsset.value?.job_id || ''}:${selectedAsset.value?.prompt_type}:${selectedAsset.value?.prompt_key}:${version.version}:${version.id || ''}`
}

function previewVersion(version) {
  previewContent.value = version.content || version.content_snapshot || ''
  previewTitle.value = `${version.version}${version.is_active ? ` (${t('prompts.active')})` : ''}`
}

async function activateVersion(version) {
  if (!selectedAsset.value?.template_id) return
  try {
    const extra = { prompt_key: selectedAsset.value.prompt_key || 'default' }
    if (selectedAsset.value.scope === 'job' && selectedAsset.value.job_id) extra.job_id = selectedAsset.value.job_id
    await promptStore.activate(selectedAsset.value.template_id, selectedAsset.value.prompt_type, version, extra)
    toast.success(t('prompts.versionActivated', { version }))
    await refreshSelectedAsset()
  } catch {
    toast.error(t('prompts.activateFailed'))
  }
}

async function rollbackVersion(version) {
  if (!selectedAsset.value?.template_id) return
  try {
    const extra = { prompt_key: selectedAsset.value.prompt_key || 'default' }
    if (selectedAsset.value.scope === 'job' && selectedAsset.value.job_id) extra.job_id = selectedAsset.value.job_id
    await promptStore.rollback(selectedAsset.value.template_id, selectedAsset.value.prompt_type, version, extra)
    toast.success(t('prompts.rollbackSuccess', { version }))
    await refreshSelectedAsset()
  } catch {
    toast.error(t('prompts.rollbackFailed'))
  }
}

function openEditVersion(version) {
  if (!selectedAsset.value || version.read_only || selectedAsset.value.scope === 'job_snapshot') return
  editingVersion.value = version
  editDraft.value = {
    title: `${selectedAsset.value.prompt_type} edited from ${version.version}`,
    content: version.content || version.content_snapshot || '',
    note: '',
    activate: true,
  }
  editViewMode.value = 'text'
  showEditDialog.value = true
}

function closeEditDialog() {
  showEditDialog.value = false
  editingVersion.value = null
  editSaving.value = false
}

async function saveEditedPrompt() {
  if (!selectedAsset.value || !editingVersion.value) return
  if (!String(editDraft.value.content || '').trim()) {
    toast.error(t('prompts.contentRequired'))
    return
  }
  editSaving.value = true
  try {
    const payload = {
      prompt_key: selectedAsset.value.prompt_key || 'default',
      ...(selectedAsset.value.scope === 'job' && selectedAsset.value.job_id ? { job_id: selectedAsset.value.job_id } : {}),
      title: editDraft.value.title || `${selectedAsset.value.prompt_type} edited from ${editingVersion.value.version}`,
      content: editDraft.value.content,
      content_format: 'markdown',
      note: editDraft.value.note || undefined,
      activate: editDraft.value.activate,
    }
    await promptStore.editVersion(
      selectedAsset.value.template_id,
      selectedAsset.value.prompt_type,
      editingVersion.value.version,
      payload
    )
    toast.success(label('editCreated'))
    closeEditDialog()
    await refreshSelectedAsset()
  } catch (error) {
    toast.error(error?.response?.data?.error?.message || label('editFailed'))
  } finally {
    editSaving.value = false
  }
}

async function refreshSelectedAsset() {
  const previous = selectedAsset.value
  await promptStore.fetchGlobalPrompts(queryParams())
  if (!previous) return
  selectedAsset.value = promptStore.jobPrompts.find((asset) =>
    asset.scope === previous.scope
    && asset.template_id === previous.template_id
    && (asset.job_id || '') === (previous.job_id || '')
    && asset.prompt_type === previous.prompt_type
    && (asset.prompt_key || 'default') === (previous.prompt_key || 'default')
  ) || null
}

function openCreateDialog() {
  newPrompt.value.template_id = selectedTemplateId.value || selectedAsset.value?.template_id || ''
  newPrompt.value.job_id = selectedJobId.value || selectedAsset.value?.job_id || ''
  newPrompt.value.prompt_type = selectedPromptType.value || selectedAsset.value?.prompt_type || ''
  newPrompt.value.prompt_key = selectedPromptKey.value || selectedAsset.value?.prompt_key || 'default'
  showCreateDialog.value = true
}

function autoPromptKey(type) {
  const ts = new Date().toISOString().replace(/\D/g, '').slice(4, 12)
  return `manual_${type || 'prompt'}_${ts}`
}

async function createNewPrompt() {
  if (!newPrompt.value.template_id || !newPrompt.value.prompt_type) {
    toast.error(t('prompts.templateTypeRequired'))
    return
  }
  if (!newPrompt.value.title.trim()) {
    toast.error(t('prompts.titleRequired'))
    return
  }
  if (!newPrompt.value.content.trim()) {
    toast.error(t('prompts.contentRequired'))
    return
  }
  const key = newPrompt.value.prompt_key.trim() || autoPromptKey(newPrompt.value.prompt_type)
  creating.value = true
  try {
    await promptStore.createVersion(newPrompt.value.template_id, {
      prompt_type: newPrompt.value.prompt_type,
      prompt_key: key,
      ...(newPrompt.value.job_id ? { job_id: newPrompt.value.job_id } : {}),
      title: newPrompt.value.title,
      content: newPrompt.value.content,
      content_format: 'markdown',
      note: newPrompt.value.note || undefined,
      activate: newPrompt.value.activate,
      source: 'manual',
    })
    toast.success(label('created'))
    showCreateDialog.value = false
    newPrompt.value = { template_id: '', job_id: '', prompt_type: '', prompt_key: 'default', title: '', content: '', note: '', activate: true }
    await loadPrompts()
  } catch (error) {
    toast.error(error?.response?.data?.error?.message || t('prompts.createFailed'))
  } finally {
    creating.value = false
  }
}

function hasExplicitRouteFilter() {
  return Boolean(
    route.query.series_id
    || route.query.template
    || route.query.template_id
    || route.query.job_id
    || route.query.prompt_type
    || route.query.prompt_key
  )
}

async function applyRecentJobFilter() {
  if (hasExplicitRouteFilter()) return
  const recentJobId = getRecentJob()
  if (!recentJobId) return
  let recentJob = localJobs.value.find((item) => item.job_id === recentJobId)
  if (!recentJob) {
    try {
      recentJob = await getJob(recentJobId)
    } catch {
      clearRecentJob(recentJobId)
      return
    }
  }
  if (!recentJob?.job_id) {
    clearRecentJob(recentJobId)
    return
  }
  selectedJobId.value = recentJob.job_id
  selectedTemplateId.value = recentJob.template_id || ''
  const template = templateStore.templates.find((item) => item.template_id === selectedTemplateId.value)
  selectedSeriesId.value = template?.series_id || template?.series || recentJob.series_id || ''
}

onMounted(async () => {
  await Promise.all([
    templateStore.fetchTemplates(),
    seriesStore.fetchSeries(),
    loadLocalJobs(),
  ])
  await applyRecentJobFilter()
  await loadPrompts()
})
</script>
