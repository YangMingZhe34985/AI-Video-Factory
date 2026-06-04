<template>
  <DefaultLayout :title="t('models.title')" :subtitle="t('models.subtitle')">
    <div class="max-w-7xl mx-auto space-y-6">
      <div class="flex items-center gap-4 bg-white p-4 rounded-xl border border-gray-100 shadow-sm">
        <SearchInput v-model="search" :placeholder="t('models.searchPlaceholder')" class="w-64" />
        <button @click="store.fetchModels()" class="p-2 bg-white border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50">
          <PhArrowsClockwise class="text-lg" />
        </button>
      </div>

      <LoadingSpinner v-if="store.loading" :text="t('models.loading')" />

      <div v-else class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <table class="w-full text-left">
          <thead>
            <tr class="bg-gray-50/50 text-gray-500 text-xs uppercase border-b">
              <th class="px-5 py-3">{{ t('models.modelName') }}</th>
              <th class="px-5 py-3">{{ t('models.modelKey') }}</th>
              <th class="px-5 py-3">{{ t('models.provider') }}</th>
              <th class="px-5 py-3">{{ t('models.status') }}</th>
              <th class="px-5 py-3">{{ t('models.actions') }}</th>
            </tr>
          </thead>
          <tbody class="text-sm divide-y divide-gray-50">
            <tr v-if="store.models.length === 0">
              <td colspan="5" class="px-5 py-8 text-center"><EmptyState :text="t('models.noModels')" /></td>
            </tr>
            <tr v-for="m in filteredModels" :key="m.id || m.model_id" class="hover:bg-gray-50/50">
              <td class="px-5 py-4 font-medium text-gray-900">{{ m.display_name || m.name || m.model_id || t('models.unnamed') }}</td>
              <td class="px-5 py-4 font-mono text-gray-500">{{ m.model_id || m.model_key || m.id }}</td>
              <td class="px-5 py-4 text-gray-500">{{ m.provider || '--' }}</td>
              <td class="px-5 py-4">
                <StatusBadge :status="m.enabled ? 'success' : 'cancelled'" />
              </td>
              <td class="px-5 py-4">
                <div class="flex items-center gap-2">
                  <ToggleSwitch
                    :id="`model-${m.id || m.model_id}`"
                    :model-value="m.enabled"
                    @update:model-value="(v) => toggleModel(m, v)"
                  />
                  <button
                    @click="openModelParams(m)"
                    class="px-3 py-1.5 border border-gray-200 rounded-lg text-xs font-medium text-gray-600 hover:bg-gray-50"
                  >
                    Params
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="editingModel" class="fixed inset-0 z-50 flex items-center justify-center">
        <div class="absolute inset-0 bg-black/40" @click="editingModel = null"></div>
        <div class="relative bg-white rounded-xl shadow-xl border border-gray-100 p-6 w-full max-w-lg mx-4 z-10">
          <div class="mb-5">
            <h3 class="text-lg font-bold text-gray-900">Edit Model Params</h3>
            <p class="text-sm text-gray-500 mt-1">{{ editingModel.display_name || editingModel.model_id }}</p>
          </div>

          <div v-if="Object.keys(editingSchema).length === 0" class="text-sm text-gray-400 bg-gray-50 border border-gray-100 rounded-lg p-4">
            This model does not expose configurable parameters yet.
          </div>

          <div v-else class="space-y-4 max-h-[55vh] overflow-y-auto pr-1">
            <div v-for="(schema, key) in editingSchema" :key="key">
              <label class="block text-xs text-gray-500 mb-1">{{ schema.label || key }}</label>
              <select
                v-if="schema.enum"
                v-model="editParams[key]"
                class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none bg-white focus:border-primary"
              >
                <option v-for="opt in schema.enum" :key="opt" :value="opt">{{ opt }}</option>
              </select>
              <label
                v-else-if="schema.type === 'boolean'"
                class="flex items-center justify-between border border-gray-200 rounded-lg px-3 py-2 bg-white"
              >
                <span class="text-sm text-gray-700">{{ editParams[key] ? 'Enabled' : 'Disabled' }}</span>
                <input v-model="editParams[key]" type="checkbox" class="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary" />
              </label>
              <input
                v-else-if="schema.type === 'integer' || schema.type === 'number'"
                v-model.number="editParams[key]"
                type="number"
                :min="schema.min"
                :max="schema.max"
                class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary"
              />
              <input
                v-else
                v-model="editParams[key]"
                type="text"
                class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary"
              />
            </div>
          </div>

          <div class="flex justify-end gap-3 mt-6">
            <button @click="editingModel = null" class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50">
              Cancel
            </button>
            <button @click="saveModelParams" :disabled="savingParams" class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-60">
              {{ savingParams ? 'Saving...' : 'Save' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import SearchInput from '@/components/common/SearchInput.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ToggleSwitch from '@/components/common/ToggleSwitch.vue'
import { useModelStore } from '@/stores/models'
import { useToast } from '@/composables/useToast'
import { PhArrowsClockwise } from '@phosphor-icons/vue'

import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const store = useModelStore()
const toast = useToast()
const search = ref('')
const editingModel = ref(null)
const editParams = ref({})
const savingParams = ref(false)

const filteredModels = computed(() => {
  if (!search.value) return store.models
  const q = search.value.toLowerCase()
  return store.models.filter((m) => {
    const name = (m.display_name || m.name || m.model_id || m.model_key || '').toLowerCase()
    return name.includes(q)
  })
})

const editingSchema = computed(() => editingModel.value?.parameter_schema || {})

function fallbackParamValue(schema) {
  if (schema.default !== undefined) return schema.default
  if (schema.enum?.length) return schema.enum[0]
  if (schema.type === 'boolean') return false
  if (schema.type === 'integer' || schema.type === 'number') return schema.min ?? 0
  return ''
}

function openModelParams(model) {
  editingModel.value = model
  const next = { ...(model.default_params || {}) }
  Object.entries(model.parameter_schema || {}).forEach(([key, schema]) => {
    if (next[key] === undefined) next[key] = fallbackParamValue(schema)
  })
  editParams.value = next
}

async function saveModelParams() {
  if (!editingModel.value) return
  const id = editingModel.value.model_id || editingModel.value.model_key || editingModel.value.id
  savingParams.value = true
  try {
    await store.updateModel(id, { default_params: { ...editParams.value } })
    await store.fetchModels()
    editingModel.value = null
    toast.success('Model parameters saved')
  } catch {
    toast.error('Failed to save model parameters')
  } finally {
    savingParams.value = false
  }
}

async function toggleModel(model, enable) {
  const id = model.model_id || model.model_key || model.id
  try {
    if (enable) {
      await store.enableModel(id)
    } else {
      await store.disableModel(id)
    }
    toast.success(`${enable ? t('models.enabled', { name: model.display_name || model.name || model.model_id }) : t('models.disabled', { name: model.display_name || model.name || model.model_id })}`)
  } catch (e) {
    toast.error(t('models.toggleFailed'))
  }
}

onMounted(() => store.fetchModels())
</script>
