<template>
  <AppLayout :responsive="responsive">
    <AppHeader :title="title" :subtitle="subtitle" :responsive="responsive">
      <slot name="header-actions" />
    </AppHeader>
    <div class="flex-1 overflow-y-auto" :class="responsive ? 'min-w-0 p-4 sm:p-8' : 'p-8'">
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
  responsive: { type: Boolean, default: false },
})
</script>