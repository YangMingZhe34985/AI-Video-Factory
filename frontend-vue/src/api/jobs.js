import request from './request'

export function getJobs(params = {}) {
  return request.get('/jobs', { params })
}

export function getJob(jobId) {
  return request.get(`/jobs/${jobId}`).then((data) => {
    if (!data?.job) return data
    return {
      ...data.job,
      nodes: data.nodes || [],
      node_runs: data.node_runs || (data.nodes || []).map((n) => n.latest_run).filter(Boolean),
      artifacts: data.artifacts || [],
      recent_events: data.recent_events || [],
      total_nodes: data.total_nodes || (data.nodes || []).length,
      completed_nodes: data.completed_nodes || 0,
      error_summary: data.error_summary || data.job.error_summary,
      error_detail: data.error_detail || data.job.error_detail || null,
    }
  })
}

export function createJob(formData) {
  return request.post('/jobs', formData)
}

export function updateJob(jobId, payload) {
  return request.patch(`/jobs/${jobId}`, payload)
}

export function deleteJob(jobId, confirmJobId) {
  return request.delete(`/jobs/${jobId}`, { data: { confirm_job_id: confirmJobId } })
}

export function runFull(jobId, force = false) {
  return request.post(`/jobs/${jobId}/run-full`, { force })
}

export function runFrom(jobId, nodeKey, force = false) {
  return request.post(`/jobs/${jobId}/run-from`, { node_key: nodeKey, force })
}

export function runNode(jobId, nodeKey, force = false) {
  return request.post(`/jobs/${jobId}/run-node`, { node_key: nodeKey, force })
}

export function pauseJob(jobId) {
  return request.post(`/jobs/${jobId}/pause`)
}

export function cancelJob(jobId) {
  return request.post(`/jobs/${jobId}/cancel`)
}

export function packageJob(jobId) {
  return request.post(`/jobs/${jobId}/package`)
}

export function getJobEvents(jobId, params = {}) {
  return request.get(`/jobs/${jobId}/events`, { params })
}

export function getQueueStatus() {
  return request.get('/jobs/queue/status')
}
