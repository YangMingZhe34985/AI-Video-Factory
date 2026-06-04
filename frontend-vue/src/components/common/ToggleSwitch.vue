<template>
  <div class="flex items-center">
    <input
      type="checkbox"
      :id="id"
      :checked="modelValue"
      class="toggle-checkbox hidden"
      @change="$emit('update:modelValue', ($event.target).checked)"
    />
    <label :for="id" class="toggle-label block"></label>
    <label v-if="label" :for="id" class="ml-3 text-sm text-gray-700 cursor-pointer">{{ label }}</label>
  </div>
</template>

<script setup>
defineProps({
  modelValue: { type: Boolean, default: false },
  label: { type: String, default: '' },
  id: { type: String, required: true },
})

defineEmits(['update:modelValue'])
</script>