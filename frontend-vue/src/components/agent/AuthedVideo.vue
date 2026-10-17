<template>
  <video v-if="url" controls preload="metadata" :src="url" v-bind="$attrs" />
  <button
    v-else type="button"
    class="flex aspect-video w-full items-center justify-center gap-2 rounded-xl bg-slate-900 text-sm text-slate-200 hover:bg-slate-800 disabled:cursor-wait"
    :disabled="loading" @click="load"
  >
    <PhPlayCircle :size="22" />
    <span>{{ failed ? errorLabel : loading ? loadingLabel : label }}</span>
  </button>
</template>

<script setup>
// Owner-protected videos (e.g. an uploaded remix source) need the Bearer
// header, so they are fetched as a blob — only on request, since sources can
// be large.
import { onBeforeUnmount, ref } from 'vue'
import { PhPlayCircle } from '@phosphor-icons/vue'
import request from '@/api/request'

defineOptions({ inheritAttrs: false })
const props = defineProps({
  src: { type: String, required: true },
  label: { type: String, default: 'Load preview' },
  loadingLabel: { type: String, default: 'Loading…' },
  errorLabel: { type: String, default: 'Preview unavailable' },
})
const url = ref('')
const loading = ref(false)
const failed = ref(false)

async function load() {
  loading.value = true
  failed.value = false
  try {
    const blob = await request.get(props.src.replace(/^\/api/, ''), { responseType: 'blob', timeout: 300000 })
    url.value = URL.createObjectURL(blob)
  } catch {
    failed.value = true
  } finally {
    loading.value = false
  }
}
onBeforeUnmount(() => url.value && URL.revokeObjectURL(url.value))
</script>
