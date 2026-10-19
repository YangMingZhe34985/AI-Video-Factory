// Public projections only. State helpers do not authorize model execution.
import { deliveryAssetUrl } from './delivery.js'
import { v3ActionAllowed } from './v3-actions.js'

const VIDEO_TOOLS = new Set(['generate_video', 'animate_shot', 'transform_video'])
const TOOL_LABELS = {
  generate_image: '生成图像', generate_video: '生成视频', animate_shot: '首帧 / 首尾帧生视频',
  transform_video: '视频参考 / 编辑 / 延长', extract_frame: '提取关键帧', retain_video_segment: '保留原片片段',
  compose_video: '拼接成片', probe_media: '读取媒体信息', qc_video: '媒体质检', package_story: '打包交付',
  select_image: '从候选图片中选择',
}
const AGENT_LABELS = { producer: '制片协调', research: '资料研究', creative: '故事创作', director: '导演规划',
  prompt_smith: '提示词编写', critic: '计划审阅', repair: '局部修复' }
const list = (value) => Array.isArray(value) ? value : []
const strings = (value) => [...new Set(list(value).filter((item) => typeof item === 'string' && item))]
export const finiteValue = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
export const planVersion = (run) => Number.isInteger(run?.plan?.plan_version) && run.plan.plan_version > 0 ? run.plan.plan_version : null
export const toolLabel = (tool) => TOOL_LABELS[tool] || String(tool || '未知工具')
export const agentLabel = (agent) => AGENT_LABELS[agent] || String(agent || '未知角色')
export const secondsLabel = (value) => finiteValue(value) === null ? '待服务器确认' : `${Number(value.toFixed(2))} 秒`

export function readableJson(value) {
  try { return JSON.stringify(value ?? {}, null, 2) } catch { return '数据不可展示' }
}

export function publicError(error) {
  if (typeof error === 'string') return error
  if (!error || typeof error !== 'object') return ''
  return [error.summary || error.message || error.hint, error.code].filter((value) => typeof value === 'string' && value).join(' · ')
}

export function nodeAssets(artifacts) {
  return list(artifacts).filter((asset) => asset && typeof asset.artifact_id === 'string').map((asset) => {
    const mime = String(asset.mime_type || '').toLowerCase()
    const kind = /^image\/(png|jpeg|jpg|webp|gif|avif)$/.test(mime) ? 'image' : /^video\//.test(mime) ? 'video' : 'file'
    return { ...asset, kind, preview: deliveryAssetUrl(asset, 'preview'), download: deliveryAssetUrl(asset) }
  })
}

export function planRows(run) {
  const tasks = new Map(list(run?.nodes).filter((item) => item?.node_id).map((item) => [item.node_id, item]))
  const costs = new Map(list(run?.estimates?.nodes).filter((item) => item?.node_id).map((item) => [item.node_id, item]))
  const seen = new Set()
  return list(run?.plan?.nodes).filter((node) => node?.id && !seen.has(node.id) && seen.add(node.id)).map((node) => {
    const task = tasks.get(node.id) || {}, estimate = costs.get(node.id)
    // Before approval, task.estimated_cost can be a placeholder zero. Use the compiled estimate.
    const cost = estimate ? finiteValue(estimate.estimated_cost) : null
    const keepStart = finiteValue(node.inputs?.source_start_sec), keepEnd = finiteValue(node.inputs?.source_end_sec)
    const keptSeconds = keepStart !== null && keepEnd !== null && keepEnd > keepStart ? keepEnd - keepStart : null
    return {
      ...node, status: typeof task.status === 'string' ? task.status : 'pending',
      dependencies_known: Array.isArray(task.depends_on), depends_on: strings(task.depends_on),
      gate_approved: task.gate_approved === true, retained: task.retained === true,
      source_plan_version: Number.isInteger(task.source_plan_version) && task.source_plan_version > 0 ? task.source_plan_version : null,
      reused_from_task_id: task.reused_from_task_id ?? null, attempt: Number.isInteger(task.attempt) ? task.attempt : 0,
      job_id: typeof task.job_id === 'string' ? task.job_id : '', error: publicError(task.error),
      estimated_cost: cost, input_video_seconds: finiteValue(estimate?.input_video_seconds),
      output_video_seconds: finiteValue(estimate?.output_video_seconds),
      duration: VIDEO_TOOLS.has(node.tool) ? finiteValue(estimate?.output_video_seconds)
        : node.tool === 'retain_video_segment' ? keptSeconds : null,
      assets: nodeAssets(task.artifacts),
      choice: task.choice ? { ready: task.choice.ready === true, digest: task.choice.choice_digest || '',
        selected: task.choice.selected_artifact_id || '', candidates: nodeAssets(task.choice.candidates) } : null,
    }
  })
}

