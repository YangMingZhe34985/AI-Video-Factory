import test from 'node:test'
import assert from 'node:assert/strict'
import { createV3ActionSession, v3ActionAllowed, v3StatusLabel, creditLabel } from '../src/components/agent/v3-actions.js'

const copy = (value) => JSON.parse(JSON.stringify(value))
function reviewRun(overrides = {}) {
  return {
    run_id: 'run-3', schema_version: 3, status: 'awaiting_plan_review',
    action_pending: false, resume_count: 0,
    plan: { plan_version: 2, nodes: [{ id: 'image', gate: 'preview' }, { id: 'video' }] },
    plan_issues: [], estimates: { total_credits: 40 }, budget_limit: 60, estimated_spent: 5,
    nodes: [], patches: [], ...overrides,
  }
}
function gateRun() {
  return reviewRun({ status: 'awaiting_gate', nodes: [
    { node_id: 'image', gate: 'preview', status: 'success', gate_approved: false },
    { node_id: 'video', status: 'pending' },
  ] })
}
function resultRun() {
  return reviewRun({ status: 'awaiting_result_review', nodes: [
    { node_id: 'image', gate: 'preview', status: 'success', gate_approved: true },
    { node_id: 'video', status: 'success' },
  ] })
}
function patchRun() {
  return reviewRun({ status: 'attention', patches: [{
    patch_id: 'patch-1', status: 'awaiting_approval', base_version: 2,
    quote: { quote_id: 'old-only', scope: 'only', can_apply: true },
  }] })
}
function inputRun() {
  return reviewRun({ status: 'awaiting_input', pending_card: {
    card_id: 'card-1', questions: [
      { question_id: 'character', blocking: true, allow_free_text: false, options: [{ option_id: 'blue' }, { option_id: 'white' }] },
      { question_id: 'tone', blocking: false, allow_free_text: true, options: [{ option_id: 'bright' }], default_option_id: 'bright' },
    ],
  } })
}
const approve = { plan_version: 2, repair_budget_credits: 5 }
const patch = { patch_id: 'patch-1', quote_id: 'fresh-cascade', scope: 'cascade' }

test('same normalized request retries with one key and returned body mutations cannot alter the pending request', () => {
  const session = createV3ActionSession(), run = reviewRun()
  const first = session.prepare(run, 'revise_plan', { plan_version: 2, message: '  让镜头更明亮  ' })
  const retry = session.prepare(copy(run), 'revise_plan', { message: '让镜头更明亮', plan_version: 2 })
  assert.equal(retry.request_key, first.request_key)
  assert.deepEqual(retry, { action: 'revise_plan', plan_version: 2, message: '让镜头更明亮', request_key: first.request_key })
  first.message = 'caller mutation'
  first.request_key = 'caller key'
  assert.deepEqual(session.prepare(run, 'revise_plan', { plan_version: 2, message: '让镜头更明亮' }), retry)
})

test('request body, plan version, run identity and patch scope changes produce new keys', () => {
  const session = createV3ActionSession(), run = reviewRun()
  const a = session.prepare(run, 'revise_plan', { plan_version: 2, message: '更明亮' })
  const b = session.prepare(run, 'revise_plan', { plan_version: 2, message: '更温暖' })
  const changedVersion = reviewRun({ plan: { ...run.plan, plan_version: 3 } })
  const c = session.prepare(changedVersion, 'revise_plan', { plan_version: 3, message: '更温暖' })
  const d = session.prepare({ ...changedVersion, run_id: 'another-run' }, 'revise_plan', { plan_version: 3, message: '更温暖' })
  const e = session.prepare(patchRun(), 'approve_patch', patch)
  const f = session.prepare(patchRun(), 'approve_patch', { ...patch, scope: 'only' })
  assert.equal(new Set([a, b, c, d, e, f].map((body) => body.request_key)).size, 6)
})

test('acknowledge and reset clear completed or abandoned actions; failed validation retains a retry key', () => {
  const session = createV3ActionSession(), run = reviewRun()
  const first = session.prepare(run, 'approve_plan', approve)
  assert.throws(() => session.prepare(run, 'approve_plan', { ...approve, unexpected: true }), /不支持/)
  assert.equal(session.prepare(run, 'approve_plan', approve).request_key, first.request_key)
  session.acknowledge()
  const next = session.prepare(run, 'approve_plan', approve)
  assert.notEqual(next.request_key, first.request_key)
  session.reset()
  assert.notEqual(session.prepare(run, 'approve_plan', approve).request_key, next.request_key)
})

