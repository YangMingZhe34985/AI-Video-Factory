<template>
  <section class="delivery-panel" data-testid="delivery-panel" :aria-label="t('label')">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 items-start gap-3">
        <span class="icon-tile"><PhFilmReel :size="18" /></span>
        <div class="min-w-0"><h3 class="text-[15px] font-semibold text-slate-900 dark:text-white">{{ t('title') }}</h3><p class="mt-0.5 text-xs text-slate-500">{{ t('version', { version: delivery.plan_version ?? '—' }) }}</p></div>
      </div>
      <span class="status-pill" :class="phaseTone" role="status"><PhCircleNotch v-if="delivery.status === 'editing'" :size="12" class="animate-spin" /><PhCheckCircle v-else-if="ready" :size="13" weight="fill" /><span v-else class="h-1.5 w-1.5 rounded-full bg-current" />{{ phaseLabel }}</span>
    </header>
    <p v-if="!delivery.enabled" class="notice mt-4">{{ t('disabled') }}</p>
    <p class="mt-3 text-xs text-slate-500">{{ t('localCost') }}</p>
    <p v-if="demo" class="mt-2 text-xs text-amber-700 dark:text-amber-400">{{ t('mock') }}</p>
    <p v-if="keptShots.length" class="notice mt-4" data-testid="delivery-continuity-warning">{{ t('keptWarning', { shots: keptShots.join(', ') }) }}</p>
    <div v-if="delivery.error" role="alert" class="notice error mt-4"><p class="font-medium">{{ t('error') }}</p><p class="mt-1">{{ delivery.error.message }} <span class="text-xs">{{ delivery.error.code }}</span></p></div>
    <p v-if="actionError" role="alert" class="mt-3 text-sm text-red-600 dark:text-red-400">{{ actionError }}</p>
    <p v-if="submitted" role="status" class="mt-3 text-xs text-slate-500">{{ t('submitted') }}</p>
    <div v-if="delivery.can_start || delivery.can_retry" class="mt-4 flex flex-wrap gap-2">
      <button v-if="delivery.can_start" type="button" data-testid="start-delivery" class="primary-btn" :disabled="!canStart" @click="submit('start_delivery')">{{ t('start') }}</button>
      <button v-if="delivery.can_retry" type="button" data-testid="retry-delivery" class="primary-btn" :disabled="!canRetry" @click="submit('retry_delivery')">{{ t('retry') }}</button>
    </div>
    <p v-if="!ready" class="mt-4 text-sm text-slate-500">{{ delivery.status === 'success' ? t('incomplete') : t('waiting') }}</p>
    <template v-else>
      <p class="notice notice-emerald mt-4" data-testid="delivery-ready"><PhCheckCircle :size="16" weight="fill" class="mt-0.5 flex-none" />{{ t('ready') }}</p>
      <div class="mt-4 overflow-hidden rounded-xl border border-slate-200 dark:border-slate-700">
        <AuthedVideo :key="master.artifact_id" :src="previewUrl" :label="t('load')" :loading-label="t('loading')" :error-label="t('previewFailed')" class="max-h-[32rem] w-full bg-black" />
        <div class="flex flex-wrap items-center justify-between gap-2 bg-slate-50 px-4 py-2.5 dark:bg-slate-800/60">
          <p class="text-sm font-medium tabular-nums text-slate-800 dark:text-slate-100">{{ metadata }}</p>
          <p v-if="master.composition_mode === 'stream_copy' || master.composition_mode === 'normalized'" class="text-xs text-slate-500">{{ t(master.composition_mode === 'stream_copy' ? 'sourceCopy' : 'normalized') }}</p>
        </div>
      </div>
      <div class="mt-4 flex flex-wrap gap-2">
        <button type="button" data-testid="download-master" class="primary-btn" :disabled="Boolean(downloading)" @click="download(master, 'master.mp4')"><PhDownloadSimple :size="15" />{{ downloading === master.artifact_id ? t('downloading') : t('master') }}</button>
        <button v-if="compressedUrl" type="button" data-testid="download-compressed" class="secondary-btn" :disabled="Boolean(downloading)" @click="download(delivery.compressed, 'compressed.mp4')"><PhDownloadSimple :size="15" />{{ downloading === delivery.compressed.artifact_id ? t('downloading') : t('compressed') }}</button>
        <button type="button" data-testid="download-package" class="secondary-btn" :disabled="Boolean(downloading)" @click="download(delivery.package, 'sources.zip')"><PhFileZip :size="15" />{{ downloading === delivery.package.artifact_id ? t('downloading') : t('package') }}</button>
      </div>
      <p v-if="compressedUrl" class="mt-2 text-xs text-slate-500">{{ t('compressionNote') }}</p>
      <p v-if="downloadError" role="alert" class="mt-3 text-sm text-red-600 dark:text-red-400">{{ downloadError }}</p>
    </template>
    <details v-if="delivery.qc" class="group mt-5 rounded-xl border border-slate-200 dark:border-slate-700" :open="delivery.qc.passed !== true">
      <summary class="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm">
        <PhCaretDown :size="14" class="text-slate-400 transition-transform group-open:rotate-180" />
        <span class="font-semibold text-slate-900 dark:text-white">{{ t('qc') }}</span>
        <span class="pill" :class="delivery.qc.passed === true ? 'pill-emerald' : delivery.qc.passed === false ? 'pill-red' : 'pill-slate'">{{ t(delivery.qc.passed === true ? 'qcPassed' : delivery.qc.passed === false ? 'qcFailed' : 'qcUnknown') }}</span>
        <span class="ml-auto text-xs tabular-nums text-slate-500">{{ checks.filter((check) => check.passed === true).length }} / {{ checks.length }}</span>
      </summary>
      <ul class="grid gap-x-4 gap-y-1.5 border-t border-slate-100 px-4 py-3 text-xs sm:grid-cols-2 dark:border-slate-800" data-testid="delivery-checks"><li v-for="(check, index) in checks" :key="`${check.code}-${index}`" class="flex items-start gap-1.5"><PhCheckCircle v-if="check.passed === true" :size="14" weight="fill" class="mt-px flex-none text-emerald-600" /><PhXCircle v-else :size="14" weight="fill" class="mt-px flex-none text-red-600" /><span class="min-w-0 break-words text-slate-700 dark:text-slate-300">{{ check.summary }}</span></li></ul>
      <p class="border-t border-slate-100 px-4 py-2.5 text-[11px] text-slate-500 dark:border-slate-800">{{ t('qcNote') }}</p>
    </details>
    <div v-if="warnings.length" class="notice mt-4 flex-col"><h4 class="font-medium">{{ t('warnings') }}</h4><ul class="mt-1 space-y-1"><li v-for="(warning, index) in warnings" :key="index">{{ warning }}</li></ul></div>
  </section>