export function planGroups(run, rows = planRows(run)) {
  const groups = [], index = new Map()
  for (const stage of list(run?.plan?.stages)) {
    if (!stage?.id || index.has(stage.id)) continue
    const group = { id: stage.id, label: String(stage.label || stage.id), nodes: [] }
    groups.push(group); index.set(stage.id, group)
  }
  for (const row of rows) {
    const id = row.stage || '__unstaged__'
    if (!index.has(id)) {
      const group = { id, label: row.stage ? `阶段 ${row.stage}` : '其他节点', nodes: [] }
      groups.push(group); index.set(id, group)
    }
    index.get(id).nodes.push(row)
  }
  return groups.filter((group) => group.nodes.length)
}

export function dependencyState(row, rows) {
  if (row.status === 'success') return { kind: 'complete', label: row.retained ? '保留既有产物，不重新生成' : '节点已完成' }
  if (['failed', 'blocked', 'cancelled', 'stale'].includes(row.status)) return { kind: 'stopped', label: '等待服务端修复或后续处理' }
  if (['running', 'queued', 'submitting', 'polling', 'downloading'].includes(row.status)) return { kind: 'running', label: '服务端正在处理' }
  if (row.gate === 'choice' && row.choice?.ready && !row.gate_approved) return { kind: 'choice', label: '候选已就绪，等待你选择；下游暂不执行' }
  if (!row.dependencies_known) return { kind: 'unknown', label: '编译后的依赖信息尚未返回' }
  const index = new Map(rows.map((item) => [item.id, item]))
  const pending = row.depends_on.filter((id) => {
    const parent = index.get(id)
    return !parent || parent.status !== 'success' || (['preview', 'choice'].includes(parent.gate) && !parent.gate_approved)
  })
  if (pending.length) return { kind: 'waiting', label: `等待上游或预览确认：${pending.join('、')}` }
  return { kind: 'ready', label: row.depends_on.length
    ? '上游已就绪 · 可并行候选，实际由服务端调度'
    : '无上游依赖 · 批准后可并行，受并发限额约束' }
}

export function planTotals(run) {
  return { deliveredSeconds: finiteValue(run?.estimates?.video_seconds),
    generatedSeconds: finiteValue(run?.estimates?.generated_video_seconds),
    credits: finiteValue(run?.estimates?.total_credits) }
}

function repairAmount(value) {
  if (value === '' || value === undefined || value === null) return 0
  if (finiteValue(value) === null) throw new Error('修复预授权额度必须是非负数。')
  return value
}

export function initialApprovalCost(run, repair = 0) {
  const price = finiteValue(run?.estimates?.total_credits)
  const amount = repairAmount(repair)
  return price === null ? null : price + amount
}