test('extra payload fields, caller-supplied keys, unsupported actions and non-v3 runs fail closed', () => {
  const run = reviewRun(), session = createV3ActionSession()
  for (const field of ['request_key', 'action', 'model_id', 'plan']) {
    assert(!v3ActionAllowed(run, 'approve_plan', { ...approve, [field]: 'injected' }))
  }
  for (const action of ['constructor', 'toString', 'generate_video', null, {}]) {
    assert(!v3ActionAllowed(run, action, {}))
  }
  for (const broken of [null, { ...run, schema_version: 2 }, { ...run, run_id: '' }]) {
    assert.throws(() => session.prepare(broken, 'approve_plan', approve))
  }
  assert(!v3ActionAllowed(run, 'approve_plan', null))
  assert(!v3ActionAllowed(run, 'approve_plan', []))
})

test('approval requires the exact positive integer version from the server', () => {
  for (const plan_version of [undefined, null, 0, -1, 1, 3, 2.1, '2', NaN, Infinity]) {
    assert(!v3ActionAllowed(reviewRun(), 'approve_plan', { ...approve, plan_version }))
  }
  assert(!v3ActionAllowed(reviewRun({ plan: null }), 'approve_plan', approve))
  assert(v3ActionAllowed(reviewRun(), 'approve_plan', approve))
})

test('unknown or invalid total, spent, budget and repair prices cannot authorize a plan', () => {
  const invalid = [undefined, null, NaN, Infinity, -1, '0']
  for (const value of invalid) {
    assert(!v3ActionAllowed(reviewRun({ estimates: { total_credits: value } }), 'approve_plan', approve))
    assert(!v3ActionAllowed(reviewRun({ estimated_spent: value }), 'approve_plan', approve))
    assert(!v3ActionAllowed(reviewRun({ budget_limit: value }), 'approve_plan', approve))
    assert(!v3ActionAllowed(reviewRun(), 'approve_plan', { ...approve, repair_budget_credits: value }))
  }
  assert(!v3ActionAllowed(reviewRun({ estimates: {} }), 'approve_plan', approve))
  assert(!v3ActionAllowed(reviewRun({ plan_issues: undefined }), 'approve_plan', approve))
  assert(!v3ActionAllowed(reviewRun({ plan_issues: [{ code: 'INVALID' }] }), 'approve_plan', approve))
})

test('zero is a known price and original spend plus repair reserve must fit the total budget', () => {
  const session = createV3ActionSession()
  assert(v3ActionAllowed(reviewRun({ estimates: { total_credits: 0 }, estimated_spent: 0, budget_limit: 0 }), 'approve_plan', { plan_version: 2 }))
  assert.equal(session.prepare(reviewRun(), 'approve_plan', { plan_version: 2 }).repair_budget_credits, 0)
  assert(v3ActionAllowed(reviewRun({ budget_limit: 50 }), 'approve_plan', approve))
  assert(!v3ActionAllowed(reviewRun({ budget_limit: 49.99 }), 'approve_plan', approve))
  assert(!v3ActionAllowed(reviewRun({ estimates: { total_credits: Number.MAX_VALUE }, budget_limit: Number.MAX_VALUE, estimated_spent: Number.MAX_VALUE }), 'approve_plan', approve))
})

test('an ordinary pending command disables new actions; attention can recover or reject an unknown old command', () => {
  assert(!v3ActionAllowed(reviewRun({ action_pending: true }), 'approve_plan', approve))
  const attention = reviewRun({ status: 'attention', action_pending: true })
  assert(v3ActionAllowed(attention, 'resume'))
  assert(v3ActionAllowed(attention, 'reject'))
  assert(!v3ActionAllowed(attention, 'revise_plan', { plan_version: 2, message: '重试' }))
  assert(!v3ActionAllowed({ ...attention, resume_count: 2 }, 'resume'))
  assert(!v3ActionAllowed({ ...attention, resume_count: undefined }, 'resume'))
  assert(!v3ActionAllowed(reviewRun({ status: 'understanding', action_pending: true }), 'reject'))
})

