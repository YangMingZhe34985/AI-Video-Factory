<template>
  <DefaultLayout :title="t('settings.title')" :subtitle="t('settings.subtitle')">
    <div class="max-w-3xl mx-auto space-y-6">
      <!-- Language Settings -->
      <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-6 shadow-sm">
        <h2 class="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">{{ t('settings.language') }}</h2>
        <div class="flex items-center justify-between">
          <div>
            <div class="text-sm font-medium text-gray-800 dark:text-gray-200">{{ t('settings.language') }}</div>
            <div class="text-xs text-gray-500 dark:text-gray-400">{{ t('settings.languageDesc') }}</div>
          </div>
          <select
            :value="settingsStore.language"
            @change="handleLanguageChange($event.target.value)"
            class="border border-gray-200 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg px-3 py-2 text-sm outline-none"
          >
            <option value="en">{{ t('settings.english') }}</option>
            <option value="zh">{{ t('settings.chinese') }}</option>
          </select>
        </div>
      </div>

      <!-- API Settings -->
      <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-6 shadow-sm">
        <h2 class="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">{{ t('settings.apiConfig') }}</h2>
        <div class="space-y-4">
          <div>
            <label class="text-sm text-gray-600 dark:text-gray-400 block mb-1">{{ t('settings.apiBaseUrl') }}</label>
            <input v-model="settingsStore.apiBaseUrl" type="text" class="w-full border border-gray-200 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" placeholder="http://127.0.0.1" />
          </div>
          <div>
            <label class="text-sm text-gray-600 dark:text-gray-400 block mb-1">{{ t('settings.apiPort') }}</label>
            <input v-model="settingsStore.apiPort" type="text" class="w-full border border-gray-200 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-100 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" placeholder="5000" />
          </div>
        </div>
      </div>

      <!-- Appearance Settings -->
      <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-100 dark:border-gray-700 p-6 shadow-sm">
        <h2 class="text-lg font-bold text-gray-900 dark:text-gray-100 mb-4">{{ t('settings.appearance') }}</h2>
        <div class="space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <div class="text-sm font-medium text-gray-800 dark:text-gray-200">{{ t('settings.darkMode') }}</div>
              <div class="text-xs text-gray-500 dark:text-gray-400">Enable dark mode interface</div>
            </div>
            <ToggleSwitch id="dark-mode" :model-value="settingsStore.darkMode" @update:model-value="toggleDarkMode" />
          </div>
          <div class="flex items-center justify-between">
            <div>
              <div class="text-sm font-medium text-gray-800 dark:text-gray-200">{{ t('settings.compactMode') }}</div>
              <div class="text-xs text-gray-500 dark:text-gray-400">Reduce spacing and padding</div>
            </div>
            <ToggleSwitch id="compact-mode" :model-value="settingsStore.compactMode" @update:model-value="settingsStore.compactMode = $event" />
          </div>
        </div>
      </div>

      <!-- Save -->
      <div class="flex justify-end">
        <button @click="handleSave" class="px-6 py-2.5 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700">
          {{ t('settings.save') }}
        </button>
      </div>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import ToggleSwitch from '@/components/common/ToggleSwitch.vue'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'

const { t, locale } = useI18n()
const settingsStore = useSettingsStore()
const toast = useToast()

function toggleDarkMode(value) {
  settingsStore.darkMode = value
  settingsStore.applyDarkMode()
  settingsStore.saveToStorage()
}

function handleLanguageChange(lang) {
  locale.value = lang
  settingsStore.setLanguage(lang)
}

function handleSave() {
  settingsStore.saveAll()
  toast.success(t('settings.saved'))
}
</script>