</template>

<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import request from '@/api/request'
import AuthedVideo from './AuthedVideo.vue'
import { PhCaretDown, PhCheckCircle, PhCircleNotch, PhDownloadSimple, PhFileZip, PhFilmReel, PhXCircle } from '@phosphor-icons/vue'
import messages from './delivery-messages'
import { buildDeliveryAction, deliveryActionAllowed, deliveryAssetUrl, deliveryChecks, deliveryKeptShots, deliveryReady, deliveryWarnings, downloadFilename } from './delivery'

const props = defineProps({ delivery: { type: Object, required: true }, keptDownstream: { type: Array, default: () => [] }, disabled: { type: Boolean, default: false }, demo: { type: Boolean, default: false } })
const emit = defineEmits(['action'])
const { t, te } = useI18n({ useScope: 'local', messages })
const actionError = ref(''), downloadError = ref(''), downloading = ref(''), submitted = ref(false)
const ready = computed(() => deliveryReady(props.delivery))
const keptShots = computed(() => deliveryKeptShots(props.keptDownstream))
const master = computed(() => props.delivery.master || {})
const previewUrl = computed(() => deliveryAssetUrl(master.value, 'preview'))
const compressedUrl = computed(() => deliveryAssetUrl(props.delivery.compressed))
const checks = computed(() => deliveryChecks(props.delivery))
// Composition warnings arrive as English server text; show known ones in the UI language.
// Mock slates differ from real sources only by construction, so the "formats differed"
// note is misleading next to the Mock note and is dropped there.
const KNOWN_WARNINGS = [['Source formats differed', 'warnNormalized'], ['Mock demonstration: placeholder', 'warnMockSlates']]
const warnings = computed(() => {
  const raw = deliveryWarnings(props.delivery)
  const mock = raw.some((warning) => warning.startsWith('Mock demonstration: placeholder'))
  return [...new Set(raw.filter((warning) => !(mock && warning.startsWith('Source formats differed')))
    .map((warning) => { const known = KNOWN_WARNINGS.find(([prefix]) => warning.startsWith(prefix)); return known ? t(known[1]) : warning }))]
})
const phaseTone = computed(() => ready.value ? 'tone-emerald' : props.delivery.status === 'delivery_attention' ? 'tone-red' : props.delivery.status === 'editing' ? 'tone-blue' : 'tone-slate')
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
.icon-tile { @apply flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400; }
.status-pill { @apply inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium; }
.tone-blue { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.tone-red { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.tone-emerald { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.tone-slate { @apply bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.pill { @apply inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium; }
.pill-emerald { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.pill-red { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.pill-slate { @apply bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.notice { @apply flex gap-2 rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200; }
.notice-emerald { @apply bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200; }
.error { @apply flex-col bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-300; }
.primary-btn { @apply inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply inline-flex items-center gap-1.5 rounded-xl border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
</style>
