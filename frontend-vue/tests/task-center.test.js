import test from 'node:test'
import assert from 'node:assert/strict'
import { activeQueues, createTaskPoller, pageCount, states, taskRoute } from '../src/components/task-center/task-center.js'

test('task routes only point to local workspaces', () => {
  assert.deepEqual(taskRoute({ source: 'agent', id: 'agent_1' }), { path: '/agent-studio', query: { run: 'agent_1' } })
  assert.deepEqual(taskRoute({ source: 'workflow', id: 'job_1' }), { path: '/jobs/job_1' })
  for (const id of ['https://evil.invalid', '../x', 'x?q=token', 'a/b', '']) assert.equal(taskRoute({ source: 'agent', id }), null)
  assert.equal(taskRoute({ source: 'admin', id: 'x' }), null)
})
test('queue counters retain phases and never invent ETA or health', () => {
  assert.deepEqual(activeQueues({ submit_waiting: 2, provider_running: 1, unknown: 0, downloading: -1, bad: 99 }),
    [{ key: 'submit_waiting', count: 2 }, { key: 'provider_running', count: 1 }])
  assert.deepEqual(activeQueues(null), [])
  assert.equal(pageCount(21, 20), 2)
  assert.equal(pageCount(0, 20), 1)
  assert.deepEqual(states, ['queued', 'running', 'waiting', 'attention', 'completed', 'cancelled'])
})
const flush = () => new Promise((resolve) => setImmediate(resolve))
function harness() {
  const pending = [], accepted = [], errors = [], timers = new Map()
  let visible = true, nextTimer = 1
  const poller = createTaskPoller({
    read: (signal) => new Promise((resolve, reject) => pending.push({ signal, resolve, reject })),
    accept: (value) => accepted.push(value), fail: (error) => errors.push(error),
    visible: () => visible,
    schedule: (callback, delay) => { const id = nextTimer++; timers.set(id, { callback, delay }); return id },
    unschedule: (id) => timers.delete(id),
  })
  return { poller, pending, accepted, errors, timers, hide: () => { visible = false; poller.visibilityChanged() },
    show: () => { visible = true; poller.visibilityChanged() } }
}
test('refresh invalidates stale response and avoids overlapping requests', async () => {
  const h = harness()
  h.poller.refresh()
  h.poller.refresh()
  assert.equal(h.pending.length, 1)
  assert(h.pending[0].signal.aborted)
  h.pending[0].resolve('stale')
  await flush()
  assert.deepEqual(h.accepted, [])
  assert.equal(h.pending.length, 2)
  h.pending[1].resolve('latest')
  await flush()
  assert.deepEqual(h.accepted, ['latest'])
  assert.equal([...h.timers.values()][0].delay, 5000)
  h.poller.stop()
  assert.equal(h.timers.size, 0)
})
test('hidden page stops reads and stale failures; visible page resumes', async () => {
  const h = harness()
  h.poller.refresh()
  h.hide()
  h.pending[0].reject(new Error('aborted'))
  await flush()
  assert.equal(h.errors.length, 0)
  assert.equal(h.timers.size, 0)
  h.poller.refresh()
  assert.equal(h.pending.length, 1)
  h.show()
  assert.equal(h.pending.length, 2)
  h.pending[1].resolve('visible')
  await flush()
  assert.deepEqual(h.accepted, ['visible'])
  h.poller.stop()
})
test('failed refresh reports error without replacing previous data', async () => {
  const h = harness()
  h.poller.refresh()
  h.pending[0].resolve('old')
  await flush()
  h.poller.refresh()
  h.pending[1].reject(new Error('offline'))
  await flush()
  assert.deepEqual(h.accepted, ['old'])
  assert.equal(h.errors.length, 1)
  assert.equal(h.timers.size, 1)
  h.poller.stop()
})
test('unmount aborts and suppresses completion, failure and further timers', async () => {
  const h = harness()
  h.poller.refresh()
  h.poller.stop()
  assert(h.pending[0].signal.aborted)
  h.pending[0].resolve('late')
  await flush()
  h.poller.refresh()
  assert.equal(h.pending.length, 1)
  assert.deepEqual(h.accepted, [])
  assert.equal(h.timers.size, 0)
})
