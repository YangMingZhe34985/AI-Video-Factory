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

export function packageTemplate(id) {
  return request.post(`/templates/${id}/package`)
}

export function getTemplatePackageDownloadUrl(id) {
  return `/api/templates/${id}/package/download`
}
