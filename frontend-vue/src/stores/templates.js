import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as templatesApi from '@/api/templates'

export const useTemplateStore = defineStore('templates', () => {
  const templates = ref([])
  const currentTemplate = ref(null)
  const loading = ref(false)

  async function fetchTemplates(params = {}) {
    loading.value = true
    try {
      const data = await templatesApi.getTemplates(params)
      templates.value = Array.isArray(data) ? data : (data.templates || [])
    } catch {
      templates.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchTemplate(id) {
    try {
      currentTemplate.value = await templatesApi.getTemplate(id)
    } catch {
      currentTemplate.value = null
    }
  }

  async function createTemplate(data) {
    return templatesApi.createTemplate(data)
  }

  return { templates, currentTemplate, loading, fetchTemplates, fetchTemplate, createTemplate }
})
