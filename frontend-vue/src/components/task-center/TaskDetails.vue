<template>
  <section class="task-detail" role="region" :aria-label="t('children')" data-testid="task-details">
    <header class="flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4 dark:border-slate-800">
      <div class="min-w-0">
        <p class="text-[11px] font-medium uppercase tracking-wide text-slate-400">{{ t('children') }}</p>
        <h2 class="mt-0.5 truncate text-base font-semibold text-slate-900 dark:text-white" :title="detail?.item?.title || selection.id">{{ detail?.item?.title || selection.id }}</h2>
        <p class="truncate font-mono text-[11px] text-slate-400">{{ selection.id }}</p>
      </div>
      <div class="flex flex-none items-center gap-1">
        <RouterLink v-if="route" class="icon-btn" :to="route" :aria-label="t('open')" :title="t('open')"><PhArrowSquareOut :size="16" /></RouterLink>
        <button class="icon-btn" type="button" :aria-label="t('close')" :title="t('close')" @click="$emit('close')"><PhX :size="16" /></button>
      </div>
    </header>
    <div class="px-5 py-4">
      <p v-if="error" class="mb-3 flex items-center gap-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950/40 dark:text-amber-200" role="status"><PhWarning :size="14" class="flex-none" />{{ detail ? t('detailStale') : t('detailUnavailable') }}</p>
      <p v-if="!detail && !error" class="flex items-center gap-2 text-sm text-slate-500"><PhCircleNotch :size="14" class="animate-spin" />{{ t('loading') }}</p>
      <template v-if="detail">
        <div class="mb-3 flex items-center justify-between text-xs text-slate-500">
          <span>{{ t('childTotal', { count: detail.total }) }}</span>
          <RouterLink v-if="route" class="font-medium text-blue-600 hover:underline dark:text-blue-300" :to="route">{{ t('open') }} →</RouterLink>
        </div>
        <p v-if="!detail.children.length" class="py-6 text-center text-sm text-slate-500">{{ t('noChildren') }}</p>
        <ol class="timeline">
          <li v-for="child in detail.children" :key="child.id" class="relative pl-6">
            <span class="node" :class="tone(child.state)" />
            <div class="flex flex-wrap items-baseline justify-between gap-x-2">
              <h3 class="text-sm font-medium text-slate-900 dark:text-slate-100">
                {{ child.shot_id || label(child.node_key) }}
                <span v-if="child.shot_id" class="ml-1 text-xs font-normal text-slate-500">{{ label(child.node_key) }}</span>
              </h3>
              <span class="text-xs" :class="textTone(child.state)">{{ label(child.stage) }}</span>
            </div>
            <p v-if="child.wait_reason" class="mt-0.5 text-xs text-slate-600 dark:text-slate-300">{{ t('wait.' + child.wait_reason) }}</p>
            <div class="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
              <span v-if="child.depends_on?.length">{{ t('dependencies', { ids: child.depends_on.join(' → ') }) }}</span>
              <span v-if="child.model_id">{{ t('model', { model: child.model_id }) }}</span>
              <span v-if="child.attempt">{{ t('attempt', { count: child.attempt }) }}</span>
              <span v-if="child.next_check_at">{{ t('nextCheck', { time: time(child.next_check_at) }) }}</span>
            </div>
            <p v-if="child.error_code" class="mt-1 inline-block rounded bg-red-50 px-1.5 py-0.5 font-mono text-[11px] text-red-700 dark:bg-red-950/50 dark:text-red-300">{{ t('error', { code: child.error_code }) }}</p>
          </li>
        </ol>
        <div v-if="pages > 1" class="mt-4 flex items-center justify-center gap-3 text-xs text-slate-500">
          <button class="icon-btn" type="button" :disabled="page <= 1" :aria-label="t('before')" @click="$emit('page', page - 1)"><PhCaretLeft :size="16" /></button>
          <span class="tabular-nums">{{ t('page', { page, total: pages }) }}</span>
          <button class="icon-btn" type="button" :disabled="page >= pages" :aria-label="t('after')" @click="$emit('page', page + 1)"><PhCaretRight :size="16" /></button>
        </div>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhArrowSquareOut, PhCaretLeft, PhCaretRight, PhCircleNotch, PhWarning, PhX } from '@phosphor-icons/vue'
import messages from './messages'
import { pageCount, taskRoute } from './task-center'
const props = defineProps({ selection: { type: Object, required: true }, detail: Object, error: Boolean, page: { type: Number, default: 1 } })
defineEmits(['close', 'page'])
const { t, te } = useI18n({ useScope: 'local', messages })
const pages = computed(() => pageCount(props.detail?.total, props.detail?.per_page))
const route = computed(() => taskRoute(props.selection))
const label = (key) => key && te('stage.' + key) ? t('stage.' + key) : key || '—'
const time = (value) => new Date(value).toLocaleString()
const tone = (state) => ({ queued: 'bg-sky-500', running: 'bg-blue-600 ring-4 ring-blue-500/20', waiting: 'bg-amber-500', attention: 'bg-red-500', completed: 'bg-emerald-500', cancelled: 'bg-slate-400' }[state] || 'bg-slate-300')
const textTone = (state) => ({ attention: 'font-medium text-red-600 dark:text-red-400', completed: 'text-emerald-700 dark:text-emerald-400', running: 'text-blue-700 dark:text-blue-300' }[state] || 'text-slate-500')
</script>

<style scoped>
.task-detail { @apply overflow-hidden rounded-xl border border-slate-200 bg-white text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200; min-width: 0; overflow-wrap: anywhere; }
.timeline { @apply relative space-y-4; }
.timeline::before { content: ''; @apply absolute bottom-1 left-[5px] top-1 w-px bg-slate-200 dark:bg-slate-700; }
.node { @apply absolute left-0 top-1.5 h-[11px] w-[11px] rounded-full border-2 border-white dark:border-slate-900; }
.icon-btn { @apply inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900 disabled:opacity-40 dark:hover:bg-slate-800 dark:hover:text-white; }
</style>
