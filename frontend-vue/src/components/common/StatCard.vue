<template>
  <component
    :is="clickable ? 'router-link' : 'div'"
    :to="clickable ? to : undefined"
    class="bg-white rounded-xl p-5 border border-gray-100 shadow-sm flex flex-col justify-between"
    :class="clickable ? 'cursor-pointer hover:shadow-md hover:border-gray-200 transition-shadow' : ''"
  >
    <div class="flex items-center mb-2">
      <div :class="iconBg" class="w-10 h-10 rounded-lg text-white flex items-center justify-center mr-3">
        <component :is="icon" class="text-xl" />
      </div>
      <div class="text-sm font-medium text-gray-500">{{ label }}</div>
    </div>
    <div class="text-2xl font-bold text-gray-900 mb-1">{{ value }}</div>
    <div class="text-xs text-gray-500">{{ subtitle }}</div>
  </component>
</template>

<script setup>
defineProps({
  icon: { type: Object, required: true },
  iconBg: { type: String, default: 'bg-blue-500' },
  label: { type: String, required: true },
  value: { type: [String, Number], default: '--' },
  subtitle: { type: String, default: '' },
  clickable: { type: Boolean, default: false },
  to: { type: String, default: '' },
})
</script>