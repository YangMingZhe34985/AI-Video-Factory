import test from 'node:test'
import assert from 'node:assert/strict'
import { buildShotAction, creditText, dependencyText, finiteCredits, isCurrentQuote, productionActionAllowed, productionCounts, productionError, productionRows, quoteImpact, startProductionCost } from '../src/components/agent/production.js'

const plan = { shots: [
  { shot_id: 's03', order: 3, duration_sec: 15, depends_on: [], summary: '独立场景', motion: { model_id: 'demo-video', mode: 'i2v' } },
  { shot_id: 's01', order: 1, duration_sec: 15, depends_on: [], summary: '起始场景', motion: { model_id: 'demo-video', mode: 'i2v' } },
  { shot_id: 's02', order: 2, duration_sec: 15, depends_on: ['s01'], summary: '连续动作', motion: { model_id: 'demo-video', mode: 'i2v' } },
] }
const quote = { quote_id: 'quote-1', base_version: 3, shot_id: 's01', affected_shot_ids: ['s01', 's02', 's02'], kept_shot_ids: ['s02'], estimated_credits: { only: 15, cascade: 30 }, can_retry: true }
const context = { planVersion: 3, shotId: 's01', motionPrompt: ' 镜头缓慢推进。 ' }

test('server tasks supplement the approved storyboard without mutating its order or inventing permissions', () => {
  const before = JSON.stringify(plan)
  const rows = productionRows(plan, { shots: [{ shot_id: 's02', status: 'success', attempt: 2, can_redo: true, retained: true }] })
  assert.deepEqual(rows.map((row) => row.shot_id), ['s01', 's02', 's03'])
  assert.equal(rows[0].can_redo, false)
  assert.equal(rows[1].summary, '连续动作')
  assert.equal(rows[1].attempt, 2)
  assert.equal(rows[1].retained, true)
  assert.equal(JSON.stringify(plan), before)
})
test('counts distinguish running, dependencies, failures and approved successful clips', () => {
  assert.deepEqual(productionCounts(['success', 'running', 'waiting_dependency', 'pending', 'blocked', 'failed', 'stale'].map((status) => ({ status }))), { total: 7, success: 1, running: 1, waiting: 2, attention: 3 })
})
test('tail dependencies are explained as serial and independent scenes as parallel candidates', () => {
  assert.match(dependencyText(plan.shots[2]), /s01 → s02/)
  assert.match(dependencyText(plan.shots[2]), /须等上游视频与尾帧完成/)
  assert.match(dependencyText(plan.shots[0]), /可与其他无依赖镜头并行/)
  assert.match(dependencyText({ shot_id: 's04', depends_on: [], motion: { mode: 'first_last_frame' } }), /首尾两端关键帧就绪/)
})
test('quotes drive cascade costs and IDs, preserving only server-declared completed downstream clips', () => {
  assert.deepEqual(quoteImpact(quote, 'cascade'), { shots: ['s01', 's02'], retained: [], continuing: [], cost: 30 })
  assert.deepEqual(quoteImpact(quote, 'only'), { shots: ['s01'], retained: ['s02'], continuing: [], cost: 15 })
  assert.deepEqual(quoteImpact({ ...quote, kept_shot_ids: [] }, 'only').retained, [])
  assert.deepEqual(quoteImpact({ ...quote, affected_shot_ids: ['s02'] }, 'cascade').shots, ['s01', 's02'])
})
test('unknown or invalid prices never appear as free, while an explicit zero remains valid', () => {
  for (const value of [undefined, null, NaN, Infinity, -1, '0']) {
    assert.equal(finiteCredits(value), null)
    assert.equal(creditText(value), '待服务器估算')
  }
  assert.equal(creditText(0), '0')
  assert.equal(creditText(12.3456), '12.35')
  assert.equal(quoteImpact({ ...quote, estimated_credits: {} }, 'only').cost, null)
})
test('a quote from a different shot or plan cannot authorize a paid action', () => {
  assert(isCurrentQuote(quote, context))
  assert(!isCurrentQuote(quote, { ...context, planVersion: 4 }))
  assert(!isCurrentQuote(quote, { ...context, shotId: 's02' }))
  assert.throws(() => buildShotAction(quote, { ...context, planVersion: 4 }, 'cascade', 'redo'), /失效/)
})
test('only and cascade actions contain the exact server quote and explicit confirmation scope', () => {
  for (const scope of ['only', 'cascade']) {
    assert.deepEqual(buildShotAction(quote, context, scope, 'redo'), { action: 'redo_shot', payload: { shot_id: 's01', base_version: 3, quote_id: 'quote-1', scope, motion_prompt: '镜头缓慢推进。' } })
  }
  assert.equal(buildShotAction(quote, context, 'cancel', 'redo').payload.scope, 'cancel')
})
test('retry preserves original inputs and requires a server-approved retry quote', () => {
  assert.deepEqual(buildShotAction(quote, context, 'only', 'retry'), { action: 'retry_shot', payload: { shot_id: 's01', base_version: 3, quote_id: 'quote-1' } })
  assert.throws(() => buildShotAction({ ...quote, can_retry: false }, context, 'only', 'retry'), /不可重试/)
  assert.throws(() => buildShotAction(quote, context, 'cascade', 'retry'), /不可重试/)
})
test('paid confirmations reject unknown prices and unsupported operations but cancellation stays free', () => {
  const unknown = { ...quote, estimated_credits: {} }
  assert.throws(() => buildShotAction(unknown, context, 'only', 'redo'), /费用/)
  assert.equal(buildShotAction(unknown, context, 'cancel', 'redo').payload.scope, 'cancel')
  assert.throws(() => buildShotAction(quote, context, 'other', 'redo'), /范围/)
  assert.throws(() => buildShotAction(quote, context, 'only', 'replace_all'), /不支持/)
})
test('buttons require both idle review state and server permission, never infer retry from failure alone', () => {
  const row = { status: 'failed', can_retry: true, can_redo: false }
  assert(productionActionAllowed('production_attention', row, 'retry'))
  assert(productionActionAllowed('awaiting_video_review', { can_redo: true }, 'redo'))
  assert(!productionActionAllowed('producing', row, 'retry'))
  assert(productionActionAllowed('awaiting_video_review', row, 'retry'))
  assert(!productionActionAllowed('awaiting_video_review', { can_retry: false }, 'retry'))
  assert(!productionActionAllowed('production_attention', { can_redo: true }, 'unknown'))
  assert(!productionActionAllowed('production_attention', row, 'redo'))
  assert(!productionActionAllowed('production_attention', row, 'retry', true))
  assert(!productionActionAllowed('production_attention', { status: 'failed' }, 'retry'))
})
test('error summaries remain display text and include diagnostic codes without executing content', () => {
  assert.equal(productionError({ code: 'SUBMISSION_UNKNOWN', summary: '<script>do not retry</script>' }), '<script>do not retry</script> · SUBMISSION_UNKNOWN')
  assert.equal(productionError('临时故障'), '临时故障')
  assert.equal(productionError(null), '')
})

