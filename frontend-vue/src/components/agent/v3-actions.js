// UI admission and retry helpers. Server receipts, authorization and quotes remain authoritative.
const ended = new Set(['success', 'partial_success', 'failed', 'cancelled'])
const runStates = new Set(['queued', 'understanding', 'awaiting_input', 'awaiting_plan_review', 'executing', 'awaiting_gate', 'delivering', 'awaiting_result_review', 'attention', ...ended])
const reviewStates = new Set(['awaiting_plan_review', 'awaiting_result_review', 'awaiting_gate', 'attention'])
const fieldSets = {
  answer: ['card_id', 'answers', 'use_defaults'],
  approve_plan: ['plan_version', 'repair_budget_credits', 'confirm_template_write'],
  approve_gate: ['plan_version', 'gate_node_id', 'selected_artifact_id', 'choice_digest'],
  approve_results: ['plan_version'],
  revise_plan: ['plan_version', 'message', 'gate_node_id'],
  approve_patch: ['patch_id', 'quote_id', 'scope'],
  reject_patch: ['patch_id', 'quote_id', 'scope'],
  resume: [],
  reject: [],
}
const labels = {
  queued: '等待规划', understanding: '理解与规划中', awaiting_input: '等待补充选择',
  awaiting_plan_review: '等待计划审核', executing: '执行中', awaiting_gate: '等待预览或候选确认',
  delivering: '整理交付中', awaiting_result_review: '等待验收结果', attention: '需要处理',
  success: '已完成', partial_success: '部分完成', failed: '失败', cancelled: '已取消',
  pending: '等待执行', running: '进行中', completed: '已完成', returned: '已退回', limit: '达到额度或次数上限',
  waiting_children: '等待协作结果', waiting_dependency: '等待上游结果', blocked: '被上游阻塞', stale: '等待重做',
  proposed: '已提出补丁', review_pending: '等待独立审阅', awaiting_review: '等待独立审阅', reviewed: '已审阅',
  awaiting_approval: '等待补丁批准', applied: '补丁已应用', rejected: '已拒绝', invalid: '需要修改',
}
const has = (value, key) => Object.prototype.hasOwnProperty.call(value, key)
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)
const credit = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0
const integer = (value) => Number.isSafeInteger(value) && value >= 1
const clone = (value) => JSON.parse(JSON.stringify(value))
function requireValue(condition, message) { if (!condition) throw new Error(message) }
function text(value, label, maximum = 80) {
  requireValue(typeof value === 'string' && value.trim().length > 0 && value.trim().length <= maximum, `${label}无效，请刷新后重试。`)
  return value.trim()
}
function exactFields(value, fields) {
  requireValue(object(value) && Object.keys(value).every((key) => fields.includes(key)), '操作包含不支持的字段。')
}
function currentVersion(run, value) {
  requireValue(integer(run.plan?.plan_version) && integer(value) && value === run.plan.plan_version, '计划版本已变化，请重新审核。')
  return value
}
function gate(run, nodeId) {
  const identity = text(nodeId, '关键帧节点', 40)
  const planNode = run.plan?.nodes?.find((node) => node.id === identity)
  const task = run.nodes?.find((node) => node.node_id === identity)
  requireValue(task?.gate_approved === false && (
    (planNode?.gate === 'preview' && task?.gate === 'preview' && task.status === 'success')
    || (planNode?.gate === 'choice' && task?.gate === 'choice' && task.status === 'pending' && task.choice?.ready === true)
  ), '请选择已就绪且尚未确认的审核节点。')
  return identity
}
function validateAnswers(run, payload) {
  const cardId = text(payload.card_id, '问题卡')
  const card = run.pending_card
  requireValue(run.status === 'awaiting_input' && card?.card_id === cardId && Array.isArray(card.questions), '问题卡已变化，请重新选择。')
  const supplied = has(payload, 'answers') ? payload.answers : []
  const useDefaults = has(payload, 'use_defaults') ? payload.use_defaults : false
  requireValue(Array.isArray(supplied) && supplied.length <= 3 && typeof useDefaults === 'boolean', '请选择有效答案。')
  const seen = new Set()
  const answers = supplied.map((answer) => {
    exactFields(answer, ['question_id', 'option_id', 'text'])
    const questionId = text(answer.question_id, '问题', 40)
    const question = card.questions.find((item) => item.question_id === questionId)
    requireValue(question && !seen.has(questionId), '答案包含未知或重复问题。')
    seen.add(questionId)
    const option = has(answer, 'option_id'), freeText = has(answer, 'text')
    requireValue(option !== freeText, '每个问题只能提交一个选项或一段补充说明。')
    if (option) {
      const optionId = text(answer.option_id, '选项', 40)
      requireValue(question.options?.some((item) => item.option_id === optionId), '所选选项已失效。')
      return { question_id: questionId, option_id: optionId }
    }
    requireValue(question.allow_free_text === true, '该问题不接受自由文本。')
    return { question_id: questionId, text: text(answer.text, '补充说明', 1000) }
  })
  requireValue(card.questions.every((question) => question.blocking === false || seen.has(question.question_id)), '请回答全部必答问题。')
  answers.sort((a, b) => a.question_id.localeCompare(b.question_id))
  return { card_id: cardId, answers, use_defaults: useDefaults }
}

