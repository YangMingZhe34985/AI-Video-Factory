<template>
  <div class="relative">
    <PhMagnifyingGlass class="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
    <input
      type="text"
      :placeholder="placeholder"
      :value="modelValue"
      class="w-full pl-9 pr-4 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-primary bg-white"
      @input="$emit('update:modelValue', ($event.target).value)"
    />
  </div>
</template>

<script setup>
import { PhMagnifyingGlass } from '@phosphor-icons/vue'

defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: 'Search...' },
})

defineEmits(['update:modelValue'])
</script>