test('task rejection is allowed only for a known nonterminal run state', () => {
  for (const status of ['queued', 'understanding', 'awaiting_input', 'executing', 'delivering', 'attention']) {
    assert(v3ActionAllowed(reviewRun({ status }), 'reject'))
  }
  for (const status of ['success', 'partial_success', 'failed', 'cancelled', 'applied', 'constructor', 'unknown']) {
    assert(!v3ActionAllowed(reviewRun({ status }), 'reject'))
  }
})

test('a gate approval targets a successful preview in the exact plan and task snapshot', () => {
  const payload = { plan_version: 2, gate_node_id: 'image' }
  assert(v3ActionAllowed(gateRun(), 'approve_gate', payload))
  assert(!v3ActionAllowed(gateRun(), 'approve_gate', { ...payload, gate_node_id: 'missing' }))
  assert(!v3ActionAllowed(gateRun(), 'approve_gate', { plan_version: 2 }))
  assert(!v3ActionAllowed(reviewRun(), 'approve_gate', payload))
  for (const override of [{ status: 'pending' }, { gate_approved: true }, { gate: null }]) {
    const run = gateRun()
    Object.assign(run.nodes[0], override)
    assert(!v3ActionAllowed(run, 'approve_gate', payload))
  }
})

test('result acceptance requires every current plan node and all preview approvals', () => {
  assert(v3ActionAllowed(resultRun(), 'approve_results', { plan_version: 2 }))
  for (const change of [
    (run) => { run.nodes[0].gate_approved = false },
    (run) => { run.nodes[1].status = 'failed' },
    (run) => { run.nodes.pop() },
    (run) => { run.nodes[1].node_id = 'old-video' },
    (run) => { run.nodes[1].node_id = 'image' },
  ]) {
    const run = resultRun()
    change(run)
    assert(!v3ActionAllowed(run, 'approve_results', { plan_version: 2 }))
  }
})

test('revision feedback is trimmed and a pending gate requires explicit gate identity', () => {
  const session = createV3ActionSession(), payload = { plan_version: 2, message: '  替换背景  ' }
  assert(!v3ActionAllowed(gateRun(), 'revise_plan', payload))
  const valid = session.prepare(gateRun(), 'revise_plan', { ...payload, gate_node_id: 'image' })
  assert.equal(valid.message, '替换背景')
  assert.equal(valid.gate_node_id, 'image')
  assert(!v3ActionAllowed(reviewRun(), 'revise_plan', { ...payload, gate_node_id: 'image' }))
  assert(!v3ActionAllowed(reviewRun(), 'revise_plan', { ...payload, message: '  ' }))
  assert(!v3ActionAllowed(reviewRun(), 'revise_plan', { ...payload, message: '字'.repeat(4001) }))
})

test('a running or unknown submission prevents plan revision until recovery has resolved it', () => {
  const payload = { plan_version: 2, message: '重新生成' }
  for (const node of [
    { node_id: 'video', status: 'running' },
    { node_id: 'video', status: 'failed', error: { category: 'submit_unknown' } },
    { node_id: 'video', status: 'failed', error: { submission_state: 'unknown' } },
  ]) {
    assert(!v3ActionAllowed(reviewRun({ status: 'attention', nodes: [node] }), 'revise_plan', payload))
  }
  assert(v3ActionAllowed(reviewRun({ status: 'attention', nodes: [{ status: 'failed', error: { category: 'known_not_submitted' } }] }), 'revise_plan', payload))
})

test('patch actions accept the freshly quoted chosen scope without comparing stale polling quotes', () => {
  const session = createV3ActionSession(), run = patchRun()
  assert(v3ActionAllowed(run, 'approve_patch', patch))
  const body = session.prepare(run, 'approve_patch', patch)
  assert.deepEqual({ ...body, request_key: undefined }, { action: 'approve_patch', ...patch, request_key: undefined })
  assert(v3ActionAllowed(run, 'reject_patch', patch))
  assert(v3ActionAllowed({ ...run, status: 'awaiting_result_review' }, 'approve_patch', patch))
  // The parent Patch component owns current quote cost and manual_can_apply checks.
  delete run.patches[0].quote
  assert(v3ActionAllowed(run, 'approve_patch', patch))
})

