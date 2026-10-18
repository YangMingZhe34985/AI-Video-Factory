export const states = ['queued', 'running', 'waiting', 'attention', 'completed', 'cancelled']
export const queueKeys = ['submit_waiting', 'submitting', 'provider_running', 'download_waiting', 'downloading', 'unknown']

export function taskRoute(item) {
  if (!item || !/^[A-Za-z0-9_-]+$/.test(item.id)) return null
  if (item.source === 'agent') return { path: '/agent-studio', query: { run: item.id } }
  if (item.source === 'workflow') return { path: `/jobs/${encodeURIComponent(item.id)}` }
  return null
}
export function pageCount(total, perPage) {
  return Math.max(1, Math.ceil(Math.max(0, Number(total) || 0) / Math.max(1, Number(perPage) || 20)))
}
export function activeQueues(counts) {
  return queueKeys.filter((key) => Number.isInteger(counts?.[key]) && counts[key] > 0)
    .map((key) => ({ key, count: counts[key] }))
}

// One in-flight read; invalidated responses never replace the latest view.
export function createTaskPoller({ read, accept, fail, busy = () => {}, visible = () => true,
  schedule = setTimeout, unschedule = clearTimeout, interval = 5000 }) {
  let timer = null, controller = null, disposed = false, generation = 0, pending = false
  const clear = () => { if (timer !== null) unschedule(timer); timer = null }
  const arm = () => { if (!disposed && visible()) timer = schedule(() => { timer = null; tick() }, interval) }
  async function tick() {
    if (disposed || !visible() || controller) return
    const request = new AbortController(), version = generation
    controller = request
    busy(true)
    try {
      const result = await read(request.signal)
      if (!disposed && !request.signal.aborted && version === generation) accept(result)
    } catch (error) {
      if (!disposed && !request.signal.aborted && version === generation) fail(error)
    } finally {
      controller = null
      if (!disposed) {
        busy(false)
        if (pending && visible()) { pending = false; tick() } else arm()
      }
    }
  }
  return {
    refresh() {
      if (disposed) return
      clear(); generation++
      if (controller) { pending = visible(); controller.abort() } else tick()
    },
    visibilityChanged() {
      clear(); generation++; pending = false
      if (!visible()) controller?.abort()
      else if (controller) { pending = true; controller.abort() } else tick()
    },
    stop() { disposed = true; clear(); generation++; pending = false; controller?.abort() },
  }
}
