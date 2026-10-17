<template>
  <section class="space-y-3">
    <div class="card">
      <h3 class="text-base font-semibold text-slate-900 dark:text-slate-100">{{ t('storyboard') }}</h3>
      <p v-if="plan.style_notes" class="mt-1 whitespace-pre-wrap text-sm text-slate-600 dark:text-slate-300">{{ plan.style_notes }}</p>
      <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">{{ t('storyboardHint') }}</p>
      <p v-if="plan.mode === 'remix'" class="mt-1 text-xs text-slate-500 dark:text-slate-400">{{ t('rangeHint') }}</p>
      <div v-for="(issue, index) in issues" :key="index" role="alert" class="mt-2 text-sm text-red-600">
        {{ t('invalidDraft') }} {{ issue.shot_id }} {{ issue.message }}
        <p v-for="detail in issue.errors || []" :key="detail">{{ detail }}</p>
      </div>
    </div>

    <article v-for="(shot, index) in plan.shots" :key="shot.shot_id" class="card">
      <header class="flex flex-wrap items-center gap-2">
        <span class="shot-no">{{ index + 1 }}</span>
        <h4 class="font-mono text-sm text-slate-700 dark:text-slate-300">{{ shot.shot_id }}</h4>
        <span v-if="state(shot).status" class="status" :class="`status-${state(shot).status}`">{{ t(state(shot).status) }}</span>
        <span class="flex-1" />
        <router-link v-if="state(shot).job_id" :to="`/jobs/${state(shot).job_id}`" class="text-xs text-blue-600 hover:underline">{{ t('job') }} ↗</router-link>
      </header>

      <div v-if="plan.mode === 'remix'" class="mt-4 grid gap-3 md:grid-cols-3">
        <label class="field-label">{{ t('editAction') }}
          <select v-model="shot.action" :disabled="!editable" class="field"><option value="keep">{{ t('keep') }}</option><option value="regenerate">{{ t('regenerate') }}</option></select>
        </label>
        <label class="field-label">{{ t('sourceStart') }}<input v-model.number="shot.source_start" :readonly="!editable" class="field tabular-nums" type="number" min="0" :max="sourceDuration" step="0.01" /></label>
        <label class="field-label">{{ t('sourceEnd') }}<input v-model.number="shot.source_end" :readonly="!editable" class="field tabular-nums" type="number" min="0" :max="sourceDuration" step="0.01" /></label>
        <label v-if="shot.action === 'regenerate'" class="field-label">{{ t('frameStrategy') }}
          <select v-model="shot.first_frame_mode" :disabled="!editable" class="field"><option value="source">{{ t('sourceFrame') }}</option><option value="generate">{{ t('newFrame') }}</option></select>
        </label>
        <label class="field-label md:col-span-2">{{ t('editReason') }}<textarea v-model="shot.edit_reason" :readonly="!editable" class="field" rows="2" maxlength="2000" /></label>
      </div>

      <div v-if="shot.action !== 'keep'" class="mt-4 grid gap-4 md:grid-cols-2">
        <label v-if="!shot.first_frame_mode || shot.first_frame_mode === 'generate'" class="field-label">{{ t('frame') }} · {{ stage(shot, 'poll_first_frame_image') }}
          <textarea v-model="shot.first_frame_prompt" :readonly="!editable" class="field" rows="4" maxlength="8000" />
        </label>
        <label class="field-label">{{ t('video') }} · {{ stage(shot, 'poll_i2v') }}
          <textarea v-model="shot.i2v_prompt" :readonly="!editable" class="field" rows="4" maxlength="8000" />
        </label>
        <label class="field-label">{{ t('generatedDuration') }}
          <input v-model.number="shot.video_params.duration" :readonly="!editable" class="field tabular-nums" type="number" min="0" step="any" />
        </label>
        <p class="self-end text-xs text-slate-500">{{ shot.first_frame_mode === 'source' ? t('sourceFrame') : shot.image_model_id }} → {{ shot.video_model_id || '—' }}</p>
      </div>

      <details v-if="shot.action !== 'keep'" class="mt-3 text-sm">
        <summary class="cursor-pointer text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">{{ t('generationSettings') }}</summary>
        <div v-for="kind in (shot.first_frame_mode === 'source' ? ['video'] : ['image', 'video'])" :key="kind" class="mt-3 grid gap-2 md:grid-cols-[12rem_1fr]">
          <label class="field-label">{{ kind }} model<input v-model="shot[`${kind}_model_id`]" :readonly="!editable" class="field font-mono" /></label>
          <label class="field-label">{{ kind }} params (JSON)
            <textarea :value="JSON.stringify(shot[`${kind}_params`], null, 2)" :readonly="!editable" class="field font-mono text-xs" rows="4" @input="editParams(shot, kind, $event.target.value)" />
            <span v-if="paramErrors[`${shot.shot_id}:${kind}`]" role="alert" class="text-red-600">{{ t('invalidParams') }}</span>
          </label>
        </div>
      </details>

      <button v-if="canRevise" type="button" class="secondary-btn mt-3" :disabled="disabled" @click="$emit('revise', shot)">{{ t('reviseShot', { cost: reviseCost(shot) }) }}</button>

      <p v-if="state(shot).error" class="mt-3 text-sm text-red-600">{{ state(shot).error.summary }}</p>
      <p v-for="message in state(shot).validation?.errors || []" :key="message" class="mt-1 text-sm text-red-600">{{ message }}</p>

      <div v-if="media(shot).length" class="mt-4 grid gap-3 sm:grid-cols-2">
        <figure v-for="artifact in media(shot)" :key="artifact.artifact_id" class="overflow-hidden rounded-xl border border-slate-200 dark:border-slate-700">
          <div v-if="mock && artifact.mime_type?.startsWith('video/') && artifact.artifact_type !== 'retained_video'" class="bg-slate-100 p-8 text-center text-xs text-slate-500 dark:bg-slate-800">{{ t('mockVideo') }}</div>
          <video v-else-if="artifact.mime_type?.startsWith('video/')" controls preload="metadata" :src="artifact.preview_url" class="max-h-64 w-full bg-black" />
          <img v-else :src="artifact.preview_url" :alt="shot.shot_id" class="max-h-64 w-full bg-slate-100 object-contain dark:bg-slate-800" />
          <figcaption class="flex items-center justify-between px-3 py-2 text-xs text-slate-500">
            <span class="font-mono">{{ artifact.artifact_type }}</span>
            <a :href="artifact.download_url" class="text-blue-600 hover:underline" download>{{ t('download') }}</a>
          </figcaption>
        </figure>
      </div>

      <details v-if="history[shot.shot_id]?.length" class="mt-3 text-sm">
        <summary class="cursor-pointer text-slate-500">{{ t('shotHistory') }}</summary>
        <div v-for="(previous, i) in history[shot.shot_id]" :key="i" class="mt-2 text-xs text-slate-600 dark:text-slate-300">
          {{ i + 1 }} · {{ previous.plan.edit_reason }} · {{ t(previous.result.status || 'pending') }}
          <a v-for="asset in previous.result.artifacts || []" :key="asset.artifact_id" :href="asset.download_url" class="ml-2 text-blue-600" download>{{ asset.artifact_type }}</a>
        </div>
      </details>
    </article>
  </section>
