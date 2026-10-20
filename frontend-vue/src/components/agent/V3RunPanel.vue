<template>
  <div class="v3-panel space-y-4" data-testid="v3-run-panel">
    <section class="panel">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="flex min-w-0 items-start gap-3">
          <span class="icon-tile"><PhSparkle :size="18" /></span>
          <div class="min-w-0">
            <p class="text-[11px] font-medium uppercase tracking-wide text-slate-400">Agent Studio · 创作进度</p>
            <h2 class="mt-0.5 text-lg font-semibold leading-snug text-slate-900 dark:text-white">{{ run.plan?.title || '正在理解你的需求' }}</h2>
          </div>
        </div>
        <span class="pill" :class="`tone-${statusTone(run.status)}`" role="status">
          <PhCircleNotch v-if="isBusy(run.status)" :size="12" class="animate-spin" /><span v-else class="h-1.5 w-1.5 rounded-full bg-current" />{{ v3StatusLabel(run.status) }}
        </span>
      </div>
      <p v-if="run.mock" class="notice notice-amber mt-3"><PhInfo :size="15" class="mt-0.5 flex-none" />Mock 演示：使用测试素材，不调用真实模型；本页不代表实际生成质量。</p>
      <p v-if="run.error" role="alert" class="notice notice-red mt-3"><PhWarning :size="15" class="mt-0.5 flex-none" />{{ run.error.code }} · {{ run.error.message }}</p>
      <p v-if="error" role="alert" class="notice notice-red mt-3"><PhWarning :size="15" class="mt-0.5 flex-none" />{{ error }}</p>
      <p v-if="run.action_pending" class="mt-3 flex items-center gap-1.5 text-sm text-slate-500"><PhCircleNotch :size="14" class="animate-spin" />{{ run.status === 'attention' ? '原操作已暂停。恢复会核对原操作状态；结果不明时继续暂停。' : '操作已提交，等待后台处理。' }}</p>
      <div v-if="(run.status === 'attention' && run.resume_count < 2) || v3ActionAllowed(run, 'reject')" class="mt-4 flex flex-wrap gap-2">
        <button v-if="run.status === 'attention' && run.resume_count < 2" type="button" class="primary" :disabled="busy || !v3ActionAllowed(run, 'resume')" @click="submit({ action: 'resume' })">恢复检查</button>
        <button v-if="v3ActionAllowed(run, 'reject')" type="button" class="secondary" :disabled="busy" @click="submit({ action: 'reject' })">结束本次创作</button>
      </div>
      <p v-if="run.message" class="mt-4 whitespace-pre-wrap rounded-xl bg-slate-50 px-3 py-2.5 text-sm leading-relaxed dark:bg-slate-800/60">{{ run.message }}</p>
    </section>

    <section class="panel" aria-label="创作预算">
      <h3 class="section-title"><PhCoins :size="16" />预算与用量</h3>
      <dl class="mt-3 grid grid-cols-[repeat(auto-fit,minmax(min(12rem,100%),1fr))] gap-2.5">
        <div v-for="meter in meters" :key="meter.label" class="stat">
          <dt>{{ meter.label }}</dt>
          <dd><strong>{{ creditLabel(meter.used) }}</strong><span> / {{ creditLabel(meter.limit) }}</span></dd>
          <div class="bar" aria-hidden="true"><span :class="meter.ratio > 0.9 ? 'bg-red-500' : meter.ratio > 0.7 ? 'bg-amber-500' : 'bg-blue-600'" :style="{ width: `${meter.ratio * 100}%` }" /></div>
        </div>
      </dl>
      <p class="mt-2.5 text-[11px] leading-relaxed text-slate-400">单位为演示 credits，不是实际账单。规划费用已计入任务花费；修复预留不重复计费，也不会在人工批准后自动补满。</p>
    </section>

    <section class="panel">
      <h3 class="section-title"><PhChatText :size="16" />你的需求</h3>
      <p class="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-slate-200">{{ run.text }}</p>
      <div v-if="run.attachments?.length" class="mt-3 flex flex-wrap gap-3">
        <figure v-for="asset in run.attachments" :key="asset.attachment_id" class="w-24 min-w-0">
          <AuthedImage v-if="asset.kind === 'image' && attachmentPreview(asset)" :src="attachmentPreview(asset)" :alt="asset.file_name" class="aspect-square w-full rounded-lg object-cover ring-1 ring-slate-200 dark:ring-slate-700" />
          <span v-else class="flex aspect-square flex-col items-center justify-center gap-1 rounded-lg bg-slate-100 text-xs text-slate-500 dark:bg-slate-800">
            <PhVideoCamera v-if="asset.kind === 'video'" :size="20" /><PhSpeakerHigh v-else-if="asset.kind === 'audio'" :size="20" /><PhPaperclip v-else :size="20" />
            {{ asset.kind === 'video' ? '视频' : asset.kind === 'audio' ? '音频' : '附件' }}
          </span>
          <figcaption class="mt-1 truncate text-[11px] text-slate-500" :title="asset.file_name">{{ asset.file_name }}</figcaption>
        </figure>
      </div>
    </section>

    <ClarificationCard v-if="run.status === 'awaiting_input' && run.pending_card" :key="run.pending_card.card_id" :card="run.pending_card" :disabled="ordinaryDisabled" @submit="answer" />
    <V3Collaboration :run="run" />
    <V3PlanBoard v-if="run.plan" :run="run" :disabled="ordinaryDisabled" @action="submit" />
    <V3PatchReview v-for="patch in run.patches || []" :key="patch.patch_id" :run="run" :patch="patch" :disabled="ordinaryDisabled" @action="submit" @refresh="emit('refresh')" />

    <section v-if="run.results?.length" class="panel" aria-label="创作产物">
      <h3 class="section-title"><PhFilmReel :size="16" />创作产物<span class="count">{{ run.results.length }}</span></h3>
      <div class="mt-3 grid grid-cols-[repeat(auto-fill,minmax(min(18rem,100%),1fr))] gap-3">
        <figure v-for="asset in run.results" :key="`${asset.node_id}-${asset.artifact_id}`" class="result">
          <AuthedImage v-if="asset.kind === 'image' && deliveryAssetUrl(asset, 'preview')" :src="deliveryAssetUrl(asset, 'preview')" :alt="asset.node_id" class="max-h-72 w-full bg-slate-100 object-contain dark:bg-slate-800" />
          <AuthedVideo v-else-if="asset.kind === 'video' && deliveryAssetUrl(asset, 'preview')" :src="deliveryAssetUrl(asset, 'preview')" label="加载视频预览" loading-label="正在加载…" error-label="预览加载失败，点击重试" class="max-h-72 w-full bg-black" />
          <span v-else class="flex h-28 items-center justify-center bg-slate-100 text-slate-400 dark:bg-slate-800"><PhFileZip v-if="asset.kind === 'package'" :size="28" /><PhFile v-else :size="28" /></span>
          <figcaption class="flex items-center justify-between gap-2 px-3 py-2.5">
            <span class="min-w-0 truncate text-sm text-slate-700 dark:text-slate-200">{{ asset.kind === 'package' ? '素材包' : asset.kind === 'video' ? '视频' : asset.kind === 'image' ? '图片' : '文件' }} · {{ asset.node_id }}</span>
            <button type="button" class="secondary flex-none" :disabled="Boolean(downloading) || !deliveryAssetUrl(asset)" @click="download(asset)">{{ downloading === asset.artifact_id ? '下载中…' : '下载产物' }}</button>
          </figcaption>
        </figure>
      </div>
      <p v-if="downloadError" class="notice notice-red mt-3" role="alert"><PhWarning :size="15" class="mt-0.5 flex-none" />{{ downloadError }}</p>
      <button v-if="run.status === 'awaiting_result_review'" type="button" class="primary mt-4" :disabled="ordinaryDisabled || !v3ActionAllowed(run, 'approve_results', { plan_version: run.plan?.plan_version })" @click="submit({ action: 'approve_results', payload: { plan_version: run.plan?.plan_version } })">确认产物</button>
      <p class="mt-3 text-[11px] text-slate-400">默认不主动压缩；拼接可能按片段格式需要统一编码。明确请求压缩时才生成压缩副本。</p>
    </section>
  </div>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { actOnAgentV3Run } from '@/api/agent'
