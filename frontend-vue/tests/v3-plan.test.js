import test from 'node:test'
import assert from 'node:assert/strict'
import { agentTree, buildPlanAction, createStepPager, dependencyState, initialApprovalCost, nodeAssets, planGroups, planRows, planTotals, publicError, secondsLabel } from '../src/components/agent/v3-plan.js'

function runFixture() {
  return {
    run_id: 'run_demo', schema_version: 3, status: 'awaiting_plan_review', action_pending: false,
    budget_limit: 100, estimated_spent: 2, plan_issues: [],
    plan: { plan_version: 3, stages: [{ id: 'frames', label: '关键帧' }, { id: 'story', label: '故事' }], nodes: [
      { id: 'frame', tool: 'generate_image', model_id: 'demo-image', gate: 'preview', stage: 'frames', inputs: { prompt: '猫' }, params: { n: 1 } },
      { id: 'clip', tool: 'animate_shot', model_id: 'demo-video', stage: 'story', depends_on: [], inputs: { prompt: '抬头', first_frame_artifact_id: { ref: 'frame.image' } }, params: { duration: 10 } },
      { id: 'independent', tool: 'generate_video', stage: 'story', inputs: { prompt: '远景' }, params: { duration: 5 } },
    ] },
    nodes: [
      { node_id: 'frame', status: 'pending', gate: 'preview', gate_approved: false, depends_on: [], estimated_cost: 0 },
      { node_id: 'clip', status: 'pending', depends_on: ['frame'], estimated_cost: 0 },
      { node_id: 'independent', status: 'pending', depends_on: [], estimated_cost: 0 },
    ],
    estimates: { total_credits: 17, video_seconds: 15, generated_video_seconds: 15, nodes: [
      { node_id: 'frame', estimated_cost: 2, input_video_seconds: 0, output_video_seconds: 0 },
      { node_id: 'clip', estimated_cost: 10, input_video_seconds: 0, output_video_seconds: 10 },
      { node_id: 'independent', estimated_cost: 5, input_video_seconds: 0, output_video_seconds: 5 },
    ] },
  }
}

test('rows use compiled dependency and estimate projections without mutating the plan', () => {
  const run = runFixture(), before = JSON.stringify(run), rows = planRows(run)
  assert.deepEqual(rows[1].depends_on, ['frame'])
  assert.equal(rows[1].estimated_cost, 10)
  assert.equal(rows[0].duration, null)
  assert.equal(rows[1].duration, 10)
  assert.equal(JSON.stringify(run), before)
  delete run.estimates.nodes
  assert.equal(planRows(run)[1].estimated_cost, null, 'placeholder task zero is not an estimate')
})

test('stage rendering keeps nodes from unknown or absent stages and preserves plan order', () => {
  const run = runFixture()
  run.plan.nodes.push({ id: 'keep', tool: 'retain_video_segment', inputs: { source_start_sec: 2, source_end_sec: 6 } })
  run.plan.nodes.push({ id: 'pack', tool: 'package_story', stage: 'delivery' })
  const groups = planGroups(run)
  assert.deepEqual(groups.map((group) => group.id), ['frames', 'story', '__unstaged__', 'delivery'])
  assert.deepEqual(groups.flatMap((group) => group.nodes.map((row) => row.id)), ['frame', 'clip', 'independent', 'keep', 'pack'])
  assert.equal(groups[2].nodes[0].duration, 4)
})

test('dependency badges distinguish a pending gate from actual readiness, not just completed output', () => {
  const run = runFixture()
  run.nodes[0].status = 'success'
  let rows = planRows(run)
  assert.equal(dependencyState(rows[1], rows).kind, 'waiting')
  assert.equal(dependencyState(rows[2], rows).kind, 'ready')
  run.nodes[0].gate_approved = true
  rows = planRows(run)
  assert.equal(dependencyState(rows[1], rows).kind, 'ready')
  delete run.nodes[2].depends_on
  rows = planRows(run)
  assert.equal(dependencyState(rows[2], rows).kind, 'unknown')
})

