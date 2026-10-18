import request from './request'

export function listTasks(params, signal) {
  return request.get('/task-center', { params, signal })
}
export function getTask(source, id, params, signal) {
  if (!['agent', 'workflow'].includes(source) || !/^[A-Za-z0-9_-]+$/.test(id)) throw new Error('INVALID_TASK')
  return request.get(`/task-center/${source}/${encodeURIComponent(id)}`, { params, signal })
}
