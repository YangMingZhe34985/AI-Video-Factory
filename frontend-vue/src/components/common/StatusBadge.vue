<template>
  <span
    class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border"
    :class="colorClass"
  >
    <span class="w-1.5 h-1.5 rounded-full mr-1.5" :class="dotClass"></span>
    {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { statusColors, statusDotColor } from '@/utils/format'

const props = defineProps({
  status: { type: String, default: 'pending' },
})

const { t, te } = useI18n()

// Map status enum to a jobs.* i18n key (handles snake_case -> camelCase)
const STATUS_KEY_MAP = {
  pending: 'jobs.pending',
  queued: 'jobs.queued',
  running: 'jobs.running',
  success: 'jobs.success',
  failed: 'jobs.failed',
  paused: 'jobs.paused',
  cancelled: 'jobs.cancelled',
  partial_success: 'jobs.partialSuccess',
  retrying: 'jobs.retrying',
  path_failed: 'jobs.pathFailed',
}

const label = computed(() => {
  const key = STATUS_KEY_MAP[props.status]
  if (key && te(key)) return t(key)
  return props.status
})

const colorClass = computed(() => statusColors(props.status))
const dotClass = computed(() => statusDotColor(props.status))
</script>
