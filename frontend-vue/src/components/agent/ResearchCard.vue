<template>
  <section class="card">
    <header class="flex flex-wrap items-center gap-2">
      <PhMagnifyingGlass :size="16" class="text-blue-600 dark:text-blue-400" />
      <h3 class="mr-1 text-sm font-semibold text-slate-900 dark:text-slate-100">{{ t('research') }}</h3>
      <span v-if="dossier.stats" class="text-xs tabular-nums text-slate-500 dark:text-slate-400">
        {{ t('researchStats', {
          searches: (dossier.stats.web_searches || 0) + (dossier.stats.image_searches || 0),
          pages: dossier.stats.pages_fetched || 0,
          images: dossier.stats.references_downloaded || 0,
        }) }}
      </span>
    </header>
    <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ t('researchHint') }}</p>

    <ul v-if="dossier.warnings?.length" class="mt-3 space-y-1 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/30 dark:text-amber-200">
      <li v-for="warning in dossier.warnings" :key="warning" class="flex gap-1.5"><PhWarning :size="14" class="mt-0.5 flex-none" />{{ warning }}</li>
    </ul>

    <!-- visual entities -->
    <article v-for="entity in dossier.entities || []" :key="entity.entity_id" class="mt-5">
      <div class="flex flex-wrap items-baseline gap-2">
        <h4 class="text-[15px] font-semibold text-slate-900 dark:text-slate-100">{{ entity.name }}</h4>
        <span v-if="!entity.selected_candidate_id && entity.candidates?.length" class="text-xs text-blue-600 dark:text-blue-400">{{ t('awaitingChoice') }}</span>
      </div>
      <p v-if="entity.description" class="mt-0.5 text-sm text-slate-600 dark:text-slate-300">{{ entity.description }}</p>
      <div v-if="entity.consensus_traits?.length" class="mt-2 flex flex-wrap items-center gap-1.5">
        <span class="text-[11px] font-medium uppercase tracking-wide text-slate-400">{{ t('consensus') }}</span>
        <span v-for="trait in entity.consensus_traits" :key="trait" class="trait">{{ trait }}</span>
      </div>
      <div class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <figure
          v-for="(candidate, index) in entity.candidates || []" :key="candidate.candidate_id"
          class="candidate" :class="{ 'candidate-selected': candidate.candidate_id === entity.selected_candidate_id }"
        >
          <span class="relative block">
            <AuthedImage :src="`/api/artifacts/${candidate.reference_id}/preview`" :alt="`${entity.name} ${index + 1}`" class="block aspect-square w-full rounded-lg object-cover" />
            <span v-if="candidate.candidate_id === entity.selected_candidate_id" class="badge-selected"><PhCheck :size="11" weight="bold" />{{ t('selected') }}</span>
            <span v-else-if="candidate.candidate_id === entity.recommended_candidate_id" class="badge-recommended">{{ t('recommended') }}</span>
          </span>
          <figcaption class="mt-1.5 space-y-1">
            <span class="flex items-center justify-between text-xs text-slate-600 dark:text-slate-300">
              <span>{{ t('candidateN', { n: index + 1 }) }}</span>
              <span v-if="candidate.popularity_hint" class="text-[11px] text-slate-400">{{ t(`popularity_${candidate.popularity_hint}`) }}</span>
            </span>
            <span v-if="candidate.traits?.length" class="block text-[11px] leading-snug text-slate-500 dark:text-slate-400">{{ candidate.traits.slice(0, 4).join('、') }}</span>
            <SourceLink v-if="sourceById[candidate.source_id]" :source="sourceById[candidate.source_id]" compact />
          </figcaption>
        </figure>
      </div>
    </article>

    <!-- topics -->
    <article v-for="topic in dossier.topics || []" :key="topic.topic_id" class="mt-5 rounded-xl bg-slate-50 p-4 dark:bg-slate-800/60">
      <h4 class="text-sm font-semibold text-slate-900 dark:text-slate-100">{{ topic.query }}</h4>
      <p class="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-slate-300">{{ topic.summary }}</p>
      <ul v-if="topic.key_facts?.length" class="mt-2 space-y-1 text-sm text-slate-700 dark:text-slate-300">
        <li v-for="(fact, index) in topic.key_facts" :key="index" class="flex gap-2">
          <span class="text-slate-400">·</span>
          <span>{{ fact.fact }}
            <sup v-for="id in fact.source_ids" :key="id" class="ml-0.5 text-[10px] font-semibold text-blue-600 dark:text-blue-400">[{{ sourceIndex[id] }}]</sup>
          </span>
        </li>
      </ul>
    </article>

    <details v-if="dossier.sources?.length" class="mt-4 text-sm">
      <summary class="cursor-pointer text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">{{ t('sources') }} · {{ dossier.sources.length }}</summary>
      <ol class="mt-2 space-y-1.5">
        <li v-for="(source, index) in dossier.sources" :key="source.source_id" class="flex gap-2">
          <span class="w-6 flex-none text-right text-xs tabular-nums text-slate-400">[{{ index + 1 }}]</span>
          <SourceLink :source="source" />
        </li>
      </ol>
    </details>
  </section>
</template>

<script setup>
import { computed, defineComponent, h } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhCheck, PhMagnifyingGlass, PhWarning } from '@phosphor-icons/vue'
import AuthedImage from './AuthedImage.vue'
import messages from './messages'

const props = defineProps({ dossier: { type: Object, required: true } })
const { t } = useI18n({ useScope: 'local', messages })

const sourceById = computed(() => Object.fromEntries((props.dossier.sources || []).map((item) => [item.source_id, item])))
const sourceIndex = computed(() => Object.fromEntries((props.dossier.sources || []).map((item, index) => [item.source_id, index + 1])))

// Sources come from the open web: only real http(s) URLs become links, and
// they open in a new tab without referrer or opener access.
const SourceLink = defineComponent({
  props: { source: { type: Object, required: true }, compact: { type: Boolean, default: false } },
  setup(linkProps) {
    return () => {
      const { url, title, site, published_at: published } = linkProps.source
      const label = title || site || url
      const meta = [site, published ? String(published).slice(0, 10) : ''].filter(Boolean).join(' · ')
      const safe = /^https?:\/\//i.test(url || '')
      const text = h('span', { class: linkProps.compact ? 'line-clamp-1 text-[11px]' : 'text-sm' }, label)
      const children = [safe ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer nofollow', class: 'text-blue-600 hover:underline dark:text-blue-400' }, [text]) : h('span', { class: 'text-slate-600 dark:text-slate-300' }, [text])]
      if (meta && !linkProps.compact) children.push(h('span', { class: 'ml-2 text-xs text-slate-400' }, meta))
      return h('span', { class: 'min-w-0 break-words' }, children)
    }
  },
})
</script>

<style scoped>
.card { @apply rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900; }
.trait { @apply rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.candidate { @apply rounded-xl border border-slate-200 p-1.5 dark:border-slate-700; }
.candidate-selected { @apply border-emerald-500 ring-2 ring-emerald-500/20; }
.badge-selected { @apply absolute left-1.5 top-1.5 inline-flex items-center gap-0.5 rounded-md bg-emerald-600 px-1.5 py-0.5 text-[10px] font-semibold text-white shadow; }
.badge-recommended { @apply absolute left-1.5 top-1.5 rounded-md bg-blue-600 px-1.5 py-0.5 text-[10px] font-semibold text-white shadow; }
</style>
