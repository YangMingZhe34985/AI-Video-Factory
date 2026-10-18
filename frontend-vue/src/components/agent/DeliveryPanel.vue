<template>
  <section class="delivery-panel" data-testid="delivery-panel" :aria-label="t('label')">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div><h3 class="font-semibold text-slate-900 dark:text-white">{{ t('title') }}</h3><p class="mt-1 text-xs text-slate-500">{{ t('version', { version: delivery.plan_version ?? '—' }) }}</p></div>
      <span class="rounded-full bg-slate-100 px-3 py-1 text-xs dark:bg-slate-800" role="status">{{ phaseLabel }}</span>
    </header>
    <p v-if="!delivery.enabled" class="notice mt-4">{{ t('disabled') }}</p>
    <p class="mt-3 text-xs text-slate-500">{{ t('localCost') }}</p>
    <p v-if="demo" class="mt-2 text-xs text-amber-700 dark:text-amber-400">{{ t('mock') }}</p>
    <div v-if="delivery.error" role="alert" class="notice error mt-4"><p class="font-medium">{{ t('error') }}</p><p class="mt-1">{{ delivery.error.message }} <span class="text-xs">{{ delivery.error.code }}</span></p></div>
    <p v-if="actionError" role="alert" class="mt-3 text-sm text-red-600 dark:text-red-400">{{ actionError }}</p>
    <p v-if="submitted" role="status" class="mt-3 text-xs text-slate-500">{{ t('submitted') }}</p>
    <div v-if="delivery.can_start || delivery.can_retry" class="mt-4 flex flex-wrap gap-2">
      <button v-if="delivery.can_start" type="button" data-testid="start-delivery" class="primary-btn" :disabled="!canStart" @click="submit('start_delivery')">{{ t('start') }}</button>
      <button v-if="delivery.can_retry" type="button" data-testid="retry-delivery" class="primary-btn" :disabled="!canRetry" @click="submit('retry_delivery')">{{ t('retry') }}</button>
    </div>
    <p v-if="!ready" class="mt-4 text-sm text-slate-500">{{ delivery.status === 'success' ? t('incomplete') : t('waiting') }}</p>
    <template v-else>
      <p class="mt-4 text-sm text-emerald-700 dark:text-emerald-300" data-testid="delivery-ready">{{ t('ready') }}</p>
      <AuthedVideo :key="master.artifact_id" :src="previewUrl" :label="t('load')" :loading-label="t('loading')" :error-label="t('previewFailed')" class="mt-3 max-h-[32rem] w-full rounded-xl bg-black" />
      <p class="mt-3 text-sm">{{ metadata }}</p>
      <p v-if="master.composition_mode === 'stream_copy' || master.composition_mode === 'normalized'" class="mt-1 text-xs text-slate-500">{{ t(master.composition_mode === 'stream_copy' ? 'sourceCopy' : 'normalized') }}</p>
      <div class="mt-4 flex flex-wrap gap-2">
        <button type="button" data-testid="download-master" class="primary-btn" :disabled="Boolean(downloading)" @click="download(master, 'master.mp4')">{{ downloading === master.artifact_id ? t('downloading') : t('master') }}</button>
        <button v-if="compressedUrl" type="button" data-testid="download-compressed" class="secondary-btn" :disabled="Boolean(downloading)" @click="download(delivery.compressed, 'compressed.mp4')">{{ downloading === delivery.compressed.artifact_id ? t('downloading') : t('compressed') }}</button>
        <button type="button" data-testid="download-package" class="secondary-btn" :disabled="Boolean(downloading)" @click="download(delivery.package, 'sources.zip')">{{ downloading === delivery.package.artifact_id ? t('downloading') : t('package') }}</button>
      </div>
      <p v-if="compressedUrl" class="mt-2 text-xs text-slate-500">{{ t('compressionNote') }}</p>
      <p v-if="downloadError" role="alert" class="mt-3 text-sm text-red-600 dark:text-red-400">{{ downloadError }}</p>
    </template>
    <div v-if="delivery.qc" class="mt-5 border-t border-slate-200 pt-4 dark:border-slate-700">
      <h4 class="text-sm font-semibold">{{ t('qc') }} · {{ t(delivery.qc.passed === true ? 'qcPassed' : delivery.qc.passed === false ? 'qcFailed' : 'qcUnknown') }}</h4>
      <ul class="mt-2 space-y-2 text-sm" data-testid="delivery-checks"><li v-for="(check, index) in checks" :key="`${check.code}-${index}`" class="flex items-start gap-2"><span class="flex-none" :class="check.passed === true ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-600 dark:text-red-400'">{{ t(check.passed === true ? 'qcPassed' : check.passed === false ? 'qcFailed' : 'qcUnknown') }}</span><span class="min-w-0 break-words">{{ check.summary }}</span></li></ul>
      <p class="mt-3 text-xs text-slate-500">{{ t('qcNote') }}</p>
    </div>
    <div v-if="warnings.length" class="notice mt-4"><h4 class="font-medium">{{ t('warnings') }}</h4><ul class="mt-1 space-y-1"><li v-for="(warning, index) in warnings" :key="index">{{ warning }}</li></ul></div>
  </section>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import request from '@/api/request'
