import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as dashboardApi from '@/api/dashboard'

export const useDashboardStore = defineStore('dashboard', () => {
  const summary = ref({})
  const loading = ref(false)

  async function fetchSummary() {
    loading.value = true
    try {
      summary.value = await dashboardApi.getSummary()
    } catch {
      summary.value = {}
    } finally {
      loading.value = false
    }
  }

  return { summary, loading, fetchSummary }
})