import test from 'node:test'
import assert from 'node:assert/strict'
import { clone, editedPlan, eligibleModels, incompleteTargets, localPlanCheck, normalizeStoryRules, priceFor, staleTargets, targetCost, timeline, videoCost } from '../src/components/agent/storyboard.js'

const models = [
  { model_id: 'wan2.7-image', task_type: 'text_to_image', enabled: true, capabilities: { agent_selectable: true, modes: ['t2i', 'i2i'], reference_images: { max: 3 }, pricing: { unit: 'image', credits_per_unit: 2 } } },
  ...['wan2.7-i2v', 'happy-horse-i2v'].map((id) => ({ model_id: id, task_type: 'image_to_video', enabled: true, capabilities: { agent_selectable: true, modes: ['i2v'], duration: { min: 5, max: 15, step: 5 }, pricing: { unit: 'second', credits_per_unit: id.startsWith('wan') ? 1 : 3 } } })),
]
const story = { characters: [{ character_id: 'cat', reference: { source: 'attachment', artifact_ids: ['ref-cat'] } }] }
const spec = { deliverable: 'video', target_duration_sec: 120, duration_tolerance_sec: 5, constraints: { model_preferences: ['wan2.7系列'], model_exclusions: ['happy horse'] } }
const makePlan = () => ({ recipe: 'story_video', target_duration_sec: 120, scenes: [{ scene_id: 'room' }], shots: Array.from({ length: 8 }, (_, index) => ({
  shot_id: `s0${index + 1}`, order: index + 1, scene_id: 'room', character_ids: ['cat'], summary: '猫寻找钥匙', framing: '中景', duration_sec: 15,
  transition_in: index === 0 ? 'start' : 'independent', depends_on: [],
  first_frame: { method: 'generate', image_mode: 'i2i', model_id: 'wan2.7-image', prompt: '保持猫的身份，蓝色围巾。', reference_artifact_ids: ['ref-cat'] },
  end_frame: null, motion: { mode: 'i2v', model_id: 'wan2.7-i2v', prompt: '猫缓慢抬头，镜头推进。', params: { duration: 15 } },
})) })

 test('two-minute storyboard checks cleanly and video fees use seconds', () => {
  const result = localPlanCheck(makePlan(), story, models, spec)
  assert.deepEqual(result.issues, [])
  assert.equal(result.total, 120)
  assert.equal(result.tolerance, 12)
  assert.equal(result.video, 120)
  assert.equal(result.preview, 16)
 })
 test('duration editing updates total, model grid and video estimate without mutating original', () => {
  const original = makePlan()
  const changed = editedPlan(original, { ...original.shots[0], duration_sec: 6 })
  assert.equal(original.shots[0].duration_sec, 15)
  assert.equal(changed.shots[0].motion.params.duration, 6)
  assert.equal(localPlanCheck(changed, story, models, spec).total, 111)
  assert.equal(videoCost(changed, models), 111)
  assert(localPlanCheck(changed, story, models, spec).issues.some((issue) => issue.code === 'MODEL_CAPABILITY_MISMATCH' && issue.shot_id === 's01'))
 })
 test('target duration mismatch uses explicit tolerance and configured ratio', () => {
  const changed = makePlan(); changed.shots[0].duration_sec = 5; changed.shots[1].duration_sec = 5
  assert(localPlanCheck(changed, story, models, spec).issues.some((issue) => issue.code === 'DURATION_MISMATCH'))
  assert(!localPlanCheck(changed, story, models, spec, { durationToleranceRatio: 0.2 }).issues.some((issue) => issue.code === 'DURATION_MISMATCH'))
 })
 test('video preference and exclusion do not wrongly filter support image models', () => {
  assert.deepEqual(eligibleModels(models, 'i2v', spec).map((model) => model.model_id), ['wan2.7-i2v'])
  assert.equal(eligibleModels(models, 'i2i', spec)[0].model_id, 'wan2.7-image')
  assert.equal(eligibleModels(models, 'i2v', { deliverable: 'video', constraints: { model_exclusions: ['wan2.7', 'happy-horse'] } }).length, 0)
 })
 test('unknown prices are unknown rather than free', () => {
  assert.equal(priceFor(models, 'missing', 5, 'second'), null)
  assert.equal(priceFor(models, 'wan2.7-image', 5, 'second'), null)
  assert.equal(priceFor(models, 'wan2.7-i2v', NaN, 'second'), null)
  const plan = makePlan(); plan.shots[0].motion.model_id = 'missing'
  assert.equal(videoCost(plan, models), null)
 })
 test('failed and stale images block approval, while supplied and tail frames need no preview generation', () => {
  const plan = makePlan()
  const previews = { keyframes: Object.fromEntries(plan.shots.map((shot) => [shot.shot_id, { status: 'success', stale: false }])) }
  previews.keyframes.s02.status = 'failed'; previews.keyframes.s03.stale = true
  plan.shots[3].first_frame.method = 'tail_frame'; plan.shots[4].first_frame.method = 'user_image'
  delete previews.keyframes.s04; delete previews.keyframes.s05
  assert.deepEqual(incompleteTargets(plan, previews).map((item) => item.id), ['s02', 's03'])
  assert.deepEqual(staleTargets(plan, previews).map((item) => item.id), ['s03'])
  assert.equal(targetCost(staleTargets(plan, previews), models), 2)
 })
 test('stale batch includes end frames without double counting missing or failed images', () => {
  const plan = makePlan(); plan.shots[0].end_frame = clone(plan.shots[0].first_frame)
  const previews = { keyframes: { s01: { status: 'stale' }, s02: { status: 'failed' } }, end_frames: { s01: { status: 'success', stale: true } } }
  assert.equal(staleTargets(plan, previews).length, 2)
  assert.equal(targetCost(staleTargets(plan, previews), models), 4)
 })
 test('character references and image model reference count are checked', () => {
  const plan = makePlan(); plan.shots[0].first_frame.reference_artifact_ids = []
  const issues = localPlanCheck(plan, story, models, spec).issues
  assert(issues.some((issue) => issue.code === 'CHARACTER_REFERENCE_MISSING' && issue.shot_id === 's01'))
  plan.shots[0].first_frame.reference_artifact_ids = ['ref-cat', 'a', 'b', 'c']
  assert(localPlanCheck(plan, story, models, spec).issues.some((issue) => issue.code === 'MODEL_CAPABILITY_MISMATCH' && issue.shot_id === 's01'))
 })
 test('tail-frame dependencies and experimental bridges are checked', () => {
  const plan = makePlan(); plan.shots[1].transition_in = 'tail_frame'
  assert(localPlanCheck(plan, story, models, spec).issues.some((issue) => issue.code === 'INVALID_TRANSITION'))
  plan.shots[1].first_frame.method = 'tail_frame'
  assert(!localPlanCheck(plan, story, models, spec).issues.some((issue) => issue.code === 'INVALID_TRANSITION'))
  plan.shots[2].transition_in = 'keyframe_bridge'
  assert(localPlanCheck(plan, story, models, spec).issues.some((issue) => issue.code === 'KEYFRAME_BRIDGE_UNAVAILABLE'))
 })
 test('timeline accumulates exact positions and invalid input cannot poison every row', () => {
  const plan = makePlan(); plan.shots[0].duration_sec = NaN
  const rows = timeline(plan)
  assert.equal(rows[1].start, 0); assert.equal(rows[7].end, 105)
  assert(Number.isNaN(plan.shots[0].duration_sec))
 })
 test('zero price stays a valid explicit price', () => {
  const free = clone(models); free[1].capabilities.pricing.credits_per_unit = 0
  assert.equal(priceFor(free, 'wan2.7-i2v', 10, 'second'), 0)
 })
 test('local budget issue and disabled model are surfaced independently', () => {
  const catalog = clone(models); catalog[1].enabled = false
  const result = localPlanCheck(makePlan(), story, catalog, spec, { remainingBudget: 100 })
  assert(result.issues.some((issue) => issue.code === 'MODEL_CAPABILITY_MISMATCH'))
  assert(result.issues.some((issue) => issue.code === 'BUDGET_EXCEEDED'))
 })

 test('server story rules override client defaults including zero tolerance', () => {
  assert.deepEqual(normalizeStoryRules(), { durationToleranceRatio: 0.1, maxShots: 30, keyframeBridgeEnabled: false })
  const rules = normalizeStoryRules({ duration_tolerance_ratio: 0, max_shots: 4, keyframe_bridge_enabled: true })
  assert.deepEqual(rules, { durationToleranceRatio: 0, maxShots: 4, keyframeBridgeEnabled: true })
  assert(localPlanCheck(makePlan(), story, models, spec, rules).issues.some((issue) => issue.code === 'INVALID_PRODUCTION_PLAN'))
  assert.equal(normalizeStoryRules({ duration_tolerance_ratio: -1, max_shots: 0, keyframe_bridge_enabled: 'false' }).durationToleranceRatio, 0.1)
 })
 test('stale batch honors server target quotes only when they match the current model', () => {
  const plan = makePlan()
  const previews = { keyframes: { s01: { status: 'stale', model_id: 'wan2.7-image', estimated_cost: 3 }, s02: { status: 'stale', model_id: 'old-image', estimated_cost: 90 } } }
  assert.equal(targetCost(staleTargets(plan, previews), models, previews), 5)
  previews.keyframes.s01.estimated_cost = 0
  assert.equal(targetCost(staleTargets(plan, previews), models, previews), 2)
 })

 test('compound Chinese model-family labels match the server normalization', () => {
  for (const preference of ['wan2.7系列视频模型', 'wan2.7系列的视频生成模型', 'wan2.7 视频生成模型']) {
    const request = { ...spec, constraints: { model_preferences: [preference] } }
    assert.deepEqual(eligibleModels(models, 'i2v', request).map((model) => model.model_id), ['wan2.7-i2v'])
    assert.equal(eligibleModels(models, 'i2i', request).length, 1)
  }
 })
