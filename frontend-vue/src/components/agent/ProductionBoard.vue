<template>
  <section class="production-card" data-testid="production-board" :aria-label="t('boardLabel')">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 items-start gap-3">
        <span class="icon-tile"><PhFilmSlate :size="18" /></span>
        <div class="min-w-0"><h3 class="text-[15px] font-semibold text-slate-900 dark:text-white">{{ t('title') }}</h3><p class="mt-0.5 text-xs text-slate-500">{{ t('subtitle', { version: production.approved_version ?? production.plan_version ?? planVersion }) }}</p></div>
      </div>
      <span class="status-pill" :class="phaseTone"><PhCircleNotch v-if="status === 'producing'" :size="12" class="animate-spin" /><span v-else class="h-1.5 w-1.5 rounded-full bg-current" />{{ phaseLabel }}</span>
    </header>
    <p v-if="!production.enabled" class="notice mt-4">{{ t('disabledNote') }}</p>
    <p v-if="demo" class="mt-3 text-xs text-amber-700 dark:text-amber-400">{{ t('demoNote') }}</p>
    <div class="mt-4 grid gap-2 text-sm sm:grid-cols-2 xl:grid-cols-4" :aria-label="t('costs')">
      <div class="metric"><span>{{ t('videoEstimate') }}</span><strong>{{ money(estimates.video_credits) }} credits</strong></div>
      <div class="metric"><span>{{ t('videoSpent') }}</span><strong>{{ money(estimates.video_spent_credits) }} credits</strong></div>
      <div class="metric"><span>{{ t('repairSpent') }}</span><strong>{{ money(estimates.repair_spent_credits) }} credits</strong></div>
      <div class="metric"><span>{{ t('allSpent') }}</span><strong>{{ money(estimates.spent_credits) }} credits</strong></div>
    </div>
    <p class="mt-2 text-xs text-slate-500">{{ t('remainingNote', { cost: money(estimates.remaining_credits), repair: money(production.repair_budget_credits ?? 0) }) }}</p>
    <p v-if="actionEstimate != null" role="status" class="mt-2 text-xs text-slate-500">{{ t('submitted', { cost: money(actionEstimate) }) }}</p>
    <p v-if="error" role="alert" class="mt-3 break-words text-sm text-red-600 dark:text-red-400">{{ error }}</p>
    <div v-if="warnings.length" class="notice mt-4"><p class="font-medium">{{ t('warningTitle') }}</p><ul class="mt-1 space-y-1"><li v-for="(warning, index) in warnings" :key="index">{{ warning }}</li></ul></div>

    <div v-if="status === 'storyboard_approved'" class="mt-4 flex flex-wrap items-center gap-3">
      <button type="button" class="primary-btn" :disabled="locked || !production.enabled" @click="openStart">{{ t('start') }}</button>
      <p class="text-xs text-slate-500">{{ t('startNote') }}</p>
    </div>
    <div v-if="status === 'awaiting_video_review'" class="mt-4 flex flex-wrap items-center gap-3">
      <button type="button" class="primary-btn" :disabled="locked || !production.enabled || counts.success !== counts.total || !counts.total" @click="openApprove">{{ t('approveAll') }}</button>
      <p class="text-xs text-slate-500">{{ t('deliveryNote') }}</p>
    </div>
    <p v-if="status === 'production_attention'" class="notice mt-4">{{ t('attentionNote') }}</p>
    <button v-if="canReviewPlan" type="button" class="secondary-btn mt-3" :disabled="locked" @click="openReviewPlan">{{ t('reviewPlan') }}</button>
    <p v-if="status === 'videos_approved'" class="mt-4 text-sm text-emerald-700 dark:text-emerald-300">{{ t('approvedNote') }}</p>

    <div class="mt-5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500" role="status" aria-live="polite">
      <span>{{ t('completed', { n: counts.success, total: counts.total }) }}</span><span>{{ t('runningCount', { n: counts.running }) }}</span><span>{{ t('waitingCount', { n: counts.waiting }) }}</span><span>{{ t('attentionCount', { n: counts.attention }) }}</span>
    </div>
    <ol class="mt-3 grid gap-3 xl:grid-cols-2" :aria-label="t('shotStates')">
      <li v-for="shot in rows" :key="shot.shot_id" class="shot-card" :class="edge(shot.status)" :data-shot-id="shot.shot_id">
        <div class="flex flex-wrap items-center justify-between gap-2 text-xs"><strong class="text-slate-900 dark:text-white">{{ t('shotHeader', { id: shot.shot_id, seconds: shot.duration_sec }) }}</strong><span class="pill" :class="tone(shot.status)">{{ shotLabel(shot) }}</span></div>
        <p class="mt-2 text-sm font-medium">{{ shot.summary }}</p>
        <p class="mt-1 break-words text-xs text-slate-500">{{ dependencyLabel(shot) }}</p>
        <p class="mt-2 break-words text-xs text-slate-500">{{ t('shotCost', { model: shot.model_id || shot.motion?.model_id, cost: money(shot.estimated_credits), attempt: shot.attempt || 0, repairs: shot.repair_count || 0 }) }}</p>
        <p v-if="shot.retained" class="mt-2 text-xs text-amber-700 dark:text-amber-400">{{ t('retainedNote') }}</p>
        <div v-if="shot.error" class="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700 dark:bg-red-950/30 dark:text-red-300">
          <p>{{ label('category', shot.error.category, t('needsAttention')) }} · {{ productionError(shot.error) }}</p>
          <p v-if="shot.error.recovery_action" class="mt-1">{{ label('recovery', shot.error.recovery_action, shot.error.recovery_action) }}</p>
        </div>
        <AuthedVideo v-if="shot.preview_url" :key="shot.preview_url" :src="shot.preview_url" class="mt-3 max-h-64 w-full rounded-lg bg-black" :label="t('preview')" :loading-label="t('previewLoading')" :error-label="t('previewError')" />
        <div v-if="reviewable" class="mt-3 flex flex-wrap gap-2">
          <button v-if="shot.can_retry" type="button" class="secondary-btn" :disabled="!canAct(shot, 'retry')" @click="openShot(shot, 'retry')">{{ t('retryCost') }}</button>
          <button v-if="shot.can_redo" type="button" class="secondary-btn" :disabled="!canAct(shot, 'redo')" @click="openShot(shot, 'redo')">{{ t('redo') }}</button>
        </div>
      </li>
    </ol>

    <dialog ref="dialog" class="production-dialog" @cancel.prevent="cancelDialog" @click="onBackdrop" @close="resetDialog">
      <div v-if="confirmation" class="p-5">
        <div class="flex items-start justify-between gap-3"><h4 class="text-base font-semibold">{{ confirmation.kind === 'start' ? t('startTitle') : confirmation.kind === 'approve' ? t('confirmVideos') : confirmation.kind === 'review_plan' ? t('reviewPlan') : `${confirmation.shotId} · ${confirmation.operation === 'retry' ? t('retryTitle') : t('redoTitle')}` }}</h4><button type="button" class="secondary-btn" :disabled="locked" @click="cancelDialog">{{ t('close') }}</button></div>
        <p v-if="modalError" role="alert" class="mt-3 break-words text-sm text-red-600 dark:text-red-400">{{ modalError }}</p>
        <template v-if="confirmation.kind === 'start'">
          <p class="mt-4 text-sm">{{ t('startBody', { n: rows.length, cost: money(estimates.remaining_credits) }) }}</p>
          <label class="field-label mt-4">{{ t('repairBudget') }}<input v-model.number="repairBudget" type="number" min="0" step="0.1" class="field" /></label>
          <p class="mt-2 text-xs text-slate-500">{{ t('repairNote') }}</p>
          <p class="mt-3 text-sm">{{ t('startTotal', { cost: money(startTotal), budget: money(remainingBudget) }) }}</p>
          <button type="button" class="primary-btn mt-4" :disabled="locked || !validStart" @click="submitStart">{{ t('confirmStart') }}</button>
        </template>
        <template v-else-if="confirmation.kind === 'approve'">
          <p class="mt-4 text-sm">{{ t('approveBody', { version: planVersion, n: counts.total }) }}</p>
          <p v-if="warnings.length" class="notice mt-3">{{ t('approveWarning') }}</p>
          <button type="button" class="primary-btn mt-4" :disabled="locked || !production.enabled || status !== 'awaiting_video_review'" @click="submitApprove">{{ t('confirmVideos') }}</button>
        </template>
        <template v-else-if="confirmation.kind === 'review_plan'">
          <p class="mt-4 text-sm">{{ t('reviewPlanNote') }}</p>
          <button type="button" class="primary-btn mt-4" :disabled="locked || !canReviewPlan" @click="submit('review_plan', { plan_version: planVersion })">{{ t('confirmReviewPlan') }}</button>
        </template>
        <template v-else>
          <label v-if="confirmation.operation === 'redo'" class="field-label mt-4">{{ t('motionLabel') }}<textarea v-model="motionPrompt" class="field" rows="5" maxlength="8000" :readonly="locked" /></label>
          <p v-else class="mt-4 text-sm">{{ t('retryNote') }}</p>
          <button type="button" class="secondary-btn mt-3" :disabled="locked || quoting || !promptValid" @click="loadQuote">{{ quoting ? t('quoting') : quote ? t('refreshQuote') : t('getQuote') }}</button>
          <p v-if="!quote" class="mt-2 text-xs text-slate-500">{{ t('quoteNote') }}</p>
          <div v-else class="mt-4 space-y-3">
            <p class="text-xs text-slate-500">{{ t('quoteVersion', { version: quote.base_version }) }}<template v-if="remainingBudget != null"> · {{ t('remainingBudget', { budget: money(remainingBudget) }) }}</template></p>
            <p v-if="quote.reason" class="text-sm">{{ quote.reason }}</p>
            <ul v-if="quote.warnings?.length" class="notice"><li v-for="(warning, index) in quote.warnings" :key="index">{{ warningText(warning) }}</li></ul>
            <template v-if="confirmation.operation === 'redo'">
              <label class="choice" :class="overBudget(onlyImpact.cost) ? 'choice-over' : ''"><input v-model="scope" type="radio" value="only" name="redo-scope" /><span><strong>{{ t('onlyCost', { cost: money(onlyImpact.cost) }) }}</strong><span v-if="overBudget(onlyImpact.cost)" class="mt-1 block text-xs font-medium text-red-600 dark:text-red-400">{{ t('overBudget', { amount: money(onlyImpact.cost - remainingBudget) }) }}</span><span class="mt-1 block text-xs text-slate-500">{{ onlyImpact.retained.length ? t('retained', { shots: onlyImpact.retained.join(', ') }) : t('noRetained') }}</span></span></label>
              <label v-if="cascadeImpact.shots.length > 1" class="choice" :class="overBudget(cascadeImpact.cost) ? 'choice-over' : ''"><input v-model="scope" type="radio" value="cascade" name="redo-scope" /><span><strong>{{ t('cascadeCost', { cost: money(cascadeImpact.cost) }) }}</strong><span v-if="overBudget(cascadeImpact.cost)" class="mt-1 block text-xs font-medium text-red-600 dark:text-red-400">{{ t('overBudget', { amount: money(cascadeImpact.cost - remainingBudget) }) }}</span><span class="mt-1 block text-xs text-slate-500">{{ t('cascadeShots', { shots: cascadeImpact.shots.join(' → ') }) }}</span></span></label>
              <p class="text-sm">{{ t('redoScope', { shots: selectedImpact.shots.join(', '), cost: money(selectedImpact.cost) }) }}</p>
            </template>
            <p v-else class="text-sm">{{ t('retryTotal', { cost: money(onlyImpact.cost) }) }}{{ quote.can_retry ? '' : t('retryBlocked') }}</p>
            <p v-if="overBudget(selectedImpact.cost)" class="notice notice-red">{{ t('overBudgetBlocked') }}</p>
            <p v-if="selectedImpact.continuing.length" class="notice">{{ t('continuing', { shots: selectedImpact.continuing.join(', ') }) }}</p>
            <div class="flex flex-wrap gap-3"><button type="button" class="primary-btn" :disabled="locked || !confirmable" @click="submitShot">{{ confirmation.operation === 'retry' ? t('confirmRetry') : t('confirmRedo') }}</button><button type="button" class="secondary-btn" :disabled="locked" @click="cancelDialog">{{ t('cancel') }}</button></div>
          </div>
        </template>
      </div>
    </dialog>
  </section>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import messages from './production-messages'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import AuthedVideo from './AuthedVideo.vue'
