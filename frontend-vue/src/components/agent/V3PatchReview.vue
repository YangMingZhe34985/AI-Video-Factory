<template>
  <section class="patch-review" aria-label="局部修改审核" data-testid="v3-patch-review">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <h3 class="font-semibold">局部修改审核</h3>
        <p class="mt-1 text-xs text-slate-500">{{ patch.patch_id }} · 基于版本 {{ patch.base_version }}</p>
      </div>
      <span class="status">{{ v3StatusLabel(patch.status) }}</span>
    </header>
    <p class="mt-3 whitespace-pre-wrap text-sm">{{ patch.reason || '尚未提供修改原因。' }}</p>
    <p class="mt-2 text-xs text-slate-500">{{ patch.author_verified ? `实际起草：${patch.final_author} · 原提议：${patch.author}` : '历史起草来源未验证' }}<span v-if="patch.trigger_kind === 'user_revision'"> · 用户要求修订</span></p>
    <div class="mt-3 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800">
      <p class="font-medium">Director · {{ patchReviewLabel(patch.review?.verdict) }}</p>
      <p v-if="patch.review?.reason" class="mt-1 whitespace-pre-wrap text-slate-600 dark:text-slate-300">{{ patch.review.reason }}</p>
    </div>
    <div v-if="patch.review" class="mt-3 rounded-lg bg-slate-50 p-3 text-sm dark:bg-slate-800" data-testid="patch-intent-assessment">
      <p class="font-medium">{{ intent.label }}</p>
      <dl v-for="(change, index) in intent.changes" :key="index" class="mt-3 space-y-1 break-words">
        <dt class="font-medium">{{ change.element }} · {{ change.change === 'removed' ? '移除' : '改变' }}</dt>
        <dd>修改前：{{ change.before }}</dd><dd>修改后：{{ change.after || '已移除' }}</dd>
        <dd>原因：{{ change.reason }}</dd>
      </dl>
      <p v-if="intent.status !== 'preserved' && patch.status !== 'applied'" class="mt-2 text-xs">请结合下方前后差异与审阅理由，决定是否批准当前修订。</p>
    </div>
    <p v-if="patch.status === 'applied'" class="mt-3 text-sm text-slate-500">{{ patch.auto_approved ? '在原授权范围内自动应用' : '经人工确认应用' }}<span v-if="patch.approved_version"> · 版本 {{ patch.approved_version }}</span>。此记录仅供查看。</p>
    <p v-else-if="!reviewable" class="mt-3 text-sm text-slate-500">当前为只读记录；待独立审阅完成、版本一致且任务可处理时才能报价与审批。</p>

    <div class="mt-4 space-y-2">
      <details v-for="(change, index) in changes" :key="`${change.node_id}-${index}`" class="change" :open="changes.length === 1">
        <summary class="cursor-pointer text-sm font-medium">{{ patchOperationLabel(change.op) }} · {{ change.node_id }}</summary>
        <div class="mt-3 grid min-w-0 gap-3 sm:grid-cols-2">
          <div class="min-w-0"><p class="mb-1 text-xs text-slate-500">修改前</p><pre>{{ patchJson(change.before) }}</pre></div>
          <div class="min-w-0"><p class="mb-1 text-xs text-slate-500">修改后</p><pre>{{ patchJson(change.after) }}</pre></div>
        </div>
      </details>
      <p v-if="!changes.length" class="text-sm text-slate-500">暂无具体变更预览。</p>
    </div>

    <div v-if="metadataChanges.length" class="mt-4 space-y-2" data-testid="patch-metadata-diff">
      <div v-for="(change, index) in metadataChanges" :key="index" class="change min-w-0 whitespace-pre-wrap break-words text-sm">
        <p class="font-medium">{{ change.node_id }}<span v-if="change.incidental"> · 插入节点带来的附带修改</span></p>
        <p v-if="change.origin" class="mt-2">来源：{{ change.origin.before?.agent || '无' }} → {{ change.origin.after?.agent || '无' }}</p>
        <template v-if="change.rationale"><p class="mt-2 font-medium">方案理由变化</p><p>修改前：{{ change.rationale.before || '无' }}</p><p>修改后：{{ change.rationale.after || '无' }}</p></template>
        <template v-if="change.depends_on"><p class="mt-2 font-medium">依赖变化</p><p>修改前：{{ dependencyLabel(change.depends_on.before) }}</p><p>修改后：{{ dependencyLabel(change.depends_on.after) }}</p></template>
      </div>
    </div>
    <fieldset v-if="reviewable" class="mt-5" :disabled="disabled || submitting">
      <legend class="text-sm font-semibold">修改范围</legend>
      <div class="mt-2 grid gap-2 sm:grid-cols-2">
        <label class="scope-option">
          <input v-model="scope" :name="`patch-scope-${run.run_id}-${patch.patch_id}`" type="radio" value="only" class="mt-1 shrink-0" />
          <span><span class="block font-medium">只重做目标（only）</span><span class="mt-1 block text-xs text-slate-500">保留已完成下游产物；它们可能使用旧输入，需确认衔接风险。</span></span>
        </label>
        <label class="scope-option">
          <input v-model="scope" :name="`patch-scope-${run.run_id}-${patch.patch_id}`" type="radio" value="cascade" class="mt-1 shrink-0" />
          <span><span class="block font-medium">重做受影响后续（cascade）</span><span class="mt-1 block text-xs text-slate-500">重新执行依赖链，费用可能增加。未开始的正常节点另计继续费用。</span></span>
        </label>
      </div>
      <p class="mt-2 text-xs text-slate-500">拼接、质量检查与打包会重新执行。受影响范围以服务器报价为准。</p>
      <button type="button" class="secondary mt-3" :disabled="quoting || disabled || submitting" @click="loadQuote">{{ quoting ? '正在核对报价…' : validFreshQuote ? '重新获取报价' : '获取当前范围报价' }}</button>
    </fieldset>

    <div class="mt-3 text-sm" aria-live="polite">
      <p v-if="quoting" class="text-slate-500">正在复核依赖、产物与预算；报价本身不会开始生成。</p>
      <p v-else-if="reviewable && !validFreshQuote" class="text-slate-500">请获取当前报价；切换范围或任务发生变化后须重新核对。</p>
    </div>
    <p v-if="error" class="mt-3 text-sm text-red-600 dark:text-red-400" role="alert">{{ error }}</p>

    <div v-if="visibleQuote" class="mt-4 space-y-4">
      <div class="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <p>{{ validFreshQuote ? '当前报价' : '历史报价快照，仅供查看' }} · {{ visibleQuote.scope === 'cascade' ? '级联重做' : visibleQuote.scope === 'only' ? '仅目标重做' : '范围待确认' }}</p>
        <p>演示 credits，非实际账单</p>
      </div>
      <dl class="grid gap-3 sm:grid-cols-3">
        <div class="cost"><dt>修复 / 重做</dt><dd>{{ creditLabel(visibleQuote.estimated_credits?.repair) }}</dd></div>
        <div class="cost"><dt>原计划继续执行</dt><dd>{{ creditLabel(visibleQuote.estimated_credits?.continuation) }}</dd></div>
        <div class="cost"><dt>本次新增合计</dt><dd>{{ creditLabel(visibleQuote.estimated_credits?.total) }}</dd></div>
      </dl>
      <p class="text-xs text-slate-500">复用和保留结果不重复收费。继续执行费用仍受任务总预算限制；人工批准不会补充自动修复额度。</p>

      <div class="grid gap-2 sm:grid-cols-2">
        <div v-for="group in impactGroups" :key="group.key" class="impact">
          <p class="text-xs font-medium">{{ group.label }} · {{ group.ids.length }}</p>
          <div v-if="group.ids.length" class="mt-2 flex flex-wrap gap-1"><span v-for="id in group.ids" :key="id" class="node-id">{{ id }}</span></div>
          <p v-else class="mt-2 text-xs text-slate-400">无</p>
        </div>
      </div>
      <p v-if="impact.failed.length" class="notice">以下范围外失败节点仍保留失败状态，不会自动重试：{{ impact.failed.join('、') }}</p>

      <details v-if="nodeCosts.length" class="change">
        <summary class="cursor-pointer text-sm font-medium">逐节点费用与计费秒数</summary>
        <dl class="mt-3 space-y-2">
          <div v-for="node in nodeCosts" :key="node.node_id" class="flex flex-wrap justify-between gap-x-4 gap-y-1 border-b border-slate-100 pb-2 text-xs dark:border-slate-700">
            <dt class="min-w-0">{{ node.node_id }} · {{ nodeActionLabel(node.action) }}<span class="mt-1 block text-slate-500">输入视频 {{ seconds(node.input_video_seconds) }} / 输出视频 {{ seconds(node.output_video_seconds) }}</span></dt>
            <dd class="tabular-nums">{{ creditLabel(node.estimated_cost) }} credits</dd>
          </div>
        </dl>
      </details>
      <div v-if="warnings.length" class="notice"><p class="font-medium">需要留意</p><ul class="mt-1 list-inside list-disc space-y-1"><li v-for="(warning, index) in warnings" :key="index">{{ issueText(warning) }}</li></ul></div>
      <div v-if="issues.length" class="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/30 dark:text-red-300" role="alert"><p class="font-medium">待解决问题</p><ul class="mt-1 list-inside list-disc space-y-1"><li v-for="(issue, index) in issues" :key="index">{{ issueText(issue) }}</li></ul></div>

      <template v-if="validFreshQuote">
        <label v-if="impact.retained.length" class="notice flex items-start gap-2">
          <input v-model="retainedAcknowledged" type="checkbox" :disabled="disabled || submitting" class="mt-1 shrink-0" />
          <span>我确认保留上述下游旧产物。它们仍基于原输入，人物、动作或衔接可能与重做结果不一致。</span>
        </label>
        <p v-if="approvalIssue" class="text-sm text-slate-500">{{ approvalIssue }}</p>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="primary" :disabled="disabled || submitting || Boolean(approvalIssue)" @click="act('approve_patch')">{{ submitting ? '提交中…' : '确认范围与费用，批准修改' }}</button>
          <button type="button" class="secondary" :disabled="disabled || submitting" @click="act('reject_patch')">拒绝此补丁</button>
        </div>
        <p class="text-xs text-slate-500">拒绝仅关闭此补丁，保留已完成产物与原失败状态；批准前服务器会再次核对报价。</p>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { quoteAgentV3Patch } from '@/api/agent'
