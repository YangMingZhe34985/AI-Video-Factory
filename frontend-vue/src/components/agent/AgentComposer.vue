<template>
  <form
    class="composer"
    :class="{ 'is-dragging': dragging }"
    @submit.prevent="submit"
    @dragover.prevent="dragging = true"
    @dragleave.self="dragging = false"
    @drop.prevent="onDrop"
  >
    <label for="agent-text" class="sr-only">{{ t('composerTitle') }}</label>
    <textarea
      id="agent-text"
      ref="textEl"
      v-model="text"
      class="composer-text"
      rows="3"
      maxlength="8000"
      :placeholder="t('placeholder')"
      @keydown.enter.ctrl.prevent="submit"
      @keydown.enter.meta.prevent="submit"
      @paste="onPaste"
      @input="autosize"
    />

    <ul v-if="items.length" class="flex flex-wrap gap-2 px-4 pb-3" :aria-label="t('attach')">
      <li v-for="item in items" :key="item.key" class="chip" :class="{ 'chip-error': item.error }">
        <span class="chip-thumb">
          <img v-if="item.kind === 'image'" :src="item.preview" alt="" />
          <span v-else class="flex h-full w-full items-center justify-center bg-slate-800 text-white"><PhFilmStrip :size="16" /></span>
          <span v-if="item.progress !== null && !item.done && !item.error" class="chip-progress" :style="{ width: `${item.progress}%` }" />
        </span>
        <span class="min-w-0">
          <span class="block max-w-[11rem] truncate text-xs font-medium">{{ item.name }}</span>
          <span class="block text-[11px] text-slate-500 dark:text-slate-400">
            <template v-if="item.error">{{ item.error }}</template>
            <template v-else-if="!item.done">{{ t('uploading', { percent: item.progress === null ? '' : `${item.progress}%` }) }}</template>
            <template v-else>{{ item.meta }}</template>
          </span>
        </span>
        <button type="button" class="chip-remove" :aria-label="`${t('remove')} ${item.name}`" @click="remove(item)"><PhX :size="12" weight="bold" /></button>
      </li>
    </ul>

    <div class="composer-bar">
      <input ref="fileEl" type="file" class="hidden" multiple :accept="ACCEPT" @change="onPick" />
      <button type="button" class="ghost-btn" :disabled="busy || items.length >= maxAttachments" @click="fileEl.click()">
        <PhPaperclip :size="16" /> <span>{{ t('attach') }}</span>
      </button>
      <span class="hidden min-w-0 truncate text-xs text-slate-400 xl:inline">{{ t('attachHint') }}</span>
      <span class="flex-1" />
      <button type="button" class="ghost-btn" :aria-expanded="showAdvanced" @click="showAdvanced = !showAdvanced">
        <PhSlidersHorizontal :size="16" /> <span class="tabular-nums">{{ budget }} cr</span>
      </button>
      <button type="submit" class="send-btn" :disabled="!canSubmit" :title="blockedReason">
        <span>{{ busy ? t('starting') : t('start') }}</span>
        <PhArrowRight :size="16" weight="bold" />
      </button>
    </div>

    <div v-if="showAdvanced" class="advanced">
      <label for="agent-budget" class="text-sm font-medium">{{ t('budget') }}</label>
      <input id="agent-budget" v-model.number="budget" type="number" min="1" :max="maxBudget" step="1" class="budget-input" />
      <p class="text-xs text-slate-500 dark:text-slate-400">{{ t('budgetHint') }}</p>
    </div>

    <p v-if="hint" class="px-4 pb-3 text-xs text-amber-700 dark:text-amber-400" role="status">{{ hint }}</p>
    <div v-if="dragging" class="drop-overlay">{{ t('dropHere') }}</div>
  </form>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhArrowRight, PhFilmStrip, PhPaperclip, PhSlidersHorizontal, PhX } from '@phosphor-icons/vue'
import { uploadAgentAttachment } from '@/api/agent'
import messages from './messages'

const props = defineProps({
  busy: { type: Boolean, default: false },
  maxAttachments: { type: Number, default: 8 },
  maxBudget: { type: Number, default: 500 },
})
const emit = defineEmits(['submit'])
const { t } = useI18n({ useScope: 'local', messages })

const ACCEPT = '.jpg,.jpeg,.png,.webp,.mp4,.mov,.mkv,.webm'
const VIDEO_EXT = /\.(mp4|mov|mkv|webm)$/i
const text = ref('')
const budget = ref(100)
const items = ref([])
const showAdvanced = ref(false)
const dragging = ref(false)
const hint = ref('')
const textEl = ref(null)
const fileEl = ref(null)
let counter = 0

const textOk = computed(() => text.value.trim().length >= 2)
const uploadsDone = computed(() => items.value.every((item) => item.done || item.error))
const canSubmit = computed(() => textOk.value && uploadsDone.value && !props.busy && budget.value > 0)
const blockedReason = computed(() => (textOk.value ? '' : t('textRequired')))

