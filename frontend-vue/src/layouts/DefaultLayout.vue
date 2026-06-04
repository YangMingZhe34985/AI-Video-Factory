<template>
  <AppLayout>
    <AppHeader :title="title" :subtitle="subtitle">
      <slot name="header-actions" />
    </AppHeader>
    <div class="flex-1 overflow-y-auto p-8">
      <slot />
    </div>
  </AppLayout>
</template>

<script setup>
import AppLayout from '@/components/layout/AppLayout.vue'
import AppHeader from '@/components/layout/AppHeader.vue'

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})
</script>