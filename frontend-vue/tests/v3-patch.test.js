import test from 'node:test'
import assert from 'node:assert/strict'
import { buildPatchAction, createPatchQuoteSession, currentPatchQuote, patchApprovalIssue, patchContextKey, patchCosts, patchImpact, patchJson, patchReviewable } from '../src/components/agent/v3-patch.js'

const copy = (value) => JSON.parse(JSON.stringify(value))
function fixture(scope = 'only') {
  const quote = {
    patch_id: 'patch_1', base_version: 2, scope, quote_id: `quote_${scope}`,
    can_apply: true, manual_can_apply: true,
    affected_node_ids: ['frame', 'clip', 'old_clip'], execute_node_ids: ['frame', 'clip'],
    reused_node_ids: ['unchanged'], kept_node_ids: ['old_clip'], removed_node_ids: ['discarded'], continuation_node_ids: ['clip'],
    estimated_credits: { repair: 2, continuation: 5, total: 7 },
    node_costs: [
      { node_id: 'frame', action: 'execute', estimated_cost: 2, input_video_seconds: 0, output_video_seconds: 0 },
      { node_id: 'clip', action: 'execute', estimated_cost: 5, input_video_seconds: 0, output_video_seconds: 10 },
      { node_id: 'unchanged', action: 'reuse', estimated_cost: 0, input_video_seconds: 0, output_video_seconds: 0 },
      { node_id: 'old_clip', action: 'retain', estimated_cost: 0, input_video_seconds: 0, output_video_seconds: 10 },
      { node_id: 'other_failure', action: 'preserve_failure', estimated_cost: 0, input_video_seconds: 0, output_video_seconds: 0 },
    ],
    automatic: { eligible: false, reasons: ['RETAINS_OUTPUT'], remaining_credits: 3 },
    warnings: [{ code: 'RETAINED_HISTORICAL_OUTPUT', node_id: 'old_clip', message: '保留旧输入生成的片段。' }], issues: [], demo: true,
  }
  if (scope === 'cascade') {
    quote.kept_node_ids = []
    quote.execute_node_ids.push('old_clip')
    Object.assign(quote.node_costs[3], { action: 'execute', estimated_cost: 4 })
    quote.estimated_credits = { repair: 6, continuation: 5, total: 11 }
    quote.warnings = []
  }
  const patch = {
    patch_id: 'patch_1', status: 'awaiting_approval', base_version: 2, scope: 'only', author: 'repair',
    reason: '修正失败首帧提示词。', review: { verdict: 'approve', reason: '符合原要求。' },
    diff_preview: [{ op: 'update_inputs', node_id: 'frame', before: { prompt: '原描述' }, after: { prompt: '新描述' } }],
    quote: { ...copy(quote), scope: 'only', quote_id: 'stored_only_quote' },
  }
  const run = {
    schema_version: 3, run_id: 'run_1', status: 'attention', action_pending: false,
    plan: { plan_version: 2 }, patches: [patch], budget_limit: 100, estimated_spent: 20,
    repair_budget: { limit: 5, committed: 2, remaining: 3 },
    nodes: [{ node_id: 'frame', status: 'failed', attempt: 1, updated_at: '2026-10-19T00:00:00Z' }],
  }
  const receipt = { context_key: patchContextKey(run, patch, scope), quote }
  return { run, patch, quote, receipt, scope }
}
const action = ({ receipt, run, patch, scope }, type = 'approve_patch', acknowledged = true) => buildPatchAction(receipt, run, patch, scope, type, acknowledged)

test('manual action contains only the exact current quote identity and scope', () => {
  const state = fixture()
  const before = JSON.stringify(state)
  assert.deepEqual(action(state), { action: 'approve_patch', payload: { patch_id: 'patch_1', quote_id: 'quote_only', scope: 'only' } })
  assert.deepEqual(action(state, 'reject_patch'), { action: 'reject_patch', payload: { patch_id: 'patch_1', quote_id: 'quote_only', scope: 'only' } })
  assert.equal(JSON.stringify(state), before)
})

test('fresh cascade quote is independent of the old only quote in Run polling', () => {
  const state = fixture('cascade')
  assert.equal(state.patch.quote.scope, 'only')
  assert.equal(currentPatchQuote(state.receipt, state.run, state.patch, 'cascade'), true)
  assert.equal(action(state, 'approve_patch', false).payload.quote_id, 'quote_cascade')
})

