import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as promptsApi from '@/api/prompts'

export const usePromptStore = defineStore('prompts', () => {
  const versions = ref([])
  const activeVersion = ref(null)
  const currentContent = ref('')
  const loading = ref(false)

  // Job-level prompt assets state
  const jobPrompts = ref([])   // list of prompt asset summaries
  const selectedAssetVersions = ref([])

  async function fetchVersions(templateId, promptType, params = {}) {
    loading.value = true
    try {
      versions.value = await promptsApi.getPromptVersions(templateId, promptType, params)
    } catch {
      versions.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchActive(templateId, promptType, params = {}) {
    try {
      activeVersion.value = await promptsApi.getActivePrompt(templateId, promptType, params)
      if (activeVersion.value) {
        currentContent.value = activeVersion.value.content || ''
      }
    } catch {
      activeVersion.value = null
      currentContent.value = ''
    }
  }

  async function createVersion(templateId, data) {
    return promptsApi.createPromptVersion(templateId, data)
  }

  async function activate(templateId, promptType, version, extra = {}) {
    await promptsApi.activatePrompt(templateId, promptType, version, extra)
  }

  async function rollback(templateId, promptType, version, extra = {}) {
    await promptsApi.rollbackPrompt(templateId, promptType, version, extra)
  }

  async function editVersion(templateId, promptType, version, data = {}) {
    return promptsApi.editPromptVersion(templateId, promptType, version, data)
  }

  // Job-level methods
  async function fetchJobPrompts(templateId, jobId, promptType = null) {
    loading.value = true
    try {
      jobPrompts.value = await promptsApi.listPrompts(templateId, {
        job_id: jobId,
        ...(promptType ? { prompt_type: promptType } : {}),
      })
    } catch {
      jobPrompts.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchVisiblePrompts(templateId, params = {}) {
    loading.value = true
    try {
      jobPrompts.value = await promptsApi.listPrompts(templateId, params)
    } catch {
      jobPrompts.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchGlobalPrompts(params = {}) {
    loading.value = true
    try {
      jobPrompts.value = await promptsApi.listGlobalPrompts(params)
    } catch {
      jobPrompts.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchAssetVersions(templateId, jobId, promptType, promptKey) {
    loading.value = true
    try {
      selectedAssetVersions.value = await promptsApi.getJobPromptVersions(templateId, jobId, promptType, promptKey)
    } catch {
      selectedAssetVersions.value = []
    } finally {
      loading.value = false
    }
  }

  return {
    versions,
    activeVersion,
    currentContent,
    loading,
    jobPrompts,
    selectedAssetVersions,
    fetchVersions,
    fetchActive,
    createVersion,
    activate,
    rollback,
    editVersion,
    fetchJobPrompts,
    fetchVisiblePrompts,
    fetchGlobalPrompts,
    fetchAssetVersions,
  }
})
