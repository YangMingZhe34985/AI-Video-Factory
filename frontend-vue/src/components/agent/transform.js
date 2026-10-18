// Local validation and estimates never replace the server's frozen quote.
import { matchesModel } from './storyboard.js'
export const TRANSFORM_MODES = { reference: 'omni_reference', edit: 'video_edit', extend: 'video_extend' }
const finite = (value) => typeof value === 'number' && Number.isFinite(value)
const round = (value) => Math.round(value * 10000) / 10000
const norm = (value) => String(value || '').normalize('NFKC').toLowerCase().replace(/[\s_-]+/g, '')
const label = (value) => String(value || '').replace(/(?:\s*(?:系列|(?:的)?(?:视频|图像|图片)?(?:生成)?模型|family|series|models?))+\s*$/i, '')

export function transformModels(models, operation, spec = {}) {
  const match = (value, model) => {
    const exact = /系列|\b(?:family|series)\b/i.test(value) ? [] : models.filter((item) =>
      [norm(item.model_id), norm(item.display_name)].includes(norm(label(value))))
    return exact.length ? exact.some((item) => item.model_id === model.model_id) : matchesModel(value, model)
  }
  const applies = (value) => {
    const known = models.filter((item) => match(value, item))
    return !known.length || !known.every((item) => item.task_type === 'text_to_image')
  }
  const preferences = (spec.constraints?.model_preferences || []).filter(applies)
  const exclusions = (spec.constraints?.model_exclusions || []).filter(applies)
  return models.filter((model) => model.enabled !== false && model.capabilities?.agent_selectable
    && model.capabilities?.modes?.includes(TRANSFORM_MODES[operation])
    && preferences.every((value) => match(value, model)) && !exclusions.some((value) => match(value, model)))
}

export function transformDraftKey(plan) {
  return JSON.stringify([plan?.recipe, plan?.operation, plan?.model_id, plan?.prompt, plan?.params,
    plan?.media, plan?.source_artifact_id, plan?.manifest])
}

export function transformDraftIssue(plan) {
  if (plan?.recipe !== 'video_transform' || !TRANSFORM_MODES[plan.operation] || !plan.model_id || !plan.prompt?.trim()) return 'invalidDraft'
  const duration = plan.params?.duration
  if (!Number.isInteger(duration) || duration < 2 || duration > 30) return 'durationInvalid'
  const incoming = (plan.manifest || []).filter((item) => item.type === 'reference_video')
  if (incoming.some((item) => !finite(item.duration_sec) || item.duration_sec <= 0)) return 'inputUnknown'
  const seconds = incoming.reduce((sum, item) => sum + item.duration_sec, 0)
  if (seconds > 15 || seconds + duration > 30 + 1e-8) return 'totalInvalid'
  if (plan.operation !== 'reference') {
    const source = incoming.find((item) => item.artifact_id === plan.source_artifact_id)
    if (!plan.source_artifact_id || ((plan.manifest || []).length && !source)) return 'sourceMissing'
    if (source && plan.operation === 'extend' && duration <= source.duration_sec) return 'extendInvalid'
  }
  return ''
}

export function transformEstimate(plan, models) {
  const model = models.find((item) => item.model_id === plan?.model_id), pricing = model?.capabilities?.pricing
  if (!pricing || pricing.unit !== 'second' || pricing.billing_basis !== 'input_plus_output_seconds' || transformDraftIssue(plan)) return null
  const manifest = plan.manifest || []
  if (!(plan.media || []).every((ref) => manifest.some((item) => item.artifact_id === ref.artifact_id && item.type === ref.type))) return null
  const params = { ...model.default_params, ...plan.params }
  const rate = pricing.resolution_rates == null ? pricing.credits_per_unit : pricing.resolution_rates[params.resolution]
  if (!finite(rate) || rate < 0) return null
  const input = manifest.filter((item) => item.type === 'reference_video').reduce((sum, item) => sum + item.duration_sec, 0)
  return round((input + params.duration) * rate)
}

export function transformQuoteReady(quote, draft) {
  const cost = quote?.cost_breakdown
  return Boolean(quote?.quote_id && quote.plan_hash && transformDraftKey(quote) === transformDraftKey(draft)
    && !transformDraftIssue(quote) && (quote.media || []).length > 0
    && (quote.media || []).every((ref) => (quote.manifest || []).some((item) => item.artifact_id === ref.artifact_id && item.type === ref.type))
    && cost && ['input_video_seconds', 'output_video_seconds', 'billable_seconds', 'credits_per_second', 'estimated_cost']
      .every((key) => finite(cost[key]) && cost[key] >= 0)
    && finite(quote.estimated_cost) && Math.abs(quote.estimated_cost - cost.estimated_cost) < 1e-4
    && Math.abs(cost.input_video_seconds - (quote.manifest || []).filter((item) => item.type === 'reference_video').reduce((sum, item) => sum + item.duration_sec, 0)) < 1e-7
    && cost.billing_basis === 'input_plus_output_seconds' && cost.output_video_seconds === quote.params.duration
    && Math.abs(cost.billable_seconds - cost.input_video_seconds - cost.output_video_seconds) < 1e-7
    && Math.abs(cost.estimated_cost - cost.billable_seconds * cost.credits_per_second) < 1e-4)
}

export function createTransformQuoter(fetchQuote, update, { delay = 400, setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  let sequence = 0, timer = null, controller = null, disposed = false
  function invalidate() {
    sequence++
    if (timer !== null) clearTimer(timer)
    timer = null
    controller?.abort()
    controller = null
  }
  async function load(draft, token) {
    if (disposed || token !== sequence) return
    timer = null
    controller = new AbortController()
    update({ status: 'loading', quote: null, error: '' })
    try {
      const quote = await fetchQuote(draft, controller.signal)
      if (disposed || token !== sequence) return
      if (quote.recipe !== draft.recipe || quote.operation !== draft.operation || quote.model_id !== draft.model_id
          || quote.prompt !== draft.prompt.trim() || quote.params?.duration !== draft.params?.duration
          || (draft.params?.resolution && quote.params?.resolution !== draft.params.resolution)
          || !transformQuoteReady(quote, quote)) throw new Error('QUOTE_RESPONSE_INVALID')
      update({ status: 'ready', quote, error: '' })
    } catch (error) {
      if (!disposed && token === sequence) update({ status: 'error', quote: null, error })
    } finally { if (token === sequence) controller = null }
  }
  return {
    schedule(plan, immediate = false) {
      if (disposed) return
      invalidate()
      const issue = transformDraftIssue(plan)
      update({ status: issue ? 'invalid' : 'waiting', quote: null, error: issue })
      if (issue) return
      const draft = structuredClone(plan), token = sequence
      if (immediate) return load(draft, token)
      timer = setTimer(() => load(draft, token), delay)
    },
    cancel() { invalidate() },
    dispose() { disposed = true; invalidate() },
  }
}
