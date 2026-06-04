<template>
  <div class="min-h-screen bg-gray-50 flex items-center justify-center">
    <div class="text-center">
      <h1 class="text-6xl font-bold text-gray-300 mb-4">{{ t('notFound.title') }}</h1>
      <p class="text-xl text-gray-500 mb-6">{{ t('notFound.subtitle') }}</p>
      <router-link to="/dashboard" class="px-6 py-2.5 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700">
        {{ t('notFound.goHome') }}
      </router-link>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
</script>