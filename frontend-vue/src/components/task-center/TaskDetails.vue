<template>
  <section class="task-detail space-y-4" role="region" :aria-label="t('children')" data-testid="task-details">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <h2 class="font-semibold text-lg">{{ detail?.item?.title || selection.id }}</h2>
        <p class="text-xs text-slate-500">{{ selection.id }}</p>
      </div>
      <button class="secondary-btn" type="button" @click="$emit('close')">{{ t('close') }}</button>
    </div>
    <p v-if="error" class="text-sm text-amber-700 dark:text-amber-300" role="status">{{ detail ? t('detailStale') : t('detailUnavailable') }}</p>
    <p v-if="!detail && !error" class="text-sm">{{ t('loading') }}</p>
    <template v-if="detail">
      <div class="flex flex-wrap items-center justify-between gap-3 text-sm">
        <span>{{ t('childTotal', { count: detail.total }) }}</span>
        <RouterLink v-if="route" class="text-blue-600 dark:text-blue-300 underline" :to="route">{{ t('open') }}</RouterLink>
      </div>
      <p v-if="!detail.children.length" class="text-sm text-slate-500">{{ t('noChildren') }}</p>
      <article v-for="child in detail.children" :key="child.id" class="rounded-lg border border-slate-200 p-3 space-y-1 dark:border-slate-700">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <h3 class="font-medium">{{ child.shot_id || label(child.node_key) }} <span v-if="child.shot_id" class="text-xs text-slate-500">{{ label(child.node_key) }}</span></h3>
          <span class="text-sm">{{ label(child.stage) }}</span>
        </div>
        <p v-if="child.wait_reason" class="text-sm text-slate-600 dark:text-slate-300">{{ t('wait.' + child.wait_reason) }}</p>
        <p v-if="child.depends_on?.length" class="text-sm">{{ t('dependencies', { ids: child.depends_on.join(' → ') }) }}</p>
        <p v-if="child.model_id" class="text-xs text-slate-500">{{ t('model', { model: child.model_id }) }}</p>
        <p v-if="child.attempt" class="text-xs text-slate-500">{{ t('attempt', { count: child.attempt }) }}</p>
        <p v-if="child.next_check_at" class="text-xs">{{ t('nextCheck', { time: time(child.next_check_at) }) }}</p>
        <p v-if="child.error_code" class="text-xs text-red-600 dark:text-red-300">{{ t('error', { code: child.error_code }) }}</p>
      </article>
      <div class="flex flex-wrap items-center gap-3 text-sm">
        <button class="secondary-btn" type="button" :disabled="page <= 1" @click="$emit('page', page - 1)">{{ t('before') }}</button>
        <span>{{ t('page', { page, total: pages }) }}</span>
        <button class="secondary-btn" type="button" :disabled="page >= pages" @click="$emit('page', page + 1)">{{ t('after') }}</button>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import messages from './messages'
import { pageCount, taskRoute } from './task-center'
const props = defineProps({ selection: { type: Object, required: true }, detail: Object, error: Boolean, page: { type: Number, default: 1 } })
defineEmits(['close', 'page'])
const { t, te } = useI18n({ useScope: 'local', messages })
const pages = computed(() => pageCount(props.detail?.total, props.detail?.per_page))
const route = computed(() => taskRoute(props.selection))
const label = (key) => key && te('stage.' + key) ? t('stage.' + key) : key || '—'
const time = (value) => new Date(value).toLocaleString()
</script>

<style scoped>
.task-detail { @apply rounded-xl border border-blue-200 bg-white p-5 text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200; min-width: 0; overflow-wrap: anywhere; }
.secondary-btn { @apply rounded-lg border border-slate-300 px-3 py-2 text-sm hover:bg-slate-50 disabled:opacity-40 dark:border-slate-600 dark:hover:bg-slate-800; }
</style>
