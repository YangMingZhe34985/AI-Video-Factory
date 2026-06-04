import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as jobsApi from '@/api/jobs'

export const useJobStore = defineStore('jobs', () => {
  const jobs = ref([])
  const currentJob = ref(null)
  const pagination = ref({ page: 1, perPage: 20, total: 0 })
  const filters = ref({ template: '', status: '', node: '', search: '' })
  const statusCounts = ref({})
  const loading = ref(false)

  async function fetchJobs(params = {}) {
    loading.value = true
    try {
      const data = await jobsApi.getJobs({ ...filters.value, ...pagination.value, ...params })
      if (Array.isArray(data)) {
        jobs.value = data
      } else if (data?.jobs) {
        jobs.value = data.jobs
        pagination.value.total = data.total || 0
        statusCounts.value = data.status_counts || {}
      }
    } catch {
      jobs.value = []
    } finally {
      loading.value = false
    }
  }

  async function fetchJob(jobId, options = {}) {
    const silent = !!options.silent
    if (!silent) loading.value = true
    try {
      currentJob.value = await jobsApi.getJob(jobId)
    } catch {
      currentJob.value = null
    } finally {
      if (!silent) loading.value = false
    }
  }

  async function createJob(formData) {
    return jobsApi.createJob(formData)
  }

  async function updateJob(jobId, payload) {
    currentJob.value = await jobsApi.updateJob(jobId, payload)
    return currentJob.value
  }

  async function deleteJob(jobId, confirmJobId) {
    return jobsApi.deleteJob(jobId, confirmJobId)
  }

  async function runFull(jobId, force = false) {
    return jobsApi.runFull(jobId, force)
  }

  async function runFrom(jobId, nodeKey, force = false) {
    return jobsApi.runFrom(jobId, nodeKey, force)
  }

  async function runNode(jobId, nodeKey, force = false) {
    return jobsApi.runNode(jobId, nodeKey, force)
  }

  async function pauseJob(jobId) {
    currentJob.value = await jobsApi.pauseJob(jobId)
  }

  async function cancelJob(jobId) {
    currentJob.value = await jobsApi.cancelJob(jobId)
  }

  return {
    jobs, currentJob, pagination, filters, statusCounts, loading,
    fetchJobs, fetchJob, createJob, updateJob, deleteJob, runFull, runFrom, runNode, pauseJob, cancelJob,
  }
})