import { creditLabel, v3StatusLabel } from './v3-actions'
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
const changes = computed(() => Array.isArray(props.patch.diff_preview) ? props.patch.diff_preview : [])
const impact = computed(() => patchImpact(visibleQuote.value))
const warnings = computed(() => Array.isArray(visibleQuote.value?.warnings) ? visibleQuote.value.warnings : [])
const issues = computed(() => Array.isArray(visibleQuote.value?.issues) ? visibleQuote.value.issues : [])
const nodeCosts = computed(() => Array.isArray(visibleQuote.value?.node_costs)
  ? visibleQuote.value.node_costs.filter((node) => node !== null && typeof node === 'object' && !Array.isArray(node)) : [])
const approvalIssue = computed(() => patchApprovalIssue(receipt.value, props.run, props.patch, scope.value, retainedAcknowledged.value))
const impactGroups = computed(() => [
  { key: 'affected', label: '依赖关系受影响', ids: impact.value.affected },
  { key: 'executing', label: '修复或重做执行', ids: impact.value.executing },
  { key: 'continuing', label: '继续原计划', ids: impact.value.continuing },
  { key: 'reused', label: '复用有效产物', ids: impact.value.reused },
  { key: 'retained', label: '保留下游旧产物', ids: impact.value.retained },
  { key: 'removed', label: '移除节点', ids: impact.value.removed },
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
.status { @apply rounded-full bg-slate-100 px-3 py-1 text-xs dark:bg-slate-800; }
.change { @apply min-w-0 rounded-xl border border-slate-200 p-3 dark:border-slate-700; }
pre { @apply max-w-full rounded-lg bg-slate-50 p-3 text-xs leading-relaxed dark:bg-slate-800; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; }
.scope-option { @apply flex min-w-0 cursor-pointer items-start gap-2 rounded-xl border border-slate-200 p-3 text-sm dark:border-slate-700; }
.cost { @apply rounded-xl bg-slate-50 p-3 dark:bg-slate-800; }
.cost dt { @apply text-xs text-slate-500; }
.cost dd { @apply mt-1 text-lg font-semibold tabular-nums; }
.impact { @apply min-w-0 rounded-lg border border-slate-100 p-3 dark:border-slate-800; }
.node-id { @apply rounded bg-slate-100 px-2 py-1 text-xs dark:bg-slate-800; }
.notice { @apply rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-300; }
.primary { @apply rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary { @apply rounded-xl border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800; }
</style>
