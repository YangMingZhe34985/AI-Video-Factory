<template>
  <DefaultLayout title="Agent Studio" :subtitle="t('subtitle')">
    <div class="mx-auto max-w-7xl">
      <p v-if="enabled === false" class="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">{{ t('disabled') }}</p>

      <div v-else-if="enabled" class="grid gap-6 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <!-- history rail -->
        <aside class="space-y-3 lg:sticky lg:top-0 lg:self-start">
          <button type="button" class="new-btn" @click="startNew"><PhPlus :size="16" weight="bold" />{{ t('newRun') }}</button>
          <nav :aria-label="t('history')" class="rounded-2xl border border-slate-200 bg-white p-2 dark:border-slate-700 dark:bg-slate-900">
            <p class="px-2 pb-1 pt-1.5 text-xs font-medium uppercase tracking-wide text-slate-400">{{ t('history') }}</p>
            <button
              v-for="item in runs" :key="item.run_id" type="button" class="history-item"
              :aria-current="selected?.run_id === item.run_id ? 'true' : undefined" @click="select(item.run_id)"
            >
              <span class="block truncate text-sm text-slate-800 dark:text-slate-100">{{ titleOf(item) }}</span>
              <span class="mt-0.5 flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
                <span class="h-1.5 w-1.5 rounded-full" :class="dotClass(item.status)" />{{ statusLabel(item.status) }}
                <span class="ml-auto tabular-nums">{{ shortTime(item.created_at) }}</span>
              </span>
            </button>
            <p v-if="!runs.length" class="px-2 py-3 text-sm text-slate-400">{{ t('noHistory') }}</p>
          </nav>
        </aside>

        <main class="min-w-0">
          <!-- new project -->
          <section v-if="!selected" class="mx-auto max-w-3xl pt-4 lg:pt-10">
            <h2 class="text-3xl font-semibold tracking-tight text-slate-900 dark:text-white">{{ t('composerTitle') }}</h2>
            <p class="mt-2 max-w-2xl text-[15px] leading-relaxed text-slate-500 dark:text-slate-400">{{ t('composerLead') }}</p>
            <AgentComposer ref="composer" class="mt-6" :busy="busy" @submit="create" />
            <p v-if="error" role="alert" class="mt-3 text-sm text-red-600">{{ error }}</p>
            <div class="mt-6">
              <p class="text-xs font-medium uppercase tracking-wide text-slate-400">{{ t('examples') }}</p>
              <div class="mt-2 flex flex-wrap gap-2">
                <button v-for="key in ['example1', 'example2', 'example3']" :key="key" type="button" class="example" @click="composer?.fill(t(key))">{{ t(key) }}</button>
              </div>
            </div>
            <p v-if="mode !== 'real'" class="mt-8 text-xs text-amber-700 dark:text-amber-400">{{ mode === 'mock' ? t('mock') : t('auto') }}</p>
          </section>

          <!-- run detail -->
          <div v-else class="space-y-5">
            <section class="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0">
                  <h2 class="text-xl font-semibold leading-snug text-slate-900 dark:text-white">{{ titleOf(selected) }}</h2>
                  <p v-if="!isV2" class="mt-1 text-xs text-slate-400">{{ t('legacyRun') }}</p>
                </div>
                <span class="status-pill" :class="pillClass(selected.status)">{{ statusLabel(selected.status) }}</span>
              </div>
              <RunStepper class="mt-4" :status="selected.status" :asked="clarifications.length > 0" :has-plan="Boolean(plan)" :has-results="results.length > 0" :story-mode="isStoryPlan" />
              <div v-if="budgetLimit" class="mt-4">
                <div class="flex justify-between text-xs text-slate-500 dark:text-slate-400">
                  <span>{{ t('spent', { spent: round(selected.estimated_spent), budget: budgetLimit }) }}</span>
                </div>
                <div class="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
                  <div class="h-full rounded-full bg-blue-500 transition-all" :style="{ width: `${Math.min(100, (selected.estimated_spent / budgetLimit) * 100)}%` }" />
                </div>
              </div>
              <p v-if="mode !== 'real'" class="mt-3 text-xs text-amber-700 dark:text-amber-400">{{ mode === 'mock' ? t('mock') : t('auto') }}</p>
              <p v-if="selected.status === 'queued'" class="mt-2 text-xs text-slate-500">{{ t('queueHint') }}</p>
              <p v-if="selected.error" role="alert" class="mt-3 break-words rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-300">{{ selected.error.code }}: {{ selected.error.message }}</p>
              <p v-if="error" role="alert" class="mt-3 text-sm text-red-600">{{ error }}</p>
              <div v-if="showRunActions" class="mt-4 flex flex-wrap items-center gap-3">
                <button v-if="selected.status === 'awaiting_delivery'" type="button" class="primary-btn" :disabled="actionDisabled" @click="act('deliver')">{{ t('deliver') }}</button>
                <button v-if="selected.status === 'needs_attention' && selected.resume_count < 2" type="button" class="secondary-btn" :disabled="actionDisabled" @click="act('resume')">{{ t('resume') }}</button>
                <span v-if="selected.command" class="text-xs text-slate-500">{{ t('pendingAction') }}</span>
              </div>
            </section>

            <!-- the request -->
            <section class="flex gap-3">
              <span class="mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-full bg-slate-200 text-slate-600 dark:bg-slate-700 dark:text-slate-200"><PhUser :size="16" /></span>
              <div class="min-w-0 rounded-2xl rounded-tl-sm bg-slate-100 px-4 py-3 dark:bg-slate-800">
                <p class="text-xs text-slate-400">{{ t('yourRequest') }}</p>
                <p class="mt-1 whitespace-pre-wrap text-[15px] leading-relaxed text-slate-800 dark:text-slate-100">{{ requestText }}</p>
                <div v-if="attachments.length" class="mt-3 flex flex-wrap gap-2">
                  <span v-for="item in attachments" :key="item.attachment_id" class="block h-16 w-16 overflow-hidden rounded-lg ring-1 ring-slate-200 dark:ring-slate-700" :title="item.file_name">
                    <AuthedImage v-if="item.kind === 'image'" :src="item.preview_url" :alt="item.file_name" class="h-full w-full object-cover" />
                    <span v-else class="flex h-full w-full items-center justify-center bg-slate-800 text-white"><PhFilmStrip :size="20" /></span>
                  </span>
                </div>
              </div>
            </section>

            <UnderstandingCard v-if="requestSpec" :spec="requestSpec" :attachments="attachments" :assumptions="assumptions" />

            <ResearchCard v-if="researchDossier" :dossier="researchDossier" />

            <ClarificationCard v-if="pendingCard && selected.status === 'awaiting_input'" :card="pendingCard" :disabled="actionDisabled" @submit="answer" />

            <details v-if="answeredCards.length" class="rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm dark:border-slate-700 dark:bg-slate-900">
              <summary class="cursor-pointer text-slate-600 dark:text-slate-300">{{ t('answered') }} · {{ answeredCards.length }}</summary>
              <ul class="mt-3 space-y-2">
                <li v-for="item in answeredCards" :key="item.key" class="flex flex-wrap gap-x-2 text-slate-700 dark:text-slate-300">
                  <span class="text-slate-500">{{ item.question }}</span>
                  <span class="font-medium">{{ item.choice }}</span>
                  <span class="text-xs text-slate-400">· {{ t(`source_${item.source}`) }}</span>
                </li>
              </ul>
            </details>

            <section v-if="sourceVideo" class="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
              <h3 class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ t('sourceVideo') }} · {{ sourceVideo.file_name }}</h3>
              <AuthedVideo :key="sourceVideo.preview_url" :src="sourceVideo.preview_url" class="mt-3 max-h-64 w-full rounded-xl bg-black"
                           :label="t('loadPreview')" :loading-label="t('loadingPreview')" :error-label="t('previewFailed')" />
              <details v-if="selected.snapshot?.analysis" class="mt-3 text-sm">
                <summary class="cursor-pointer text-slate-500">{{ t('sourceAnalysis') }}</summary>
                <p class="mt-2 whitespace-pre-wrap text-slate-600 dark:text-slate-300">{{ selected.snapshot.analysis.content }}</p>
              </details>
            </section>

            <SimplePlanEditor
              v-if="draft && !draft.shots && !isStoryPlan"
              :key="`simple-${selected.run_id}-${selected.status}`"
              :plan="draft" :models="models" :attachments="attachments"
              :editable="selected.status === 'awaiting_approval' && !selected.command" :disabled="actionDisabled"
              @approve="act('approve', $event)" @reject="act('reject')"
            />

            <StoryboardEditor
              v-if="isStoryPlan" :key="`story-${selected.run_id}`"
              :run-id="selected.run_id" :plan="plan" :story="story || {}" :plan-version="planVersion"
              :previews="previews" :estimates="storyEstimates" :issues="storyIssues" :spec="requestSpec || {}"
              :models="models" :status="storyboardStatus" :disabled="busy || Boolean(selected.command)"
              :demo="mode === 'mock'" :duration-tolerance-ratio="storyConfig.durationToleranceRatio"
              :keyframe-bridge-enabled="storyConfig.keyframeBridgeEnabled" :max-shots="storyConfig.maxShots"
              @action="storyAction" @refresh="select(selected.run_id)"
            />

            <ProductionBoard
              v-if="isStoryPlan && production && (production.approved_version || productionStatuses.includes(selected.status))" :key="`production-${selected.run_id}`"
              :run-id="selected.run_id" :plan="plan" :plan-version="planVersion" :production="production"
              :status="productionStatus" :budget-limit="budgetLimit" :disabled="busy || Boolean(selected.command)"
              :demo="mode === 'mock'" @action="storyAction"
            />

            <DeliveryPanel
              v-if="deliveryVisible" :key="`delivery-${selected.run_id}`" :delivery="delivery" :kept-downstream="production?.kept_downstream || []"
              :disabled="busy || Boolean(selected.command)" :demo="mode === 'mock'" @action="storyAction"
            />

            <template v-if="draft?.shots && !isStoryPlan">
              <ShotPlanEditor
                :plan="draft" :shots="selected.snapshot?.shots" :history="selected.snapshot?.shot_history" :issues="selected.snapshot?.plan_issues || []"
                :source-duration="sourceVideo?.duration ?? null" :mock="Boolean(selected.snapshot?.mock)"
                :editable="shotEditable" :can-revise="canRevise" :disabled="actionDisabled"
                @revise="revise" @invalid="paramsInvalid = $event"
              />
              <div v-if="selected.status === 'awaiting_approval'" class="flex flex-wrap gap-3">
                <button type="button" class="primary-btn" :disabled="actionDisabled" @click="act('approve', draft)">{{ t('approve') }}</button>
                <button type="button" class="secondary-btn" :disabled="actionDisabled" @click="act('reject')">{{ t('reject') }}</button>
              </div>
            </template>

            <section v-if="results.length && !isStoryPlan" class="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
              <h3 class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ t('results') }}</h3>
              <div class="mt-3 grid gap-3 sm:grid-cols-2">
                <figure v-for="item in results" :key="item.artifact_id" class="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-700">
                  <div v-if="selected.snapshot?.mock && item.kind === 'video'" class="bg-slate-100 p-8 text-center text-xs text-slate-500 dark:bg-slate-800">{{ t('mockVideo') }}</div>
                  <video v-else-if="item.kind === 'video'" controls preload="metadata" :src="item.preview_url" class="max-h-80 w-full bg-black" />
                  <AuthedImage v-else :src="item.preview_url" class="max-h-80 w-full bg-slate-100 object-contain dark:bg-slate-800" />
                  <figcaption class="flex justify-end px-3 py-2"><a :href="item.download_url" class="text-xs text-blue-600 hover:underline" download>{{ t('download') }}</a></figcaption>
                </figure>
              </div>
            </section>

            <section v-if="selected.snapshot?.packages?.length && !isStoryPlan" class="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
              <h3 class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ t('packages') }}</h3>
              <p class="mt-1 text-xs text-slate-500">{{ t('packageHint') }}</p>
              <a v-for="pack in selected.snapshot.packages" :key="pack.artifact_id" :href="pack.download_url" class="mt-2 block text-sm text-blue-600 hover:underline" download>{{ t('download') }} ZIP · {{ pack.job_id }}</a>
              <p v-for="issue in selected.snapshot.package_errors || []" :key="issue.job_id" class="mt-1 text-sm text-red-600">{{ issue.job_id }}: {{ issue.message }}</p>
            </section>
          </div>
        </main>
      </div>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { PhFilmStrip, PhPlus, PhUser } from '@phosphor-icons/vue'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import AgentComposer from '@/components/agent/AgentComposer.vue'
