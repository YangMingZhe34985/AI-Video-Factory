import { finiteValue } from './v3-plan.js'

// User-stated delivery constraints (V13a duration, D-048 aspect ratio), read-only.
const MODE_LABELS = { approx: '约', exact: '正好', at_most: '不超过' }
const ASPECTS = new Set(['16:9', '9:16', '1:1', '4:3', '3:4'])
const DELIVERY_TOOLS = new Set(['compose_video', 'qc_video'])
const EPSILON = 1e-6

function durationConstraint(run) {
  const value = run?.plan?.duration_constraint
  const target = finiteValue(value?.target_duration_sec)
  if (!target || !MODE_LABELS[value?.mode]) return null
  const tolerance = value.mode === 'approx' ? finiteValue(value.duration_tolerance_sec) ?? 0 : 0
  const min = value.mode === 'at_most' ? 0 : Math.max(0, target - tolerance)
  const max = target + tolerance
  const actual = finiteValue(run?.estimates?.video_seconds)
  const issues = Array.isArray(run?.plan_issues) ? run.plan_issues : []
  const flagged = issues.some((issue) => issue?.code === 'PLAN_DURATION_MISMATCH' || issue?.code === 'PLAN_DURATION_UNKNOWN')
  let state = 'unknown'
  if (flagged) state = 'mismatch'
  else if (actual !== null) state = actual >= min - EPSILON && actual <= max + EPSILON ? 'ok' : 'mismatch'
  return { mode: value.mode, modeLabel: MODE_LABELS[value.mode], target, tolerance, min, max, actual, state }
}

function aspectConstraint(run) {
  const nodes = Array.isArray(run?.plan?.nodes) ? run.plan.nodes : []
  const found = new Set(nodes
    .filter((node) => DELIVERY_TOOLS.has(node?.tool))
    .map((node) => node?.inputs?.target_aspect_ratio)
    .filter((value) => ASPECTS.has(value)))
  return found.size === 1 ? [...found][0] : null
}

export function planConstraints(run) {
  const duration = durationConstraint(run)
  const aspect = aspectConstraint(run)
  return { duration, aspect, visible: Boolean(duration || aspect) }
}

const fmt = (value) => `${Number.isInteger(value) ? value : Number(value.toFixed(1))} 秒`

export function durationTargetLabel(duration) {
  if (!duration) return ''
  if (duration.mode === 'approx') return `约 ${fmt(duration.target)}（${fmt(duration.min).replace(' 秒', '')}–${fmt(duration.max)}）`
  return `${duration.modeLabel} ${fmt(duration.target)}`
}

export function durationStateLabel(duration) {
  if (!duration) return ''
  if (duration.state === 'ok') return `当前 ${fmt(duration.actual)} · 符合`
  if (duration.state === 'mismatch') return duration.actual === null ? '时长无法核对' : `当前 ${fmt(duration.actual)} · 不符合`
  return '待核对'
}
