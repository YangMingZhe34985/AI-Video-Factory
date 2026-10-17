<template>
  <section class="card">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 class="text-base font-semibold text-slate-900 dark:text-slate-100">{{ plan.title || t('planTitle') }}</h3>
        <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ t('planHint') }}</p>
      </div>
      <div class="sm:text-right">
        <p class="text-2xl font-semibold tabular-nums text-slate-900 dark:text-slate-100">{{ format(total) }}<span class="ml-1 text-sm font-normal text-slate-500">credits</span></p>
        <p class="text-[11px] text-slate-400">{{ t('estimateLocal') }}</p>
      </div>
    </header>

    <ol class="mt-5 space-y-4">
      <li v-if="plan.image" class="step">
        <div class="step-head">
          <span class="step-no">1</span>
          <span class="font-medium">{{ t('imageStep') }}</span>
          <span class="tag">{{ t(`mode_${plan.image.mode}`) }}</span>
          <span class="ml-auto text-xs tabular-nums text-slate-500">{{ t('estimate', { cost: format(imageCost) }) }}</span>
        </div>
        <div class="grid gap-4 md:grid-cols-[minmax(0,1fr)_14rem]">
          <label class="field-label">{{ t('prompt') }}
            <textarea v-model="plan.image.prompt" class="field" rows="5" maxlength="8000" :readonly="!editable" />
          </label>
          <div class="space-y-3">
            <label class="field-label">{{ t('model') }}
              <select v-model="plan.image.model_id" class="field" :disabled="!editable">
                <option v-for="model in modelsFor(plan.image.mode)" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option>
              </select>
            </label>
            <label class="field-label">{{ t('count') }}
              <input v-model.number="plan.image.n" type="number" min="1" max="4" class="field tabular-nums" :readonly="!editable" />
            </label>
            <div v-if="plan.image.reference_attachment_ids?.length">
              <span class="field-label">{{ t('references') }}</span>
              <div class="mt-1 flex flex-wrap gap-1.5">
                <AuthedImage v-for="id in plan.image.reference_attachment_ids" :key="id" :src="previewOf(id)" class="h-12 w-12 rounded-lg object-cover ring-1 ring-slate-200 dark:ring-slate-700" />
              </div>
            </div>
          </div>
        </div>
      </li>

      <li v-if="plan.video" class="step">
        <div class="step-head">
          <span class="step-no">{{ plan.image ? 2 : 1 }}</span>
          <span class="font-medium">{{ t('videoStep') }}</span>
          <span class="tag">{{ t(`mode_${plan.video.mode}`) }}</span>
          <span class="ml-auto text-xs tabular-nums text-slate-500">{{ t('estimate', { cost: format(videoCost) }) }}</span>
        </div>
        <div class="grid gap-4 md:grid-cols-[minmax(0,1fr)_14rem]">
          <div class="space-y-3">
            <div class="flex items-center gap-3 rounded-xl bg-slate-50 p-2 dark:bg-slate-800/60">
              <AuthedImage v-if="plan.video.first_frame === 'user_attachment'" :src="previewOf(plan.video.first_frame_attachment_id)" class="h-12 w-12 flex-none rounded-lg object-cover" />
              <span v-else class="flex h-12 w-12 items-center justify-center rounded-lg bg-slate-200 text-xs text-slate-500 dark:bg-slate-700">1 →</span>
              <span class="text-xs text-slate-600 dark:text-slate-300">{{ t('firstFrame') }} · {{ t(plan.video.first_frame === 'user_attachment' ? 'firstFrameUser' : 'firstFrameGenerated') }}</span>
            </div>
            <label class="field-label">{{ t('motionPrompt') }}
              <textarea v-model="plan.video.prompt" class="field" rows="4" maxlength="8000" :readonly="!editable" />
            </label>
          </div>
          <div class="space-y-3">
            <label class="field-label">{{ t('model') }}
              <select v-model="plan.video.model_id" class="field" :disabled="!editable">
                <option v-for="model in modelsFor(plan.video.mode)" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option>
              </select>
            </label>
            <label class="field-label">{{ t('durationSec') }}
              <input v-model.number="plan.video.params.duration" type="number" class="field tabular-nums" :min="range?.min" :max="range?.max" :step="range?.step || 1" :readonly="!editable" />
              <span v-if="range" class="text-[11px]" :class="durationOk ? 'text-slate-400' : 'text-red-600'">{{ t('durationRange', range) }}</span>
            </label>
          </div>
        </div>
      </li>
    </ol>

    <details v-if="plan.rationale" class="mt-4 text-sm">
      <summary class="cursor-pointer text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">{{ t('rationale') }}</summary>
      <p class="mt-2 whitespace-pre-wrap text-slate-600 dark:text-slate-300">{{ plan.rationale }}</p>
    </details>

    <footer v-if="editable" class="mt-5 flex flex-wrap gap-3">
      <button type="button" class="primary-btn" :disabled="disabled || !durationOk" @click="$emit('approve', plan)">{{ t('approve') }}</button>
      <button type="button" class="secondary-btn" :disabled="disabled" @click="$emit('reject')">{{ t('reject') }}</button>
    </footer>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AuthedImage from './AuthedImage.vue'
