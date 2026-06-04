<template>
  <div class="h-screen flex overflow-hidden">
    <AppSidebar />
    <main class="flex-1 flex flex-col h-screen overflow-hidden relative">
      <slot />
    </main>
    <ToastContainer />
  </div>
</template>

<script setup>
import AppSidebar from './AppSidebar.vue'
import ToastContainer from '@/components/common/ToastContainer.vue'
</script>