export function buildPlanAction(run, action, values = {}, disabled = false) {
  const version = planVersion(run)
  if (disabled || run?.action_pending || run?.schema_version !== 3 || !version || values.expectedVersion !== version) {
    throw new Error('计划状态或版本已变化，请刷新后重新确认。')
  }
  let payload
  if (action === 'approve_plan') {
    const amount = repairAmount(values.repairCredits)
    const cost = initialApprovalCost(run, amount), budget = finiteValue(run.budget_limit), spent = finiteValue(run.estimated_spent)
    if (cost === null || budget === null || spent === null) throw new Error('费用或剩余预算尚未由服务器确认。')
    if (cost > Math.max(0, budget - spent) + 1e-8) throw new Error('计划费用与修复预留超过剩余总预算，请调整后审核。')
    payload = { plan_version: version, repair_budget_credits: amount }
  } else if (action === 'approve_gate') {
    const gate = planRows(run).find((row) => row.id === values.gateNodeId)
    if (!gate || !gateReady(gate)) throw new Error('该审核门当前不可确认。')
    payload = { plan_version: version, gate_node_id: gate.id }
    if (gate.gate === 'choice') {
      if (!values.selectedArtifactId || !values.choiceDigest || values.choiceDigest !== gate.choice?.digest
          || !gate.choice?.candidates.some((item) => item.artifact_id === values.selectedArtifactId)) throw new Error('请从当前候选中选择一张图片。')
      payload.selected_artifact_id = values.selectedArtifactId
      payload.choice_digest = values.choiceDigest
    }
  } else if (action === 'revise_plan') {
    const message = typeof values.message === 'string' ? values.message.trim() : ''
    if (!message || message.length > 4000) throw new Error('请填写 1–4000 字的修改意图。')
    payload = { plan_version: version, message }
    if (values.gateNodeId) {
      const gate = planRows(run).find((row) => row.id === values.gateNodeId)
      if (run.status !== 'awaiting_gate' || !gate || !gateReady(gate)) {
        throw new Error('只能针对当前未批准且已就绪的审核节点提出修改。')
      }
      payload.gate_node_id = gate.id
    } else if (run.status === 'awaiting_gate') throw new Error('请先选择需要修改的预览节点。')
  } else throw new Error('不支持的计划动作。')
  if (!v3ActionAllowed(run, action, payload)) throw new Error('此操作在当前状态不可用，请等待或刷新。')
  return { action, payload }
}

export function gateReady(row) {
  return !row.gate_approved && ((row.gate === 'preview' && row.status === 'success')
    || (row.gate === 'choice' && row.status === 'pending' && row.choice?.ready === true))
}

// Include order and membership as well as the server digest. Never preselect a candidate.
export function choiceIdentity(row) {
  return row.choice?.ready && !row.gate_approved
    ? JSON.stringify([row.choice.digest, row.choice.candidates.map((item) => item.artifact_id)]) : ''
}

export function agentTree(agents) {
  const byId = new Map(), children = new Map(), seen = new Set(), output = []
  for (const agent of list(agents)) {
    if (Number.isInteger(agent?.delegation_id) && !byId.has(agent.delegation_id)) byId.set(agent.delegation_id, agent)
  }
  for (const agent of byId.values()) {
    const parent = byId.has(agent.parent_id) && agent.parent_id !== agent.delegation_id ? agent.parent_id : null
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent).push(agent)
  }
  function visit(root, detached = false) {
    const stack = [{ row: root, depth: 0 }]
    while (stack.length) {
      const { row, depth } = stack.pop()
      if (seen.has(row.delegation_id)) continue
      seen.add(row.delegation_id)
      output.push({ ...row, depth, detached, label: agentLabel(row.agent) })
      for (const child of [...(children.get(row.delegation_id) || [])].reverse()) stack.push({ row: child, depth: depth + 1 })
    }
  }
  for (const root of children.get(null) || []) visit(root, root.parent_id != null)
  for (const orphan of byId.values()) if (!seen.has(orphan.delegation_id)) visit(orphan, true)
  return output
}

// Page requests can finish out of order even when transport cancellation is supported.
export function createStepPager(fetchPage, update) {
  let generation = 0, controller = null, disposed = false
  function cancel() { generation++; controller?.abort(); controller = null }
  return {
    async load(runId, page) {
      if (disposed) return
      cancel()
      const token = generation
      if (!runId || !Number.isInteger(page) || page < 1) { update({ items: [], total: 0, page: 1, loading: false, error: '' }); return }
      const active = new AbortController(); controller = active
      update({ items: [], loading: true, error: '', page })
      try {
        const result = await fetchPage(runId, page, 30, active.signal)
        if (disposed || generation !== token) return
        if (!result || !Array.isArray(result.items) || result.page !== page || result.per_page !== 30
            || !Number.isInteger(result.total) || result.total < 0) throw new Error('Invalid step page')
        update({ items: result.items.slice(0, 30), total: result.total, page, error: '' })
      } catch (error) {
        if (!disposed && generation === token && !active.signal.aborted) update({ items: [], total: 0, error: '步骤记录暂时无法读取，请重试。' })
      } finally {
        if (!disposed && generation === token) { controller = null; update({ loading: false }) }
      }
    },
    cancel,
    dispose() { disposed = true; cancel() },
  }
}