function describe(attachment) {
  const size = attachment.width && attachment.height ? `${attachment.width}×${attachment.height}` : ''
  const duration = attachment.duration ? `${Math.round(attachment.duration)}s` : ''
  return [size, duration].filter(Boolean).join(' · ')
}

async function addFiles(files) {
  hint.value = ''
  for (const file of files) {
    if (items.value.length >= props.maxAttachments) {
      hint.value = t('tooManyAttachments', { max: props.maxAttachments })
      break
    }
    const isVideo = VIDEO_EXT.test(file.name) || file.type.startsWith('video/')
    const item = {
      key: `att-${++counter}`, name: file.name, kind: isVideo ? 'video' : 'image',
      preview: isVideo ? '' : URL.createObjectURL(file), progress: null, done: false, error: '', attachment: null, meta: '',
    }
    items.value.push(item)
    const live = items.value[items.value.length - 1]
    try {
      const attachment = await uploadAgentAttachment(file, (percent) => { live.progress = percent })
      if (!items.value.includes(live)) continue
      live.attachment = attachment
      live.kind = attachment.kind
      live.meta = describe(attachment)
      live.done = true
    } catch (err) {
      live.error = err.response?.data?.error?.message || t('uploadFailed')
    }
  }
}

function onPick(event) {
  addFiles([...(event.target.files || [])])
  event.target.value = ''
}
function onDrop(event) {
  dragging.value = false
  addFiles([...(event.dataTransfer?.files || [])])
}
function onPaste(event) {
  const files = [...(event.clipboardData?.files || [])].filter((file) => file.type.startsWith('image/'))
  if (files.length) addFiles(files)
}
function remove(item) {
  if (item.preview) URL.revokeObjectURL(item.preview)
  items.value = items.value.filter((entry) => entry !== item)
}
function autosize() {
  const el = textEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 320)}px`
}
function submit() {
  if (!textOk.value) { hint.value = t('textRequired'); return }
  if (!canSubmit.value) return
  emit('submit', {
    text: text.value.trim(),
    attachment_ids: items.value.filter((item) => item.done).map((item) => item.attachment.attachment_id),
    budget_limit: budget.value,
  })
}
function fill(value) {
  text.value = value
  nextTick(() => { autosize(); textEl.value?.focus() })
}
function reset() {
  items.value.forEach((item) => item.preview && URL.revokeObjectURL(item.preview))
  items.value = []
  text.value = ''
  hint.value = ''
  nextTick(autosize)
}
onBeforeUnmount(() => items.value.forEach((item) => item.preview && URL.revokeObjectURL(item.preview)))
defineExpose({ fill, reset })
</script>

<style scoped>
.composer { @apply relative rounded-2xl border border-slate-200 bg-white shadow-[0_1px_2px_rgba(15,23,42,0.04),0_12px_32px_-12px_rgba(15,23,42,0.12)] transition-colors dark:border-slate-700 dark:bg-slate-900; }
.composer:focus-within { @apply border-blue-400 dark:border-blue-500; }
.composer.is-dragging { @apply border-blue-500 bg-blue-50/40 dark:bg-blue-950/30; }
.composer-text { @apply block w-full resize-none bg-transparent px-5 pb-3 pt-5 text-[17px] leading-relaxed text-slate-900 placeholder:text-slate-400 focus:outline-none dark:text-slate-100 dark:placeholder:text-slate-500; min-height: 6.5rem; }
.composer-bar { @apply flex items-center gap-2 border-t border-slate-100 px-3 py-2.5 dark:border-slate-800; }
.ghost-btn { @apply inline-flex flex-none items-center gap-1.5 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-sm text-slate-600 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40 dark:text-slate-300 dark:hover:bg-slate-800; }
.send-btn { @apply inline-flex flex-none items-center gap-1.5 whitespace-nowrap rounded-xl bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-600 disabled:cursor-not-allowed disabled:bg-slate-300 dark:bg-blue-600 dark:hover:bg-blue-500 dark:disabled:bg-slate-700 dark:disabled:text-slate-400; }
.chip { @apply relative flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 py-1.5 pl-1.5 pr-7 dark:border-slate-700 dark:bg-slate-800; }
.chip-error { @apply border-red-300 bg-red-50 dark:border-red-800 dark:bg-red-950/40; }
.chip-thumb { @apply relative h-10 w-10 flex-none overflow-hidden rounded-lg bg-slate-200 dark:bg-slate-700; }
.chip-thumb img { @apply h-full w-full object-cover; }
.chip-progress { @apply absolute bottom-0 left-0 h-1 bg-blue-500 transition-all; }
.chip-remove { @apply absolute right-1.5 top-1.5 rounded-full p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700 dark:hover:bg-slate-700 dark:hover:text-slate-200; }
.advanced { @apply grid gap-1.5 border-t border-slate-100 px-5 py-3 dark:border-slate-800; }
.budget-input { @apply w-40 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-950; }
.drop-overlay { @apply pointer-events-none absolute inset-0 flex items-center justify-center rounded-2xl border-2 border-dashed border-blue-400 bg-white/70 text-sm font-medium text-blue-700 dark:bg-slate-900/70 dark:text-blue-300; }
</style>
