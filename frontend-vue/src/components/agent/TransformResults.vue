<template>
  <section class="min-w-0 rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900" data-testid="transform-results">
    <h3 class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ t('results') }}</h3>
    <p v-if="mock" class="mt-2 text-xs text-amber-700 dark:text-amber-400">{{ t('mock') }}</p>
    <div v-for="item in results" :key="item.artifact_id" class="mt-3">
      <AuthedVideo v-if="assetUrl(item, 'preview')" :key="item.artifact_id" :src="assetUrl(item, 'preview')" :label="t('load')" :loading-label="t('loading')" :error-label="t('previewFailed')" class="max-h-96 w-full bg-black" />
      <button v-if="assetUrl(item)" type="button" class="mt-2 text-sm text-blue-600 underline disabled:opacity-50" :disabled="Boolean(downloading)" @click="download(item)">{{ downloading === item.artifact_id ? t('downloading') : t('download') }}</button>
    </div>
    <p v-if="error" role="alert" class="mt-2 text-sm text-red-600">{{ error }}</p>
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import request from '@/api/request'
import AuthedVideo from './AuthedVideo.vue'
import { deliveryAssetUrl as assetUrl, downloadFilename } from './delivery'
import messages from './transform-messages'
defineProps({ results: { type: Array, default: () => [] }, mock: { type: Boolean, default: false } })
const { t } = useI18n({ useScope: 'local', messages })
const downloading = ref(''), error = ref('')
const urls = new Map()
let disposed = false, controller = null
async function download(item) {
  const url = assetUrl(item)
  if (!url || downloading.value) return
  downloading.value = item.artifact_id
  error.value = ''
  controller = new AbortController()
  try {
    const blob = await request.get(url.replace(/^\/api/, ''), { responseType: 'blob', timeout: 300000, signal: controller.signal })
    if (disposed) return
    const objectUrl = URL.createObjectURL(blob), link = document.createElement('a')
    link.href = objectUrl
    link.download = downloadFilename(item, 'cinecrew-video.mp4')
    document.body.appendChild(link)
    link.click()
    link.remove()
    urls.set(objectUrl, setTimeout(() => { URL.revokeObjectURL(objectUrl); urls.delete(objectUrl) }, 1000))
  } catch { if (!disposed) error.value = t('downloadFailed') }
  finally { if (!disposed) downloading.value = ''; controller = null }
}
onBeforeUnmount(() => {
  disposed = true
  controller?.abort()
  for (const [url, timer] of urls) { clearTimeout(timer); URL.revokeObjectURL(url) }
  urls.clear()
})
</script>