import { PhCircleNotch, PhFilmSlate } from '@phosphor-icons/vue'
import { quoteAgentProduction } from '@/api/agent'
import { buildShotAction, creditText, exceedsBudget, finiteCredits, isCurrentQuote, productionActionAllowed, productionCounts, productionError, productionRows, quoteImpact, reviewStatuses, startProductionCost } from './production'

const props = defineProps({
  runId: { type: String, required: true }, plan: { type: Object, required: true }, production: { type: Object, required: true },
  planVersion: { type: Number, required: true }, status: { type: String, required: true },
  budgetLimit: { type: Number, default: null }, disabled: Boolean, demo: Boolean,
})
const { t, te } = useI18n({ useScope: 'local', messages })
const emit = defineEmits(['action'])
const dialog = ref(null), confirmation = ref(null), repairBudget = ref(0), motionPrompt = ref(''), scope = ref('only')
const quote = ref(null), quoting = ref(false), error = ref(''), modalError = ref(''), actionEstimate = ref(null)
let quoteEpoch = 0
const rows = computed(() => productionRows(props.plan, props.production))
const counts = computed(() => productionCounts(rows.value))
const estimates = computed(() => props.production.estimates || {})
const locked = computed(() => props.disabled)
const reviewable = computed(() => reviewStatuses.has(props.status))
const canReviewPlan = computed(() => props.production.enabled && props.status === 'production_attention' && rows.value.some((shot) => shot.error?.recovery_action === 'replan'))
const phaseLabel = computed(() => te(`phase.${props.status}`) ? t(`phase.${props.status}`) : t('productionPending'))
const warnings = computed(() => [...new Set([...(props.production.warnings || []).map(warningText), ...(props.production.kept_downstream?.length ? [t('keptWarning', { shots: props.production.kept_downstream.join(', ') })] : [])])])
const remainingBudget = computed(() => finiteCredits(estimates.value.remaining_budget) ?? (finiteCredits(props.budgetLimit) != null && finiteCredits(estimates.value.spent_credits) != null ? Math.max(0, props.budgetLimit - estimates.value.spent_credits) : null))
const startTotal = computed(() => startProductionCost(estimates.value, repairBudget.value))
const validStart = computed(() => props.status === 'storyboard_approved' && props.production.enabled && startTotal.value != null && (remainingBudget.value == null || startTotal.value <= remainingBudget.value))
const currentShot = computed(() => rows.value.find((shot) => shot.shot_id === confirmation.value?.shotId))
const quoteContext = computed(() => ({ planVersion: props.planVersion, shotId: confirmation.value?.shotId, motionPrompt: motionPrompt.value }))
const onlyImpact = computed(() => quoteImpact(quote.value, 'only'))
const cascadeImpact = computed(() => quoteImpact(quote.value, 'cascade'))
const selectedImpact = computed(() => quoteImpact(quote.value, scope.value))
const promptValid = computed(() => confirmation.value?.operation !== 'redo' || Boolean(motionPrompt.value.trim()))
const confirmable = computed(() => isCurrentQuote(quote.value, quoteContext.value) && finiteCredits(selectedImpact.value.cost) != null && !overBudget(selectedImpact.value.cost) && canAct(currentShot.value, confirmation.value?.operation) && (confirmation.value?.operation !== 'retry' || quote.value.can_retry))
const money = (value) => finiteCredits(value) == null ? t('unknownCost') : creditText(value)
const label = (group, value, fallback) => te(`${group}.${value}`) ? t(`${group}.${value}`) : fallback
const dependencyLabel = (shot) => shot.depends_on?.length ? t('serial', { shots: shot.depends_on.join(', '), shot: shot.shot_id }) : t(shot.motion?.mode === 'first_last_frame' ? 'bridge' : 'independent')
const canAct = (shot, operation) => productionActionAllowed(props.status, shot, operation, locked.value || !props.production.enabled)
const warningText = (warning) => typeof warning === 'string' ? warning : warning?.summary || warning?.message || warning?.code || t('warningFallback')
const tone = (status) => ({ success: 'pill-emerald', failed: 'pill-red', blocked: 'pill-amber', stale: 'pill-amber', running: 'pill-blue' }[status] || 'pill-slate')
const edge = (status) => ({ success: 'edge-emerald', failed: 'edge-red', blocked: 'edge-amber', stale: 'edge-amber', running: 'edge-blue' }[status] || '')
// Before start_production nothing is queued; say so instead of "queued".
const shotLabel = (shot) => props.status === 'storyboard_approved' && shot.status === 'pending' ? t('notStarted') : label('shot', shot.status, shot.status)
const phaseTone = computed(() => ({ producing: 'tone-blue', production_attention: 'tone-red', awaiting_video_review: 'tone-amber', videos_approved: 'tone-emerald' }[props.status] || 'tone-slate'))
// Quotes are not budget checks; flag options the server would reject anyway.
const overBudget = (cost) => exceedsBudget(cost, remainingBudget.value)
function resetDialog() { confirmation.value = null; quote.value = null; modalError.value = ''; quoting.value = false; quoteEpoch++ }
async function show() { await nextTick(); dialog.value?.showModal() }
function openStart() { error.value = ''; repairBudget.value = 0; confirmation.value = { kind: 'start' }; show() }
function openReviewPlan() { error.value = ''; confirmation.value = { kind: 'review_plan' }; show() }
function openApprove() { error.value = ''; confirmation.value = { kind: 'approve' }; show() }
function openShot(shot, operation) {
  if (!canAct(shot, operation)) return
  error.value = ''; quote.value = null; scope.value = 'only'; motionPrompt.value = shot.motion?.prompt || ''
  confirmation.value = { kind: 'shot', shotId: shot.shot_id, operation }; show()
}
watch(motionPrompt, () => { quote.value = null; quoteEpoch++; quoting.value = false })
watch(() => [props.runId, props.planVersion, props.status], (next, previous) => {
  if (next.some((value, index) => value !== previous[index]) && confirmation.value) {
    error.value = t('stateChanged')
    dialog.value?.close(); resetDialog()
  }
})
onBeforeUnmount(() => { quoteEpoch++ })
async function loadQuote() {
  if (!confirmation.value || !promptValid.value) return
  const epoch = ++quoteEpoch, runId = props.runId
  const input = { shot_id: confirmation.value.shotId, base_version: props.planVersion, operation: confirmation.value.operation }
  if (confirmation.value.operation === 'redo') input.motion_prompt = motionPrompt.value.trim()
  quote.value = null; quoting.value = true; modalError.value = ''
  try {
    const result = await quoteAgentProduction(runId, input)
    if (epoch === quoteEpoch && props.runId === runId) {
      if (!isCurrentQuote(result, quoteContext.value)) throw new Error(t('quoteExpired'))
      quote.value = result
    }
  } catch (failure) {
    if (epoch === quoteEpoch) modalError.value = failure.response?.data?.error?.message || failure.message || t('quoteFailed')
  } finally { if (epoch === quoteEpoch) quoting.value = false }
}
function submit(action, payload) {
  modalError.value = ''; error.value = ''
  emit('action', { action, payload, onSuccess: (result) => { actionEstimate.value = result.action_estimated_credits ?? null; dialog.value?.close(); resetDialog() }, onError: (message) => { error.value = message; modalError.value = message; quote.value = null } })
}
function submitStart() { if (validStart.value) submit('start_production', { plan_version: props.planVersion, repair_budget_credits: repairBudget.value }) }
function submitApprove() { if (props.production.enabled && props.status === 'awaiting_video_review') submit('approve_videos', { plan_version: props.planVersion }) }
function submitShot() {
  if (!confirmable.value) return
  try { const request = buildShotAction(quote.value, quoteContext.value, scope.value, confirmation.value.operation); submit(request.action, request.payload) }
  catch (failure) { modalError.value = failure.message }
}
function cancelDialog() {
  if (locked.value) return
  if (confirmation.value?.kind === 'shot' && confirmation.value.operation === 'redo' && isCurrentQuote(quote.value, quoteContext.value)) {
    const request = buildShotAction(quote.value, quoteContext.value, 'cancel', 'redo'); submit(request.action, request.payload)
  } else { dialog.value?.close(); resetDialog() }
}
function onBackdrop(event) { if (event.target === dialog.value) cancelDialog() }
</script>