function normalizeAction(run, action, payload = {}) {
  requireValue(object(run) && run.schema_version === 3, '此操作仅适用于新版 Agent 任务。')
  text(run.run_id, '任务', 80)
  requireValue(typeof action === 'string' && has(fieldSets, action), '不支持此操作。')
  exactFields(payload, fieldSets[action])
  requireValue(!run.action_pending || (run.status === 'attention' && ['resume', 'reject'].includes(action)), '上一操作仍在处理中。')
  if (action === 'resume') {
    requireValue(run.status === 'attention' && Number.isInteger(run.resume_count) && run.resume_count >= 0 && run.resume_count < 2, '当前任务暂不可恢复。')
    return { action }
  }
  if (action === 'reject') {
    requireValue(runStates.has(run.status) && !ended.has(run.status), '该任务已经结束。')
    return { action }
  }
  if (action === 'answer') return { action, ...validateAnswers(run, payload) }
  if (['approve_patch', 'reject_patch'].includes(action)) {
    requireValue(['attention', 'awaiting_result_review'].includes(run.status), '当前阶段不能处理补丁。')
    const patchId = text(payload.patch_id, '补丁', 128), quoteId = text(payload.quote_id, '报价', 128)
    requireValue(['only', 'cascade'].includes(payload.scope), '请选择明确的修改范围。')
    const patch = run.patches?.find((item) => item.patch_id === patchId)
    requireValue(patch && ['reviewed', 'awaiting_approval'].includes(patch.status), '补丁不存在或已处理。')
    currentVersion(run, patch.base_version)
    // Fresh quotes are checked by the Patch review component. A newly requested
    // cascade quote must not be compared with the old only quote in Run polling.
    return { action, patch_id: patchId, quote_id: quoteId, scope: payload.scope }
  }
  const version = currentVersion(run, payload.plan_version)
  if (action === 'approve_plan') {
    requireValue(run.status === 'awaiting_plan_review', '当前阶段不能批准计划。')
    requireValue(Array.isArray(run.plan_issues) && run.plan_issues.length === 0, '计划仍有未解决的问题。')
    const repair = has(payload, 'repair_budget_credits') ? payload.repair_budget_credits : 0
    const total = run.estimates?.total_credits
    requireValue([total, run.budget_limit, run.estimated_spent, repair].every(credit), '费用尚未确认，请重新获取估算。')
    const planned = total + repair + run.estimated_spent
    requireValue(Number.isFinite(planned) && planned <= run.budget_limit + 1e-9, '计划和修复预留超过剩余总预算。')
    // Classic-path plans write prompt versions into a user template (V.25.3).
    const writes = Array.isArray(run.template_writes) && run.template_writes.length > 0
    requireValue(!writes || payload.confirm_template_write === true, '请先确认将作业与提示词写入经典模板。')
    return { action, plan_version: version, repair_budget_credits: repair, ...(writes ? { confirm_template_write: true } : {}) }
  }
  if (action === 'approve_gate') {
    requireValue(run.status === 'awaiting_gate', '当前没有待确认预览或候选。')
    const nodeId = gate(run, payload.gate_node_id)
    const task = run.nodes.find((node) => node.node_id === nodeId)
    const body = { action, plan_version: version, gate_node_id: nodeId }
    if (task.gate === 'choice') {
      const selected = text(payload.selected_artifact_id, '候选图片', 100)
      const digest = text(payload.choice_digest, '候选摘要', 128)
      requireValue(digest === task.choice?.choice_digest && task.choice?.candidates?.some((item) => item.artifact_id === selected), '候选已变化，请重新选择。')
      return { ...body, selected_artifact_id: selected, choice_digest: digest }
    }
    requireValue(!has(payload, 'selected_artifact_id') && !has(payload, 'choice_digest'), '普通预览不接受候选选择。')
    return body
  }
  if (action === 'approve_results') {
    requireValue(run.status === 'awaiting_result_review', '当前没有待验收结果。')
    requireValue(Array.isArray(run.nodes) && Array.isArray(run.plan.nodes) && run.nodes.length > 0
      && run.nodes.length === run.plan.nodes.length && new Set(run.nodes.map((node) => node.node_id)).size === run.nodes.length
      && run.plan.nodes.every((node) => run.nodes.some((task) => task.node_id === node.id))
      && run.nodes.every((node) => node.status === 'success' && (!['preview', 'choice'].includes(node.gate) || node.gate_approved === true)), '任务尚未全部完成或审核门尚未确认。')
    return { action, plan_version: version }
  }
  requireValue(action === 'revise_plan' && reviewStates.has(run.status), '当前阶段不能修改计划。')
  requireValue(!run.nodes?.some((node) => node.status === 'running' || node.error?.category === 'submit_unknown'
    || node.error?.submission_state === 'unknown'), '先核实或恢复当前任务，再修改计划。')
  const body = { action, plan_version: version, message: text(payload.message, '修改意见', 4000) }
  if (run.status === 'awaiting_gate') body.gate_node_id = gate(run, payload.gate_node_id)
  else requireValue(!has(payload, 'gate_node_id'), '关键帧反馈必须针对当前待确认节点。')
  return body
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical)
  if (!object(value)) return value
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]))
}
function requestKey() {
  if (globalThis.crypto?.randomUUID) return `v3_${globalThis.crypto.randomUUID()}`
  if (globalThis.crypto?.getRandomValues) {
    const bytes = globalThis.crypto.getRandomValues(new Uint32Array(4))
    return `v3_${Array.from(bytes, (value) => value.toString(16).padStart(8, '0')).join('')}`
  }
  // Older non-secure local browsers may not expose Web Crypto. This is an
  // idempotency identifier, never an authentication or authorization secret.
  return `v3_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}_${Math.random().toString(36).slice(2)}`
}
export function createV3ActionSession() {
  let pending = null
  const clear = () => { pending = null }
  return {
    prepare(run, action, payload = {}) {
      const body = normalizeAction(run, action, payload)
      const identity = JSON.stringify(canonical({ run_id: run.run_id, plan_version: run.plan?.plan_version ?? null, body }))
      if (!pending || pending.identity !== identity) pending = { identity, body: { ...body, request_key: requestKey() } }
      return clone(pending.body)
    },
    // Call only after a successful server response; network errors keep the key.
    acknowledge: clear,
    reset: clear,
  }
}
export function v3ActionAllowed(run, action, payload = {}) {
  try { normalizeAction(run, action, payload); return true } catch { return false }
}
export function v3StatusLabel(status) { return typeof status === 'string' && has(labels, status) ? labels[status] : '未知状态' }
export function creditLabel(value) {
  return credit(value) ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value) : '待服务器估算'
}
