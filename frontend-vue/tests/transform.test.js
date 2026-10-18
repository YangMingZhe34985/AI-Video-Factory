import test from 'node:test'
import assert from 'node:assert/strict'
import { ATTACHMENT_ACCEPT, attachmentKind, attachmentDescription, composerReady } from '../src/components/agent/attachments.js'
import { createTransformQuoter, transformDraftIssue, transformEstimate, transformModels, transformQuoteReady } from '../src/components/agent/transform.js'
import { deliveryAssetUrl } from '../src/components/agent/delivery.js'

const models = ['wan3.0-video', 'wan3.0-video-prime'].map((model_id) => ({
  model_id, task_type: 'text_to_video', enabled: true, default_params: { resolution: '720P' },
  capabilities: { agent_selectable: true, family: 'wan3.0', modes: ['omni_reference', 'video_edit', 'video_extend'],
    pricing: { unit: 'second', billing_basis: 'input_plus_output_seconds', resolution_rates: { '480P': 1, '720P': 2, '1080P': 3 } } },
}))
const draft = () => ({
  recipe: 'video_transform', operation: 'extend', title: 'Longer cat video', prompt: 'Keep the cat dancing',
  model_id: 'wan3.0-video', params: { duration: 10, resolution: '720P' }, source_artifact_id: 'source',
  media: [{ type: 'reference_video', artifact_id: 'source' }, { type: 'reference_video', artifact_id: 'other' }],
  manifest: [{ type: 'reference_video', artifact_id: 'source', duration_sec: 4.125 }, { type: 'reference_video', artifact_id: 'other', duration_sec: 2 }],
})
function quote(plan = draft()) {
  const value = structuredClone(plan), input = value.manifest.filter((item) => item.type === 'reference_video').reduce((sum, item) => sum + item.duration_sec, 0)
  value.prompt = value.prompt.trim()
  return { ...value, plan_hash: 'hash', quote_id: 'quote', estimated_cost: (input + value.params.duration) * 2,
    cost_breakdown: { input_video_seconds: input, output_video_seconds: value.params.duration,
      billable_seconds: input + value.params.duration, credits_per_second: 2, estimated_cost: (input + value.params.duration) * 2,
      billing_basis: 'input_plus_output_seconds', extension_seconds: value.params.duration - 4.125 } }
}

test('attachment hints cover supported media without treating arbitrary files as images', () => {
  for (const name of ['voice.WAV', 'voice.mp3']) assert.equal(attachmentKind(name), 'audio')
  for (const name of ['brief.txt', 'brief.MD', 'brief.pdf']) assert.equal(attachmentKind(name), 'file')
  assert.equal(attachmentKind('photo.webp'), 'image')
  assert.equal(attachmentKind('clip.MOV'), 'video')
  assert.equal(attachmentKind('unsupported.docx'), null)
  assert(ATTACHMENT_ACCEPT.includes('.mp3'))
  assert.equal(attachmentDescription({ duration: 4.125 }), '4.125s')
  assert.equal(attachmentDescription({ page_count: 3 }), '3p')
  assert.equal(attachmentDescription({ width: 640, height: 480 }), '640×480')
})

test('required text and incomplete or failed references block creation', () => {
  const done = [{ done: true, error: '' }]
  assert(composerReady('make a video', done, false, 100))
  assert(!composerReady(' ', done, false, 100))
  assert(!composerReady('make a video', [{ done: false, error: '' }], false, 100))
  assert(!composerReady('make a video', [{ done: false, error: 'upload failed' }], false, 100))
  assert(!composerReady('make a video', done, true, 100))
  assert(!composerReady('make a video', done, false, NaN))
})

test('transform selection requires its actual mode and respects exact model, family and exclusions', () => {
  const all = [...models, { ...models[0], model_id: 'legacy-r2v', capabilities: { agent_selectable: true, modes: ['r2v'] } }]
  assert.equal(transformModels(all, 'reference').length, 2)
  assert.deepEqual(transformModels(all, 'edit', { constraints: { model_preferences: ['wan3.0-video'] } }).map((m) => m.model_id), ['wan3.0-video'])
  assert.deepEqual(transformModels(all, 'extend', { constraints: { model_preferences: ['WAN 3.0系列'], model_exclusions: ['wan3.0-video-prime'] } }).map((m) => m.model_id), ['wan3.0-video'])
  assert.equal(transformModels(all, 'extend', { constraints: { model_preferences: ['wan3.01系列'] } }).length, 0)
  assert.equal(transformModels([{ ...models[0], enabled: false }], 'edit').length, 0)
})

test('draft estimate includes every actual input second and the complete output at the selected resolution', () => {
  const plan = draft()
  assert.equal(transformEstimate(plan, models), 32.25)
  plan.params.duration = 11
  plan.params.resolution = '1080P'
  assert.equal(transformEstimate(plan, models), 51.375)
  plan.params.resolution = '4K'
  assert.equal(transformEstimate(plan, models), null)
  plan.manifest = []
  assert.equal(transformEstimate(plan, models), null)
})

