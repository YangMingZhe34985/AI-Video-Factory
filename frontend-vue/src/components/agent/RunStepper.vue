<template>
  <ol class="flex flex-wrap items-center gap-y-2 text-xs" :aria-label="t('stageUnderstand')">
    <li v-for="(stage, index) in stages" :key="stage.key" class="flex items-center">
      <span class="step" :class="`step-${stage.state}`" :aria-current="stage.state === 'active' ? 'step' : undefined">
        <PhCheck v-if="stage.state === 'done'" :size="11" weight="bold" />
        <PhWarning v-else-if="stage.state === 'error'" :size="11" weight="bold" />
        <span v-else class="dot" />
        {{ t(stage.label) }}
      </span>
      <span v-if="index < stages.length - 1" class="mx-1.5 h-px w-4 bg-slate-300 dark:bg-slate-600" aria-hidden="true" />
    </li>
  </ol>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhCheck, PhWarning } from '@phosphor-icons/vue'
import messages from './messages'

const props = defineProps({
  status: { type: String, required: true },
  asked: { type: Boolean, default: false },          // any clarification card shown in this run
  hasPlan: { type: Boolean, default: false },
  hasResults: { type: Boolean, default: false },
})
const { t } = useI18n({ useScope: 'local', messages })

const STATUS_STAGE = {
  queued: 'understand', understanding: 'understand', analyzing: 'understand', researching: 'understand',
  awaiting_input: 'clarify', planning: 'plan', awaiting_approval: 'review',
  producing: 'produce', awaiting_delivery: 'deliver', delivering: 'deliver',
}

const stages = computed(() => {
  const keys = ['understand', ...(props.asked || props.status === 'awaiting_input' ? ['clarify'] : []), 'plan', 'review', 'produce', 'deliver']
  const labels = { understand: 'stageUnderstand', clarify: 'stageClarify', plan: 'stagePlan', review: 'stageReview', produce: 'stageProduce', deliver: 'stageDeliver' }
  let current = STATUS_STAGE[props.status]
  const finished = ['success', 'partial_success'].includes(props.status)
  const broken = ['failed', 'cancelled', 'needs_attention'].includes(props.status)
  if (broken) current = props.hasResults ? 'produce' : props.hasPlan ? 'review' : 'understand'
  const activeIndex = finished ? keys.length : keys.indexOf(current)
  return keys.map((key, index) => ({
    key,
    label: labels[key],
    state: index < activeIndex ? 'done' : index === activeIndex ? (broken ? 'error' : 'active') : 'todo',
  }))
})
</script>

<style scoped>
.step { @apply inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-medium; }
.dot { @apply h-1.5 w-1.5 rounded-full bg-current; }
.step-done { @apply border-transparent bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.step-active { @apply border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-950/60 dark:text-blue-300; }
.step-active .dot { @apply animate-pulse; }
.step-error { @apply border-red-200 bg-red-50 text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300; }
.step-todo { @apply border-slate-200 text-slate-400 dark:border-slate-700 dark:text-slate-500; }
</style>