test('stored quote without a captured context is never a new approval receipt', () => {
  const state = fixture()
  state.receipt = { quote: state.patch.quote }
  assert.throws(() => action(state), /报价已失效/)
})

test('quote must match the requested patch, version and scope with an opaque nonempty id', () => {
  for (const changed of [{ patch_id: 'foreign' }, { base_version: 3 }, { base_version: '2' }, { scope: 'cascade' }, { scope: null }, { quote_id: '' }, { quote_id: '   ' }, { quote_id: 1 }, { quote_id: 'x'.repeat(129) }]) {
    const state = fixture()
    Object.assign(state.quote, changed)
    assert.equal(currentPatchQuote(state.receipt, state.run, state.patch, state.scope), false)
    assert.throws(() => action(state, 'reject_patch'), /失效/)
  }
})

test('foreign, missing or stale Patch props cannot authorize an action', () => {
  const state = fixture()
  const stale = copy(state.patch)
  state.patch.reason = '新的修订原因'
  assert.equal(patchReviewable(state.run, stale), false)
  assert.equal(patchReviewable({ ...state.run, patches: [] }, state.patch), false)
  assert.equal(patchReviewable({ ...state.run, schema_version: 2 }, state.patch), false)
  assert.equal(patchReviewable(state.run, state.patch, true), false)
})

test('only completed independent Director review can admit quotation', () => {
  for (const verdict of ['approve', 'revise']) {
    const { run, patch } = fixture()
    patch.review.verdict = verdict
    assert.equal(patchReviewable(run, patch), true)
  }
  for (const verdict of ['reject', '', undefined]) {
    const { run, patch } = fixture()
    patch.review.verdict = verdict
    assert.equal(patchReviewable(run, patch), false)
  }
})

test('historical and unfinished patches remain read-only', () => {
  for (const status of ['applied', 'rejected', 'invalid', 'proposed', 'review_pending']) {
    const state = fixture()
    state.patch.status = status
    assert.equal(patchReviewable(state.run, state.patch), false)
    assert.throws(() => action(state, 'reject_patch'), /失效/)
  }
})

test('only current actionable Run states admit manual Patch actions', () => {
  for (const status of ['queued', 'understanding', 'executing', 'awaiting_gate', 'awaiting_plan_review', 'success', 'partial_success', 'failed', 'cancelled']) {
    const state = fixture()
    state.run.status = status
    assert.equal(patchReviewable(state.run, state.patch), false)
  }
  const { run, patch } = fixture()
  run.action_pending = true
  assert.equal(patchReviewable(run, patch), false)
})

test('context invalidates on run, version, scope, Patch content, status or stored quote changes', () => {
  for (const change of [
    (state) => { state.run.run_id = 'run_2' },
    (state) => { state.run.plan.plan_version++ },
    (state) => { state.scope = 'cascade' },
    (state) => { state.patch.status = 'reviewed' },
    (state) => { state.patch.diff_preview[0].after.prompt = '再修改' },
    (state) => { state.patch.review.reason = '新审阅' },
    (state) => { state.patch.quote.quote_id = 'new_server_quote' },
    (state) => { state.patch.quote.estimated_credits.total = 9 },
  ]) {
    const state = fixture()
    change(state)
    assert.equal(currentPatchQuote(state.receipt, state.run, state.patch, state.scope), false)
  }
})

test('budget and task changes invalidate a receipt, but unrelated poll timestamps do not', () => {
  for (const change of [
    (state) => { state.run.budget_limit-- },
    (state) => { state.run.estimated_spent++ },
    (state) => { state.run.repair_budget.remaining-- },
    (state) => { state.run.nodes[0].attempt++ },
    (state) => { state.run.nodes[0].status = 'running' },
    (state) => { state.run.nodes[0].updated_at = '2026-10-19T01:00:00Z' },
  ]) {
    const state = fixture()
    change(state)
    assert.equal(currentPatchQuote(state.receipt, state.run, state.patch, state.scope), false)
  }
  const state = fixture()
  state.run.updated_at = '2026-10-19T01:00:00Z'
  assert.equal(currentPatchQuote(state.receipt, state.run, state.patch, state.scope), true)
})

test('equivalent JSON objects keep the same context across polling', () => {
  const state = fixture()
  const reordered = Object.fromEntries(Object.entries(state.patch).reverse())
  assert.equal(patchContextKey(copy(state.run), reordered, state.scope), state.receipt.context_key)
})

