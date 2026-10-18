import test from 'node:test'
import assert from 'node:assert/strict'
import { createPreviewLoader } from '../src/components/agent/media-preview.js'

function harness() {
  const pending = [], events = [], created = [], revoked = []
  const loader = createPreviewLoader((src, signal) => new Promise((resolve, reject) => pending.push({ src, signal, resolve, reject })),
    (state) => events.push(state), {
      createObjectURL(blob) { created.push(blob); return `blob:${created.length}` },
      revokeObjectURL(url) { revoked.push(url) },
    })
  return { loader, pending, events, created, revoked }
}
test('unmount aborts pending request and late bytes never create or leak an object URL', async () => {
  const h = harness(), request = h.loader.load('first')
  h.loader.dispose()
  assert.equal(h.pending[0].signal.aborted, true)
  const count = h.events.length
  h.pending[0].resolve('late-video')
  await request
  assert.deepEqual(h.created, [])
  assert.equal(h.events.length, count)
  await h.loader.load('after-unmount')
  assert.equal(h.pending.length, 1)
})
test('source change invalidates old completion without clearing the new loading state', async () => {
  const h = harness(), first = h.loader.load('old')
  h.loader.reset()
  const second = h.loader.load('new')
  h.pending[0].resolve('old-bytes')
  await first
  assert.deepEqual(h.created, [])
  assert.deepEqual(h.events.at(-1), { loading: true, failed: false })
  h.pending[1].resolve('new-bytes')
  await second
  assert.deepEqual(h.created, ['new-bytes'])
  assert.deepEqual(h.events.at(-1), { loading: false })
  h.loader.dispose()
  assert.deepEqual(h.revoked, ['blob:1'])
})
test('completed URLs are revoked once on reset or disposal', async () => {
  const h = harness(), first = h.loader.load('one')
  h.pending[0].resolve('first'); await first
  h.loader.reset()
  assert.deepEqual(h.revoked, ['blob:1'])
  const second = h.loader.load('two')
  h.pending[1].resolve('second'); await second
  h.loader.dispose(); h.loader.dispose()
  assert.deepEqual(h.revoked, ['blob:1', 'blob:2'])
})
test('duplicate clicks share one pending request and real failure remains retryable', async () => {
  const h = harness(), first = h.loader.load('one')
  await h.loader.load('one')
  assert.equal(h.pending.length, 1)
  h.pending[0].reject(new Error('network failed')); await first
  assert(h.events.some((event) => event.failed === true))
  const retry = h.loader.load('one')
  h.pending[1].resolve('valid'); await retry
  assert.deepEqual(h.created, ['valid'])
  h.loader.dispose()
})
