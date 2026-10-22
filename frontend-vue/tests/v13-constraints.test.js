import test from 'node:test'
import assert from 'node:assert/strict'
import { durationStateLabel, durationTargetLabel, planConstraints } from '../src/components/agent/v3-constraints.js'

const run = (plan, estimates = {}, issues = []) => ({ plan, estimates, plan_issues: issues })
const approx120 = { target_duration_sec: 120, duration_tolerance_sec: 15, mode: 'approx' }

test('no constraints stays hidden', () => {
  const value = planConstraints(run({ nodes: [] }, { video_seconds: 10 }))
  assert.deepEqual(value, { duration: null, aspect: null, visible: false })
})

test('approx duration within tolerance is ok', () => {
  const { duration } = planConstraints(run({ duration_constraint: approx120, nodes: [] }, { video_seconds: 120 }))
  assert.equal(duration.state, 'ok')
  assert.equal(duration.min, 105)
  assert.equal(duration.max, 135)
  assert.equal(durationTargetLabel(duration), '约 120 秒（105–135 秒）')
  assert.equal(durationStateLabel(duration), '当前 120 秒 · 符合')
})

test('c3-2 style 70s plan against 120s is a mismatch', () => {
  const { duration } = planConstraints(run({ duration_constraint: approx120, nodes: [] }, { video_seconds: 70 }))
  assert.equal(duration.state, 'mismatch')
  assert.equal(durationStateLabel(duration), '当前 70 秒 · 不符合')
})

test('server mismatch issue wins over local arithmetic', () => {
  const { duration } = planConstraints(run({ duration_constraint: approx120, nodes: [] }, { video_seconds: 120 },
    [{ code: 'PLAN_DURATION_MISMATCH', message: 'x' }]))
  assert.equal(duration.state, 'mismatch')
})

test('exact and at_most ignore tolerance and label plainly', () => {
  const exact = planConstraints(run({ duration_constraint: { target_duration_sec: 5, duration_tolerance_sec: 0, mode: 'exact' }, nodes: [] }, { video_seconds: 5 })).duration
  assert.equal(exact.state, 'ok')
  assert.equal(durationTargetLabel(exact), '正好 5 秒')
  const most = planConstraints(run({ duration_constraint: { target_duration_sec: 60, duration_tolerance_sec: 0, mode: 'at_most' }, nodes: [] }, { video_seconds: 40 })).duration
  assert.equal(most.min, 0)
  assert.equal(most.state, 'ok')
  assert.equal(durationTargetLabel(most), '不超过 60 秒')
})

test('missing estimate is pending, invalid constraint is ignored', () => {
  assert.equal(planConstraints(run({ duration_constraint: approx120, nodes: [] })).duration.state, 'unknown')
  assert.equal(planConstraints(run({ duration_constraint: { target_duration_sec: 10, mode: 'weird' }, nodes: [] })).duration, null)
})

test('aspect comes from a single consistent delivery target', () => {
  const nodes = [{ tool: 'compose_video', inputs: { target_aspect_ratio: '16:9' } }, { tool: 'qc_video', inputs: { target_aspect_ratio: '16:9' } },
    { tool: 'generate_image', inputs: { target_aspect_ratio: '1:1' } }]
  assert.equal(planConstraints(run({ nodes })).aspect, '16:9')
  const conflicting = [{ tool: 'compose_video', inputs: { target_aspect_ratio: '16:9' } }, { tool: 'qc_video', inputs: { target_aspect_ratio: '9:16' } }]
  assert.equal(planConstraints(run({ nodes: conflicting })).aspect, null)
})
