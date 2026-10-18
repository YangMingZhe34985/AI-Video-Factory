<template>
  <section class="card" data-testid="transform-plan">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <h3 class="text-base font-semibold text-slate-900 dark:text-slate-100">{{ draft.title || t('title') }}</h3>
        <p class="mt-1 text-sm font-medium">{{ t('operation_' + draft.operation) }}</p>
        <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">{{ t('hint') }}</p>
      </div>
      <div class="text-sm tabular-nums">
        <strong class="text-xl">{{ amount(displayCost) }}</strong> credits
        <p class="text-xs text-slate-500">{{ quoteState.status === 'ready' ? t('quote_ready') : t('local') }}</p>
      </div>
    </header>

    <p class="notice mt-4">{{ t('fullOutput') }}</p>
    <div class="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_14rem]">
      <label class="field-label">{{ t('prompt') }}
        <textarea v-model="draft.prompt" data-testid="transform-prompt" class="field" rows="5" maxlength="8000" :readonly="!editable || disabled" />
      </label>
      <div class="space-y-3">
        <label class="field-label">{{ t('model') }}
          <select v-model="draft.model_id" data-testid="transform-model" class="field" :disabled="!editable || disabled">
            <option v-if="!hasModel" :value="draft.model_id" disabled>{{ draft.model_id }} · {{ t('unavailable') }}</option>
            <option v-for="model in options" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option>
          </select>
        </label>
        <label class="field-label">{{ t('duration') }}
          <input v-model.number="draft.params.duration" data-testid="transform-duration" class="field tabular-nums" type="number" min="2" max="30" step="1" :readonly="!editable || disabled" />
        </label>
        <label class="field-label">{{ t('resolution') }}
          <select v-model="draft.params.resolution" data-testid="transform-resolution" class="field" :disabled="!editable || disabled">
            <option v-if="draft.params.resolution && !resolutions.includes(draft.params.resolution)" :value="draft.params.resolution">{{ draft.params.resolution }}</option>
            <option v-for="value in resolutions" :key="value" :value="value">{{ value }}</option>
          </select>
        </label>
      </div>
    </div>

    <section class="mt-5">
      <h4 class="text-sm font-semibold">{{ t('materials') }}</h4>
      <ul class="mt-2 grid gap-2 sm:grid-cols-2">
        <li v-for="item in materials" :key="item.artifact_id" class="min-w-0 rounded-xl bg-slate-50 p-3 text-xs dark:bg-slate-800/60">
          <p class="font-medium">{{ item.source_url ? t('snapshot') : t(item.type) }}<span v-if="item.artifact_id === draft.source_artifact_id"> · {{ t('source') }}</span></p>
          <p class="mt-1 break-all">{{ item.file_name }}</p>
          <p v-if="item.unverified" class="mt-1 text-amber-700 dark:text-amber-400">{{ t('unverified') }}</p>
          <p v-if="Number.isFinite(item.duration_sec)" class="mt-1 tabular-nums">{{ t('durationValue', { seconds: amount(item.duration_sec) }) }}</p>
          <p v-if="item.page_count">{{ t('pages', { count: item.page_count }) }}</p>
          <p v-if="item.source_url" class="mt-1 break-all text-slate-500">{{ item.source_url }}</p>
        </li>
      </ul>
      <p v-if="draft.media?.some((item) => item.type === 'reference_audio')" class="mt-2 text-xs text-slate-500">{{ t('audioHint') }}</p>
      <p v-if="draft.media?.some((item) => item.type === 'file')" class="mt-2 text-xs text-slate-500">{{ t('textHint') }}</p>
    </section>

    <section class="mt-5 rounded-xl border border-slate-200 p-3 dark:border-slate-700" data-testid="transform-cost">
      <dl class="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div v-for="row in costRows" :key="row.key" class="min-w-0">
          <dt class="text-xs text-slate-500">{{ t(row.key) }}</dt>
          <dd class="mt-1 break-words font-medium tabular-nums">{{ row.value === null ? t('unknown') : t(row.key === 'rate' ? 'perSecond' : 'seconds', { value: amount(row.value) }) }}</dd>
        </div>
      </dl>
      <p class="mt-3 text-xs">{{ t('formula') }}</p>
      <p class="mt-1 text-xs text-slate-500">{{ t('demo') }}</p>
    </section>
    <div v-if="editable" class="mt-3 text-sm" role="status" data-testid="transform-quote-state">
      <p>{{ t('quote_' + quoteState.status) }}</p>
      <p v-if="failure" class="mt-1 break-words text-red-600 dark:text-red-400">{{ failure }}</p>
      <button type="button" class="mt-2 text-blue-600 underline disabled:opacity-50" :disabled="disabled || quoteState.status === 'loading'" @click="refresh">{{ t('refresh') }}</button>
    </div>
    <details v-if="draft.rationale || draft.assumptions?.length" class="mt-4 text-sm">
      <summary class="cursor-pointer text-slate-500">{{ t('rationale') }}</summary>
      <p class="mt-2 whitespace-pre-wrap">{{ draft.rationale }}</p>
      <ul v-if="draft.assumptions?.length" class="mt-2 list-disc space-y-1 pl-5" :aria-label="t('assumptions')"><li v-for="item in draft.assumptions" :key="item">{{ item }}</li></ul>
    </details>
    <footer v-if="editable" class="mt-5 flex flex-wrap gap-3">
      <button type="button" class="primary-btn" data-testid="transform-approve" :disabled="!canApprove" @click="approve">{{ t('approve') }}</button>
      <button type="button" class="secondary-btn" :disabled="disabled" @click="$emit('reject')">{{ t('reject') }}</button>
    </footer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { quoteAgentTransform } from '@/api/agent'
