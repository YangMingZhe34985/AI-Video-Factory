<template>
  <section class="card" data-testid="transform-plan">
    <header class="flex flex-wrap items-start justify-between gap-4">
      <div class="flex min-w-0 items-start gap-3">
        <span class="icon-tile"><component :is="operationIcon" :size="18" /></span>
        <div class="min-w-0">
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="text-[15px] font-semibold text-slate-900 dark:text-slate-100">{{ draft.title || t('title') }}</h3>
            <span class="chip-strong">{{ t('operation_' + draft.operation) }}</span>
          </div>
          <p class="mt-1 text-xs leading-relaxed text-slate-500 dark:text-slate-400">{{ t('hint') }}</p>
        </div>
      </div>
      <div class="cost-card">
        <p class="text-[11px] text-slate-500">{{ quoteState.status === 'ready' ? t('costLabel') : t('local') }}</p>
        <p class="mt-0.5 flex items-baseline gap-1"><strong class="text-2xl font-semibold tabular-nums text-slate-900 dark:text-white">{{ amount(displayCost) }}</strong><span class="text-xs text-slate-500">credits</span></p>
        <p class="mt-1 inline-flex items-center gap-1 text-[11px]" :class="quoteTone">
          <PhCircleNotch v-if="quoteState.status === 'loading'" :size="12" class="animate-spin" />
          <PhCheckCircle v-else-if="quoteState.status === 'ready'" :size="12" weight="fill" />
          <PhWarning v-else :size="12" />
          {{ t('quote_' + quoteState.status) }}
        </p>
      </div>
    </header>

    <p class="notice notice-blue mt-4"><PhInfo :size="16" class="mt-0.5 flex-none" />{{ t('fullOutput') }}</p>

    <!-- billable seconds against the 30 second input+output ceiling -->
    <div class="mt-4 rounded-xl bg-slate-50 p-4 dark:bg-slate-800/50" data-testid="transform-seconds">
      <div class="flex flex-wrap items-baseline justify-between gap-2 text-xs">
        <span class="font-medium text-slate-700 dark:text-slate-200">{{ t('secondsBar') }}</span>
        <span class="tabular-nums text-slate-500">{{ t('secondsUsed', { used: amount(barInput + barOutput), max: MAX_TOTAL }) }}</span>
      </div>
      <div class="relative mt-2 flex h-7 overflow-hidden rounded-lg bg-white ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700">
        <span v-if="barInput > 0" class="seg bg-slate-500" :style="{ width: share(barInput) }"><span class="truncate">{{ t('inputShort', { value: amount(barInput) }) }}</span></span>
        <span v-if="barOutput > 0" class="seg bg-blue-600" :style="{ width: share(barOutput) }"><span class="truncate">{{ t('outputShort', { value: amount(barOutput) }) }}</span></span>
        <span class="absolute inset-y-0 border-l border-dashed border-amber-500" :style="{ left: share(MAX_INPUT) }" :title="t('inputLimit')" />
      </div>
      <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
        <span class="legend"><span class="h-2 w-2 rounded-sm bg-slate-500" />{{ t('input') }}</span>
        <span class="legend"><span class="h-2 w-2 rounded-sm bg-blue-600" />{{ t('output') }}</span>
        <span class="legend"><span class="h-2 w-0 border-l border-dashed border-amber-500" />{{ t('inputLimit') }}</span>
        <span v-if="draft.operation === 'extend' && sourceSeconds != null" class="legend">{{ t('extendLegend', { source: amount(sourceSeconds), final: amount(barOutput) }) }}</span>
      </div>
    </div>

    <div class="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_15rem]">
      <label class="field-label">{{ t('prompt') }}
        <textarea v-model="draft.prompt" data-testid="transform-prompt" class="field" rows="7" maxlength="8000" :readonly="!editable || disabled" />
      </label>
      <div class="space-y-3 rounded-xl border border-slate-200 p-3 dark:border-slate-700">
        <label class="field-label">{{ t('model') }}
          <select v-model="draft.model_id" data-testid="transform-model" class="field" :disabled="!editable || disabled">
            <option v-if="!hasModel" :value="draft.model_id" disabled>{{ draft.model_id }} · {{ t('unavailable') }}</option>
            <option v-for="model in options" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option>
          </select>
        </label>
        <label class="field-label">{{ t('duration') }}
          <input v-model.number="draft.params.duration" data-testid="transform-duration" class="field tabular-nums" type="number" min="2" max="30" step="1" :readonly="!editable || disabled">
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
      <h4 class="flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100"><PhPaperclip :size="15" />{{ t('materials') }}<span class="count">{{ materials.length }}</span></h4>
      <ul class="mt-2 grid grid-cols-[repeat(auto-fill,minmax(min(15rem,100%),1fr))] gap-2">
        <li v-for="item in materials" :key="item.artifact_id" class="material" :class="item.artifact_id === draft.source_artifact_id ? 'material-source' : ''">
          <span class="material-icon"><component :is="materialIcon(item)" :size="16" /></span>
          <div class="min-w-0 flex-1 text-xs">
            <p class="flex flex-wrap items-center gap-1.5 font-medium text-slate-800 dark:text-slate-100">{{ item.source_url ? t('snapshot') : t(item.type) }}<span v-if="item.artifact_id === draft.source_artifact_id" class="chip-strong">{{ t('source') }}</span></p>
            <p class="mt-0.5 truncate text-slate-600 dark:text-slate-300" :title="item.file_name">{{ item.file_name }}</p>
            <p class="mt-0.5 flex flex-wrap gap-x-2 text-slate-500">
              <span v-if="Number.isFinite(item.duration_sec)" class="tabular-nums">{{ t('durationValue', { seconds: amount(item.duration_sec) }) }}</span>
              <span v-if="item.page_count">{{ t('pages', { count: item.page_count }) }}</span>
            </p>
            <p v-if="item.unverified" class="mt-0.5 text-amber-700 dark:text-amber-400">{{ t('unverified') }}</p>
            <p v-if="item.source_url" class="mt-0.5 truncate text-slate-400" :title="item.source_url">{{ item.source_url }}</p>
          </div>
        </li>
      </ul>
      <p v-if="draft.media?.some((item) => item.type === 'reference_audio')" class="mt-2 text-xs text-slate-500">{{ t('audioHint') }}</p>
      <p v-if="draft.media?.some((item) => item.type === 'file')" class="mt-2 text-xs text-slate-500">{{ t('textHint') }}</p>
    </section>

    <section class="mt-5 rounded-xl border border-slate-200 p-4 dark:border-slate-700" data-testid="transform-cost">
      <dl class="grid grid-cols-[repeat(auto-fit,minmax(8rem,1fr))] gap-3 text-sm">
        <div v-for="row in costRows" :key="row.key" class="min-w-0">
          <dt class="text-[11px] text-slate-500">{{ t(row.key) }}</dt>
          <dd class="mt-1 break-words font-semibold tabular-nums text-slate-900 dark:text-white">{{ row.value === null ? t('unknown') : t(row.key === 'rate' ? 'perSecond' : 'seconds', { value: amount(row.value) }) }}</dd>
        </div>
      </dl>
      <p class="mt-3 text-xs text-slate-600 dark:text-slate-300">{{ t('formula') }}</p>
      <p class="mt-1 text-[11px] text-slate-500">{{ t('demo') }}</p>
    </section>

    <details v-if="draft.rationale || draft.assumptions?.length" class="group mt-4 rounded-xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-700">
      <summary class="flex cursor-pointer list-none items-center gap-2 text-slate-600 dark:text-slate-300"><PhCaretDown :size="14" class="text-slate-400 transition-transform group-open:rotate-180" />{{ t('rationale') }}</summary>
      <p class="mt-2 text-xs text-slate-500">{{ t('initialRationaleHint') }}</p>
      <p class="mt-2 whitespace-pre-wrap">{{ draft.rationale }}</p>
      <ul v-if="draft.assumptions?.length" class="mt-2 list-disc space-y-1 pl-5" :aria-label="t('assumptions')"><li v-for="item in draft.assumptions" :key="item">{{ item }}</li></ul>
    </details>

    <footer v-if="editable" class="mt-5 flex flex-wrap items-center gap-3 rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-800/50">
      <div class="min-w-0 flex-1 text-xs" role="status" data-testid="transform-quote-state">
        <p :class="quoteTone">{{ t('quote_' + quoteState.status) }}</p>
        <p v-if="failure" class="mt-1 break-words text-red-600 dark:text-red-400">{{ failure }}</p>
      </div>
      <button type="button" class="secondary-btn" :disabled="disabled || quoteState.status === 'loading'" @click="refresh"><PhArrowClockwise :size="14" />{{ t('refresh') }}</button>
      <button type="button" class="ghost-btn" :disabled="disabled" @click="$emit('reject')">{{ t('reject') }}</button>
      <button type="button" class="primary-btn" data-testid="transform-approve" :disabled="!canApprove" @click="approve"><PhCheckCircle :size="15" />{{ t('approve') }}</button>
    </footer>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { quoteAgentTransform } from '@/api/agent'
