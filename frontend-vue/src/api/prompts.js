import request from './request'

// ---------------------------------------------------------------------------
// Legacy / template-level (backward compat)
// ---------------------------------------------------------------------------

export function getPromptVersions(templateId, promptType, params = {}) {
  return request.get(`/templates/${templateId}/prompts/${promptType}/versions`, { params })
    .then((data) => data.versions || data)
}

export function getActivePrompt(templateId, promptType, params = {}) {
  return request.get(`/templates/${templateId}/prompts/${promptType}/active`, { params })
}

export function createPromptVersion(templateId, data) {
  return request.post(`/templates/${templateId}/prompts`, data)
}

export function activatePrompt(templateId, promptType, version, extra = {}) {
  return request.post(`/templates/${templateId}/prompts/${promptType}/activate`, { version, ...extra })
}

export function rollbackPrompt(templateId, promptType, version, extra = {}) {
  return request.post(`/templates/${templateId}/prompts/${promptType}/rollback`, { version, ...extra })
}

export function editPromptVersion(templateId, promptType, version, data) {
  return request.post(`/templates/${templateId}/prompts/${promptType}/versions/${version}/edit`, data)
}

// ---------------------------------------------------------------------------
// New: job-level prompt hierarchy
// ---------------------------------------------------------------------------

/** List all prompts for a job, optionally filtered by prompt_type */
export function getJobPrompts(templateId, jobId, promptType = null) {
  if (promptType) {
    return request.get(`/templates/${templateId}/jobs/${jobId}/prompts/${promptType}`)
      .then((d) => d.prompts || d)
  }
  return request.get(`/templates/${templateId}/jobs/${jobId}/prompts`)
    .then((d) => d.prompts || d)
}

/** List versions of a specific prompt asset for a job */
export function getJobPromptVersions(templateId, jobId, promptType, promptKey) {
  return request.get(`/templates/${templateId}/jobs/${jobId}/prompts/${promptType}/${promptKey}/versions`)
    .then((d) => d.versions || d)
}

/** Get active version of a specific prompt asset for a job */
export function getJobPromptActive(templateId, jobId, promptType, promptKey) {
  return request.get(`/templates/${templateId}/jobs/${jobId}/prompts/${promptType}/${promptKey}/active`)
}

/** Get all prompts for a template with optional job_id/prompt_type filters */
export function listPrompts(templateId, params = {}) {
  return request.get(`/templates/${templateId}/prompts`, { params })
    .then((d) => d.prompts || d)
}

/** List prompt assets globally with optional series/template/job/type/key filters */
export function listGlobalPrompts(params = {}) {
  return request.get('/prompts', { params })
    .then((d) => d.prompts || d)
}
