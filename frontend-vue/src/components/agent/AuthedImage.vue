<template>
  <img v-if="url" :src="url" :alt="alt" />
  <span v-else class="block h-full w-full animate-pulse bg-slate-200 dark:bg-slate-700" :class="{ 'bg-red-100 dark:bg-red-950/40 animate-none': failed }" />
</template>

<script>
// Uploaded attachments and research references are owner-protected, so a
// bare <img src> (which cannot send the Bearer header) fails when auth is on.
// Fetch through the authenticated client once per URL and reuse the blob URL.
const cache = new Map()
</script>

<script setup>
import { ref, watch } from 'vue'
import request from '@/api/request'

const props = defineProps({
  src: { type: String, required: true },
  alt: { type: String, default: '' },
})
const url = ref('')
const failed = ref(false)

function load(src) {
  if (!src.startsWith('/api/')) return Promise.resolve(src)
  if (!cache.has(src)) {
    const pending = request.get(src.slice(4), { responseType: 'blob' })
      .then((blob) => URL.createObjectURL(blob))
      .catch((error) => { cache.delete(src); throw error })
    cache.set(src, pending)
  }
  return cache.get(src)
}

watch(() => props.src, async (src) => {
  url.value = ''
  failed.value = false
  try {
    const value = await load(src)
    if (src === props.src) url.value = value
  } catch {
    failed.value = true
  }
}, { immediate: true })
</script>
