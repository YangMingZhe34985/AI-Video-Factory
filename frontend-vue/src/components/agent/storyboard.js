// Local storyboard estimates are advisory; the server validates ownership and the final plan.
export const clone = (value) => JSON.parse(JSON.stringify(value))
const round = (value) => Math.round(value * 10000) / 10000
const norm = (value) => String(value || '').normalize('NFKC').toLowerCase().replace(/[\s_-]+/g, '')
const label = (value) => String(value || '').replace(/\s*(系列|模型|family|series|model)\s*$/i, '')

export function matchesModel(value, model) {
  const requested = norm(label(value))
  const family = norm(model.model_id?.split(/[-_](?:t2v|i2v|r2v|image)(?:[-_]|$)/i)[0])
  return [norm(model.model_id), norm(model.display_name), family].includes(requested)
    || (/[a-z]$/.test(requested) && family.startsWith(requested))
}

export function eligibleModels(models, mode, spec = {}) {
  const video = ['i2v', 'first_last_frame'].includes(mode)
  const applies = (value) => {
    const exact = models.filter((model) => [norm(model.model_id), norm(model.display_name)].includes(norm(label(value))))
    const matches = exact.length ? exact : models.filter((model) => matchesModel(value, model))
    const imageOnly = matches.length > 0 && matches.every((model) => model.task_type === 'text_to_image')
    return spec.deliverable === 'image' ? !video : imageOnly !== video
  }
  const preferences = (spec.constraints?.model_preferences || []).filter(applies)
  const exclusions = (spec.constraints?.model_exclusions || []).filter(applies)
  return models.filter((model) => model.enabled !== false && model.capabilities?.agent_selectable
    && model.capabilities?.modes?.includes(mode)
    && preferences.every((value) => matchesModel(value, model))
    && !exclusions.some((value) => matchesModel(value, model)))
}

export function priceFor(models, modelId, quantity, expectedUnit) {
  const pricing = models.find((model) => model.model_id === modelId)?.capabilities?.pricing
  if (!pricing || pricing.unit !== expectedUnit || !Number.isFinite(pricing.credits_per_unit)
    || pricing.credits_per_unit < 0 || !Number.isFinite(quantity) || quantity < 0) return null
  return round(pricing.credits_per_unit * quantity)
}

export function previewTargets(plan) {
  return (plan?.shots || []).flatMap((shot) => [
    ...(shot.first_frame?.method === 'generate' ? [{ type: 'keyframe', id: shot.shot_id, frame: shot.first_frame }] : []),
    ...(shot.end_frame?.method === 'generate' ? [{ type: 'end_frame', id: shot.shot_id, frame: shot.end_frame }] : []),
  ])
}

export function previewFor(previews, type, id) {
  return previews?.[{ character: 'characters', keyframe: 'keyframes', end_frame: 'end_frames' }[type]]?.[id]
}

export function staleTargets(plan, previews) {
  return previewTargets(plan).filter((item) => {
    const preview = previewFor(previews, item.type, item.id)
    return preview?.stale || preview?.status === 'stale'
  })
}

export function incompleteTargets(plan, previews) {
  return previewTargets(plan).filter((item) => {
    const preview = previewFor(previews, item.type, item.id)
    return !preview || preview.status !== 'success' || preview.stale
  })
}

export function targetCost(targets, models) {
  const values = targets.map((item) => priceFor(models, item.frame.model_id, 1, 'image'))
  return values.some((value) => value === null) ? null : round(values.reduce((sum, value) => sum + value, 0))
}

export function videoCost(plan, models) {
  const values = (plan?.shots || []).map((shot) => priceFor(models, shot.motion?.model_id, shot.duration_sec, 'second'))
  return values.some((value) => value === null) ? null : round(values.reduce((sum, value) => sum + value, 0))
}

export function timeline(plan) {
  let start = 0
  return (plan?.shots || []).map((shot) => {
    const duration = Number.isFinite(shot.duration_sec) && shot.duration_sec > 0 ? shot.duration_sec : 0
    const entry = { ...shot, start, end: round(start + duration) }
    start = entry.end
    return entry
  })
}

