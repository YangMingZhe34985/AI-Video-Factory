// Presentation helpers only. Scheduling, permissions and prices stay server-authoritative.
export const reviewStatuses = new Set(['awaiting_video_review', 'production_attention'])
export const productionLabels = {
  pending: '排队待执行', waiting_dependency: '等待上游尾帧', running: '生成中', success: '已完成',
  failed: '失败 · 待处理', blocked: '被上游阻塞', stale: '待重做', cancelled: '已取消',
}
export const recoveryLabels = {
  retry: '可局部重试', retry_local: '可恢复本地处理', retry_same_task: '查询原任务结果',
  rewrite_prompt: '改写动作提示词后重做', revise_plan: '需要修改计划',
  return_to_director: '需要修改计划', replan: '返回分镜修改', manual_review: '需要人工核实', stop: '已停止自动修复',
}
export const categoryLabels = {
  transient: '临时服务故障', content_policy: '内容审核', invalid_params: '参数不符',
  capability: '模型能力不符', budget: '预算不足', unknown_submission: '提交结果不确定',
  output_invalid: '输出无效', dependency: '依赖尚未完成', local_media: '本地媒体处理失败', unknown: '需要核实',
}

export function finiteCredits(value) {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}
export function creditText(value) {
  const numeric = finiteCredits(value)
  return numeric == null ? '待服务器估算' : String(Math.round(numeric * 100) / 100)
}
export function productionRows(plan, production) {
  const rows = new Map((production?.shots || []).map((shot) => [shot.shot_id, shot]))
  return [...(plan?.shots || [])].sort((a, b) => a.order - b.order).map((shot) => ({
    ...shot, status: 'pending', attempt: 0, can_retry: false, can_redo: false,
    ...rows.get(shot.shot_id),
  }))
}
export function productionCounts(rows) {
  const counts = { total: rows.length, success: 0, running: 0, waiting: 0, attention: 0 }
  for (const row of rows) {
    if (row.status === 'success') counts.success++
    else if (row.status === 'running') counts.running++
    else if (['failed', 'blocked', 'stale'].includes(row.status)) counts.attention++
    else counts.waiting++
  }
  return counts
}
export function dependencyText(row) {
  if (row.depends_on?.length) return `串行承接 ${row.depends_on.join('、')} → ${row.shot_id}；须等上游视频与尾帧完成`
  if (row.motion?.mode === 'first_last_frame') return '首尾两端关键帧就绪后生成；可与无依赖镜头并行'
  return '独立镜头；关键帧就绪后可与其他无依赖镜头并行'
}
export function quoteImpact(quote, scope) {
  if (!quote?.shot_id || !['only', 'cascade'].includes(scope)) return { shots: [], retained: [], cost: null }
  const descendants = [...new Set((quote.affected_shot_ids || []).filter((id) => id !== quote.shot_id))]
  return {
    shots: scope === 'cascade' ? [quote.shot_id, ...descendants] : [quote.shot_id],
    retained: scope === 'only' ? [...new Set((quote.kept_shot_ids || []).filter((id) => id !== quote.shot_id))] : [],
    cost: finiteCredits(quote.estimated_credits?.[scope]),
  }
}
export function isCurrentQuote(quote, context) {
  return Boolean(quote?.quote_id && quote.base_version === context?.planVersion && quote.shot_id === context?.shotId)
}
export function productionActionAllowed(status, row, operation, disabled = false) {
  return !disabled && reviewStatuses.has(status) && Boolean(operation === 'retry' ? row?.can_retry : row?.can_redo)
}
export function buildShotAction(quote, context, scope, operation) {
  if (!['redo', 'retry'].includes(operation)) throw new Error('不支持的生产操作。')
  if (!isCurrentQuote(quote, context)) throw new Error('报价已失效，请重新获取报价。')
  if (operation === 'retry' && (!quote.can_retry || scope !== 'only')) throw new Error('此镜头暂不可重试。')
  if (!['only', 'cascade', 'cancel'].includes(scope)) throw new Error('请选择重做范围。')
  if (scope !== 'cancel' && quoteImpact(quote, scope).cost == null) throw new Error('无法确认费用，请重新获取报价。')
  const payload = { shot_id: quote.shot_id, base_version: quote.base_version, quote_id: quote.quote_id }
  if (operation === 'redo') {
    payload.scope = scope
    if (context.motionPrompt?.trim()) payload.motion_prompt = context.motionPrompt.trim()
  }
  return { action: operation === 'retry' ? 'retry_shot' : 'redo_shot', payload }
}
export function productionError(error) {
  if (!error) return ''
  if (typeof error === 'string') return error
  return [error.summary || error.message, error.code].filter(Boolean).join(' · ') || '生成失败，请核实后再处理。'
}