import RunStepper from '@/components/agent/RunStepper.vue'
import UnderstandingCard from '@/components/agent/UnderstandingCard.vue'
import ResearchCard from '@/components/agent/ResearchCard.vue'
import ClarificationCard from '@/components/agent/ClarificationCard.vue'
import SimplePlanEditor from '@/components/agent/SimplePlanEditor.vue'
import ShotPlanEditor from '@/components/agent/ShotPlanEditor.vue'
import StoryboardEditor from '@/components/agent/StoryboardEditor.vue'
import ProductionBoard from '@/components/agent/ProductionBoard.vue'
import DeliveryPanel from '@/components/agent/DeliveryPanel.vue'
import { deliveryRunStatuses } from '@/components/agent/delivery'
import AuthedImage from '@/components/agent/AuthedImage.vue'
import AuthedVideo from '@/components/agent/AuthedVideo.vue'
import messages from '@/components/agent/messages'
import { normalizeStoryRules } from '@/components/agent/storyboard'
import { actOnAgentRun, actOnStoryboard, answerAgentCard, createAgentRun, getAgentRun, listAgentRuns, listModels, reviseAgentShot } from '@/api/agent'

const { t, locale } = useI18n({ useScope: 'local', messages })
const route = useRoute()
const router = useRouter()

