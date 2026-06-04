import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as modelsApi from '@/api/models'

export const useModelStore = defineStore('models', () => {
  const models = ref([])
  const currentModel = ref(null)
  const loading = ref(false)

  function canonicalModelId(value) {
    const raw = String(value || '').trim()
    if (!raw) return ''
    const key = raw.toLowerCase().replace(/[^a-z0-9]/g, '')
    const aliases = {
      wan26image: 'wan2.6-image',
      wan27image: 'wan2.7-image',
      wan27imagepro: 'wan2.7-image-pro',
      wan26i2vflash: 'wan2.6-i2v-flash',
      wan27i2v: 'wan2.7-i2v',
      wan27t2v: 'wan2.7-t2v',
      wan26r2vflash: 'wan2.6-r2v-flash',
      glm51: 'glm5-1',
      deepseekv4pro: 'deepseek-v4-pro',
    }
    return aliases[key] || raw
  }

  function normalizeModels(rawModels) {
    const byId = new Map()
    ;(rawModels || []).forEach((model) => {
      const modelId = canonicalModelId(model.model_id || model.model_key || model.id)
      if (!modelId) return
      const normalized = {
        ...model,
        model_id: modelId,
        model_key: modelId,
      }
      const existing = byId.get(modelId)
      if (!existing || (!existing.enabled && normalized.enabled)) {
        byId.set(modelId, normalized)
      }
    })
    return [...byId.values()]
  }

  async function fetchModels(params = {}) {
    loading.value = true
    try {
      const data = await modelsApi.getModels(params)
      models.value = normalizeModels(Array.isArray(data) ? data : (data.models || []))
    } catch {
      models.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchModel(modelId) {
    try {
      currentModel.value = await modelsApi.getModel(modelId)
    } catch {
      currentModel.value = null
    }
  }

  async function createModel(data) {
    return modelsApi.createModel(data)
  }

  async function updateModel(modelId, data) {
    currentModel.value = await modelsApi.updateModel(modelId, data)
  }

  async function enableModel(modelId) {
    await modelsApi.enableModel(modelId)
    const m = models.value.find((m2) => [m2.model_id, m2.model_key, m2.id].includes(modelId))
    if (m) m.enabled = true
  }

  async function disableModel(modelId) {
    await modelsApi.disableModel(modelId)
    const m = models.value.find((m2) => [m2.model_id, m2.model_key, m2.id].includes(modelId))
    if (m) m.enabled = false
  }

  return { models, currentModel, loading, fetchModels, fetchModel, createModel, updateModel, enableModel, disableModel }
})