import messages from './messages'

const props = defineProps({
  plan: { type: Object, required: true },          // mutable draft (SimplePlan, CONTRACTS A.8)
  models: { type: Array, default: () => [] },
  attachments: { type: Array, default: () => [] },
  editable: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
defineEmits(['approve', 'reject'])
const { t } = useI18n({ useScope: 'local', messages })

if (props.plan.video && !props.plan.video.params) props.plan.video.params = {}

const byId = (id) => props.models.find((model) => model.model_id === id)
function modelsFor(mode) {
  const options = props.models.filter((model) => model.enabled !== false && model.capabilities?.agent_selectable && model.capabilities?.modes?.includes(mode))
  const current = props.plan[mode === 'i2v' ? 'video' : 'image']?.model_id
  return current && !options.some((model) => model.model_id === current) ? [{ model_id: current }, ...options] : options
}
const previewOf = (id) => props.attachments.find((item) => item.attachment_id === id)?.preview_url || `/api/artifacts/${id}/preview`

function price(model, quantity) {
  const pricing = model?.capabilities?.pricing
  return pricing ? Number(pricing.credits_per_unit || 0) * quantity : 0
}
const imageCost = computed(() => (props.plan.image ? price(byId(props.plan.image.model_id), props.plan.image.n || 1) : 0))
const videoCost = computed(() => (props.plan.video ? price(byId(props.plan.video.model_id), props.plan.video.params?.duration || 0) : 0))
const total = computed(() => (imageCost.value || videoCost.value ? imageCost.value + videoCost.value : props.plan.estimated_cost || 0))
const range = computed(() => byId(props.plan.video?.model_id)?.capabilities?.duration || null)
const durationOk = computed(() => {
  if (!props.plan.video || !range.value) return true
  const value = props.plan.video.params?.duration
  return Number.isFinite(value) && value >= range.value.min && value <= range.value.max
})
const format = (value) => (Math.round(value * 10) / 10).toString()
</script>

<style scoped>
.card { @apply rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900; }
.step { @apply rounded-xl border border-slate-200 p-4 dark:border-slate-700; }
.step-head { @apply mb-3 flex flex-wrap items-center gap-2 text-sm text-slate-900 dark:text-slate-100; }
.step-no { @apply flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white dark:bg-slate-200 dark:text-slate-900; }
.tag { @apply rounded-md border border-slate-200 px-2 py-0.5 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300; }
.field-label { @apply flex flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400; }
.field { @apply w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 read-only:bg-slate-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:read-only:bg-slate-900; }
.primary-btn { @apply rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply rounded-xl border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
</style>