const enabled = ref(null), mode = ref('auto'), runs = ref([]), selected = ref(null), draft = ref(null)
const busy = ref(false), error = ref(''), models = ref([]), paramsInvalid = ref(false), composer = ref(null)
let timer, disposed = false, selectionVersion = 0
let requestKey = null, requestPayload = null, revisionKey = null, revisionPayload = null
let storyKey = null, storyPayload = null

// v2 fields (CONTRACTS A.10) with fallbacks to the run snapshot / v1 request.
const pick = (run, key) => run?.[key] ?? run?.snapshot?.[key] ?? null
const storyConfig = computed(() => normalizeStoryRules(pick(selected.value, 'story_rules') || {}))
const isV2 = computed(() => (selected.value?.schema_version ?? selected.value?.request?.schema_version) === 2)
const requestSpec = computed(() => pick(selected.value, 'request_spec'))
const researchDossier = computed(() => pick(selected.value, 'research_dossier'))
const pendingCard = computed(() => pick(selected.value, 'pending_card'))
const attachments = computed(() => pick(selected.value, 'attachments') || [])
const results = computed(() => pick(selected.value, 'results') || [])
const clarifications = computed(() => selected.value?.snapshot?.clarifications || [])
const assumptions = computed(() => selected.value?.snapshot?.assumptions || [])
const plan = computed(() => pick(selected.value, 'plan'))
const story = computed(() => pick(selected.value, 'story'))
const planVersion = computed(() => pick(selected.value, 'plan_version') ?? plan.value?.plan_version)
const isStoryPlan = computed(() => plan.value?.recipe === 'story_video' && Number.isInteger(planVersion.value) && Array.isArray(plan.value?.scenes))
const previews = computed(() => pick(selected.value, 'previews') || {})
const storyEstimates = computed(() => pick(selected.value, 'estimates') || {})
const storyIssues = computed(() => pick(selected.value, 'plan_issues') || [])
const production = computed(() => pick(selected.value, 'production'))
const productionStatuses = ['storyboard_approved', 'producing', 'production_attention', 'awaiting_video_review', 'videos_approved']
const delivery = computed(() => pick(selected.value, 'delivery'))
const deliveryVisible = computed(() => isStoryPlan.value && delivery.value && (selected.value?.status === 'videos_approved' || deliveryRunStatuses.has(selected.value?.status)))
const productionStatus = computed(() => deliveryRunStatuses.has(selected.value?.status) ? 'videos_approved' : selected.value?.status)
const storyboardStatus = computed(() => productionStatuses.includes(productionStatus.value) ? 'storyboard_approved' : selected.value?.status)
const isRemix = computed(() => selected.value?.request?.mode === 'remix' || requestSpec.value?.recipe_hint === 'remix')
// v1 stores the remix source on the request; v2 has it as the remix_source attachment.
const sourceVideo = computed(() => {
  if (selected.value?.request?.source) return selected.value.request.source
  const use = requestSpec.value?.attachments?.find((item) => item.role === 'remix_source')
  return use ? attachments.value.find((item) => item.attachment_id === use.attachment_id) || null : null
})
const requestText = computed(() => selected.value?.text || selected.value?.request?.text || selected.value?.request?.goal || '')
const budgetLimit = computed(() => selected.value?.request?.budget_limit ?? selected.value?.budget_limit ?? null)
const answeredCards = computed(() => clarifications.value.flatMap((record) =>
  Object.values(record.answers || {}).map((item) => ({
    key: `${record.card.card_id}:${item.question_id}`, question: item.question, choice: item.label || item.text, source: item.source,
  }))))

