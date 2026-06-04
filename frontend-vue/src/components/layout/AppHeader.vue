<template>
  <header class="bg-white px-8 py-5 flex items-center justify-between z-10 border-b border-gray-100">
    <div>
      <h1 class="text-2xl font-bold text-gray-900">{{ title }}</h1>
      <p class="text-sm text-gray-500 mt-1">{{ subtitle }}</p>
    </div>
    <div class="flex items-center space-x-4">
      <div class="relative hidden md:block">
        <PhMagnifyingGlass class="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="t('header.searchPlaceholder')"
          class="pl-9 pr-8 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary w-64 bg-gray-50"
          @keypress.enter="handleSearch"
        />
        <span class="absolute right-3 top-1/2 transform -translate-y-1/2 text-xs text-gray-400 border border-gray-200 rounded px-1">/</span>
      </div>
      <button @click="handleBellClick" class="relative p-2 text-gray-500 hover:bg-gray-100 rounded-full transition-colors">
        <PhBell class="text-xl" />
        <span class="absolute top-1.5 right-1.5 w-2 h-2 bg-red-500 rounded-full border-2 border-white"></span>
      </button>
      <button @click="handleHelpClick" class="p-2 text-gray-500 hover:bg-gray-100 rounded-full transition-colors">
        <PhQuestion class="text-xl" />
      </button>
      <slot />
    </div>
  </header>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { PhMagnifyingGlass, PhBell, PhQuestion } from '@phosphor-icons/vue'
import { useToast } from '@/composables/useToast'

defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})

const { t } = useI18n()
const router = useRouter()
const toast = useToast()
const searchQuery = ref('')

function handleSearch() {
  const q = searchQuery.value.trim()
  if (q) {
    router.push(`/jobs?search=${encodeURIComponent(q)}`)
  }
}

function handleBellClick() {
  toast.info(t('header.notifications'))
}

function handleHelpClick() {
  toast.info(t('header.help'))
}
</script>