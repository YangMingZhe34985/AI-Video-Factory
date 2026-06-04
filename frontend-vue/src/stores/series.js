import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as seriesApi from '@/api/series'

export const useSeriesStore = defineStore('series', () => {
  const seriesList = ref([])
  const loading = ref(false)

  async function fetchSeries() {
    loading.value = true
    try {
      seriesList.value = await seriesApi.getSeries()
    } catch {
      seriesList.value = []
    } finally {
      loading.value = false
    }
  }

  async function createSeries(data) {
    const result = await seriesApi.createSeries(data)
    await fetchSeries()
    return result
  }

  async function updateSeries(seriesId, data) {
    const result = await seriesApi.updateSeries(seriesId, data)
    await fetchSeries()
    return result
  }

  async function deleteSeries(seriesId) {
    await seriesApi.deleteSeries(seriesId)
    await fetchSeries()
  }

  async function moveTemplate(templateId, targetSeriesId) {
    return seriesApi.moveTemplate(templateId, targetSeriesId)
  }

  return {
    seriesList,
    loading,
    fetchSeries,
    createSeries,
    updateSeries,
    deleteSeries,
    moveTemplate,
  }
})
