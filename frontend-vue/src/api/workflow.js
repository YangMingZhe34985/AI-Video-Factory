import request from './request'

export function getNodes() {
  return request.get('/workflow/nodes')
}

export function enableNode(nodeKey) {
  return request.post(`/workflow/nodes/${nodeKey}/enable`)
}

export function disableNode(nodeKey) {
  return request.post(`/workflow/nodes/${nodeKey}/disable`)
}

export function updateNodeConfig(nodeKey, config) {
  return request.put(`/workflow/nodes/${nodeKey}/config`, config)
}

/** Validate a workflow node selection and get required inputs */
export function validateRun(payload) {
  return request.post('/workflow/validate-run', payload)
}