import AuthedVideo from './AuthedVideo.vue'
import messages from './delivery-messages'
import { buildDeliveryAction, deliveryActionAllowed, deliveryAssetUrl, deliveryChecks, deliveryReady, deliveryWarnings, downloadFilename } from './delivery'

const props = defineProps({ delivery: { type: Object, required: true }, disabled: { type: Boolean, default: false }, demo: { type: Boolean, default: false } })
const emit = defineEmits(['action'])
const { t, te } = useI18n({ useScope: 'local', messages })
const actionError = ref(''), downloadError = ref(''), downloading = ref(''), submitted = ref(false)
const ready = computed(() => deliveryReady(props.delivery))
const master = computed(() => props.delivery.master || {})
const previewUrl = computed(() => deliveryAssetUrl(master.value, 'preview'))
const compressedUrl = computed(() => deliveryAssetUrl(props.delivery.compressed))
const checks = computed(() => deliveryChecks(props.delivery)), warnings = computed(() => deliveryWarnings(props.delivery))
const canStart = computed(() => deliveryActionAllowed(props.delivery, 'start_delivery', props.disabled))
const canRetry = computed(() => deliveryActionAllowed(props.delivery, 'retry_delivery', props.disabled))
const phaseLabel = computed(() => props.delivery.stage === 'complete' && !ready.value ? t('incomplete') : te(`phase.${props.delivery.stage}`) ? t(`phase.${props.delivery.stage}`) : t('phase.pending'))
const number = (value) => typeof value === 'number' && Number.isFinite(value) ? Math.round(value * 100) / 100 : '—'
const metadata = computed(() => t('metadata', { seconds: number(master.value.duration_sec), width: number(master.value.width), height: number(master.value.height), fps: number(master.value.fps) }))
let disposed = false, controller = null
const downloads = new Map()
watch(() => [props.delivery.plan_version, props.delivery.status, props.delivery.stage], () => { submitted.value = false; actionError.value = '' })
function submit(action) {
  try {
    const command = buildDeliveryAction(props.delivery, action, props.disabled)
    actionError.value = ''
    emit('action', { ...command, onSuccess: () => { submitted.value = true }, onError: (message) => { actionError.value = message } })
  } catch { actionError.value = t('unavailable') }
}
async function download(asset, fallback) {
  const url = deliveryAssetUrl(asset)
  if (!ready.value || !url || downloading.value) return
  downloading.value = asset.artifact_id
  downloadError.value = ''
  controller = new AbortController()
  try {
    const blob = await request.get(url.replace(/^\/api/, ''), { responseType: 'blob', timeout: 300000, signal: controller.signal })
    if (disposed) return
    const objectUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = downloadFilename(asset, fallback)
    document.body.appendChild(link)
    link.click()
    link.remove()
    downloads.set(objectUrl, setTimeout(() => { URL.revokeObjectURL(objectUrl); downloads.delete(objectUrl) }, 1000))
  } catch { if (!disposed) downloadError.value = t('downloadFailed') }
  finally { if (!disposed) downloading.value = ''; controller = null }
}
onUnmounted(() => {
  disposed = true
  controller?.abort()
  for (const [url, timer] of downloads) { clearTimeout(timer); URL.revokeObjectURL(url) }
  downloads.clear()
})
</script>

<style scoped>
.delivery-panel { @apply min-w-0 rounded-2xl border border-slate-200 bg-white p-5 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200; overflow-wrap: anywhere; }
.notice { @apply rounded-xl bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200; }
.error { @apply bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300; }
.primary-btn { @apply rounded-xl bg-blue-600 px-4 py-2 text-left text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply rounded-xl border border-slate-300 px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
</style>
