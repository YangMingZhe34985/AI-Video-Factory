import test from 'node:test'
import assert from 'node:assert/strict'
import { supportsTaskType } from '../src/utils/modelCapabilities.js'
import { eligibleModels, priceFor, videoCost } from '../src/components/agent/storyboard.js'
const models = [
  ...['wan3.0-video', 'wan3.0-video-prime'].map((id) => ({ model_id: id, task_type: 'text_to_video', enabled: true,
    default_params: { resolution: '720P' }, capabilities: { agent_selectable: true, family: 'wan3.0',
      modes: ['t2v', 'i2v', 'first_last_frame', 'r2v'], pricing: { unit: 'second', credits_per_unit: 2,
        resolution_rates: { '480P': 1, '720P': 2, '1080P': 3 }, billing_basis: 'input_plus_output_seconds' } } })),
  ...['qwen-image-3.0', 'qwen-image-3.0-pro'].map((id) => ({ model_id: id, task_type: 'text_to_image', enabled: true,
    capabilities: { family: 'qwen-image-3.0', modes: ['t2i', 'i2i'], agent_selectable: true } })),
]
const spec = (preferences, exclusions = []) => ({ deliverable: 'video', constraints: { model_preferences: preferences, model_exclusions: exclusions } })
test('classic filters accept executable modes without widening LLM roles', () => {
  for (const type of ['text_to_video', 'image_to_video', 'reference_to_video']) assert(supportsTaskType(models[0], type))
  assert(!supportsTaskType(models[0], 'video_understanding'))
  assert(!supportsTaskType({ task_type: 'prompt_rewrite', capabilities: { provider_capabilities: { modes: ['i2v'] } } }, 'image_to_video'))
  assert(supportsTaskType({ task_type: 'image_to_video' }, 'image_to_video'))
})
test('declared families preserve version boundaries and exact exclusions', () => {
  assert.deepEqual(eligibleModels(models, 'i2v', spec(['WAN 3.0系列'], ['wan3.0-video-prime'])).map((m) => m.model_id), ['wan3.0-video'])
  assert.equal(eligibleModels(models, 'i2v', spec(['wan3.01系列'])).length, 0)
})
test('exact image model wins over same-named family', () => {
  const imageSpec = (preference) => ({ deliverable: 'image', constraints: { model_preferences: [preference] } })
  assert.deepEqual(eligibleModels(models, 'i2i', imageSpec('qwen-image-3.0')).map((m) => m.model_id), ['qwen-image-3.0'])
  assert.equal(eligibleModels(models, 'i2i', imageSpec('qwen-image-3.0系列')).length, 2)
  const disabled = structuredClone(models); disabled[2].enabled = false
  assert.equal(eligibleModels(disabled, 'i2i', imageSpec('qwen-image-3.0')).length, 0)
})
test('resolution estimates match server and input plus output basis', () => {
  assert.equal(priceFor(models, 'wan3.0-video', 5, 'second'), 10)
  assert.equal(priceFor(models, 'wan3.0-video', 5, 'second', { resolution: '1080P' }), 15)
  assert.equal(priceFor(models, 'wan3.0-video', 5, 'second', { n_outputs: 2, input_video_seconds: 3 }), 26)
  assert.equal(priceFor(models, 'wan3.0-video', 5, 'second', { resolution: '4K' }), null)
  assert.equal(priceFor(models, 'wan3.0-video', 5, 'second', { input_video_seconds: -1 }), null)
  assert.equal(videoCost({ shots: [{ duration_sec: 5, motion: { model_id: 'wan3.0-video', params: { resolution: '1080P' } } }] }, models), 15)
})
