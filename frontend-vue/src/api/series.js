import request from './request'

export function getSeries() {
  return request.get('/series').then((d) => d.series || d)
}

export function getSeriesItem(seriesId) {
  return request.get(`/series/${seriesId}`)
}

export function createSeries(data) {
  return request.post('/series', data)
}

export function updateSeries(seriesId, data) {
  return request.put(`/series/${seriesId}`, data)
}

export function deleteSeries(seriesId) {
  return request.delete(`/series/${seriesId}`)
}

export function moveTemplate(templateId, targetSeriesId) {
  return request.post(`/templates/${templateId}/move`, { target_series_id: targetSeriesId })
}

export function getTemplatesBySeries(seriesId) {
  return request.get('/templates', { params: { series_id: seriesId } })
    .then((d) => d.templates || d)
}
