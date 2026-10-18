<template>
  <div class="h-screen flex overflow-hidden">
    <AppSidebar :responsive="responsive" />
    <main class="flex-1 flex flex-col h-screen overflow-hidden relative" :class="{ 'min-w-0 bg-slate-50 dark:bg-slate-950': responsive }">
      <slot />
    </main>
    <ToastContainer />
  </div>
</template>

<script setup>
import AppSidebar from './AppSidebar.vue'
import ToastContainer from '@/components/common/ToastContainer.vue'

defineProps({ responsive: { type: Boolean, default: false } })
</script>