<template>
  <section class="clarify" aria-live="polite">
    <header class="flex flex-wrap items-center gap-2">
      <span class="badge"><PhChatCircleDots :size="14" weight="fill" />{{ t('clarifyTitle') }}</span>
      <span class="text-xs text-slate-500 dark:text-slate-400">{{ t(`askedBy_${card.asked_by}`) }}</span>
    </header>

    <fieldset v-for="question in card.questions" :key="question.question_id" class="mt-5" :disabled="disabled">
      <legend class="flex flex-wrap items-baseline gap-2">
        <span class="text-[15px] font-semibold text-slate-900 dark:text-slate-100">{{ question.text }}</span>
        <span v-if="!question.blocking" class="text-xs text-slate-400">{{ t('optional') }}</span>
      </legend>
      <p class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ question.why }}</p>

      <div class="mt-3 grid gap-2" :class="hasImages(question) ? 'grid-cols-2 sm:grid-cols-4' : 'sm:grid-cols-2'" role="radiogroup" :aria-label="question.text">
        <button
          v-for="option in question.options"
          :key="option.option_id"
          type="button"
          role="radio"
          class="option"
          :class="{ 'option-image': option.image_artifact_id }"
          :aria-checked="choice[question.question_id]?.option_id === option.option_id"
          @click="pick(question, option.option_id)"
        >
          <span v-if="option.image_artifact_id" class="relative mb-2 block">
            <AuthedImage :src="`/api/artifacts/${option.image_artifact_id}/preview`" :alt="option.label" class="block aspect-square w-full rounded-lg object-cover" />
            <span v-if="option.option_id === question.recommended_option_id" class="pill-overlay">{{ t('recommended') }}</span>
          </span>
          <span class="flex items-start justify-between gap-2">
            <span class="text-sm font-medium">{{ option.label }}</span>
            <template v-if="!option.image_artifact_id">
              <span v-if="option.option_id === question.recommended_option_id" class="pill pill-blue">{{ t('recommended') }}</span>
              <span v-else-if="option.option_id === question.default_option_id" class="pill">{{ t('defaultTag') }}</span>
            </template>
          </span>
          <span v-if="option.detail" class="mt-1 block text-xs leading-snug text-slate-500 dark:text-slate-400">{{ option.detail }}</span>
        </button>
      </div>

      <div v-if="question.allow_free_text" class="mt-2">
        <button
          type="button"
          class="text-xs font-medium text-slate-500 underline-offset-2 hover:text-blue-600 hover:underline"
          :aria-expanded="choice[question.question_id]?.mode === 'text'"
          @click="pick(question, null)"
        >{{ t('freeText') }}</button>
        <input
          v-if="choice[question.question_id]?.mode === 'text'"
          v-model="choice[question.question_id].text"
          class="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 dark:border-slate-600 dark:bg-slate-950"
          maxlength="1000"
          :placeholder="t('freeTextPlaceholder')"
          :aria-label="t('freeText')"
        />
      </div>
    </fieldset>

    <footer class="mt-6 flex flex-wrap items-center gap-3">
      <button type="button" class="primary-btn" :disabled="disabled || missing > 0" @click="submit(false)">{{ t('submitAnswers') }}</button>
      <button v-if="onlyOptionalLeft" type="button" class="secondary-btn" :disabled="disabled" @click="submit(true)">{{ t('useDefaults') }}</button>
      <span v-if="missing > 0" class="text-xs text-slate-500">{{ t('answerMissing', { count: missing }) }}</span>
    </footer>
  </section>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { PhChatCircleDots } from '@phosphor-icons/vue'
import AuthedImage from './AuthedImage.vue'
import messages from './messages'

const props = defineProps({
  card: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['submit'])
const { t } = useI18n({ useScope: 'local', messages })

const choice = reactive({})
watch(() => props.card.card_id, () => {
  Object.keys(choice).forEach((key) => delete choice[key])
  for (const question of props.card.questions) {
    const preset = question.recommended_option_id || question.default_option_id
    if (preset) choice[question.question_id] = { mode: 'option', option_id: preset, text: '' }
  }
}, { immediate: true })

const hasImages = (question) => question.options.some((option) => option.image_artifact_id)
function pick(question, optionId) {
  choice[question.question_id] = optionId
    ? { mode: 'option', option_id: optionId, text: '' }
    : { mode: 'text', option_id: null, text: choice[question.question_id]?.text || '' }
}
const answered = (question) => {
  const value = choice[question.question_id]
  return value && (value.mode === 'option' ? Boolean(value.option_id) : value.text.trim().length > 0)
}
const missing = computed(() => props.card.questions.filter((question) => question.blocking && !answered(question)).length)
const onlyOptionalLeft = computed(() => props.card.questions.some((question) => !question.blocking) && missing.value === 0)

function submit(useDefaults) {
  const answers = props.card.questions
    .filter((question) => answered(question) && !(useDefaults && !question.blocking))
    .map((question) => {
      const value = choice[question.question_id]
      return value.mode === 'option'
        ? { question_id: question.question_id, option_id: value.option_id }
        : { question_id: question.question_id, text: value.text.trim() }
    })
  emit('submit', { answers, useDefaults })
}
</script>

<style scoped>
.clarify { @apply rounded-2xl border border-blue-200 bg-gradient-to-b from-blue-50/80 to-white p-5 shadow-[0_8px_24px_-16px_rgba(37,99,235,0.45)] dark:border-blue-900/70 dark:from-blue-950/40 dark:to-slate-900; }
.badge { @apply inline-flex items-center gap-1.5 rounded-full bg-blue-600 px-2.5 py-1 text-xs font-semibold text-white; }
.option { @apply rounded-xl border border-slate-200 bg-white p-3 text-left text-slate-800 transition hover:border-blue-300 disabled:cursor-not-allowed disabled:opacity-60 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100 dark:hover:border-blue-700; }
.option[aria-checked='true'] { @apply border-blue-500 ring-2 ring-blue-500/20 dark:border-blue-400; }
.option-image { @apply p-2; }
.pill { @apply flex-none rounded px-1.5 py-0.5 text-[10px] font-semibold text-slate-500 ring-1 ring-slate-200 dark:ring-slate-700; }
.pill-overlay { @apply absolute left-1.5 top-1.5 rounded-md bg-blue-600 px-1.5 py-0.5 text-[10px] font-semibold text-white shadow; }
.pill-blue { @apply text-blue-700 ring-blue-200 dark:text-blue-300 dark:ring-blue-800; }
.primary-btn { @apply rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply rounded-xl border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
</style>
