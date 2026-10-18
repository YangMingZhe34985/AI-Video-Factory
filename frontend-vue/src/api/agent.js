import request from './request'

export const listAgentRuns = () => request.get('/agent/runs')
export const getAgentRun = (id) => request.get(`/agent/runs/${id}`)
// v2 contract (CONTRACTS A.2): text + attachment ids; the Agent decides everything else.
export const createAgentRun = (input) => request.post('/agent/runs', input)
export const actOnAgentRun = (id, action, plan) => request.post(`/agent/runs/${id}/actions`, { action, ...(plan ? { plan } : {}) })
export const reviseAgentShot = (id, shot, requestKey) => request.post(`/agent/runs/${id}/actions`, { action: 'revise', shot, request_key: requestKey })
// CONTRACTS A.9: answers to a clarification card.
export const answerAgentCard = (id, cardId, answers, useDefaults = false) =>
  request.post(`/agent/runs/${id}/actions`, { action: 'answer', card_id: cardId, answers, use_defaults: useDefaults })

// CONTRACTS W.1: one validated image, video, audio or document per request.
export const uploadAgentAttachment = (file, onProgress) => {
  const data = new FormData()
  data.append('file', file)
  return request.post('/agent/attachments', data, {
    timeout: 180000,
    onUploadProgress: (event) => onProgress?.(event.total ? Math.round((event.loaded / event.total) * 100) : null),
  })
}

// CONTRACTS W.3: authoritative, side-effect-free transform quote.
export const quoteAgentTransform = (id, plan, signal) => request.post(`/agent/runs/${id}/transform-quote`, { plan }, { signal, timeout: 180000 })

export const listModels = () => request.get('/models')

// CONTRACTS C.8: actions enter the same durable command inbox.
export const actOnStoryboard = (id, action, payload = {}) => request.post(`/agent/runs/${id}/actions`, { ...payload, action })

// CONTRACTS D: read-only quote; model submission still requires an explicit action.
export const quoteAgentProduction = (id, input) => request.post(`/agent/runs/${id}/production/quote`, input)

// V3 actions use a stable caller-owned key; never retry with a new request body.
export const actOnAgentV3Run = (id, body, signal) => request.post(`/agent/runs/${id}/actions`, body, { signal })
export const listAgentV3Steps = (id, page = 1, perPage = 30, signal) =>
  request.get(`/agent/runs/${id}/steps`, { params: { page, per_page: perPage }, signal })
// The read-only server quote binds scope and cost to one exact Patch version.
export const quoteAgentV3Patch = (id, input, signal) =>
  request.post(`/agent/runs/${id}/patch-quote`, input, { signal, timeout: 180000 })
