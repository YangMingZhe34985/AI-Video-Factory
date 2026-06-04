<template>
  <div class="flex items-center justify-center py-12">
    <div class="flex flex-col items-center gap-3">
      <svg class="animate-spin h-8 w-8 text-primary" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
      <span class="text-sm text-gray-500">{{ text || 'Loading...' }}</span>
    </div>
  </div>
</template>

<script setup>
defineProps({ text: { type: String, default: '' } })
</script>