const actionDisabled = computed(() => busy.value || Boolean(selected.value?.command) || paramsInvalid.value)
const canRevise = computed(() => isRemix.value && selected.value?.status === 'awaiting_delivery')
const shotEditable = computed(() => (selected.value?.status === 'awaiting_approval' || canRevise.value) && !busy.value && !selected.value?.command)
const showRunActions = computed(() => ['awaiting_delivery', 'needs_attention'].includes(selected.value?.status) || selected.value?.command)

const titleOf = (run) => run?.snapshot?.plan?.title || run?.plan?.title || run?.request_spec?.summary || run?.snapshot?.request_spec?.summary
  || run?.text || run?.request?.text || run?.request?.goal || '—'
const statusLabel = (status) => t(status || 'pending')
const round = (value) => Math.round((value || 0) * 10) / 10
const shortTime = (value) => (value ? new Date(value).toLocaleDateString(locale.value === 'zh' ? 'zh-CN' : 'en-US', { month: 'numeric', day: 'numeric' }) : '')
const TONE = {
  success: 'good', partial_success: 'warn', failed: 'bad', cancelled: 'muted', needs_attention: 'bad',
  awaiting_input: 'ask', awaiting_approval: 'ask', awaiting_delivery: 'ask',
  awaiting_characters: 'ask', awaiting_storyboard: 'ask', storyboard_approved: 'ask',
  awaiting_video_review: 'ask', production_attention: 'bad', videos_approved: 'good', delivery_attention: 'bad',
}
const dotClass = (status) => ({ good: 'bg-emerald-500', warn: 'bg-amber-500', bad: 'bg-red-500', muted: 'bg-slate-400', ask: 'bg-blue-500' }[TONE[status]] || 'bg-blue-300 animate-pulse')
const pillClass = (status) => `tone-${TONE[status] || 'busy'}`
const newKey = () => globalThis.crypto?.randomUUID?.() || `agent-${Date.now()}-${Math.random().toString(36).slice(2)}`
const message = (err) => {
  const failure = err.response?.data?.error
  return failure
    ? [failure.details?.shot_id, failure.message, ...(failure.details?.errors || []).map((item) => (typeof item === 'string' ? item : item.msg))].filter(Boolean).join(' · ')
    : err.message
}

