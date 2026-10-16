import request from './request'

export const listAgentRuns = () => request.get('/agent/runs')
export const getAgentRun = (id) => request.get(`/agent/runs/${id}`)
export const createAgentRun = (input) => request.post('/agent/runs', input)
export const actOnAgentRun = (id, action, plan) => request.post(`/agent/runs/${id}/actions`, { action, ...(plan ? { plan } : {}) })
export const reviseAgentShot = (id, shot, requestKey) => request.post(`/agent/runs/${id}/actions`, { action: 'revise', shot, request_key: requestKey })
export const uploadAgentSource = (file) => {
  const data = new FormData()
  data.append('file', file)
  return request.post('/agent/sources', data, { timeout: 90000 })
}
