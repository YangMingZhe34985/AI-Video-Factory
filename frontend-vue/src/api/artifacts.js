import request from './request'

export function getArtifacts(jobId) {
  return request.get(`/jobs/${jobId}/artifacts`).then((data) => data.artifacts || data)
}

export function searchArtifacts(params = {}) {
  return request.get('/artifacts', { params }).then((data) => data.artifacts || data)
}

export function getDownloadUrl(artifactId) {
  return `/api/artifacts/${artifactId}/download`
}

export function getPreviewUrl(artifactId) {
  return `/api/artifacts/${artifactId}/preview`
}
