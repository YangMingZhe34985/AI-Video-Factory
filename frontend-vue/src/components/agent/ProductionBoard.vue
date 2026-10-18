<template>
  <section class="production-card" data-testid="production-board" aria-label="视频生产看板">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div><h3 class="font-semibold text-slate-900 dark:text-white">视频生产</h3><p class="mt-1 text-xs text-slate-500">批准版本 {{ production.approved_version ?? production.plan_version ?? planVersion }} · 无依赖镜头可并行，尾帧承接按依赖串行</p></div>
      <span class="tag">{{ phaseLabel }}</span>
    </header>
    <p v-if="!production.enabled" class="notice mt-4">视频生产暂未启用。已确认的分镜保留，开启生产功能后可从这里继续。</p>
    <p v-if="demo" class="mt-3 text-xs text-amber-700 dark:text-amber-400">Mock 演示：素材、单价与模型能力用于功能测试，不代表真实生成效果。</p>
    <div class="mt-4 grid gap-2 text-sm sm:grid-cols-2 xl:grid-cols-4" aria-label="生产费用">
      <div class="metric"><span>本版视频预计 · 按秒</span><strong>{{ money(estimates.video_credits) }} credits</strong></div>
      <div class="metric"><span>视频累计已花</span><strong>{{ money(estimates.video_spent_credits) }} credits</strong></div>
      <div class="metric"><span>修复累计已花</span><strong>{{ money(estimates.repair_spent_credits) }} credits</strong></div>
      <div class="metric"><span>全部累计 · 含规划和图片</span><strong>{{ money(estimates.spent_credits) }} credits</strong></div>
    </div>
    <p class="mt-2 text-xs text-slate-500">待生成预计 {{ money(estimates.remaining_credits) }} credits · 自动修复额度 {{ money(production.repair_budget_credits ?? 0) }} credits。以服务器账本和报价为准；失败重做也会累计费用。</p>
    <p v-if="actionEstimate != null" role="status" class="mt-2 text-xs text-slate-500">操作已提交，本次服务器报价 {{ money(actionEstimate) }} credits。</p>
    <p v-if="error" role="alert" class="mt-3 break-words text-sm text-red-600 dark:text-red-400">{{ error }}</p>
    <div v-if="warnings.length" class="notice mt-4"><p class="font-medium">连贯性与生产提示</p><ul class="mt-1 space-y-1"><li v-for="(warning, index) in warnings" :key="index">{{ warning }}</li></ul></div>

    <div v-if="status === 'storyboard_approved'" class="mt-4 flex flex-wrap items-center gap-3">
      <button type="button" class="primary-btn" :disabled="locked || !production.enabled" @click="openStart">开始生成视频</button>
      <p class="text-xs text-slate-500">确认生产费用后才提交视频模型任务。</p>
    </div>
    <div v-if="status === 'awaiting_video_review'" class="mt-4 flex flex-wrap items-center gap-3">
      <button type="button" class="primary-btn" :disabled="locked || counts.success !== counts.total || !counts.total" @click="openApprove">确认全部视频</button>
      <p class="text-xs text-slate-500">确认当前版本素材，成片拼接与交付将在后续阶段开放。</p>
    </div>
    <p v-if="status === 'production_attention'" class="notice mt-4">部分镜头需要处理。已完成素材保留；请查看失败原因，按镜头确认重试或重做费用。</p>
    <button v-if="canReviewPlan" type="button" class="secondary-btn mt-3" :disabled="locked" @click="openReviewPlan">返回分镜修改</button>
    <p v-if="status === 'videos_approved'" class="mt-4 text-sm text-emerald-700 dark:text-emerald-300">视频素材已确认，等待后续成片拼接与交付。</p>

    <div class="mt-5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500" role="status" aria-live="polite">
      <span>完成 {{ counts.success }} / {{ counts.total }}</span><span>执行中 {{ counts.running }}</span><span>排队 / 等依赖 {{ counts.waiting }}</span><span>待处理 {{ counts.attention }}</span>
    </div>
    <ol class="mt-3 grid gap-3 xl:grid-cols-2" aria-label="镜头生产状态">
      <li v-for="shot in rows" :key="shot.shot_id" class="shot-card" :data-shot-id="shot.shot_id">
        <div class="flex flex-wrap items-center justify-between gap-2 text-xs"><strong>{{ shot.shot_id }} · {{ shot.duration_sec }} 秒</strong><span class="tag" :class="tone(shot.status)">{{ labels[shot.status] || shot.status }}</span></div>
        <p class="mt-2 text-sm font-medium">{{ shot.summary }}</p>
        <p class="mt-1 break-words text-xs text-slate-500">{{ dependencyText(shot) }}</p>
        <p class="mt-2 break-words text-xs text-slate-500">{{ shot.model_id || shot.motion?.model_id }} · 预计 {{ money(shot.estimated_credits) }} credits · 第 {{ shot.attempt || 0 }} 次执行 · 已修复 {{ shot.repair_count || 0 }} 次</p>
        <p v-if="shot.retained" class="mt-2 text-xs text-amber-700 dark:text-amber-400">保留了上次视频；上游已变化，接续画面需要人工检查。</p>
        <div v-if="shot.error" class="mt-3 rounded-lg bg-red-50 p-3 text-xs text-red-700 dark:bg-red-950/30 dark:text-red-300">
          <p>{{ categoryLabels[shot.error.category] || '需要处理' }} · {{ productionError(shot.error) }}</p>
          <p v-if="shot.error.recovery_action" class="mt-1">{{ recoveryLabels[shot.error.recovery_action] || shot.error.recovery_action }}</p>
        </div>
        <AuthedVideo v-if="shot.preview_url" :key="shot.preview_url" :src="shot.preview_url" class="mt-3 max-h-64 w-full rounded-lg bg-black" label="加载镜头预览" loading-label="正在加载镜头…" error-label="预览不可用，点击重试" />
        <div v-if="reviewable" class="mt-3 flex flex-wrap gap-2">
          <button v-if="shot.can_retry" type="button" class="secondary-btn" :disabled="!canAct(shot, 'retry')" @click="openShot(shot, 'retry')">查看局部重试费用</button>
          <button v-if="shot.can_redo" type="button" class="secondary-btn" :disabled="!canAct(shot, 'redo')" @click="openShot(shot, 'redo')">重做此镜头</button>
        </div>
      </li>
    </ol>

    <dialog ref="dialog" class="production-dialog" @cancel.prevent="cancelDialog" @click="onBackdrop" @close="resetDialog">
      <div v-if="confirmation" class="p-5">
        <div class="flex items-start justify-between gap-3"><h4 class="text-base font-semibold">{{ confirmation.kind === 'start' ? '确认视频生产' : confirmation.kind === 'approve' ? '确认视频素材' : confirmation.kind === 'review_plan' ? '返回分镜修改' : `${confirmation.shotId} · ${confirmation.operation === 'retry' ? '局部重试' : '重做与影响范围'}` }}</h4><button type="button" class="secondary-btn" :disabled="locked" @click="cancelDialog">关闭</button></div>
        <p v-if="modalError" role="alert" class="mt-3 break-words text-sm text-red-600 dark:text-red-400">{{ modalError }}</p>
        <template v-if="confirmation.kind === 'start'">
          <p class="mt-4 text-sm">将按已审核分镜生成 {{ rows.length }} 个镜头，视频预计 {{ money(estimates.video_credits) }} credits，按模型单价 × 秒数计算。</p>
          <label class="field-label mt-4">本次允许自动修复的额外额度（credits）<input v-model.number="repairBudget" type="number" min="0" step="0.1" class="field" /></label>
          <p class="mt-2 text-xs text-slate-500">默认 0。自动修复只处理明确可恢复的错误，并受单镜头次数、额度与总预算约束；提交结果不确定时先核实，不重复提交。</p>
          <p class="mt-3 text-sm">视频与自动修复授权合计上限 {{ money(startTotal) }} credits；剩余总预算 {{ money(remainingBudget) }} credits。</p>
          <button type="button" class="primary-btn mt-4" :disabled="locked || !validStart" @click="submitStart">确认费用并开始</button>
        </template>
        <template v-else-if="confirmation.kind === 'approve'">
          <p class="mt-4 text-sm">确认版本 {{ planVersion }} 的 {{ counts.total }} 个视频素材。此操作不生成新视频。</p>
          <p v-if="warnings.length" class="notice mt-3">请先检查保留旧下游镜头造成的连贯性差异。</p>
          <button type="button" class="primary-btn mt-4" :disabled="locked || status !== 'awaiting_video_review'" @click="submitApprove">确认视频素材</button>
        </template>
        <template v-else-if="confirmation.kind === 'review_plan'">
          <p class="mt-4 text-sm">返回当前分镜审核，修改有问题的模型或参数。已完成的旧素材保留；重新生产仍需审核和费用确认。</p>
          <button type="button" class="primary-btn mt-4" :disabled="locked || !canReviewPlan" @click="submit('review_plan', { plan_version: planVersion })">确认返回分镜</button>
        </template>
        <template v-else>
          <label v-if="confirmation.operation === 'redo'" class="field-label mt-4">动作提示词（可修改，仅影响本镜头）<textarea v-model="motionPrompt" class="field" rows="5" maxlength="8000" :readonly="locked" /></label>
          <p v-else class="mt-4 text-sm">使用原镜头输入恢复失败环节。不会因重试重新执行其他已完成镜头。</p>
          <button type="button" class="secondary-btn mt-3" :disabled="locked || quoting || !promptValid" @click="loadQuote">{{ quoting ? '报价中…' : quote ? '更新报价' : '获取影响范围和费用' }}</button>
          <p v-if="!quote" class="mt-2 text-xs text-slate-500">仅查询报价，不提交模型任务。修改提示词或版本变化后需重新报价。</p>
          <div v-else class="mt-4 space-y-3">
            <p class="text-xs text-slate-500">报价基于版本 {{ quote.base_version }}；确认时服务器会重新检查版本、状态与预算。</p>
            <p v-if="quote.reason" class="text-sm">{{ quote.reason }}</p>
            <ul v-if="quote.warnings?.length" class="notice"><li v-for="(warning, index) in quote.warnings" :key="index">{{ warningText(warning) }}</li></ul>
            <template v-if="confirmation.operation === 'redo'">
              <label class="choice"><input v-model="scope" type="radio" value="only" name="redo-scope" /><span><strong>只重做此镜头 · {{ money(onlyImpact.cost) }} credits</strong><span class="mt-1 block text-xs text-slate-500">{{ onlyImpact.retained.length ? `保留 ${onlyImpact.retained.join('、')} 的旧视频，可能不再与新上游画面连贯。` : '没有需要保留的下游视频。' }}</span></span></label>
              <label v-if="cascadeImpact.shots.length > 1" class="choice"><input v-model="scope" type="radio" value="cascade" name="redo-scope" /><span><strong>连带重做尾帧依赖链 · {{ money(cascadeImpact.cost) }} credits</strong><span class="mt-1 block text-xs text-slate-500">{{ cascadeImpact.shots.join(' → ') }}；其他独立镜头保留。</span></span></label>
              <p class="text-sm">本次执行：{{ selectedImpact.shots.join('、') }} · 预计新增 {{ money(selectedImpact.cost) }} credits。旧版本和旧素材保留。</p>
            </template>
            <p v-else class="text-sm">本次局部恢复预计 {{ money(onlyImpact.cost) }} credits。{{ quote.can_retry ? '' : '当前不允许重试，请按失败原因处理。' }}</p>
            <div class="flex flex-wrap gap-3"><button type="button" class="primary-btn" :disabled="locked || !confirmable" @click="submitShot">{{ confirmation.operation === 'retry' ? '确认局部重试' : '确认重做范围与费用' }}</button><button type="button" class="secondary-btn" :disabled="locked" @click="cancelDialog">取消，不生成</button></div>
          </div>
        </template>
      </div>
    </dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import AuthedVideo from './AuthedVideo.vue'
