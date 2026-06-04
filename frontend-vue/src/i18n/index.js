import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import zh from './locales/zh.json'

function getSavedLanguage() {
  try {
    const saved = localStorage.getItem('settings')
    if (saved) {
      const parsed = JSON.parse(saved)
      if (parsed.language && ['en', 'zh'].includes(parsed.language)) {
        return parsed.language
      }
    }
  } catch {
    // ignore parse errors
  }
  return 'en'
}

const i18n = createI18n({
  legacy: false,
  locale: getSavedLanguage(),
  fallbackLocale: 'en',
  messages: { en, zh },
})

export default i18n