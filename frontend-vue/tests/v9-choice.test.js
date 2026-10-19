import test from 'node:test'
import assert from 'node:assert/strict'
import { buildPlanAction, choiceIdentity, dependencyState, gateReady, planRows } from '../src/components/agent/v3-plan.js'
import { createV3ActionSession } from '../src/components/agent/v3-actions.js'

const asset = (id) => ({ artifact_id: id, mime_type: 'image/png', preview_url: `/api/artifacts/${id}/preview` })
function fixture() {
  return { run_id: 'run_choice', schema_version: 3, status: 'awaiting_gate', action_pending: false,
    plan: { plan_version: 2, nodes: [{ id: 'choose', tool: 'select_image', gate: 'choice' }, { id: 'clip', tool: 'animate_shot' }] },
    nodes: [{ node_id: 'choose', status: 'pending', gate: 'choice', gate_approved: false, depends_on: [],
      choice: { ready: true, choice_digest: 'a'.repeat(64), candidates: [asset('a'), asset('b')], selected_artifact_id: null } },
    { node_id: 'clip', status: 'pending', depends_on: ['choose'] }], estimates: { nodes: [] } }
}
const values = { expectedVersion: 2, gateNodeId: 'choose', selectedArtifactId: 'b', choiceDigest: 'a'.repeat(64) }

test('choice requires an explicit current candidate and includes version and digest in stable retries', () => {
  const run = fixture(), session = createV3ActionSession()
  assert.throws(() => buildPlanAction(run, 'approve_gate', { ...values, selectedArtifactId: '' }))
  assert.throws(() => buildPlanAction(run, 'approve_gate', { ...values, selectedArtifactId: 'foreign' }))
  assert.throws(() => buildPlanAction(run, 'approve_gate', { ...values, choiceDigest: 'old' }))
  const action = buildPlanAction(run, 'approve_gate', values)
  assert.deepEqual(action.payload, { plan_version: 2, gate_node_id: 'choose', selected_artifact_id: 'b', choice_digest: 'a'.repeat(64) })
  const first = session.prepare(run, action.action, action.payload)
  assert.deepEqual(session.prepare(structuredClone(run), action.action, action.payload), first)
  const changed = session.prepare(run, action.action, { ...action.payload, selected_artifact_id: 'a' })
  assert.notEqual(changed.request_key, first.request_key)
})

test('choice invalidation key preserves equivalent polling and changes with digest or order', () => {
  const run = fixture(), key = choiceIdentity(planRows(run)[0])
  assert.equal(choiceIdentity(planRows(structuredClone(run))[0]), key)
  run.nodes[0].choice.candidates.reverse()
  assert.notEqual(choiceIdentity(planRows(run)[0]), key)
  run.nodes[0].choice.candidates.reverse()
  run.nodes[0].choice.choice_digest = 'b'.repeat(64)
  assert.notEqual(choiceIdentity(planRows(run)[0]), key)
  run.nodes[0].gate_approved = true
  assert.equal(choiceIdentity(planRows(run)[0]), '')
})

test('ready pending choice accepts feedback and blocks downstream until selected output succeeds', () => {
  const run = fixture(), rows = planRows(run)
  assert.equal(gateReady(rows[0]), true)
  assert.equal(dependencyState(rows[0], rows).kind, 'choice')
  assert.equal(dependencyState(rows[1], rows).kind, 'waiting')
  assert.equal(buildPlanAction(run, 'revise_plan', { ...values, message: '候选都不满意' }).payload.gate_node_id, 'choose')
  run.nodes[0].choice.ready = false
  assert.throws(() => buildPlanAction(run, 'approve_gate', values))
  assert.throws(() => buildPlanAction(run, 'revise_plan', { ...values, message: '修改' }))
})

test('public action admission rejects stale selection, mismatched gates and preview choice injection', () => {
  const run = fixture(), session = createV3ActionSession()
  const body = buildPlanAction(run, 'approve_gate', values).payload
  run.nodes[0].choice.choice_digest = 'changed'
  assert.throws(() => session.prepare(run, 'approve_gate', body))
  run.nodes[0].choice.choice_digest = body.choice_digest
  run.plan.plan_version++
  assert.throws(() => session.prepare(run, 'approve_gate', body))
  run.plan.plan_version--
  run.nodes[0].gate = run.plan.nodes[0].gate = 'preview'
  run.nodes[0].status = 'success'
  assert.throws(() => session.prepare(run, 'approve_gate', body))
  assert.equal(session.prepare(run, 'approve_gate', { plan_version: 2, gate_node_id: 'choose' }).gate_node_id, 'choose')
})

test('result approval requires choice receipt even when all nodes report success', () => {
  const run = fixture(), session = createV3ActionSession()
  run.status = 'awaiting_result_review'
  run.nodes.forEach((node) => { node.status = 'success' })
  assert.throws(() => session.prepare(run, 'approve_results', { plan_version: 2 }))
  run.nodes[0].gate_approved = true
  assert.equal(session.prepare(run, 'approve_results', { plan_version: 2 }).action, 'approve_results')
})