import request from '@/api/request'
import AuthedImage from './AuthedImage.vue'
import AuthedVideo from './AuthedVideo.vue'
import ClarificationCard from './ClarificationCard.vue'
import V3Collaboration from './V3Collaboration.vue'
import V3PlanBoard from './V3PlanBoard.vue'
import V3PatchReview from './V3PatchReview.vue'
import { createV3ActionSession, creditLabel, v3ActionAllowed, v3StatusLabel } from './v3-actions'
import { deliveryAssetUrl, downloadFilename } from './delivery'
import { isBusy, statusTone } from './v3-tones'
import { PhChatText, PhCircleNotch, PhCoins, PhFile, PhFileZip, PhFilmReel, PhInfo, PhPaperclip, PhSparkle, PhSpeakerHigh, PhVideoCamera, PhWarning } from '@phosphor-icons/vue'

const props = defineProps({ run: { type: Object, required: true } })
const emit = defineEmits(['updated', 'refresh'])
const busy = ref(false), error = ref(''), downloading = ref(''), downloadError = ref('')
const ordinaryDisabled = computed(() => busy.value || Boolean(props.run.action_pending))
const session = createV3ActionSession()
let disposed = false, epoch = 0, actionController, downloadController
const objectUrls = new Map()
watch([() => props.run.run_id, () => props.run.plan?.plan_version], () => {
  epoch++
  actionController?.abort()
  downloadController?.abort()
  downloadController = null
  downloading.value = ''
  downloadError.value = ''
  busy.value = false
  error.value = ''
})
const finite = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
const ratio = (used, total) => finite(used) !== null && finite(total) ? Math.min(1, used / total) : 0
const meters = computed(() => {
  const committed = props.run.repair_budget?.committed, remaining = props.run.repair_budget?.remaining
  return [
    { label: '任务已花费 / 总上限', used: props.run.estimated_spent, limit: props.run.budget_limit, ratio: ratio(props.run.estimated_spent, props.run.budget_limit) },
    { label: '规划已用 / 规划额度', used: props.run.planning_budget?.spent, limit: props.run.planning_budget?.limit, ratio: ratio(props.run.planning_budget?.spent, props.run.planning_budget?.limit) },
    { label: '自动修复已占用 / 剩余', used: committed, limit: remaining, ratio: ratio(committed, (finite(committed) ?? 0) + (finite(remaining) ?? 0)) },
  ]
})
const attachmentPreview = (asset) => deliveryAssetUrl({ ...asset, artifact_id: asset.attachment_id }, 'preview')