test('only mode requires an explicit acknowledgement of retained downstream risk', () => {
  const state = fixture()
  assert.match(patchApprovalIssue(state.receipt, state.run, state.patch, 'only'), /衔接风险/)
  for (const value of [false, 1, 'true']) assert.throws(() => action(state, 'approve_patch', value), /衔接风险/)
  assert.throws(() => buildPatchAction(state.receipt, state.run, state.patch, 'only', 'approve_patch'), /衔接风险/)
  assert.equal(action(state, 'approve_patch', true).action, 'approve_patch')
  assert.equal(action(state, 'reject_patch', false).action, 'reject_patch')
})

test('automatic eligibility does not grant manual approval', () => {
  const state = fixture()
  state.quote.automatic.eligible = true
  state.quote.manual_can_apply = false
  assert.throws(() => action(state), /不允许人工批准/)
  assert.equal(action(state, 'reject_patch').action, 'reject_patch')
})

test('missing manual eligibility and global refusal fail closed', () => {
  for (const changes of [{ manual_can_apply: undefined }, { manual_can_apply: 'true' }, { can_apply: false }]) {
    const state = fixture()
    Object.assign(state.quote, changes)
    assert.throws(() => action(state), /不允许人工批准/)
  }
})

test('unknown, nonnumeric and negative costs never become free approvals', () => {
  for (const value of [undefined, null, '0', NaN, Infinity, -Infinity, -1]) {
    for (const field of ['repair', 'continuation', 'total']) {
      const state = fixture()
      state.quote.estimated_credits[field] = value
      assert.equal(patchCosts(state.quote), null)
      assert.throws(() => action(state), /费用或影响范围/)
      assert.equal(action(state, 'reject_patch').action, 'reject_patch')
    }
  }
})

test('invalid node costs and seconds block paid confirmation', () => {
  for (const field of ['estimated_cost', 'input_video_seconds', 'output_video_seconds']) {
    for (const value of [undefined, null, '0', NaN, Infinity, -1]) {
      const state = fixture()
      state.quote.node_costs[0][field] = value
      assert.equal(patchCosts(state.quote), null)
      assert.throws(() => action(state), /费用或影响范围/)
    }
  }
})

test('server totals must agree with split and node costs, including overflow rejection', () => {
  const state = fixture()
  state.quote.estimated_credits.total = 8
  assert.equal(patchCosts(state.quote), null)
  state.quote.estimated_credits = { repair: 2, continuation: 5, total: 7 }
  state.quote.node_costs[0].estimated_cost = 3
  assert.equal(patchCosts(state.quote), null)
  state.quote.estimated_credits = { repair: Number.MAX_VALUE, continuation: Number.MAX_VALUE, total: Number.MAX_VALUE }
  assert.equal(patchCosts(state.quote), null)
})

test('explicit zero-cost execution remains valid', () => {
  const state = fixture()
  state.quote.estimated_credits = { repair: 0, continuation: 0, total: 0 }
  for (const node of state.quote.node_costs) node.estimated_cost = 0
  assert.deepEqual(patchCosts(state.quote), { repair: 0, continuation: 0, total: 0 })
  assert.equal(action(state).action, 'approve_patch')
})

test('impact separates repaired work from unstarted continuation and kept failures', () => {
  const { quote } = fixture()
  assert.deepEqual(patchImpact(quote), {
    affected: ['frame', 'clip', 'old_clip'], executing: ['frame'], continuing: ['clip'],
    reused: ['unchanged'], retained: ['old_clip'], removed: ['discarded'], failed: ['other_failure'],
  })
})

test('incomplete or contradictory impact data cannot bypass acknowledgement', () => {
  for (const change of [
    (quote) => { delete quote.kept_node_ids },
    (quote) => { quote.kept_node_ids = [] },
    (quote) => { quote.kept_node_ids = ['old_clip', 'old_clip'] },
    (quote) => { quote.continuation_node_ids = ['not_executed'] },
    (quote) => { quote.removed_node_ids = ['frame'] },
    (quote) => { quote.node_costs.push({ ...quote.node_costs[2] }) },
    (quote) => { quote.node_costs[2].action = 'unknown' },
  ]) {
    const state = fixture()
    change(state.quote)
    assert.throws(() => action(state), /费用或影响范围/)
    assert.equal(action(state, 'reject_patch').action, 'reject_patch')
  }
})

