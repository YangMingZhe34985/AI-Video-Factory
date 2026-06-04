import request from './request'

export function getTemplates(params = {}) {
  return request.get('/templates', { params })
}

export function getTemplate(id) {
  return request.get(`/templates/${id}`)
}

export function createTemplate(data) {
  return request.post('/templates', data)
}
