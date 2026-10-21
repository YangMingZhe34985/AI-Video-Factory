<template>
  <section class="patch-review" aria-label="局部修改审核" data-testid="v3-patch-review">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 items-start gap-3">
        <span class="icon-tile"><PhGitDiff :size="18" /></span>
        <div class="min-w-0">
          <h3 class="text-[15px] font-semibold text-slate-900 dark:text-white">局部修改审核</h3>
          <p class="mt-0.5 font-mono text-[11px] text-slate-500 dark:text-slate-400">{{ patch.patch_id }} · 基于版本 {{ patch.base_version }}</p>
        </div>
      </div>
      <span class="pill" :class="`tone-${statusTone(patch.status)}`">{{ v3StatusLabel(patch.status) }}</span>
    </header>

    <p class="mt-4 whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-slate-200">{{ patch.reason || '尚未提供修改原因。' }}</p>
    <p class="meta-line"><PhUserCircle :size="14" class="flex-none" /><span>{{ patch.author_verified ? `实际起草：${patch.final_author} · 原提议：${patch.author}` : '历史起草来源未验证' }}<span v-if="patch.trigger_kind === 'user_revision'"> · 用户要求修订</span></span></p>

    <div class="mt-4 grid min-w-0 gap-3 lg:grid-cols-2">
      <div class="card" :class="`card-${reviewTone}`">
        <p class="card-title"><PhSealCheck :size="16" class="flex-none" />Director · {{ patchReviewLabel(patch.review?.verdict) }}</p>
        <p class="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-600 dark:text-slate-300">审阅对象：最终草稿与原需求、已确认修订。</p>
        <p v-if="patch.review?.reason" class="mt-1.5 whitespace-pre-wrap text-[13px] leading-relaxed text-slate-600 dark:text-slate-300">最终草稿审阅理由：{{ patch.review.reason }}</p>
      </div>
      <div v-if="patch.review" class="card" :class="`card-${intent.status === 'preserved' ? 'emerald' : 'amber'}`" data-testid="patch-intent-assessment">
        <p class="card-title"><component :is="intent.status === 'preserved' ? PhCheckCircle : PhWarning" :size="16" class="flex-none" />{{ intent.label }}</p>
        <dl v-for="(change, index) in intent.changes" :key="index" class="intent-change">
          <dt class="font-medium text-slate-800 dark:text-slate-100">{{ change.element }} · <span :class="change.change === 'removed' ? 'text-red-600 dark:text-red-400' : 'text-amber-700 dark:text-amber-300'">{{ change.change === 'removed' ? '移除' : '改变' }}</span></dt>
          <dd><span class="tag tag-before">修改前</span><span class="sr-only">：</span>{{ change.before }}</dd>
          <dd><span class="tag tag-after">修改后</span><span class="sr-only">：</span>{{ change.after || '已移除' }}</dd>
          <dd class="text-slate-500 dark:text-slate-400">原因：{{ change.reason }}</dd>
        </dl>
        <p v-if="intent.status !== 'preserved' && patch.status !== 'applied'" class="mt-2.5 text-xs text-slate-600 dark:text-slate-300">请结合下方前后差异与审阅理由，决定是否批准当前修订。</p>
      </div>
    </div>

    <p v-if="patch.status === 'applied'" class="notice notice-slate mt-3"><PhLockSimple :size="15" class="mt-0.5 flex-none" /><span>{{ patch.auto_approved ? '在原授权范围内自动应用' : '经人工确认应用' }}<span v-if="patch.approved_version"> · 版本 {{ patch.approved_version }}</span>。此记录仅供查看。</span></p>
    <p v-else-if="!reviewable" class="notice notice-slate mt-3"><PhLockSimple :size="15" class="mt-0.5 flex-none" /><span>当前为只读记录；待独立审阅完成、版本一致且任务可处理时才能报价与审批。</span></p>

    <h4 class="section-title mt-5"><PhListChecks :size="16" />变更内容<span v-if="changes.length" class="count">{{ changes.length }}</span></h4>
    <div class="mt-2.5 space-y-2">
      <details v-for="(change, index) in changes" :key="`${change.node_id}-${index}`" class="change" :open="changes.length === 1">
        <summary><PhCaretRight :size="13" class="chev" /><span class="op-chip">{{ patchOperationLabel(change.op) }}</span><span class="font-mono text-[13px]">{{ change.node_id }}</span></summary>
        <div class="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
          <div class="min-w-0"><p class="diff-label text-red-600 dark:text-red-400">修改前</p><pre class="pre-before">{{ patchJson(change.before) }}</pre></div>
          <div class="min-w-0"><p class="diff-label text-emerald-600 dark:text-emerald-400">修改后</p><pre class="pre-after">{{ patchJson(change.after) }}</pre></div>
        </div>
      </details>
      <p v-if="!changes.length" class="empty">暂无具体变更预览。</p>
    </div>

    <div v-if="metadataChanges.length" class="mt-3 space-y-2" data-testid="patch-metadata-diff">
      <div v-for="(change, index) in metadataChanges" :key="index" class="change min-w-0 whitespace-pre-wrap break-words text-[13px]">
        <p class="font-medium"><span class="font-mono">{{ change.node_id }}</span><span v-if="change.incidental" class="text-slate-500"> · 插入节点带来的附带修改</span></p>
        <p v-if="change.origin" class="mt-2 text-slate-600 dark:text-slate-300">来源：{{ change.origin.before?.agent || '无' }} → {{ change.origin.after?.agent || '无' }}</p>
        <template v-if="change.rationale"><p class="meta-head">方案理由变化</p><p class="text-slate-600 dark:text-slate-300">修改前：{{ change.rationale.before || '无' }}</p><p class="text-slate-600 dark:text-slate-300">修改后：{{ change.rationale.after || '无' }}</p></template>
        <template v-if="change.depends_on"><p class="meta-head">依赖变化</p><p class="text-slate-600 dark:text-slate-300">修改前：{{ dependencyLabel(change.depends_on.before) }}</p><p class="text-slate-600 dark:text-slate-300">修改后：{{ dependencyLabel(change.depends_on.after) }}</p></template>
      </div>
    </div>

    <fieldset v-if="reviewable" class="mt-5 min-w-0" :disabled="disabled || submitting">
      <legend class="section-title"><PhTreeStructure :size="16" />修改范围</legend>
      <div class="mt-2.5 grid gap-2 sm:grid-cols-2">
        <label class="scope-option">
          <input v-model="scope" :name="`patch-scope-${run.run_id}-${patch.patch_id}`" type="radio" value="only" class="mt-0.5 shrink-0 accent-blue-600" />
          <span><span class="block font-medium text-slate-900 dark:text-slate-100">只重做目标（only）</span><span class="mt-1 block text-xs leading-relaxed text-slate-500 dark:text-slate-400">保留已完成下游产物；它们可能使用旧输入，需确认衔接风险。</span></span>
        </label>
        <label class="scope-option">
          <input v-model="scope" :name="`patch-scope-${run.run_id}-${patch.patch_id}`" type="radio" value="cascade" class="mt-0.5 shrink-0 accent-blue-600" />
          <span><span class="block font-medium text-slate-900 dark:text-slate-100">重做受影响后续（cascade）</span><span class="mt-1 block text-xs leading-relaxed text-slate-500 dark:text-slate-400">重新执行依赖链，费用可能增加。未开始的正常节点另计继续费用。</span></span>
        </label>
      </div>
      <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">拼接、质量检查与打包会重新执行。受影响范围以服务器报价为准。</p>
      <button type="button" class="secondary mt-3" :disabled="quoting || disabled || submitting" @click="loadQuote"><PhCircleNotch v-if="quoting" :size="14" class="animate-spin" /><PhCalculator v-else :size="14" />{{ quoting ? '正在核对报价…' : validFreshQuote ? '重新获取报价' : '获取当前范围报价' }}</button>
    </fieldset>

    <div class="mt-3 text-xs" aria-live="polite">
      <p v-if="quoting" class="text-slate-500 dark:text-slate-400">正在复核依赖、产物与预算；报价本身不会开始生成。</p>
      <p v-else-if="reviewable && !validFreshQuote" class="text-slate-500 dark:text-slate-400">请获取当前报价；切换范围或任务发生变化后须重新核对。</p>
    </div>
    <p v-if="error" class="notice notice-red mt-3" role="alert"><PhWarning :size="15" class="mt-0.5 flex-none" /><span>{{ error }}</span></p>

    <div v-if="visibleQuote" class="quote-box">
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
        <p class="flex items-center gap-1.5 font-medium text-slate-700 dark:text-slate-200"><PhCoins :size="15" />{{ validFreshQuote ? '当前报价' : '历史报价快照，仅供查看' }} · {{ visibleQuote.scope === 'cascade' ? '级联重做' : visibleQuote.scope === 'only' ? '仅目标重做' : '范围待确认' }}</p>
        <p class="text-slate-400">演示 credits，非实际账单</p>
      </div>
      <dl class="grid gap-2.5 sm:grid-cols-3">
        <div class="cost"><dt>修复 / 重做</dt><dd>{{ creditLabel(visibleQuote.estimated_credits?.repair) }}</dd></div>
        <div class="cost"><dt>原计划继续执行</dt><dd>{{ creditLabel(visibleQuote.estimated_credits?.continuation) }}</dd></div>
        <div class="cost cost-total"><dt>本次新增合计</dt><dd>{{ creditLabel(visibleQuote.estimated_credits?.total) }}</dd></div>
      </dl>
      <p class="text-xs text-slate-500 dark:text-slate-400">复用和保留结果不重复收费。继续执行费用仍受任务总预算限制；人工批准不会补充自动修复额度。</p>

      <div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        <div v-for="group in impactGroups" :key="group.key" class="impact" :class="{ 'impact-empty': !group.ids.length }">
          <p class="flex items-center justify-between gap-2 text-xs font-medium text-slate-700 dark:text-slate-200"><span class="flex items-center gap-1.5"><span class="dot" :class="`dot-${group.tone}`" />{{ group.label }}</span><span class="tabular-nums text-slate-400">{{ group.ids.length }}</span></p>
          <div v-if="group.ids.length" class="mt-2 flex flex-wrap gap-1"><span v-for="id in group.ids" :key="id" class="node-id">{{ id }}</span></div>
          <p v-else class="mt-1.5 text-xs text-slate-400">无</p>
        </div>
      </div>
      <p v-if="impact.failed.length" class="notice notice-amber"><PhWarning :size="15" class="mt-0.5 flex-none" /><span>以下范围外失败节点仍保留失败状态，不会自动重试：{{ impact.failed.join('、') }}</span></p>

      <details v-if="nodeCosts.length" class="change">
        <summary><PhCaretRight :size="13" class="chev" />逐节点费用与计费秒数</summary>
        <dl class="mt-3 space-y-2">
          <div v-for="node in nodeCosts" :key="node.node_id" class="flex flex-wrap justify-between gap-x-4 gap-y-1 border-b border-slate-100 pb-2 text-xs last:border-0 dark:border-slate-800">
            <dt class="min-w-0"><span class="font-mono">{{ node.node_id }}</span> · {{ nodeActionLabel(node.action) }}<span class="mt-1 block text-slate-500 dark:text-slate-400">输入视频 {{ seconds(node.input_video_seconds) }} / 输出视频 {{ seconds(node.output_video_seconds) }}</span></dt>
            <dd class="tabular-nums font-medium">{{ creditLabel(node.estimated_cost) }} credits</dd>
          </div>
        </dl>
      </details>
      <div v-if="warnings.length" class="notice notice-amber"><PhInfo :size="15" class="mt-0.5 flex-none" /><div class="min-w-0"><p class="font-medium">需要留意</p><ul class="mt-1 list-inside list-disc space-y-1"><li v-for="(warning, index) in warnings" :key="index">{{ issueText(warning) }}</li></ul></div></div>
      <div v-if="issues.length" class="notice notice-red" role="alert"><PhWarning :size="15" class="mt-0.5 flex-none" /><div class="min-w-0"><p class="font-medium">待解决问题</p><ul class="mt-1 list-inside list-disc space-y-1"><li v-for="(issue, index) in issues" :key="index">{{ issueText(issue) }}</li></ul></div></div>

      <div v-if="validFreshQuote" class="action-box">
        <label v-if="impact.retained.length" class="ack">
          <input v-model="retainedAcknowledged" type="checkbox" :disabled="disabled || submitting" class="mt-0.5 h-4 w-4 shrink-0 accent-amber-600" />
          <span>我确认保留上述下游旧产物。它们仍基于原输入，人物、动作或衔接可能与重做结果不一致。</span>
        </label>
        <p v-if="approvalIssue" class="text-xs text-slate-500 dark:text-slate-400">{{ approvalIssue }}</p>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="primary" :disabled="disabled || submitting || Boolean(approvalIssue)" @click="act('approve_patch')"><PhCircleNotch v-if="submitting" :size="15" class="animate-spin" /><PhCheck v-else :size="15" />{{ submitting ? '提交中…' : '确认范围与费用，批准修改' }}</button>
          <button type="button" class="secondary" :disabled="disabled || submitting" @click="act('reject_patch')"><PhX :size="14" />拒绝此补丁</button>
        </div>
        <p class="text-xs text-slate-500 dark:text-slate-400">拒绝仅关闭此补丁，保留已完成产物与原失败状态；批准前服务器会再次核对报价。</p>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { quoteAgentV3Patch } from '@/api/agent'
