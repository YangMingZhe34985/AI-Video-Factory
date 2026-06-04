<template>
  <div class="fixed top-5 right-5 z-[9999] flex flex-col gap-2">
    <TransitionGroup name="toast">
      <div
        v-for="toast in toastStore.toasts"
        :key="toast.id"
        :class="bgClass(toast.type)"
        class="text-white px-5 py-3 rounded-xl shadow-lg flex items-center gap-2 text-sm font-medium"
      >
        <component :is="iconComponent(toast.type)" class="text-lg" />
        <span>{{ toast.message }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup>
import { useToastStore } from '@/stores/toast'
import { PhCheckCircle, PhXCircle, PhWarning, PhInfo } from '@phosphor-icons/vue'

const toastStore = useToastStore()

const bgMap = { success: 'bg-green-600', error: 'bg-red-600', warning: 'bg-yellow-500', info: 'bg-gray-700' }
const iconMap = { success: PhCheckCircle, error: PhXCircle, warning: PhWarning, info: PhInfo }

function bgClass(type) { return bgMap[type] || bgMap.info }
function iconComponent(type) { return iconMap[type] || iconMap.info }
</script>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from { opacity: 0; transform: translateX(30px); }
.toast-leave-to { opacity: 0; transform: translateX(30px); }
</style>