<style scoped>
.production-card { @apply min-w-0 rounded-2xl border border-slate-200 bg-white p-5 text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100; }
.icon-tile { @apply flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400; }
.status-pill { @apply inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium; }
.tone-blue { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.tone-red { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.tone-amber { @apply bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300; }
.tone-emerald { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.tone-slate { @apply bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.metric { @apply min-w-0 rounded-lg bg-white px-3 py-2.5 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700; }
.metric span { @apply block text-[11px] text-slate-500 dark:text-slate-400; }
.metric strong { @apply mt-1 block break-words text-base font-semibold tabular-nums text-slate-900 dark:text-white; }
.tag { @apply rounded-md bg-slate-100 px-2 py-1 text-xs dark:bg-slate-800; }
.pill { @apply inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium; }
.pill-emerald { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.pill-red { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.pill-amber { @apply bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300; }
.pill-blue { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.pill-slate { @apply bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.shot-card { @apply min-w-0 break-words rounded-xl border border-slate-200 bg-white p-3.5 transition hover:shadow-sm dark:border-slate-700 dark:bg-slate-900; border-left-width: 3px; }
.edge-emerald { border-left-color: #10b981; }
.edge-red { border-left-color: #ef4444; }
.edge-amber { border-left-color: #f59e0b; }
.edge-blue { border-left-color: #2563eb; }
.notice { @apply break-words rounded-xl bg-amber-50 px-3 py-2.5 text-xs leading-relaxed text-amber-800 dark:bg-amber-950/40 dark:text-amber-200; }
.notice-red { @apply bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300; }
.primary-btn { @apply inline-flex items-center justify-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
.field-label { @apply block text-xs font-medium text-slate-500 dark:text-slate-400; }
.field { @apply mt-1 block w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100; }
.choice { @apply flex cursor-pointer items-start gap-3 rounded-xl border border-slate-200 p-3 text-sm transition hover:border-slate-300 dark:border-slate-700; }
.choice:has(input:checked) { @apply border-blue-500 bg-blue-50/50 ring-2 ring-blue-500/15 dark:bg-blue-950/30; }
.choice-over { @apply border-red-300 dark:border-red-900; }
.choice input { @apply mt-1; }
.production-dialog { @apply m-auto max-h-[90vh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto rounded-2xl border-0 bg-white p-0 text-slate-800 shadow-2xl dark:bg-slate-900 dark:text-slate-100; }
.production-dialog::backdrop { background: rgb(15 23 42 / 0.5); backdrop-filter: blur(2px); }
</style>