test('duration guards distinguish complete output from extension and allow server hydration', () => {
  for (const duration of [-1, 1, 3.5, NaN, Infinity, 31]) {
    const plan = draft(); plan.params.duration = duration
    assert.equal(transformDraftIssue(plan), 'durationInvalid')
  }
  const plan = draft(); plan.params.duration = 4
  assert.equal(transformDraftIssue(plan), 'extendInvalid')
  plan.params.duration = 25
  assert.equal(transformDraftIssue(plan), 'totalInvalid')
  plan.manifest = []; plan.params.duration = 10
  assert.equal(transformDraftIssue(plan), '')
  plan.source_artifact_id = null
  assert.equal(transformDraftIssue(plan), 'sourceMissing')
})

test('approval requires a matching finite server quote and invalidates when editable values change', () => {
  const current = quote(), edited = structuredClone(current)
  assert(transformQuoteReady(current, edited))
  edited.params.duration = 11
  assert(!transformQuoteReady(current, edited))
  const bad = quote(); bad.cost_breakdown.estimated_cost = NaN
  assert(!transformQuoteReady(bad, bad))
  const inconsistent = quote(); inconsistent.cost_breakdown.billable_seconds = 10
  assert(!transformQuoteReady(inconsistent, inconsistent))
  const missing = quote(); delete missing.quote_id
  assert(!transformQuoteReady(missing, missing))
})

function harness() {
  const requests = [], events = [], timers = new Map()
  let timerId = 0
  const quoter = createTransformQuoter((plan, signal) => new Promise((resolve, reject) => requests.push({ plan, signal, resolve, reject })),
    (state) => events.push(state), { setTimer(fn) { timers.set(++timerId, fn); return timerId }, clearTimer(id) { timers.delete(id) } })
  return { quoter, requests, events, timers, fire() { const [id, fn] = timers.entries().next().value; timers.delete(id); return fn() } }
}

test('debounce discards earlier drafts before submitting a quote', async () => {
  const h = harness(), plan = draft()
  h.quoter.schedule(plan); plan.prompt = 'New request'; h.quoter.schedule(plan)
  assert.equal(h.timers.size, 1)
  assert.equal(h.events.at(-1).quote, null)
  const pending = h.fire()
  assert.equal(h.requests.length, 1)
  assert.equal(h.requests[0].plan.prompt, 'New request')
  h.requests[0].resolve(quote(h.requests[0].plan)); await pending
  assert.equal(h.events.at(-1).status, 'ready')
  h.quoter.dispose()
})

test('late success from an aborted request cannot authorize a newer draft', async () => {
  const h = harness(), plan = draft()
  const first = h.quoter.schedule(plan, true)
  plan.prompt = 'Changed'; const second = h.quoter.schedule(plan, true)
  assert(h.requests[0].signal.aborted)
  h.requests[0].resolve(quote(h.requests[0].plan)); await first
  assert.equal(h.events.at(-1).status, 'loading')
  h.requests[1].resolve(quote(h.requests[1].plan)); await second
  assert.equal(h.events.at(-1).quote.prompt, 'Changed')
  h.quoter.dispose()
})

test('failed quotes retain no approvable value and can be retried without changing the draft', async () => {
  const h = harness(), plan = draft(), first = h.quoter.schedule(plan, true)
  h.requests[0].reject(new Error('network')); await first
  assert.equal(h.events.at(-1).status, 'error')
  assert.equal(h.events.at(-1).quote, null)
  const retry = h.quoter.schedule(plan, true)
  h.requests[1].resolve(quote(plan)); await retry
  assert.equal(h.events.at(-1).status, 'ready')
  h.quoter.dispose()
})

test('unmount cancels timers and requests and ignores late failures', async () => {
  const h = harness(), pending = h.quoter.schedule(draft(), true)
  h.quoter.dispose()
  assert(h.requests[0].signal.aborted)
  const count = h.events.length
  h.requests[0].reject(new Error('late')); await pending
  h.quoter.schedule(draft())
  assert.equal(h.events.length, count)
  assert.equal(h.timers.size, 0)
})

test('invalid draft cancels outstanding quote without submitting work', async () => {
  const h = harness(), first = h.quoter.schedule(draft(), true), invalid = draft()
  invalid.params.duration = -1
  h.quoter.schedule(invalid)
  assert(h.requests[0].signal.aborted)
  assert.equal(h.events.at(-1).status, 'invalid')
  assert.equal(h.requests.length, 1)
  h.requests[0].resolve(quote()); await first
  assert.equal(h.events.at(-1).status, 'invalid')
})

test('server defaults can be filled but a changed decision or corrupt price is never approved', async () => {
  const h = harness(), plan = draft(); plan.prompt += ' '
  const first = h.quoter.schedule(plan, true)
  const normalized = quote(plan); normalized.params.audio = true
  h.requests[0].resolve(normalized); await first
  assert.equal(h.events.at(-1).status, 'ready')
  const second = h.quoter.schedule(plan, true), wrong = quote(plan); wrong.params.duration = 12
  h.requests[1].resolve(wrong); await second
  assert.equal(h.events.at(-1).status, 'error')
  assert.equal(h.events.at(-1).quote, null)
})

test('new result URLs are constrained to the exact local artifact route', () => {
  assert.equal(deliveryAssetUrl({ artifact_id: 'result_1', download_url: '/api/artifacts/result_1/download' }), '/api/artifacts/result_1/download')
  assert.equal(deliveryAssetUrl({ artifact_id: 'result_1', download_url: 'https://example.com/steal-token' }), '')
  assert.equal(deliveryAssetUrl({ artifact_id: 'result_1', preview_url: '/api/artifacts/other/preview' }, 'preview'), '')
})