import { createTransformQuoter, transformDraftKey, transformEstimate, transformModels, transformQuoteReady } from './transform'
import messages from './transform-messages'

const props = defineProps({
  runId: { type: String, required: true }, plan: { type: Object, required: true },
  models: { type: Array, default: () => [] }, attachments: { type: Array, default: () => [] }, spec: { type: Object, default: () => ({}) },
  editable: { type: Boolean, default: false }, disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['approve', 'reject'])
const { t, te } = useI18n({ useScope: 'local', messages })
const copy = (value) => JSON.parse(JSON.stringify(value))
const draft = ref({ ...copy(props.plan), params: { ...props.plan.params } })
const quoteState = reactive({ status: transformQuoteReady(props.plan, props.plan) ? 'ready' : 'invalid', quote: copy(props.plan), error: '' })
let applyingQuote = false
const quoter = createTransformQuoter((plan, signal) => quoteAgentTransform(props.runId, plan, signal), (state) => {
  if (state.quote) {
    applyingQuote = true
    draft.value = copy(state.quote)
    applyingQuote = false
  }
  Object.assign(quoteState, state)
})
const materials = computed(() => draft.value.manifest?.length ? draft.value.manifest : (draft.value.media || []).map((ref) => {
  const attachment = props.attachments.find((item) => item.attachment_id === ref.artifact_id)
  return { ...ref, file_name: attachment?.file_name || ref.artifact_id, unverified: true }
}))
const options = computed(() => transformModels(props.models, draft.value.operation, props.spec))
const hasModel = computed(() => options.value.some((model) => model.model_id === draft.value.model_id))
const model = computed(() => props.models.find((item) => item.model_id === draft.value.model_id))
const resolutions = computed(() => Object.keys(model.value?.capabilities?.pricing?.resolution_rates || {}))
const canApprove = computed(() => props.editable && !props.disabled && hasModel.value && quoteState.status === 'ready' && transformQuoteReady(quoteState.quote, draft.value))
const cost = computed(() => quoteState.status === 'ready' ? quoteState.quote?.cost_breakdown : null)
const displayCost = computed(() => cost.value?.estimated_cost ?? transformEstimate(draft.value, props.models))
const costRows = computed(() => [
  { key: 'input', value: cost.value?.input_video_seconds ?? null },
  { key: 'output', value: cost.value?.output_video_seconds ?? null },
  { key: 'billable', value: cost.value?.billable_seconds ?? null },
  { key: 'rate', value: cost.value?.credits_per_second ?? null },
  ...(draft.value.operation === 'extend' ? [{ key: 'extension', value: cost.value?.extension_seconds ?? null }] : []),
])
const amount = (value) => typeof value === 'number' && Number.isFinite(value) ? Math.round(value * 10000) / 10000 : t('unknown')
const failure = computed(() => {
  const error = quoteState.error
  if (!error) return ''
  if (typeof error === 'string') return te(error) ? t(error) : error
  const payload = error.response?.data?.error
  return payload ? [payload.code, payload.message].filter(Boolean).join(': ') : t('quote_error')
})
function refresh() { if (props.editable && !props.disabled) quoter.schedule(copy(draft.value), true) }
function approve() {
  if (canApprove.value) emit('approve', { plan: copy(quoteState.quote), onError(error) {
    quoter.cancel()
    Object.assign(quoteState, { status: 'error', quote: null, error })
  } })
}
watch(() => transformDraftKey(draft.value), () => {
  if (!applyingQuote && props.editable) quoter.schedule(copy(draft.value))
}, { flush: 'sync' })
watch(() => props.editable, (editable) => {
  if (editable) refresh()
  else quoter.cancel()
}, { immediate: true })
watch(() => props.plan.plan_hash, (hash, previous) => {
  if (hash !== previous) {
    applyingQuote = true
    draft.value = { ...copy(props.plan), params: { ...props.plan.params } }
    applyingQuote = false
    if (props.editable) refresh()
  }
})
onBeforeUnmount(() => quoter.dispose())
</script>

<style scoped>
.card { @apply min-w-0 rounded-2xl border border-slate-200 bg-white p-5 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200; overflow-wrap: anywhere; }
.notice { @apply rounded-xl bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200; }
.field-label { @apply flex min-w-0 flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400; }
.field { @apply w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 read-only:bg-slate-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:read-only:bg-slate-900; }
.primary-btn { @apply rounded-xl bg-blue-600 px-4 py-2 text-left text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply rounded-xl border border-slate-300 px-4 py-2 text-left text-sm disabled:opacity-50 dark:border-slate-600; }
</style>