function applyRun(value) {
  if (selected.value?.run_id !== value.run_id || selected.value?.status !== value.status || !draft.value) {
    const source = value.plan ?? value.snapshot?.plan
    draft.value = source ? structuredClone(source) : null
    paramsInvalid.value = false
  }
  selected.value = value
}
function startNew() {
  selectionVersion++
  selected.value = null
  draft.value = null
  error.value = ''
  router.replace({ query: {} })
}
async function select(id) {
  const version = ++selectionVersion
  error.value = ''
  try {
    const value = await getAgentRun(id)
    if (!disposed && version === selectionVersion) {
      applyRun(value)
      await router.replace({ query: { run: id } })
    }
  } catch (err) { error.value = message(err) }
}
async function refresh() {
  try {
    const data = await listAgentRuns()
    if (disposed) return
    runs.value = data.items
    const current = data.items.find((item) => item.run_id === selected.value?.run_id)
    if (current) applyRun(current)
  } catch (err) { error.value = message(err) }
}
async function create(payload) {
  busy.value = true
  error.value = ''
  const serialized = JSON.stringify(payload)
  if (serialized !== requestPayload) { requestPayload = serialized; requestKey = newKey() }
  try {
    const value = await createAgentRun({ ...payload, request_key: requestKey })
    requestKey = null; requestPayload = null
    composer.value?.reset()
    applyRun(value)
    await router.replace({ query: { run: value.run_id } })
    await refresh()
  } catch (err) { error.value = message(err) } finally { busy.value = false }
}
async function act(action, planValue) {
  busy.value = true
  error.value = ''
  try { applyRun(await actOnAgentRun(selected.value.run_id, action, action === 'approve' ? planValue : undefined)); await refresh() }
  catch (err) { error.value = message(err) } finally { busy.value = false }
}
async function answer({ answers, useDefaults }) {
  busy.value = true
  error.value = ''
  try { applyRun(await answerAgentCard(selected.value.run_id, pendingCard.value.card_id, answers, useDefaults)); await refresh() }
  catch (err) { error.value = message(err) } finally { busy.value = false }
}
async function revise(shot) {
  busy.value = true
  error.value = ''
  const serialized = JSON.stringify({ run: selected.value.run_id, shot })
  if (serialized !== revisionPayload) { revisionPayload = serialized; revisionKey = newKey() }
  try {
    applyRun(await reviseAgentShot(selected.value.run_id, shot, revisionKey))
    revisionKey = null; revisionPayload = null
    await refresh()
  } catch (err) { error.value = message(err) } finally { busy.value = false }
}
async function storyAction({ action, payload, onSuccess, onError }) {
  const runId = selected.value.run_id
  const serialized = JSON.stringify({ runId, action, payload })
  const requiresKey = ['regenerate', 'regenerate_stale', 'edit_plan', 'start_production', 'retry_shot', 'redo_shot', 'approve_videos', 'review_plan', 'start_delivery', 'retry_delivery'].includes(action)
  if (serialized !== storyPayload) { storyPayload = serialized; storyKey = newKey() }
  busy.value = true
  error.value = ''
  try {
    const value = await actOnStoryboard(runId, action, { ...payload, ...(requiresKey ? { request_key: storyKey } : {}) })
    if (selected.value?.run_id === runId) { applyRun(value); onSuccess?.(value) }
    storyKey = null; storyPayload = null
    await refresh()
  } catch (err) {
    const failure = err.response?.data?.error
    const hint = failure?.code === 'PLAN_VERSION_CONFLICT' ? '计划版本已更新，请刷新后重新编辑。' : message(err)
    if (selected.value?.run_id === runId) {
      error.value = hint; onError?.(hint)
      // Retain the local draft; the editor exposes an explicit discard-and-refresh action.
      if (failure?.code === 'PLAN_VERSION_CONFLICT') {
        try { const latest = await getAgentRun(runId); if (selected.value?.run_id === runId) applyRun(latest) } catch { /* keep the conflict message */ }
      }
    }
  } finally { busy.value = false }
}
async function poll() {
  await refresh()
  if (!disposed) timer = setTimeout(poll, 3000)
}
onMounted(async () => {
  try {
    const response = await fetch('/api/health')
    if (!response.ok) throw new Error(`Health check failed (${response.status})`)
    const data = (await response.json()).data
    enabled.value = Boolean(data.agent_mode)
    mode.value = data.mode
    if (enabled.value && !disposed) {
      listModels().then((value) => { models.value = value.models || [] }).catch(() => {})
      if (route.query.run) await select(route.query.run)
      await poll()
    }
  } catch (err) { error.value = message(err) }
})
onUnmounted(() => { disposed = true; clearTimeout(timer); selectionVersion++ })
</script>

<style scoped>
.new-btn { @apply flex w-full items-center justify-center gap-2 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-600 dark:bg-blue-600 dark:hover:bg-blue-500; }
.history-item { @apply block w-full rounded-xl px-2.5 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800; }
.history-item[aria-current='true'] { @apply bg-blue-50 dark:bg-blue-950/50; }
.example { @apply rounded-full border border-slate-200 bg-white px-3.5 py-1.5 text-left text-sm text-slate-600 transition hover:border-blue-300 hover:text-blue-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-blue-700 dark:hover:text-blue-300; }
.status-pill { @apply flex-none rounded-full px-3 py-1 text-xs font-semibold; }
.tone-good { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.tone-warn { @apply bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300; }
.tone-bad { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.tone-muted { @apply bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400; }
.tone-ask { @apply bg-blue-600 text-white; }
.tone-busy { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.primary-btn { @apply rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply rounded-xl border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
</style>
