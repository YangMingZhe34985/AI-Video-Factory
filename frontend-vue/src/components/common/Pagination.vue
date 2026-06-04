<template>
  <div class="flex items-center space-x-2 text-sm text-gray-500">
    <button
      class="w-8 h-8 flex items-center justify-center border border-gray-200 rounded hover:bg-gray-50"
      :disabled="currentPage <= 1"
      @click="$emit('change', currentPage - 1)"
    >
      <PhCaretLeft />
    </button>
    <button
      v-for="page in visiblePages"
      :key="page"
      :class="page === currentPage ? 'border-primary bg-primary text-white' : 'border-gray-200 hover:bg-gray-50'"
      class="w-8 h-8 flex items-center justify-center border rounded font-medium"
      @click="$emit('change', page)"
    >
      {{ page }}
    </button>
    <button
      class="w-8 h-8 flex items-center justify-center border border-gray-200 rounded hover:bg-gray-50"
      :disabled="currentPage >= totalPages"
      @click="$emit('change', currentPage + 1)"
    >
      <PhCaretRight />
    </button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { PhCaretLeft, PhCaretRight } from '@phosphor-icons/vue'

const props = defineProps({
  currentPage: { type: Number, default: 1 },
  totalPages: { type: Number, default: 1 },
})

defineEmits(['change'])

const visiblePages = computed(() => {
  const pages = []
  const start = Math.max(1, props.currentPage - 1)
  const end = Math.min(props.totalPages, start + 2)
  for (let i = start; i <= end; i++) pages.push(i)
  return pages
})
</script>