test('retained outputs disclose their historical version instead of appearing as new generation', () => {
  const run = runFixture()
  Object.assign(run.nodes[1], { status: 'success', retained: true, source_plan_version: 1, reused_from_task_id: 9 })
  const row = planRows(run)[1]
  assert.equal(row.source_plan_version, 1)
  assert.equal(row.retained, true)
  assert.match(dependencyState(row, planRows(run)).label, /保留既有产物/)
})

test('duration overview uses authoritative delivery and cumulative generation seconds, not node sums', () => {
  const run = runFixture()
  run.estimates.video_seconds = 120
  run.estimates.generated_video_seconds = 90
  assert.deepEqual(planTotals(run), { deliveredSeconds: 120, generatedSeconds: 90, credits: 17 })
  assert.deepEqual(planTotals({}), { deliveredSeconds: null, generatedSeconds: null, credits: null })
  assert.equal(secondsLabel(0), '0 秒')
  for (const invalid of [null, undefined, '5', Infinity, NaN, -2]) assert.equal(secondsLabel(invalid), '待服务器确认')
})

test('artifact previews accept only exact local artifact routes and supported media types', () => {
  const asset = { artifact_id: 'art_a', mime_type: 'image/png', preview_url: '/api/artifacts/art_a/preview', download_url: '/api/artifacts/art_a/download' }
  assert.equal(nodeAssets([asset])[0].preview, asset.preview_url)
  assert.equal(nodeAssets([asset])[0].kind, 'image')
  for (const preview_url of ['https://example.com/art.png', '//example.com/a', '/api/artifacts/other/preview', '/api/artifacts/art_a/preview?token=secret']) {
    assert.equal(nodeAssets([{ ...asset, preview_url }])[0].preview, '')
  }
  assert.equal(nodeAssets([{ ...asset, mime_type: 'image/svg+xml' }])[0].kind, 'file')
  assert.equal(nodeAssets([{ ...asset, artifact_id: '../outside' }])[0].preview, '')
})

test('plan approval sends exact version and finite optional repair allowance with no model payload', () => {
  const run = runFixture()
  assert.deepEqual(buildPlanAction(run, 'approve_plan', { expectedVersion: 3, repairCredits: '' }), {
    action: 'approve_plan', payload: { plan_version: 3, repair_budget_credits: 0 },
  })
  assert.equal(initialApprovalCost(run, 5), 22)
  assert.throws(() => buildPlanAction(run, 'approve_plan', { expectedVersion: 2 }), /版本/)
  assert.throws(() => buildPlanAction(run, 'approve_plan', { expectedVersion: 3 }, true), /状态/)
  assert.throws(() => buildPlanAction({ ...run, action_pending: true }, 'approve_plan', { expectedVersion: 3 }), /状态/)
})

test('unknown or oversized charges cannot enable a paid approval and zero remains a real value', () => {
  const run = runFixture()
  for (const repairCredits of [-1, NaN, Infinity, '5']) assert.throws(() => buildPlanAction(run, 'approve_plan', { expectedVersion: 3, repairCredits }), /非负/)
  assert.throws(() => buildPlanAction(run, 'approve_plan', { expectedVersion: 3, repairCredits: 99 }), /预算/)
  run.estimates.total_credits = null
  assert.throws(() => buildPlanAction(run, 'approve_plan', { expectedVersion: 3 }), /费用/)
  run.estimates.total_credits = 0
  assert.equal(buildPlanAction(run, 'approve_plan', { expectedVersion: 3 }).payload.repair_budget_credits, 0)
  run.plan_issues = [{ code: 'INVALID_INPUT', message: 'invalid' }]
  assert.throws(() => buildPlanAction(run, 'approve_plan', { expectedVersion: 3 }), /不可用/)
})