async function submit({ action, payload = {}, onSuccess, onError }) {
  if (busy.value || disposed) { onError?.('已有操作处理中，请稍后重试。'); return }
  const requestEpoch = epoch, runId = props.run.run_id
  const controller = new AbortController()
  actionController = controller
  busy.value = true
  error.value = ''
  try {
    const body = session.prepare(props.run, action, payload)
    const value = await actOnAgentV3Run(runId, body, controller.signal)
    if (disposed || requestEpoch !== epoch || props.run.run_id !== runId) return
    if (value?.run_id !== runId || value.schema_version !== 3) throw new Error('服务器返回的任务不匹配，请刷新后检查。')
    session.acknowledge()
    emit('updated', value)
    onSuccess?.(value)
  } catch (failure) {
    if (disposed || requestEpoch !== epoch || controller.signal.aborted) return
    error.value = failure.response?.data?.error?.message || failure.message || '操作未完成，可重试同一请求。'
    onError?.(error.value)
    if (['PLAN_VERSION_CONFLICT', 'PATCH_QUOTE_CHANGED', 'PATCH_SUPERSEDED'].includes(failure.response?.data?.error?.code)) emit('refresh')
  } finally {
    if (!disposed && requestEpoch === epoch) busy.value = false
    if (actionController === controller) actionController = null
  }
}
function answer({ answers, useDefaults }) {
  submit({ action: 'answer', payload: { card_id: props.run.pending_card.card_id, answers, use_defaults: useDefaults } })
}
async function download(asset) {
  const url = deliveryAssetUrl(asset)
  if (!url || downloading.value || disposed) return
  const runId = props.run.run_id
  const controller = new AbortController()
  downloadController = controller
  downloading.value = asset.artifact_id
  downloadError.value = ''
  try {
    const blob = await request.get(url.replace(/^\/api/, ''), { responseType: 'blob', timeout: 300000, signal: controller.signal })
    if (disposed || runId !== props.run.run_id || controller.signal.aborted) return
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = downloadFilename(asset, asset.kind === 'package' ? 'sources.zip' : asset.kind === 'image' ? 'image.png' : 'video.mp4')
    document.body.appendChild(link)
    link.click()
    link.remove()
    objectUrls.set(objectUrl, setTimeout(() => { URL.revokeObjectURL(objectUrl); objectUrls.delete(objectUrl) }, 1000))
  } catch {
    if (!disposed && runId === props.run.run_id && downloadController === controller && !controller.signal.aborted) downloadError.value = '下载失败，请重试。'
  } finally {
    if (downloadController === controller) { downloading.value = ''; downloadController = null }
  }
}
onUnmounted(() => {
  disposed = true
  epoch++
  actionController?.abort()
  downloadController?.abort()
  session.reset()
  for (const [url, timer] of objectUrls) { clearTimeout(timer); URL.revokeObjectURL(url) }
  objectUrls.clear()
})
</script>

<style scoped>
.v3-panel { @apply min-w-0 text-slate-800 dark:text-slate-100; overflow-wrap: anywhere; }
.panel { @apply min-w-0 rounded-2xl border border-slate-200 bg-white p-4 sm:p-5 dark:border-slate-700 dark:bg-slate-900; }
.stat { @apply flex min-w-0 flex-col gap-1 rounded-xl bg-slate-50 px-3.5 py-3 dark:bg-slate-800/60; }
.stat dt { @apply text-[11px] text-slate-500 dark:text-slate-400; }
.stat dd { @apply flex items-baseline gap-1 tabular-nums; }
.stat dd strong { @apply text-base font-semibold text-slate-900 dark:text-white; }
.stat dd span { @apply text-xs text-slate-400; }
.bar { @apply mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700; }
.bar span { @apply block h-full rounded-full transition-all; }
.result { @apply min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900; }
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
