import test from 'node:test'
import assert from 'node:assert/strict'
import { buildDeliveryAction, deliveryActionAllowed, deliveryAssetUrl, deliveryChecks, deliveryKeptShots, deliveryReady, deliveryWarnings, downloadFilename } from '../src/components/agent/delivery.js'

const asset = (id) => ({ artifact_id: id, preview_url: `/api/artifacts/${id}/preview`, download_url: `/api/artifacts/${id}/download`, file_name: `${id}.mp4` })
const ready = { enabled: true, plan_version: 3, status: 'success', stage: 'complete', cost_credits: 0,
  master: asset('art_master'), package: asset('art_package'), compressed: null,
  qc: { passed: true, checks: [{ code: 'decode', passed: true, summary: '可解码' }], warnings: [] }, warnings: [] }

test('delivery needs final state, passing QC, master and package before showing downloads', () => {
  assert(deliveryReady(ready))
  for (const change of [{ status: 'videos_approved' }, { status: 'editing' }, { status: 'delivery_attention' },
    { stage: 'packaging' }, { qc: null }, { qc: { passed: false } }, { qc: { passed: 'true' } },
    { master: null }, { package: null }, { package: { ...ready.package, download_url: null } }]) {
    assert(!deliveryReady({ ...ready, ...change }), JSON.stringify(change))
  }
  assert(!deliveryReady(null))
})
test('artifact routes must exactly match local IDs, keeping Bearer headers away from external destinations', () => {
  assert.equal(deliveryAssetUrl(ready.master), '/api/artifacts/art_master/download')
  assert.equal(deliveryAssetUrl(ready.master, 'preview'), '/api/artifacts/art_master/preview')
  for (const path of ['https://evil.invalid/file', '//evil.invalid/file', '/api/artifacts/art_other/download',
    '/api/artifacts/art_master/download?token=secret', '/api/artifacts/art_master/download#fragment',
    '/api/artifacts/art_master/../download', 'javascript:alert(1)', '/api/artifacts/art_master/preview']) {
    assert.equal(deliveryAssetUrl({ ...ready.master, download_url: path }), '')
  }
  for (const id of ['../master', 'art/a', 'art%2Fa', '', null]) assert.equal(deliveryAssetUrl({ ...ready.master, artifact_id: id }), '')
  assert.equal(deliveryAssetUrl(ready.master, 'raw'), '')
})
test('free delivery actions require exact server permission, current version and zero model cost', () => {
  const base = { ...ready, status: 'videos_approved', can_start: true, can_retry: false }
  assert(deliveryActionAllowed(base, 'start_delivery'))
  assert(!deliveryActionAllowed(base, 'retry_delivery'))
  assert(deliveryActionAllowed({ ...base, status: 'success', can_retry: true }, 'retry_delivery'))
  for (const change of [{ enabled: false }, { can_start: false }, { can_start: 'true' }, { cost_credits: null },
    { cost_credits: 1 }, { plan_version: 0 }, { plan_version: '3' }]) {
    assert(!deliveryActionAllowed({ ...base, ...change }, 'start_delivery'))
  }
  assert(!deliveryActionAllowed(base, 'start_delivery', true))
  assert(!deliveryActionAllowed(base, 'redo_shot'))
  assert(!deliveryActionAllowed({ ...base, status: 'delivery_attention', can_start: false }, 'retry_delivery'))
})
test('actions only carry approved version and never request generation or automatic compression', () => {
  assert.deepEqual(buildDeliveryAction({ ...ready, can_start: true }, 'start_delivery'), {
    action: 'start_delivery', payload: { plan_version: 3 },
  })
  assert.deepEqual(buildDeliveryAction({ ...ready, can_retry: true }, 'retry_delivery'), {
    action: 'retry_delivery', payload: { plan_version: 3 },
  })
  assert.throws(() => buildDeliveryAction({ ...ready, can_retry: false }, 'retry_delivery'), /UNAVAILABLE/)
})
test('quality-check outcomes and untrusted text are retained as data without inventing passes', () => {
  const checks = [{ code: 'decode', passed: false, summary: '<img src=x onerror=alert(1)>' }, { code: 'duration', summary: '未知' }]
  assert.deepEqual(deliveryChecks({ qc: { checks } }), checks)
  assert.deepEqual(deliveryChecks({ qc: { checks: [null, { code: 'x' }, ...checks] } }), checks)
  assert.deepEqual(deliveryChecks(null), [])
  assert.deepEqual(deliveryWarnings({ warnings: ['MOCK', 'MOCK', null], qc: { warnings: ['MOCK', '规格已统一'] } }), ['MOCK', '规格已统一'])
})
test('download names do not introduce filesystem separators or control characters', () => {
  assert.equal(downloadFilename({ file_name: 'story.mp4' }, 'master.mp4'), 'story.mp4')
  assert.equal(downloadFilename({ file_name: '../folder/a.mp4' }, 'master.mp4'), '.._folder_a.mp4')
  assert.equal(downloadFilename(null, 'sources.zip'), 'sources.zip')
})

test('retained downstream IDs remain a read-only warning without changing delivery authorization', () => {
  const kept = ['s04', ' s02 ', 's04', '', '  ', null, 3, { shot_id: 's03' }]
  const original = structuredClone(kept)
  assert.deepEqual(deliveryKeptShots(kept), ['s04', 's02'])
  assert.deepEqual(kept, original)
  for (const missing of [undefined, null, '', 's04', {}]) assert.deepEqual(deliveryKeptShots(missing), [])
  const withRetained = { ...ready, kept_downstream: kept, can_retry: true }
  assert(deliveryReady(withRetained))
  assert.deepEqual(buildDeliveryAction(withRetained, 'retry_delivery'), {
    action: 'retry_delivery', payload: { plan_version: 3 },
  })
})
