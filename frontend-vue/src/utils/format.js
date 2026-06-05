export function formatDate(iso) {
  if (!iso) return '--'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

export function statusColors(status) {
  const map = {
    queued: 'bg-indigo-50 text-indigo-600 border-indigo-100',
    running: 'bg-blue-50 text-blue-600 border-blue-100',
    success: 'bg-green-50 text-green-600 border-green-100',
    failed: 'bg-red-50 text-red-600 border-red-100',
    paused: 'bg-yellow-50 text-yellow-600 border-yellow-100',
    cancelled: 'bg-gray-50 text-gray-500 border-gray-100',
    pending: 'bg-gray-50 text-gray-500 border-gray-100',
    partial_success: 'bg-purple-50 text-purple-600 border-purple-100',
    retrying: 'bg-blue-50 text-blue-600 border-blue-100',
    path_failed: 'bg-amber-50 text-amber-700 border-amber-100',
  }
  return map[status] || map.pending
}

export function statusDotColor(status) {
  const map = {
    queued: 'bg-indigo-500',
    running: 'bg-blue-500',
    success: 'bg-green-500',
    failed: 'bg-red-500',
    paused: 'bg-yellow-500',
    cancelled: 'bg-gray-400',
    pending: 'bg-gray-400',
    partial_success: 'bg-purple-500',
    retrying: 'bg-blue-500',
    path_failed: 'bg-amber-500',
  }
  return map[status] || 'bg-gray-400'
}