import { creditLabel, v3StatusLabel } from './v3-actions'
import { statusTone } from './v3-tones'
import { PhCalculator, PhCaretRight, PhCheck, PhCheckCircle, PhCircleNotch, PhCoins, PhGitDiff, PhInfo, PhListChecks, PhLockSimple, PhSealCheck, PhTreeStructure, PhUserCircle, PhWarning, PhX } from '@phosphor-icons/vue'
import { buildPatchAction, createPatchQuoteSession, currentPatchQuote, patchApprovalIssue, patchContextKey, patchImpact, patchIntent, patchJson, patchOperationLabel, patchReviewable, patchReviewLabel } from './v3-patch'

const props = defineProps({ run: { type: Object, required: true }, patch: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['action', 'refresh'])
const scope = ref(props.patch.scope === 'cascade' ? 'cascade' : 'only')
const receipt = ref(null), quoting = ref(false), error = ref(''), submitting = ref(false), retainedAcknowledged = ref(false)
const session = createPatchQuoteSession()
let controller = null, disposed = false, actionEpoch = 0
const contextKey = computed(() => patchContextKey(props.run, props.patch, scope.value))
const reviewable = computed(() => patchReviewable(props.run, props.patch))
const validFreshQuote = computed(() => currentPatchQuote(receipt.value, props.run, props.patch, scope.value))
const visibleQuote = computed(() => validFreshQuote.value ? receipt.value.quote : props.patch.quote)
const metadataChanges = computed(() => Array.isArray(props.patch.metadata_diff) ? props.patch.metadata_diff : [])
const dependencyLabel = (value) => Array.isArray(value) && value.length ? value.join('、') : '无'
const intent = computed(() => patchIntent(props.patch.review))
const reviewTone = computed(() => ({ approve: 'emerald', revise: 'blue', reject: 'red' })[props.patch.review?.verdict] || 'slate')
const changes = computed(() => Array.isArray(props.patch.diff_preview) ? props.patch.diff_preview : [])
const impact = computed(() => patchImpact(visibleQuote.value))
const warnings = computed(() => Array.isArray(visibleQuote.value?.warnings) ? visibleQuote.value.warnings : [])
const issues = computed(() => Array.isArray(visibleQuote.value?.issues) ? visibleQuote.value.issues : [])
const nodeCosts = computed(() => Array.isArray(visibleQuote.value?.node_costs)
  ? visibleQuote.value.node_costs.filter((node) => node !== null && typeof node === 'object' && !Array.isArray(node)) : [])
const approvalIssue = computed(() => patchApprovalIssue(receipt.value, props.run, props.patch, scope.value, retainedAcknowledged.value))
const impactGroups = computed(() => [
  { key: 'affected', label: '依赖关系受影响', ids: impact.value.affected, tone: 'slate' },
  { key: 'executing', label: '修复或重做执行', ids: impact.value.executing, tone: 'blue' },
  { key: 'continuing', label: '继续原计划', ids: impact.value.continuing, tone: 'violet' },
  { key: 'reused', label: '复用有效产物', ids: impact.value.reused, tone: 'emerald' },
  { key: 'retained', label: '保留下游旧产物', ids: impact.value.retained, tone: 'amber' },
  { key: 'removed', label: '移除节点', ids: impact.value.removed, tone: 'red' },
])
const nodeActionLabel = (action) => ({ execute: '执行', reuse: '复用', retain: '保留旧产物', preserve_failure: '保留失败' })[action] || '待确认'
const seconds = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? `${value} 秒` : '待确认'
const issueText = (issue) => typeof issue === 'string' ? issue : `${issue?.node_id ? `${issue.node_id} · ` : ''}${issue?.message || issue?.code || '请刷新后查看具体原因。'}`

function invalidateQuote() {
  session.invalidate()
  controller?.abort()
  controller = null
  receipt.value = null
  quoting.value = false
  retainedAcknowledged.value = false
}
watch([() => props.run.run_id, () => props.patch.patch_id], () => {
  scope.value = props.patch.scope === 'cascade' ? 'cascade' : 'only'
  error.value = ''
}, { flush: 'sync' })
watch(contextKey, () => {
  invalidateQuote()
  actionEpoch++
  submitting.value = false
}, { flush: 'sync' })
watch(() => props.disabled, (disabled) => { if (disabled) invalidateQuote() }, { flush: 'sync' })

async function loadQuote() {
  if (disposed || props.disabled || submitting.value || !reviewable.value) return
  invalidateQuote()
  const ticket = session.begin(contextKey.value)
  const requestController = new AbortController()
  controller = requestController
  quoting.value = true
  error.value = ''
  try {
    const quote = await quoteAgentV3Patch(props.run.run_id, { patch_id: props.patch.patch_id, scope: scope.value }, requestController.signal)
    if (requestController.signal.aborted || !session.current(ticket, contextKey.value)) return
    const received = session.accept(ticket, contextKey.value, quote)
    if (!currentPatchQuote(received, props.run, props.patch, scope.value)) throw new Error('服务器报价与当前补丁或范围不一致，请刷新后重试。')
    receipt.value = received
  } catch (failure) {
    if (requestController.signal.aborted || !session.current(ticket, contextKey.value)) return
    error.value = failure.response?.data?.error?.message || failure.message || '获取报价失败，请重试。'
    if (['PLAN_VERSION_CONFLICT', 'PATCH_SUPERSEDED', 'PATCH_QUOTE_CHANGED'].includes(failure.response?.data?.error?.code)) emit('refresh')
  } finally {
    if (session.current(ticket, contextKey.value)) quoting.value = false
    if (controller === requestController) controller = null
  }
}

function act(action) {
  if (disposed || props.disabled || submitting.value || quoting.value) return
  try {
    const event = buildPatchAction(receipt.value, props.run, props.patch, scope.value, action, retainedAcknowledged.value)
    const activeEpoch = ++actionEpoch
    submitting.value = true
    error.value = ''
    emit('action', {
      ...event,
      onSuccess() {
        if (disposed || activeEpoch !== actionEpoch) return
        submitting.value = false
        invalidateQuote()
        emit('refresh')
      },
      onError(message) {
        if (disposed || activeEpoch !== actionEpoch) return
        submitting.value = false
        invalidateQuote()
        error.value = message || '操作未完成，请刷新并重新核对报价。'
        emit('refresh')
      },
    })
  } catch (failure) { error.value = failure.message }
}
onUnmounted(() => {
  disposed = true
  actionEpoch++
  controller?.abort()
  session.dispose()
})
</script>

<style scoped>
.patch-review { @apply min-w-0 rounded-2xl border border-slate-200 bg-white p-4 text-slate-800 sm:p-5 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100; overflow-wrap: anywhere; }
.meta-line { @apply mt-2 flex items-start gap-1.5 text-xs text-slate-500 dark:text-slate-400; }
.card { @apply min-w-0 rounded-xl border p-3.5 text-sm; }
.card-title { @apply flex items-start gap-1.5 font-medium leading-snug; }
.card-emerald { @apply border-emerald-200 bg-emerald-50/50 dark:border-emerald-900 dark:bg-emerald-950/20; }
.card-emerald .card-title { @apply text-emerald-800 dark:text-emerald-300; }
.card-amber { @apply border-amber-200 bg-amber-50/50 dark:border-amber-900 dark:bg-amber-950/20; }
.card-amber .card-title { @apply text-amber-800 dark:text-amber-300; }
.card-blue { @apply border-blue-200 bg-blue-50/50 dark:border-blue-900 dark:bg-blue-950/20; }
.card-blue .card-title { @apply text-blue-800 dark:text-blue-300; }
.card-red { @apply border-red-200 bg-red-50/50 dark:border-red-900 dark:bg-red-950/20; }
.card-red .card-title { @apply text-red-700 dark:text-red-300; }
.card-slate { @apply border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-800/50; }
.intent-change { @apply mt-3 space-y-1.5 break-words rounded-lg bg-white/70 p-2.5 text-[13px] leading-relaxed text-slate-700 dark:bg-slate-900/60 dark:text-slate-200; }
.tag { @apply mr-1.5 inline-block rounded px-1.5 py-px text-[10px] font-medium; }
.tag-before { @apply bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300; }
.tag-after { @apply bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300; }
.change { @apply min-w-0 rounded-xl border border-slate-200 p-3 dark:border-slate-700; }
.change summary { @apply flex cursor-pointer list-none items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200; }
.change[open] > summary .chev { transform: rotate(90deg); }
.chev { @apply flex-none text-slate-400 transition-transform; }
.op-chip { @apply rounded-md bg-blue-50 px-1.5 py-0.5 text-[11px] font-medium text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.diff-label { @apply mb-1 text-[11px] font-medium; }
pre { @apply max-w-full rounded-lg p-3 text-[11px] leading-relaxed text-slate-700 dark:text-slate-200; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; }
.pre-before { @apply border-l-2 border-red-300 bg-red-50/50 dark:border-red-800 dark:bg-red-950/20; }
.pre-after { @apply border-l-2 border-emerald-300 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/20; }
.meta-head { @apply mt-2.5 text-xs font-medium text-slate-500 dark:text-slate-400; }
.empty { @apply rounded-xl border border-dashed border-slate-200 px-4 py-6 text-center text-xs text-slate-400 dark:border-slate-700; }
.scope-option { @apply flex min-w-0 cursor-pointer items-start gap-2.5 rounded-xl border-2 border-slate-200 p-3 text-sm transition hover:border-slate-300 dark:border-slate-700 dark:hover:border-slate-600; }
.scope-option:has(input:checked) { @apply border-blue-500 bg-blue-50/40 dark:border-blue-500 dark:bg-blue-950/20; }
.quote-box { @apply mt-4 min-w-0 space-y-3.5 rounded-xl border border-slate-200 bg-slate-50/60 p-4 dark:border-slate-700 dark:bg-slate-800/30; }
.cost { @apply rounded-xl bg-white px-3.5 py-3 dark:bg-slate-900; }
.cost dt { @apply text-[11px] text-slate-500 dark:text-slate-400; }
.cost dd { @apply mt-1 text-lg font-semibold tabular-nums text-slate-900 dark:text-white; }
.cost-total { @apply ring-1 ring-blue-200 dark:ring-blue-900; }
.cost-total dd { @apply text-blue-700 dark:text-blue-300; }
.impact { @apply min-w-0 rounded-lg border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-900; }
.impact-empty { @apply opacity-60; }
.dot { @apply inline-block h-2 w-2 flex-none rounded-full; }
.dot-slate { @apply bg-slate-400; }
.dot-blue { @apply bg-blue-500; }
.dot-violet { @apply bg-violet-500; }
.dot-emerald { @apply bg-emerald-500; }
.dot-amber { @apply bg-amber-500; }
.dot-red { @apply bg-red-500; }
.node-id { @apply rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.action-box { @apply grid min-w-0 gap-3 rounded-xl border border-blue-200 bg-blue-50/40 p-4 dark:border-blue-900 dark:bg-blue-950/20; }
.ack { @apply flex cursor-pointer items-start gap-2 rounded-lg bg-amber-50 p-3 text-sm leading-relaxed text-amber-800 dark:bg-amber-950/40 dark:text-amber-200; }
.icon-tile { @apply flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400; }
.pill { @apply inline-flex flex-none items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium; }
.tone-emerald { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.tone-red { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.tone-amber { @apply bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300; }
.tone-blue { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.tone-slate { @apply bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.tone-violet { @apply bg-violet-50 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300; }
.tone-teal { @apply bg-teal-50 text-teal-700 dark:bg-teal-950/50 dark:text-teal-300; }
.tone-sky { @apply bg-sky-50 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300; }
.tone-rose { @apply bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300; }
.tone-orange { @apply bg-orange-50 text-orange-700 dark:bg-orange-950/50 dark:text-orange-300; }
.notice { @apply flex gap-2 rounded-xl px-3 py-2.5 text-sm leading-relaxed; }
.notice-amber { @apply bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200; }
.notice-red { @apply bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300; }
.notice-blue { @apply bg-blue-50 text-blue-800 dark:bg-blue-950/40 dark:text-blue-200; }
.notice-slate { @apply bg-slate-50 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300; }
.section-title { @apply flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100; }
.count { @apply ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400; }
.primary { @apply inline-flex items-center justify-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary { @apply inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
</style>