export function localPlanCheck(plan, story, models, spec = {}, options = {}) {
  const issues = []
  const add = (code, message, shotId = null) => issues.push({ code, message, shot_id: shotId })
  const shots = plan?.shots || []
  const total = shots.reduce((sum, shot) => sum + (Number.isFinite(shot.duration_sec) ? shot.duration_sec : 0), 0)
  const target = spec.target_duration_sec ?? plan?.target_duration_sec ?? 0
  const tolerance = Math.max(spec.duration_tolerance_sec ?? 10, target * (options.durationToleranceRatio ?? 0.1))
  if (Math.abs(total - target) > tolerance + 1e-8) add('DURATION_MISMATCH', `总时长 ${round(total)} 秒，需在 ${round(Math.max(0, target - tolerance))}–${round(target + tolerance)} 秒内`)
  const characters = new Map((story?.characters || []).map((character) => [character.character_id, character]))
  const scenes = new Set((plan?.scenes || []).map((scene) => scene.scene_id))
  shots.forEach((shot, index) => {
    const id = shot.shot_id
    if (!shot.summary?.trim() || !shot.framing?.trim()) add('INVALID_PRODUCTION_PLAN', '画面内容和景别不能为空', id)
    if (shot.order !== index + 1 || (index === 0 && shot.transition_in !== 'start')
      || (index > 0 && shot.transition_in === 'start')
      || ((shot.transition_in === 'tail_frame') !== (shot.first_frame?.method === 'tail_frame'))) add('INVALID_TRANSITION', '镜头顺序或首帧来源与衔接方式不一致', id)
    if (shot.transition_in === 'keyframe_bridge' && (!options.keyframeBridgeEnabled || !shot.end_frame)) add('KEYFRAME_BRIDGE_UNAVAILABLE', '首尾帧衔接未开放或缺少尾帧', id)
    if (!scenes.has(shot.scene_id) || (shot.character_ids || []).some((characterId) => !characters.has(characterId))) add('INVALID_REFERENCE', '场景或角色引用不存在', id)
    const model = models.find((item) => item.model_id === shot.motion?.model_id)
    const mode = shot.motion?.mode
    if (!['i2v', 'first_last_frame'].includes(mode) || !eligibleModels(models, mode, spec).some((item) => item.model_id === model?.model_id)) add('MODEL_CAPABILITY_MISMATCH', '视频模型不满足模式或用户模型约束', id)
    const range = model?.capabilities?.duration
    const duration = shot.duration_sec
    const steps = range?.step ? (duration - range.min) / range.step : 0
    if (!Number.isFinite(duration) || duration <= 0 || !range || duration < range.min || duration > range.max
      || (range.step != null && (!Number.isFinite(range.step) || range.step <= 0 || Math.abs(steps - Math.round(steps)) > 1e-7))) add('MODEL_CAPABILITY_MISMATCH', '时长不符合模型范围或步长', id)
    for (const frame of [shot.first_frame, shot.end_frame].filter(Boolean)) {
      if (frame.method !== 'generate') continue
      if (!frame.prompt?.trim()) add('INVALID_PRODUCTION_PLAN', '生成关键帧的提示词不能为空', id)
      const image = models.find((item) => item.model_id === frame.model_id)
      const references = frame.reference_artifact_ids || []
      if (!eligibleModels(models, frame.image_mode, spec).some((item) => item.model_id === image?.model_id)
        || references.length > (image?.capabilities?.reference_images?.max || 0)
        || (frame.image_mode === 'i2i' && !references.length)) add('MODEL_CAPABILITY_MISMATCH', '图片模型不支持当前模式或参考图数量', id)
      const required = (shot.character_ids || []).flatMap((characterId) => characters.get(characterId)?.reference?.artifact_ids || [])
      if (required.length && (frame.image_mode !== 'i2i' || required.some((artifactId) => !references.includes(artifactId)))) add('CHARACTER_REFERENCE_MISSING', '关键帧必须引用角色参考图并使用图生图', id)
    }
    if (!shot.motion?.prompt?.trim()) add('INVALID_PRODUCTION_PLAN', '动作提示词不能为空', id)
  })
  const video = videoCost(plan, models)
  const preview = targetCost(previewTargets(plan), models)
  if (Number.isFinite(options.remainingBudget) && video !== null && preview !== null && video + preview > options.remainingBudget) add('BUDGET_EXCEEDED', '预计图片与视频费用超过剩余预算')
  return { issues, total: round(total), target, tolerance, video, preview }
}

export function editedPlan(plan, shot) {
  const next = clone(plan)
  const index = next.shots.findIndex((item) => item.shot_id === shot.shot_id)
  if (index < 0) return next
  next.shots[index] = clone(shot)
  // Duration is authoritative on ShotPlan; do not submit a stale provider parameter.
  if (next.shots[index].motion?.params && 'duration' in next.shots[index].motion.params) next.shots[index].motion.params.duration = shot.duration_sec
  return next
}