import { quoteAgentProduction } from '@/api/agent'
import { buildShotAction, categoryLabels, creditText, dependencyText, finiteCredits, isCurrentQuote, productionActionAllowed, productionCounts, productionError, productionLabels, productionRows, quoteImpact, recoveryLabels, reviewStatuses } from './production'

const props = defineProps({
  runId: { type: String, required: true }, plan: { type: Object, required: true }, production: { type: Object, required: true },
  planVersion: { type: Number, required: true }, status: { type: String, required: true },
  budgetLimit: { type: Number, default: null }, disabled: Boolean, demo: Boolean,
})
const emit = defineEmits(['action'])
const dialog = ref(null), confirmation = ref(null), repairBudget = ref(0), motionPrompt = ref(''), scope = ref('only')
const quote = ref(null), quoting = ref(false), error = ref(''), modalError = ref(''), actionEstimate = ref(null)
let quoteEpoch = 0
const rows = computed(() => productionRows(props.plan, props.production))
const counts = computed(() => productionCounts(rows.value))
const estimates = computed(() => props.production.estimates || {})
const locked = computed(() => props.disabled)
const reviewable = computed(() => reviewStatuses.has(props.status))
const canReviewPlan = computed(() => props.status === 'production_attention' && rows.value.some((shot) => shot.error?.recovery_action === 'replan'))
const phaseLabel = computed(() => ({ storyboard_approved: '待开始生产', producing: '生产中', production_attention: '需要处理', awaiting_video_review: '审核 B · 视频素材', videos_approved: '视频素材已确认' }[props.status] || '待生产'))
const warnings = computed(() => [...new Set([...(props.production.warnings || []).map(warningText), ...(props.production.kept_downstream?.length ? [`保留旧下游视频：${props.production.kept_downstream.join('、')}。请检查与新上游的画面衔接。`] : [])])])
const remainingBudget = computed(() => finiteCredits(estimates.value.remaining_budget) ?? (finiteCredits(props.budgetLimit) != null && finiteCredits(estimates.value.spent_credits) != null ? Math.max(0, props.budgetLimit - estimates.value.spent_credits) : null))
const startTotal = computed(() => finiteCredits(repairBudget.value) != null && finiteCredits(estimates.value.video_credits) != null ? repairBudget.value + estimates.value.video_credits : null)
const validStart = computed(() => props.status === 'storyboard_approved' && props.production.enabled && startTotal.value != null && (remainingBudget.value == null || startTotal.value <= remainingBudget.value))
const currentShot = computed(() => rows.value.find((shot) => shot.shot_id === confirmation.value?.shotId))
const quoteContext = computed(() => ({ planVersion: props.planVersion, shotId: confirmation.value?.shotId, motionPrompt: motionPrompt.value }))
const onlyImpact = computed(() => quoteImpact(quote.value, 'only'))
const cascadeImpact = computed(() => quoteImpact(quote.value, 'cascade'))
const selectedImpact = computed(() => quoteImpact(quote.value, scope.value))
const promptValid = computed(() => confirmation.value?.operation !== 'redo' || Boolean(motionPrompt.value.trim()))
const confirmable = computed(() => isCurrentQuote(quote.value, quoteContext.value) && finiteCredits(selectedImpact.value.cost) != null && canAct(currentShot.value, confirmation.value?.operation) && (confirmation.value?.operation !== 'retry' || quote.value.can_retry))
const labels = productionLabels, money = creditText
const canAct = (shot, operation) => productionActionAllowed(props.status, shot, operation, locked.value)
const warningText = (warning) => typeof warning === 'string' ? warning : warning?.summary || warning?.message || warning?.code || '请检查镜头衔接。'
const tone = (status) => ({ success: 'text-emerald-700 dark:text-emerald-300', failed: 'text-red-700 dark:text-red-300', blocked: 'text-amber-700 dark:text-amber-300', stale: 'text-amber-700 dark:text-amber-300', running: 'text-blue-700 dark:text-blue-300' }[status] || '')
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
    error.value = '生产状态或计划版本已更新，请重新查看并确认操作。'
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
      if (!isCurrentQuote(result, quoteContext.value)) throw new Error('报价版本已过期，请重新获取。')
      quote.value = result
    }
  } catch (failure) {
    if (epoch === quoteEpoch) modalError.value = failure.response?.data?.error?.message || failure.message || '报价失败，请重试。'
  } finally { if (epoch === quoteEpoch) quoting.value = false }
}
function submit(action, payload) {
  modalError.value = ''; error.value = ''
  emit('action', { action, payload, onSuccess: (result) => { actionEstimate.value = result.action_estimated_credits ?? null; dialog.value?.close(); resetDialog() }, onError: (message) => { error.value = message; modalError.value = message; quote.value = null } })
}
function submitStart() { if (validStart.value) submit('start_production', { plan_version: props.planVersion, repair_budget_credits: repairBudget.value }) }
function submitApprove() { if (props.status === 'awaiting_video_review') submit('approve_videos', { plan_version: props.planVersion }) }
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
.metric { @apply min-w-0 rounded-lg bg-slate-50 p-3 dark:bg-slate-800; }
.metric span { @apply block text-xs text-slate-500; }
.metric strong { @apply mt-1 block break-words tabular-nums; }
.tag { @apply rounded-md bg-slate-100 px-2 py-1 text-xs dark:bg-slate-800; }
.shot-card { @apply min-w-0 break-words rounded-xl border border-slate-200 p-3 dark:border-slate-700; }
.notice { @apply break-words rounded-lg bg-amber-50 p-3 text-xs leading-relaxed text-amber-800 dark:bg-amber-950/40 dark:text-amber-300; }
.primary-btn { @apply rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
.field-label { @apply block text-xs text-slate-500; }
.field { @apply mt-1 block w-full min-w-0 rounded-lg border border-slate-300 bg-white p-2 text-sm text-slate-800 focus:border-blue-500 focus:outline-none dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100; }
.choice { @apply flex items-start gap-3 rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-700; }
.choice input { @apply mt-1; }
.production-dialog { @apply max-h-[90vh] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto rounded-2xl border border-slate-200 bg-white text-slate-800 shadow-xl dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100; }
.production-dialog::backdrop { background: rgb(15 23 42 / 0.5); }
</style>
