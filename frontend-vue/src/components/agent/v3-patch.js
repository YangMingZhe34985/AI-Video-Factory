// Client checks prevent stale clicks; the server remains the approval authority.
const scopes = new Set(['only', 'cascade'])
const patchStates = new Set(['reviewed', 'awaiting_approval'])
const runStates = new Set(['attention', 'awaiting_result_review'])
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value)
const positiveInteger = (value) => Number.isSafeInteger(value) && value >= 1
const identity = (value, limit = 128) => typeof value === 'string' && value.length > 0 && value === value.trim() && value.length <= limit
const credit = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0
const clone = (value) => JSON.parse(JSON.stringify(value))
const ids = (value) => Array.isArray(value) && value.every((id) => identity(id, 40)) && new Set(value).size === value.length
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical)
  if (!object(value)) return value
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonical(value[key])]))
}
const stable = (value) => JSON.stringify(canonical(value))
const sameCost = (left, right) => Number.isFinite(left) && Number.isFinite(right)
  && Math.abs(left - right) <= 1e-8 * Math.max(1, Math.abs(left), Math.abs(right))

export function patchContextKey(run, patch, scope) {
  // Exclude the Run poll timestamp. Relevant task, budget or Patch changes do
  // invalidate a quote, even if the plan version has not advanced yet.
  return stable({
    schema_version: run?.schema_version,
    run_id: run?.run_id,
    status: run?.status,
    action_pending: Boolean(run?.action_pending),
    plan_version: run?.plan?.plan_version,
    budget_limit: run?.budget_limit,
    estimated_spent: run?.estimated_spent,
    repair_budget: run?.repair_budget,
    nodes: run?.nodes,
    patch,
    current_patch: run?.patches?.find((item) => item.patch_id === patch?.patch_id),
    scope,
  })
}

export function patchReviewable(run, patch, disabled = false) {
  if (disabled || run?.schema_version !== 3 || !identity(run?.run_id, 80)
    || !runStates.has(run?.status) || run?.action_pending
    || !identity(patch?.patch_id) || !patchStates.has(patch?.status)
    || !positiveInteger(patch?.base_version) || patch.base_version !== run?.plan?.plan_version
    || !['approve', 'revise'].includes(patch?.review?.verdict)) return false
  const current = run.patches?.find((item) => item.patch_id === patch.patch_id)
  return Boolean(current && stable(current) === stable(patch))
}

export function currentPatchQuote(receipt, run, patch, scope) {
  const quote = receipt?.quote
  return Boolean(patchReviewable(run, patch) && scopes.has(scope)
    && receipt?.context_key === patchContextKey(run, patch, scope)
    && object(quote) && identity(quote.quote_id)
    && quote.patch_id === patch.patch_id
    && positiveInteger(quote.base_version) && quote.base_version === patch.base_version
    && quote.base_version === run.plan.plan_version && quote.scope === scope)
  // A freshly fetched cascade quote may differ from the stored only quote in
  // patch.quote. The latter is a polling snapshot, never the approval receipt.
}

export function patchCosts(quote) {
  const costs = quote?.estimated_credits
  if (!object(costs) || ![costs.repair, costs.continuation, costs.total].every(credit)
    || !sameCost(costs.repair + costs.continuation, costs.total)) return null
  if (!Array.isArray(quote?.node_costs) || !quote.node_costs.every((node) => object(node)
    && identity(node.node_id, 40) && credit(node.estimated_cost)
    && credit(node.input_video_seconds) && credit(node.output_video_seconds))) return null
  if (!sameCost(quote.node_costs.reduce((total, node) => total + node.estimated_cost, 0), costs.total)) return null
  return { repair: costs.repair, continuation: costs.continuation, total: costs.total }
}

function completeImpact(quote) {
  const fields = ['affected_node_ids', 'execute_node_ids', 'reused_node_ids', 'kept_node_ids', 'removed_node_ids', 'continuation_node_ids']
  if (!fields.every((key) => ids(quote?.[key])) || !Array.isArray(quote.node_costs)
    || !quote.node_costs.every((node) => object(node) && identity(node.node_id, 40))) return false
  if (!quote.continuation_node_ids.every((id) => quote.execute_node_ids.includes(id))) return false
  const actions = new Map(quote.node_costs.map((node) => [node.node_id, node.action]))
  if (actions.size !== quote.node_costs.length) return false
  if (!quote.node_costs.every((node) => ['execute', 'reuse', 'retain', 'preserve_failure'].includes(node.action))) return false
  if (![['execute_node_ids', 'execute'], ['reused_node_ids', 'reuse'], ['kept_node_ids', 'retain']]
    .every(([field, action]) => quote[field].every((id) => actions.get(id) === action)
      && quote.node_costs.filter((node) => node.action === action).every((node) => quote[field].includes(node.node_id)))) return false
  if (quote.removed_node_ids.some((id) => actions.has(id))) return false
  return quote.node_costs.every((node) => node.action === 'execute' || node.estimated_cost === 0)
}

