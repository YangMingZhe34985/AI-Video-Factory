<template>
  <div class="v3-panel space-y-5" data-testid="v3-run-panel">
    <section class="panel">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0"><p class="text-xs text-slate-500">Agent Studio · 创作进度</p><h2 class="mt-1 text-xl font-semibold">{{ run.plan?.title || '正在理解你的需求' }}</h2></div>
        <span class="rounded-full bg-blue-50 px-3 py-1 text-xs text-blue-700 dark:bg-blue-950 dark:text-blue-300" role="status">{{ v3StatusLabel(run.status) }}</span>
      </div>
      <p v-if="run.mock" class="notice mt-3">Mock 演示：使用测试素材，不调用真实模型；本页不代表实际生成质量。</p>
      <p v-if="run.error" role="alert" class="mt-3 text-sm text-red-600 dark:text-red-400">{{ run.error.code }} · {{ run.error.message }}</p>
      <p v-if="error" role="alert" class="mt-3 text-sm text-red-600 dark:text-red-400">{{ error }}</p>
      <p v-if="run.action_pending" class="mt-3 text-sm text-slate-500">{{ run.status === 'attention' ? '原操作已暂停。恢复会核对原操作状态；结果不明时继续暂停。' : '操作已提交，等待后台处理。' }}</p>
      <div class="mt-4 flex flex-wrap gap-2">
        <button v-if="run.status === 'attention' && run.resume_count < 2" type="button" class="primary" :disabled="busy || !v3ActionAllowed(run, 'resume')" @click="submit({ action: 'resume' })">恢复检查</button>
        <button v-if="v3ActionAllowed(run, 'reject')" type="button" class="secondary" :disabled="busy" @click="submit({ action: 'reject' })">结束本次创作</button>
      </div>
      <p v-if="run.message" class="mt-4 whitespace-pre-wrap text-sm">{{ run.message }}</p>
    </section>

    <section class="panel" aria-label="创作预算">
      <h3 class="font-semibold">预算与用量</h3>
      <dl class="mt-3 grid gap-4 sm:grid-cols-3">
        <div><dt class="text-xs text-slate-500">任务已花费 / 总上限</dt><dd class="mt-1 font-medium tabular-nums">{{ creditLabel(run.estimated_spent) }} / {{ creditLabel(run.budget_limit) }}</dd></div>
        <div><dt class="text-xs text-slate-500">规划已用 / 规划额度</dt><dd class="mt-1 font-medium tabular-nums">{{ creditLabel(run.planning_budget?.spent) }} / {{ creditLabel(run.planning_budget?.limit) }}</dd></div>
        <div><dt class="text-xs text-slate-500">自动修复已占用 / 剩余</dt><dd class="mt-1 font-medium tabular-nums">{{ creditLabel(run.repair_budget?.committed) }} / {{ creditLabel(run.repair_budget?.remaining) }}</dd></div>
      </dl>
      <p class="mt-3 text-xs text-slate-500">单位为演示 credits，不是实际账单。规划费用已计入任务花费；修复预留不重复计费，也不会在人工批准后自动补满。</p>
    </section>

    <section class="panel">
      <h3 class="font-semibold">你的需求</h3><p class="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{{ run.text }}</p>
      <div v-if="run.attachments?.length" class="mt-3 flex flex-wrap gap-3">
        <figure v-for="asset in run.attachments" :key="asset.attachment_id" class="w-24 min-w-0">
          <AuthedImage v-if="asset.kind === 'image' && attachmentPreview(asset)" :src="attachmentPreview(asset)" :alt="asset.file_name" class="aspect-square w-full rounded-lg object-cover" />
          <span v-else class="flex h-16 items-center justify-center rounded-lg bg-slate-100 text-sm dark:bg-slate-800">{{ asset.kind === 'video' ? '视频' : asset.kind === 'audio' ? '音频' : '附件' }}</span>
          <figcaption class="mt-1 break-all text-xs text-slate-500">{{ asset.file_name }}</figcaption>
        </figure>
      </div>
    </section>

    <ClarificationCard v-if="run.status === 'awaiting_input' && run.pending_card" :key="run.pending_card.card_id" :card="run.pending_card" :disabled="ordinaryDisabled" @submit="answer" />
    <V3Collaboration :run="run" />
    <V3PlanBoard v-if="run.plan" :run="run" :disabled="ordinaryDisabled" @action="submit" />
    <V3PatchReview v-for="patch in run.patches || []" :key="patch.patch_id" :run="run" :patch="patch" :disabled="ordinaryDisabled" @action="submit" @refresh="emit('refresh')" />

    <section v-if="run.results?.length" class="panel" aria-label="创作产物">
      <h3 class="font-semibold">创作产物</h3>
      <div class="mt-3 grid gap-4 sm:grid-cols-2">
        <figure v-for="asset in run.results" :key="`${asset.node_id}-${asset.artifact_id}`" class="min-w-0 rounded-xl border border-slate-200 p-3 dark:border-slate-700">
          <AuthedImage v-if="asset.kind === 'image' && deliveryAssetUrl(asset, 'preview')" :src="deliveryAssetUrl(asset, 'preview')" :alt="asset.node_id" class="max-h-72 w-full rounded-lg object-contain" />
          <AuthedVideo v-else-if="asset.kind === 'video' && deliveryAssetUrl(asset, 'preview')" :src="deliveryAssetUrl(asset, 'preview')" label="加载视频预览" loading-label="正在加载…" error-label="预览加载失败，点击重试" class="max-h-72 w-full rounded-lg bg-black" />
          <figcaption class="mt-2 text-sm">{{ asset.kind === 'package' ? '素材包' : asset.kind === 'video' ? '视频' : asset.kind === 'image' ? '图片' : '文件' }} · {{ asset.node_id }}</figcaption>
          <button type="button" class="secondary mt-2" :disabled="Boolean(downloading) || !deliveryAssetUrl(asset)" @click="download(asset)">{{ downloading === asset.artifact_id ? '下载中…' : '下载产物' }}</button>
        </figure>
      </div>
      <p v-if="downloadError" class="mt-3 text-sm text-red-600" role="alert">{{ downloadError }}</p>
      <button v-if="run.status === 'awaiting_result_review'" type="button" class="primary mt-4" :disabled="ordinaryDisabled || !v3ActionAllowed(run, 'approve_results', { plan_version: run.plan?.plan_version })" @click="submit({ action: 'approve_results', payload: { plan_version: run.plan?.plan_version } })">确认产物</button>
      <p class="mt-3 text-xs text-slate-500">默认不主动压缩；拼接可能按片段格式需要统一编码。明确请求压缩时才生成压缩副本。</p>
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
.notice { @apply rounded-lg bg-amber-50 p-3 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-300; }
.primary { @apply rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary { @apply rounded-xl border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:hover:bg-slate-800; }
</style>
