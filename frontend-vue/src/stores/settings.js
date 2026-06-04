import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export const useSettingsStore = defineStore('settings', () => {
  const darkMode = ref(false)
  const compactMode = ref(false)
  const language = ref('en')
  const apiBaseUrl = ref('http://127.0.0.1')
  const apiPort = ref('5000')

  function loadFromStorage() {
    try {
      const raw = localStorage.getItem('settings')
      if (raw) {
        const data = JSON.parse(raw)
        darkMode.value = data.darkMode ?? false
        compactMode.value = data.compactMode ?? false
        language.value = data.language ?? 'en'
        apiBaseUrl.value = data.apiBaseUrl ?? 'http://127.0.0.1'
        apiPort.value = data.apiPort ?? '5000'
      }
    } catch {
      // ignore
    }
  }

  function saveToStorage() {
    localStorage.setItem('settings', JSON.stringify({
      darkMode: darkMode.value,
      compactMode: compactMode.value,
      language: language.value,
      apiBaseUrl: apiBaseUrl.value,
      apiPort: apiPort.value,
    }))
  }

  function applyDarkMode() {
    if (darkMode.value) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }

  function toggleDarkMode() {
    darkMode.value = !darkMode.value
    applyDarkMode()
    saveToStorage()
  }

  function setLanguage(lang) {
    language.value = lang
    saveToStorage()
  }

  function saveAll() {
    applyDarkMode()
    saveToStorage()
  }

  // Initialize on first load
  loadFromStorage()
  applyDarkMode()

  return {
    darkMode, compactMode, language, apiBaseUrl, apiPort,
    loadFromStorage, saveToStorage, applyDarkMode,
    toggleDarkMode, setLanguage, saveAll,
  }
})