export function patchImpact(quote) {
  const list = (key) => ids(quote?.[key]) ? [...quote[key]] : []
  const continuing = list('continuation_node_ids')
  return {
    affected: list('affected_node_ids'),
    executing: list('execute_node_ids').filter((id) => !continuing.includes(id)),
    continuing,
    reused: list('reused_node_ids'),
    retained: list('kept_node_ids'),
    removed: list('removed_node_ids'),
    failed: Array.isArray(quote?.node_costs)
      ? quote.node_costs.filter((node) => node?.action === 'preserve_failure' && identity(node.node_id, 40)).map((node) => node.node_id) : [],
  }
}

export function patchApprovalIssue(receipt, run, patch, scope, acknowledged = false) {
  if (!currentPatchQuote(receipt, run, patch, scope)) return '报价已失效，请重新获取当前范围的报价。'
  const quote = receipt.quote
  if (quote.manual_can_apply !== true || quote.can_apply !== true) return '服务端暂不允许人工批准，请检查问题与预算提示。'
  if (!Array.isArray(quote.issues) || quote.issues.length > 0) return '补丁仍有未解决的问题。'
  if (!completeImpact(quote) || !patchCosts(quote)) return '费用或影响范围不完整，请重新获取报价。'
  if (quote.kept_node_ids.length > 0 && acknowledged !== true) return '请先确认保留下游旧产物的衔接风险。'
  return ''
}

export function buildPatchAction(receipt, run, patch, scope, action, acknowledged = false) {
  if (!['approve_patch', 'reject_patch'].includes(action)) throw new Error('不支持此补丁操作。')
  if (!currentPatchQuote(receipt, run, patch, scope)) throw new Error('报价已失效，请重新获取当前范围的报价。')
  if (action === 'approve_patch') {
    const issue = patchApprovalIssue(receipt, run, patch, scope, acknowledged)
    if (issue) throw new Error(issue)
  }
  // Rejection changes no generation authorization, so unknown prices or a
  // manual budget refusal must not prevent rejecting a current reviewed patch.
  return { action, payload: { patch_id: patch.patch_id, quote_id: receipt.quote.quote_id, scope } }
}

export function createPatchQuoteSession() {
  let epoch = 0, disposed = false
  const invalidate = () => { epoch++ }
  const current = (ticket, contextKey) => Boolean(!disposed && ticket
    && ticket.epoch === epoch && ticket.context_key === contextKey)
  return {
    begin(contextKey) {
      if (disposed) return null
      return Object.freeze({ epoch: ++epoch, context_key: contextKey })
    },
    current,
    accept(ticket, contextKey, quote) {
      return current(ticket, contextKey) ? { context_key: contextKey, quote: clone(quote) } : null
    },
    invalidate,
    dispose() { disposed = true; invalidate() },
  }
}

export function patchOperationLabel(operation) {
  return ({ update_inputs: '修改输入', replace_node: '替换节点', insert_node: '新增节点', remove_node: '移除节点' })[operation] || '变更'
}

export function patchIntent(review) {
  const changes = Array.isArray(review?.changed_elements) ? review.changed_elements.filter((item) => object(item)
    && typeof item.element === 'string' && ['changed', 'removed'].includes(item.change)
    && ['before', 'after', 'reason'].every((key) => typeof item[key] === 'string')) : []
  if (changes.length) return { status: 'changed', label: '用户点名内容有变化，需要人工确认', changes }
  if (review?.intent_preserved === true && Array.isArray(review.changed_elements) && review.changed_elements.length === 0)
    return { status: 'preserved', label: 'Director 判断保留了原需求', changes }
  return { status: 'unknown', label: '尚未确认是否保留原需求，需要人工确认', changes }
}

export function patchReviewLabel(verdict) {
  return ({ approve: '审阅通过', revise: '修订后通过', reject: '审阅拒绝' })[verdict] || '等待独立审阅'
}

export function patchJson(value) {
  if (value === null || value === undefined) return '无'
  return JSON.stringify(value, null, 2)
}
