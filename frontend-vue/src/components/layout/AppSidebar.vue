<template>
  <aside
    class="bg-sidebar text-white flex flex-col transition-none shrink-0 relative select-none"
    :style="{ width: `${sidebarWidth}px` }"
  >
    <!-- Logo -->
    <div class="h-16 flex items-center px-4 border-b border-gray-800 overflow-hidden">
      <router-link to="/dashboard" class="flex items-center text-base font-bold text-white truncate">
        <PhPlayCircle weight="fill" class="text-primary text-2xl mr-2 shrink-0" />
        <span v-if="sidebarWidth > 200" class="truncate">{{ t('app.title') }}</span>
      </router-link>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 px-3 py-5 space-y-1 overflow-y-auto overflow-x-hidden">
      <router-link
        v-for="item in navItems"
        :key="item.to"
        :to="item.to"
        class="w-full flex items-center py-2.5 text-sm font-medium rounded-lg transition-colors"
        :class="[
          isActive(item.to) ? 'bg-primary text-white' : 'text-gray-400 hover:bg-sidebarItem hover:text-white',
          sidebarWidth > 200 ? 'px-4' : 'px-2 justify-center',
        ]"
        :title="sidebarWidth <= 200 ? item.label : undefined"
      >
        <component :is="iconMap[item.icon]" class="text-lg shrink-0" :class="sidebarWidth > 200 ? 'mr-3' : ''" />
        <span v-if="sidebarWidth > 200" class="truncate">{{ item.label }}</span>
      </router-link>
    </nav>

    <!-- API status + user -->
    <div class="p-3">
      <div v-if="sidebarWidth > 200" class="bg-sidebarItem rounded-xl p-3 mb-3 text-xs">
        <div class="flex justify-between items-center mb-2">
          <span class="text-gray-400 font-medium">{{ t('sidebar.apiEnv') }}</span>
          <span
            :class="healthConnected ? 'bg-green-500/20 text-green-400 border-green-500/30' : 'bg-red-500/20 text-red-400 border-red-500/30'"
            class="px-1.5 py-0.5 rounded text-[10px] font-semibold border"
          >
            {{ healthConnected ? t('sidebar.connected') : t('sidebar.offline') }}
          </span>
        </div>
        <div class="flex justify-between items-center">
          <span class="text-gray-400">{{ t('sidebar.apiStatus') }}</span>
          <span class="flex items-center" :class="healthConnected ? 'text-green-400' : 'text-red-400'">
            <span class="w-1.5 h-1.5 rounded-full mr-1" :class="healthConnected ? 'bg-green-500' : 'bg-red-500'"></span>
            {{ healthConnected ? t('sidebar.healthy') : t('sidebar.offline') }}
          </span>
        </div>
      </div>

      <div class="flex items-center p-2 rounded-lg overflow-hidden">
        <div class="w-7 h-7 rounded-full bg-gray-500 flex items-center justify-center text-xs font-bold shrink-0">
          {{ (authStore.username || 'A')[0].toUpperCase() }}
        </div>
        <div v-if="sidebarWidth > 200" class="flex-1 min-w-0 ml-2.5">
          <p class="text-sm font-medium text-white truncate">{{ authStore.username }}</p>
          <p class="text-xs text-gray-400 truncate">{{ t('sidebar.admin') }}</p>
        </div>
      </div>
    </div>

    <!-- Drag handle (right edge) -->
    <div
      class="absolute top-0 right-0 w-1 h-full cursor-col-resize group z-10"
      @mousedown.prevent="startDrag"
    >
      <div class="absolute right-0 top-1/2 -translate-y-1/2 w-[3px] h-12 rounded-full bg-transparent group-hover:bg-primary/40 transition-colors" />
    </div>
  </aside>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import { NAV_ITEMS } from '@/utils/constants'
import { useResizablePanel } from '@/composables/useResizablePanel'
import {
  PhPlayCircle, PhSquaresFour, PhFolder, PhChatText, PhCube, PhBriefcase, PhGitMerge, PhImage, PhGear,
} from '@phosphor-icons/vue'

const { t } = useI18n()
const route = useRoute()
const authStore = useAuthStore()
const healthConnected = ref(true)

const { width: sidebarWidth, startDrag } = useResizablePanel('sidebar:width', {
  defaultWidth: 260,
  minWidth: 220,
  maxWidth: 360,
  side: 'right',
})

const iconMap = {
  PhSquaresFour, PhFolder, PhChatText, PhCube, PhBriefcase, PhGitMerge, PhImage, PhGear,
}

const navItems = computed(() => NAV_ITEMS.map(item => ({
  ...item,
  label: t(item.labelKey),
})))

function isActive(path) {
  if (path === '/dashboard') return route.path === '/dashboard'
  return route.path.startsWith(path)
}

onMounted(async () => {
  try {
    const res = await fetch('/api/health', { signal: AbortSignal.timeout(3000) })
    healthConnected.value = res.ok
  } catch {
    healthConnected.value = false
  }
})
</script>
