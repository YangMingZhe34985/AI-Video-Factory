<template>
  <section class="card">
    <header class="flex flex-wrap items-center gap-2">
      <PhSparkle :size="16" class="text-blue-600 dark:text-blue-400" />
      <h3 class="card-title">{{ t('understanding') }}</h3>
      <span class="tag tag-strong">{{ t(spec.deliverable === 'image' ? 'deliverableImage' : 'deliverableVideo') }}</span>
      <span class="tag">{{ t(`recipe_${spec.recipe_hint}`) }}</span>
      <span v-if="spec.target_duration_sec" class="tag tabular-nums">{{ t('duration', { sec: spec.target_duration_sec }) }}</span>
      <span v-if="spec.aspect_ratio" class="tag">{{ t('aspect', { ratio: spec.aspect_ratio }) }}</span>
      <span v-if="spec.deliverable === 'image' && spec.output_count > 1" class="tag">{{ t('outputCount', { count: spec.output_count }) }}</span>
    </header>

    <p class="mt-3 text-[15px] leading-relaxed text-slate-800 dark:text-slate-200">{{ spec.summary }}</p>

    <div v-if="spec.attachments?.length" class="mt-4">
      <h4 class="section-label">{{ t('attachmentUse') }}</h4>
      <ul class="mt-2 grid gap-2 sm:grid-cols-2">
        <li v-for="use in spec.attachments" :key="use.attachment_id" class="flex gap-3 rounded-xl bg-slate-50 p-2 dark:bg-slate-800/60">
          <span class="thumb">
            <AuthedImage v-if="thumb(use.attachment_id)?.kind === 'image'" :src="thumb(use.attachment_id).preview_url" class="h-full w-full object-cover" />
            <span v-else class="flex h-full w-full items-center justify-center bg-slate-800 text-white"><PhFilmStrip v-if="use.kind === 'video'" :size="18" /><PhWaveform v-else-if="use.kind === 'audio'" :size="18" /><PhFileText v-else :size="18" /></span>
          </span>
          <span class="min-w-0">
            <span class="role" :class="use.role === 'unused' ? 'role-muted' : ''">{{ t(`role_${use.role}`) }}</span>
            <span class="mt-1 block text-xs leading-snug text-slate-600 dark:text-slate-300">{{ use.description }}</span>
            <span v-if="use.reason" class="mt-0.5 block text-[11px] leading-snug text-slate-400">{{ use.reason }}</span>
          </span>
        </li>
      </ul>
    </div>

    <dl v-if="spec.subjects?.length || constraintRows.length" class="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[7rem_1fr]">
      <template v-if="spec.subjects?.length">
        <dt class="section-label pt-0.5">{{ t('subjects') }}</dt>
        <dd class="flex flex-wrap gap-1.5">
          <span v-for="subject in spec.subjects" :key="subject.name" class="tag" :title="subject.description">
            {{ subject.name }}<PhMagnifyingGlass v-if="subject.source === 'needs_research'" :size="11" class="ml-1" />
          </span>
        </dd>
      </template>
      <template v-for="row in constraintRows" :key="row.label">
        <dt class="section-label pt-0.5">{{ t(row.label) }}</dt>
        <dd class="text-slate-700 dark:text-slate-300">{{ row.value }}</dd>
      </template>
    </dl>

    <div v-if="assumptions.length" class="assumptions">
      <h4 class="flex items-center gap-1.5 text-sm font-semibold text-amber-800 dark:text-amber-300"><PhLightbulb :size="15" />{{ t('assumptions') }}</h4>
      <p class="mt-0.5 text-xs text-amber-700/80 dark:text-amber-300/70">{{ t('assumptionsHint') }}</p>
      <ul class="mt-2 list-disc space-y-1 pl-5 text-sm text-amber-900 dark:text-amber-200">
        <li v-for="item in assumptions" :key="item">{{ item }}</li>
      </ul>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhFileText, PhFilmStrip, PhLightbulb, PhMagnifyingGlass, PhSparkle, PhWaveform } from '@phosphor-icons/vue'
import AuthedImage from './AuthedImage.vue'
import messages from './messages'

const props = defineProps({
  spec: { type: Object, required: true },
  attachments: { type: Array, default: () => [] },
  assumptions: { type: Array, default: () => [] },
})
const { t } = useI18n({ useScope: 'local', messages })

const thumb = (id) => props.attachments.find((item) => item.attachment_id === id)
const constraintRows = computed(() => {
  const c = props.spec.constraints || {}
  const rows = [
    ['style', c.style],
    ['mustInclude', c.must_include?.join('、')],
    ['mustAvoid', c.must_avoid?.join('、')],
    ['modelPrefs', c.model_preferences?.join('、')],
    ['modelExclusions', c.model_exclusions?.join('、')],
    ['researchNeeds', props.spec.research_needs?.map((item) => item.query).join('、')],
  ]
  return rows.filter(([, value]) => value).map(([label, value]) => ({ label, value }))
})
</script>

<style scoped>
.card { @apply rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900; }
.card-title { @apply mr-1 text-sm font-semibold text-slate-900 dark:text-slate-100; }
.tag { @apply inline-flex items-center rounded-md border border-slate-200 px-2 py-0.5 text-xs text-slate-600 dark:border-slate-700 dark:text-slate-300; }
.tag-strong { @apply border-slate-900 bg-slate-900 text-white dark:border-slate-200 dark:bg-slate-200 dark:text-slate-900; }
.section-label { @apply text-xs font-medium uppercase tracking-wide text-slate-400; }
.thumb { @apply h-14 w-14 flex-none overflow-hidden rounded-lg bg-slate-200 dark:bg-slate-700; }
.thumb img { @apply h-full w-full object-cover; }
.role { @apply inline-block rounded bg-blue-600 px-1.5 py-0.5 text-[11px] font-semibold text-white; }
.role-muted { @apply bg-slate-400; }
.assumptions { @apply mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 dark:border-amber-900/60 dark:bg-amber-950/30; }
</style>
