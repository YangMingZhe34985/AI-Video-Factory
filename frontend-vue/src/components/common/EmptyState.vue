<template>
  <div class="flex flex-col items-center justify-center py-16 text-gray-400">
    <component :is="icon" class="text-5xl mb-3" />
    <p class="text-sm">{{ text }}</p>
  </div>
</template>

<script setup>
import { PhEmpty } from '@phosphor-icons/vue'

defineProps({
  icon: { type: Object, default: () => PhEmpty },
  text: { type: String, default: 'No data' },
})
</script>