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
import { onBeforeUnmount, reactive, toRefs, watch } from 'vue'
import { PhPlayCircle } from '@phosphor-icons/vue'
import request from '@/api/request'
import { createPreviewLoader } from './media-preview'

defineOptions({ inheritAttrs: false })
const props = defineProps({
  src: { type: String, required: true },
  label: { type: String, default: 'Load preview' },
  loadingLabel: { type: String, default: 'Loading…' },
  errorLabel: { type: String, default: 'Preview unavailable' },
})
const state = reactive({ url: '', loading: false, failed: false })
const { url, loading, failed } = toRefs(state)
const preview = createPreviewLoader(
  (src, signal) => request.get(src.replace(/^\/api/, ''), { responseType: 'blob', timeout: 300000, signal }),
  (values) => Object.assign(state, values),
)
const load = () => preview.load(props.src)
watch(() => props.src, () => preview.reset())
onBeforeUnmount(() => preview.dispose())
</script>