test('gate approval and feedback are bound to one successful unapproved current gate', () => {
  const run = runFixture()
  run.status = 'awaiting_gate'; run.nodes[0].status = 'success'
  assert.deepEqual(buildPlanAction(run, 'approve_gate', { expectedVersion: 3, gateNodeId: 'frame' }).payload, { plan_version: 3, gate_node_id: 'frame' })
  assert.deepEqual(buildPlanAction(run, 'revise_plan', { expectedVersion: 3, gateNodeId: 'frame', message: '  保持原角色发型  ' }).payload,
    { plan_version: 3, gate_node_id: 'frame', message: '保持原角色发型' })
  assert.throws(() => buildPlanAction(run, 'revise_plan', { expectedVersion: 3, message: '换造型' }), /预览节点/)
  assert.throws(() => buildPlanAction(run, 'approve_gate', { expectedVersion: 3, gateNodeId: 'clip' }), /预览门/)
  run.nodes[0].gate_approved = true
  assert.throws(() => buildPlanAction(run, 'approve_gate', { expectedVersion: 3, gateNodeId: 'frame' }), /预览门/)
})

test('revision is intent-only and never admits a new model or an unsafe execution state', () => {
  const run = runFixture()
  assert.deepEqual(buildPlanAction(run, 'revise_plan', { expectedVersion: 3, message: '让结尾更轻松' }).payload,
    { plan_version: 3, message: '让结尾更轻松' })
  assert.throws(() => buildPlanAction(run, 'revise_plan', { expectedVersion: 3, message: ' ' }), /修改意图/)
  run.status = 'executing'
  assert.throws(() => buildPlanAction(run, 'revise_plan', { expectedVersion: 3, message: '修改' }), /不可用/)
  run.status = 'attention'; run.nodes[1].error = { category: 'submit_unknown' }
  assert.throws(() => buildPlanAction(run, 'revise_plan', { expectedVersion: 3, message: '再试' }), /不可用/)
})

test('delegation tree follows parent IDs and preserves orphan or cyclic rows without looping', () => {
  const agents = [{ delegation_id: 2, parent_id: 1, agent: 'director', credits: 3 },
    { delegation_id: 1, parent_id: null, agent: 'producer', credits: 2 },
    { delegation_id: 3, parent_id: 4, agent: 'critic' }, { delegation_id: 4, parent_id: 3, agent: 'research' }]
  const tree = agentTree(agents)
  assert.deepEqual(tree.map((row) => row.delegation_id), [1, 2, 3, 4])
  assert.equal(tree[1].depth, 1)
  assert.equal(tree[0].credits, 2, 'own credits are not double-counted with children')
  assert.equal(tree[2].detached, true)
  assert.equal(agents[0].depth, undefined)
})

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const response = (page, summary) => ({ page, per_page: 30, total: 60, items: [{ summary }] })

test('late step responses from a previous task or page cannot overwrite the current page', async () => {
  const pending = [], state = {}
  const pager = createStepPager((id, page, limit, signal) => { const item = deferred(); pending.push({ ...item, id, page, limit, signal }); return item.promise }, (value) => Object.assign(state, value))
  const first = pager.load('old', 1), second = pager.load('new', 2)
  assert.equal(pending[0].signal.aborted, true)
  assert.equal(pending[1].limit, 30)
  pending[1].resolve(response(2, 'new page')); await second
  pending[0].resolve(response(1, 'old page')); await first
  assert.equal(state.items[0].summary, 'new page')
  assert.equal(state.page, 2)
  assert.equal(state.loading, false)
})

test('unmount cancels the current fetch and ignores its late completion', async () => {
  const pending = deferred(), updates = []; let signal
  const pager = createStepPager((_id, _page, _limit, value) => { signal = value; return pending.promise }, (value) => updates.push(value))
  const request = pager.load('run', 1), before = updates.length
  pager.dispose(); pending.resolve(response(1, 'late')); await request
  assert.equal(signal.aborted, true)
  assert.equal(updates.length, before)
  await pager.load('other', 1)
  assert.equal(updates.length, before)
})

test('invalid pagination fails visibly and a later retry replaces the error', async () => {
  const state = {}; let valid = false
  const pager = createStepPager(async () => valid ? response(1, 'ok') : response(2, 'wrong page'), (value) => Object.assign(state, value))
  await pager.load('run', 1)
  assert.match(state.error, /无法读取/)
  assert.deepEqual(state.items, [])
  valid = true; await pager.load('run', 1)
  assert.equal(state.error, '')
  assert.equal(state.items[0].summary, 'ok')
  assert.equal(publicError({ code: 'ERR', message: '<script>data only</script>' }), '<script>data only</script> · ERR')
})
