import test from 'node:test'
import assert from 'node:assert/strict'
import { buildPlanAction, planRows, templateWrites, workflowView } from '../src/components/agent/v3-plan.js'
import { v3ActionAllowed } from '../src/components/agent/v3-actions.js'

function workflowRun(result = null) {
  return {
    run_id: 'run_v8', schema_version: 3, status: 'awaiting_plan_review', action_pending: false,
    budget_limit: 100, estimated_spent: 1, plan_issues: [],
    template_writes: [{ node_id: 'workflow', mode: 'new', series_id: 'default', series_name: 'Default Series',
      template_id: 'tpl_v3_x', template_name: '参考视频反推', prompt_types: ['first_frame_image', 'i2v', 't2v'] }],
    plan: { plan_version: 1, nodes: [{ id: 'workflow', tool: 'run_workflow_template', inputs: {
      template_target: { series_id: 'default', new_template_name: '参考视频反推' },
      branches: ['reverse_prompts', 'rewrite_prompts', 'first_frame_image', 'i2v'] }, params: {} }] },
    nodes: [{ node_id: 'workflow', status: result ? 'success' : 'pending', depends_on: [], workflow: result }],
    estimates: { total_credits: 9, video_seconds: 0, generated_video_seconds: 5, nodes: [
      { node_id: 'workflow', estimated_cost: 9, input_video_seconds: 0, output_video_seconds: 5 }] },
  }
}

test('template writes are projected for the approval card', () => {
  assert.deepEqual(templateWrites(workflowRun()), [{ nodeId: 'workflow', isNew: true, template: '参考视频反推',
    series: 'Default Series', promptTypes: ['首帧图', '图生视频', '文生视频'] }])
  assert.deepEqual(templateWrites({ template_writes: [null, { template_name: 3 }] }), [])
})

test('approval requires the explicit template write confirmation', () => {
  const run = workflowRun()
  assert.throws(() => buildPlanAction(run, 'approve_plan', { expectedVersion: 1 }), /写入经典模板/)
  const action = buildPlanAction(run, 'approve_plan', { expectedVersion: 1, confirmTemplateWrite: true })
  assert.deepEqual(action.payload, { plan_version: 1, repair_budget_credits: 0, confirm_template_write: true })
  assert.equal(v3ActionAllowed(run, 'approve_plan', { plan_version: 1, repair_budget_credits: 0 }), false)
})

test('private plans keep the original approval payload', () => {
  const run = workflowRun()
  delete run.template_writes
  const action = buildPlanAction(run, 'approve_plan', { expectedVersion: 1, confirmTemplateWrite: true })
  assert.deepEqual(action.payload, { plan_version: 1, repair_budget_credits: 0 })
})

test('workflow rows show branches, generated seconds and the classic job link', () => {
  const result = { job_id: 'job_123', template: { name: '参考视频反推' }, package: 'art_zip',
    prompts: { t2v: { version: 'v2', content: '雨夜霓虹街道' } } }
  const [row] = planRows(workflowRun(result))
  assert.equal(row.duration, 5)
  assert.deepEqual(row.workflow.branches, ['视频反推提示词', '拆分首帧与 i2v 提示词', '首帧图', '图生视频'])
  assert.equal(row.workflow.jobUrl, '/jobs/job_123')
  assert.equal(row.workflow.packaged, true)
  assert.deepEqual(row.workflow.prompts, [{ kind: 't2v', label: '文生视频', version: 'v2', content: '雨夜霓虹街道' }])
  assert.equal(workflowView({ inputs: {} }, { job_id: '../evil' }).jobUrl, '', 'only plain job IDs become links')
})