</template>

<script setup>
import { reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import messages from './messages'

const props = defineProps({
  plan: { type: Object, required: true },
  shots: { type: Object, default: () => ({}) },          // snapshot.shots
  history: { type: Object, default: () => ({}) },        // snapshot.shot_history
  issues: { type: Array, default: () => [] },
  sourceDuration: { type: Number, default: null },
  mock: { type: Boolean, default: false },
  editable: { type: Boolean, default: false },
  canRevise: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['revise', 'invalid'])
const { t } = useI18n({ useScope: 'local', messages })

const paramErrors = reactive({})
const state = (shot) => props.shots?.[shot.shot_id] || {}
const stage = (shot, key) => t(state(shot).nodes?.find((node) => node.node_key === key)?.status || (state(shot).status === 'failed' ? 'failed' : 'pending'))
const media = (shot) => (state(shot).artifacts || []).filter((item) => /^(image|video)\//.test(item.mime_type || ''))
const reviseCost = (shot) => (shot.action === 'keep' ? 0 : shot.first_frame_mode === 'source' ? 10 : 12)

function editParams(shot, kind, text) {
  const key = `${shot.shot_id}:${kind}`
  try {
    const value = JSON.parse(text)
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('object required')
    shot[`${kind}_params`] = value
    delete paramErrors[key]
  } catch {
    paramErrors[key] = true
  }
  emit('invalid', Object.keys(paramErrors).length > 0)
}
</script>

<style scoped>
.card { @apply rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900; }
.shot-no { @apply flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white dark:bg-slate-200 dark:text-slate-900; }
.status { @apply rounded-full px-2 py-0.5 text-[11px] font-medium bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.status-success { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.status-failed { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.status-running, .status-pending { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.field-label { @apply flex flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400; }
.field { @apply w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 read-only:bg-slate-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:read-only:bg-slate-900; }
.secondary-btn { @apply rounded-xl border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
</style>
