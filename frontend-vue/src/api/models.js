import request from './request'

export function getModels(params = {}) {
  return request.get('/models', { params })
}

export function getModel(modelId) {
  return request.get(`/models/${modelId}`)
}

export function createModel(data) {
  return request.post('/models', data)
}

export function updateModel(modelId, data) {
  return request.put(`/models/${modelId}`, data)
}

export function enableModel(modelId) {
  return request.post(`/models/${modelId}/enable`)
}

export function disableModel(modelId) {
  return request.post(`/models/${modelId}/disable`)
}