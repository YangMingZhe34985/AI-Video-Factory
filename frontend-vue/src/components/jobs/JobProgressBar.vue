<template>
  <div class="flex items-center">
    <div class="w-16 bg-gray-100 rounded-full h-1.5 mr-2">
      <div class="h-1.5 rounded-full" :class="barColor" :style="{ width: pct + '%' }"></div>
    </div>
    <span class="text-xs text-gray-500">{{ pct }}%</span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ job: { type: Object, required: true } })

const pct = computed(() => {
  const total = props.job.total_nodes || 12
  const done = Number.isFinite(Number(props.job.completed_nodes))
    ? Number(props.job.completed_nodes)
    : latestRuns(props.job.node_runs || []).filter((n) => n.status === 'success').length
  return total > 0 ? Math.min(100, Math.max(0, Math.round(done / total * 100))) : 0
})

function latestRuns(runs) {
  const byNode = new Map()
  runs.forEach((run) => {
    if (run?.node_key) byNode.set(run.node_key, run)
  })
  return [...byNode.values()]
}

const barColor = computed(() => {
  const status = props.job.status
  if (status === 'success') return 'bg-green-500'
  if (status === 'failed') return 'bg-red-500'
  if (status === 'paused') return 'bg-orange-500'
  return 'bg-primary'
})
</script>