test('patch actions require a real reviewed patch, exact base version and only the necessary fields', () => {
  for (const payload of [
    { ...patch, patch_id: 'missing' }, { ...patch, quote_id: '' }, { ...patch, scope: 'all' },
    { patch_id: 'patch-1', quote_id: 'quote-1' }, { ...patch, plan_version: 2 }, { ...patch, budget_credits: 0 },
  ]) assert(!v3ActionAllowed(patchRun(), 'approve_patch', payload))
  for (const status of ['proposed', 'awaiting_review', 'applied', 'rejected', 'invalid']) {
    const run = patchRun()
    run.patches[0].status = status
    assert(!v3ActionAllowed(run, 'approve_patch', patch))
  }
  const stale = patchRun()
  stale.patches[0].base_version = 1
  assert(!v3ActionAllowed(stale, 'approve_patch', patch))
  assert(!v3ActionAllowed({ ...patchRun(), status: 'executing' }, 'approve_patch', patch))
  assert(!v3ActionAllowed({ ...patchRun(), action_pending: true }, 'reject_patch', patch))
})

test('patch identifiers follow the public API 128-character boundary', () => {
  const run = patchRun(), id = 'p'.repeat(128)
  run.patches[0].patch_id = id
  assert(v3ActionAllowed(run, 'approve_patch', { ...patch, patch_id: id }))
  run.patches[0].patch_id = `${id}x`
  assert(!v3ActionAllowed(run, 'approve_patch', { ...patch, patch_id: `${id}x` }))
})

test('clarification retries sort answers by question identity and retain one key', () => {
  const session = createV3ActionSession(), run = inputRun()
  const answers = [{ question_id: 'tone', text: '  温暖  ' }, { question_id: 'character', option_id: 'blue' }]
  const first = session.prepare(run, 'answer', { card_id: 'card-1', answers })
  const second = session.prepare(run, 'answer', { answers: [{ question_id: 'character', option_id: 'blue' }, { question_id: 'tone', text: '温暖' }], use_defaults: false, card_id: 'card-1' })
  assert.deepEqual(second, first)
  assert.equal(second.answers[0].question_id, 'character')
  assert.equal(second.answers[1].text, '温暖')
  assert(!Object.hasOwn(second, 'plan_version'))
})

test('clarification rejects stale cards, duplicate questions, unsupported options and two simultaneous answers', () => {
  const run = inputRun(), valid = { question_id: 'character', option_id: 'blue' }
  const payload = { card_id: 'card-1', answers: [valid] }
  assert(v3ActionAllowed(run, 'answer', payload))
  assert(!v3ActionAllowed(run, 'answer', { ...payload, card_id: 'old-card' }))
  for (const answers of [
    [valid, valid], [{ question_id: 'unknown', option_id: 'blue' }],
    [{ question_id: 'character', option_id: 'missing' }],
    [{ ...valid, text: 'both' }], [{ question_id: 'character', text: 'not allowed' }],
    [{ ...valid, injected: true }], [{ question_id: 'character' }],
  ]) assert(!v3ActionAllowed(run, 'answer', { ...payload, answers }))
})

test('defaults never bypass an unanswered blocking question', () => {
  const run = inputRun()
  assert(!v3ActionAllowed(run, 'answer', { card_id: 'card-1', answers: [], use_defaults: true }))
  assert(v3ActionAllowed(run, 'answer', { card_id: 'card-1', answers: [{ question_id: 'character', option_id: 'white' }], use_defaults: true }))
  assert(!v3ActionAllowed(run, 'answer', { card_id: 'card-1', answers: [], use_defaults: 'true' }))
})

test('status and cost labels show unknown data honestly without exposing prototype values', () => {
  assert.equal(v3StatusLabel('awaiting_plan_review'), '等待计划审核')
  assert.equal(v3StatusLabel('awaiting_review'), '等待独立审阅')
  assert.equal(v3StatusLabel('waiting_dependency'), '等待上游结果')
  for (const status of ['constructor', 'toString', '__proto__', 'unknown', null, {}]) {
    assert.equal(v3StatusLabel(status), '未知状态')
  }
  for (const value of [undefined, null, NaN, Infinity, -1, '0']) assert.equal(creditLabel(value), '待服务器估算')
  assert.equal(creditLabel(0), '0')
  assert.equal(creditLabel(12.345), '12.35')
})