import { createTransformQuoter, transformDraftKey, transformEstimate, transformModels, transformQuoteReady } from './transform'
import messages from './transform-messages'
import { knownErrorText } from './agent-errors'
import { PhArrowClockwise, PhArrowsOutLineHorizontal, PhCaretDown, PhCheckCircle, PhCircleNotch, PhFileText, PhGlobe, PhImage,
  PhInfo, PhMagicWand, PhPaperclip, PhScissors, PhSpeakerHigh, PhVideoCamera, PhWarning } from '@phosphor-icons/vue'

const props = defineProps({
  runId: { type: String, required: true }, plan: { type: Object, required: true },
  models: { type: Array, default: () => [] }, attachments: { type: Array, default: () => [] }, spec: { type: Object, default: () => ({}) },
  editable: { type: Boolean, default: false }, disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['approve', 'reject'])
const { t, te, locale } = useI18n({ useScope: 'local', messages })
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
  const known = knownErrorText(error, locale.value)
  if (known) return known
  const payload = error.response?.data?.error
  return payload ? [payload.code, payload.message].filter(Boolean).join(': ') : t('quote_error')
})
// Wan3 limits: input videos <= 15 s, input + output <= 30 s (CONTRACTS W.3).
const MAX_TOTAL = 30, MAX_INPUT = 15
const operationIcon = computed(() => ({ edit: PhScissors, extend: PhArrowsOutLineHorizontal }[draft.value.operation] || PhMagicWand))
const materialIcon = (item) => item.source_url ? PhGlobe : ({ reference_image: PhImage, reference_video: PhVideoCamera, reference_audio: PhSpeakerHigh, file: PhFileText }[item.type] || PhPaperclip)
const finiteOr = (value, fallback) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
// Prefer the authoritative quote; before it arrives show the draft's verified manifest seconds.
const barInput = computed(() => finiteOr(cost.value?.input_video_seconds, (draft.value.manifest || []).filter((item) => item.type === 'reference_video').reduce((sum, item) => sum + finiteOr(item.duration_sec, 0), 0)))
const barOutput = computed(() => finiteOr(cost.value?.output_video_seconds, finiteOr(draft.value.params?.duration, 0)))
const sourceSeconds = computed(() => finiteOr(cost.value?.source_video_seconds, (draft.value.manifest || []).find((item) => item.artifact_id === draft.value.source_artifact_id)?.duration_sec ?? null))
const share = (value) => `${Math.min(100, Math.max(0, (value / Math.max(MAX_TOTAL, barInput.value + barOutput.value)) * 100))}%`
const quoteTone = computed(() => ({ ready: 'text-emerald-700 dark:text-emerald-400', loading: 'text-blue-700 dark:text-blue-300', error: 'text-red-600 dark:text-red-400' }[quoteState.status] || 'text-amber-700 dark:text-amber-400'))
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
.icon-tile { @apply flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400; }
.chip-strong { @apply inline-flex items-center rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.cost-card { @apply min-w-[11rem] rounded-xl bg-slate-50 px-4 py-3 text-right dark:bg-slate-800/60; }
.notice { @apply flex gap-2 rounded-xl px-3 py-2.5 text-sm; }
.notice-blue { @apply bg-blue-50 text-blue-800 dark:bg-blue-950/40 dark:text-blue-200; }
.seg { @apply flex h-full min-w-0 items-center px-2 text-[11px] font-medium text-white; }
.legend { @apply inline-flex items-center gap-1.5; }
.count { @apply ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400; }
.material { @apply flex min-w-0 items-start gap-2.5 rounded-xl border border-slate-200 p-3 dark:border-slate-700; }
.material-source { @apply border-blue-300 bg-blue-50/40 dark:border-blue-800 dark:bg-blue-950/20; }
.material-icon { @apply flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.field-label { @apply flex min-w-0 flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400; }
.field { @apply w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 read-only:bg-slate-50 disabled:bg-slate-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:read-only:bg-slate-900 dark:disabled:bg-slate-900; }
.primary-btn { @apply inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply inline-flex items-center gap-1.5 rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-white disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
.ghost-btn { @apply rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:text-slate-300 dark:hover:bg-slate-800; }
</style>