test('malformed node-cost rows fail closed without breaking the review controls', () => {
  for (const row of [null, false, 3, 'frame', [], {}]) {
    const state = fixture()
    state.quote.node_costs.push(row)
    assert.equal(patchCosts(state.quote), null)
    assert.match(patchApprovalIssue(state.receipt, state.run, state.patch, state.scope, true), /费用或影响范围/)
    assert.equal(action(state, 'reject_patch').action, 'reject_patch')
    assert.deepEqual(patchImpact(state.quote).retained, ['old_clip'])
  }
})

test('API helper must provide the unwrapped quote, never an HTTP envelope', () => {
  const state = fixture()
  state.receipt.quote = { success: true, data: state.quote }
  assert.equal(currentPatchQuote(state.receipt, state.run, state.patch, state.scope), false)
  assert.throws(() => action(state, 'reject_patch'), /失效/)
})

test('blocking issues prevent approval but still permit rejecting the current patch', () => {
  for (const issues of [undefined, null, [{ code: 'INVALID_PLAN', message: '无法执行' }]]) {
    const state = fixture()
    state.quote.issues = issues
    assert.throws(() => action(state), /未解决的问题/)
    assert.equal(action(state, 'reject_patch').action, 'reject_patch')
  }
})

test('unsupported actions cannot be sent through the patch helper', () => {
  assert.throws(() => action(fixture(), 'resume'), /不支持/)
})

test('late only response is discarded after a cascade request', () => {
  const session = createPatchQuoteSession()
  const only = fixture(), cascade = fixture('cascade')
  const old = session.begin(only.receipt.context_key)
  const latest = session.begin(cascade.receipt.context_key)
  assert.equal(session.accept(old, cascade.receipt.context_key, only.quote), null)
  const received = session.accept(latest, cascade.receipt.context_key, cascade.quote)
  assert.equal(currentPatchQuote(received, cascade.run, cascade.patch, cascade.scope), true)
  assert.equal(session.accept(old, only.receipt.context_key, only.quote), null)
})

test('new request in the same scope invalidates an older in-flight request', () => {
  const state = fixture(), session = createPatchQuoteSession()
  const old = session.begin(state.receipt.context_key)
  const latest = session.begin(state.receipt.context_key)
  assert.equal(session.accept(old, state.receipt.context_key, state.quote), null)
  assert.equal(session.accept(latest, state.receipt.context_key, state.quote).quote.quote_id, 'quote_only')
})

test('context drift discards responses even when the network ignores abort', () => {
  const state = fixture(), session = createPatchQuoteSession()
  const ticket = session.begin(state.receipt.context_key)
  state.run.run_id = 'run_other'
  const nextKey = patchContextKey(state.run, state.patch, state.scope)
  assert.equal(session.accept(ticket, nextKey, state.quote), null)
})

test('invalidation cannot be undone by restoring the previous context', () => {
  const state = fixture(), session = createPatchQuoteSession()
  const ticket = session.begin(state.receipt.context_key)
  session.invalidate()
  assert.equal(session.accept(ticket, state.receipt.context_key, state.quote), null)
})

test('unmount disposal rejects late results and any further request', () => {
  const state = fixture(), session = createPatchQuoteSession()
  const ticket = session.begin(state.receipt.context_key)
  session.dispose()
  assert.equal(session.accept(ticket, state.receipt.context_key, state.quote), null)
  assert.equal(session.current(ticket, state.receipt.context_key), false)
  assert.equal(session.begin(state.receipt.context_key), null)
})

test('accepted quote is detached from the mutable HTTP response', () => {
  const state = fixture(), session = createPatchQuoteSession()
  const ticket = session.begin(state.receipt.context_key)
  const received = session.accept(ticket, state.receipt.context_key, state.quote)
  state.quote.quote_id = 'later_mutation'
  assert.equal(received.quote.quote_id, 'quote_only')
})

test('diff formatting is plain text and leaves untrusted strings intact for Vue escaping', () => {
  assert.equal(patchJson(null), '无')
  const text = patchJson({ prompt: '<img src=x onerror=alert(1)>' })
  assert.match(text, /<img src=x onerror=alert\(1\)>/)
  assert.deepEqual(JSON.parse(text), { prompt: '<img src=x onerror=alert(1)>' })
})