test('starting after plan correction authorizes only remaining video costs and optional repair allowance', () => {
  assert.equal(startProductionCost({ video_credits: 120, remaining_credits: 15 }, 5), 20)
  assert.equal(startProductionCost({ remaining_credits: 0 }, 0), 0)
  assert.equal(startProductionCost({ video_credits: 120 }, 0), null)
  assert.equal(startProductionCost({ remaining_credits: 15 }, -1), null)
})

test('quotes disclose ungenerated continuation separately from redo scope without double-listing a cascade', () => {
  const withContinuation = { ...quote, continuation_shot_ids: ['s02', 's03', 's03'] }
  assert.deepEqual(quoteImpact(withContinuation, 'only').continuing, ['s02', 's03'])
  assert.deepEqual(quoteImpact(withContinuation, 'cascade').continuing, ['s03'])
  assert.equal(quoteImpact(withContinuation, 'only').cost, 15)
})

test('blocked tail-frame children can retry only when the server explicitly permits recovery', () => {
  assert(productionActionAllowed('production_attention', { status: 'blocked', can_retry: true }, 'retry'))
  assert(!productionActionAllowed('production_attention', { status: 'blocked', can_retry: false }, 'retry'))
  assert(!productionActionAllowed('producing', { status: 'blocked', can_retry: true }, 'retry'))
})
