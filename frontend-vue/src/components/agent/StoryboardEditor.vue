<template>
  <section class="card min-w-0" data-testid="storyboard-editor">
    <!-- header -->
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 items-start gap-3">
        <span class="icon-tile"><PhFilmStrip :size="18" /></span>
        <div class="min-w-0">
          <h3 class="text-[15px] font-semibold leading-snug text-slate-900 dark:text-white">{{ plan.title || t('title') }}</h3>
          <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{{ t('subtitle', { version: baseVersion }) }}</p>
        </div>
      </div>
      <span class="status-pill" :class="statusTone">
        <PhCircleNotch v-if="status === 'previewing' || status === 'planning'" :size="12" class="animate-spin" />
        <PhCheckCircle v-else-if="status === 'storyboard_approved'" :size="13" weight="fill" />
        <span v-else class="h-1.5 w-1.5 rounded-full bg-current" />
        {{ statusText }}
      </span>
    </header>

    <!-- review steps -->
    <ol class="mt-4 flex flex-wrap items-center gap-1.5 text-xs" :aria-label="t('title')">
      <template v-for="(step, index) in reviewSteps" :key="step.key">
        <li v-if="index" class="h-px w-4 bg-slate-200 dark:bg-slate-700" aria-hidden="true" />
        <li class="step" :class="`step-${step.state}`" :aria-current="step.state === 'current' ? 'step' : undefined">
          <PhCheck v-if="step.state === 'done'" :size="11" weight="bold" />
          <span v-else class="tabular-nums">{{ index + 1 }}</span>
          {{ step.label }}
        </li>
      </template>
    </ol>

    <div v-if="versionConflict" role="alert" class="notice notice-amber mt-4">
      <PhWarning :size="16" class="mt-0.5 flex-none" />
      <span>{{ t('conflict') }} <button type="button" class="font-medium underline underline-offset-2" @click="reload">{{ t('conflictReload') }}</button></span>
    </div>
    <p v-if="actionError" role="alert" class="notice notice-red mt-3 break-words"><PhWarning :size="16" class="mt-0.5 flex-none" />{{ actionError }}</p>
    <p v-if="actionEstimate != null" role="status" class="mt-3 flex items-center gap-1.5 text-xs text-slate-500"><PhCheckCircle :size="14" class="text-emerald-600" />{{ t('submitted', { cost: money(actionEstimate) }) }}</p>
    <p v-if="status === 'storyboard_approved'" class="notice notice-emerald mt-4"><PhCheckCircle :size="16" weight="fill" class="mt-0.5 flex-none" />{{ t('approvedNote') }}</p>

    <!-- overview: duration bar + costs -->
    <div class="mt-5 rounded-xl bg-slate-50 p-4 dark:bg-slate-800/50">
      <div class="flex flex-wrap items-baseline justify-between gap-2">
        <p class="flex items-baseline gap-2">
          <PhClock :size="15" class="self-center text-slate-400" />
          <strong class="text-lg font-semibold tabular-nums text-slate-900 dark:text-white">{{ t('seconds', { n: format(check.total) }) }}</strong>
          <span class="text-sm text-slate-500">{{ t('target', { n: check.target }) }}</span>
        </p>
        <span class="text-xs" :class="durationIssue ? 'font-medium text-red-600 dark:text-red-400' : 'text-slate-500'">{{ t('tolerance', { n: format(check.tolerance) }) }}</span>
      </div>
      <div class="relative mt-3">
        <div class="flex h-10 gap-[3px]" :aria-label="t('durationBar')">
          <button
            v-for="shot in timelineShots" :key="shot.shot_id" type="button"
            :title="`${shot.shot_id} · ${t('seconds', { n: format(shot.duration_sec) })} · ${shot.summary}`"
            :style="{ flexGrow: Math.max(shot.duration_sec || 0, 0.1), flexBasis: 0 }"
            class="segment" :class="[sceneTone(shot.scene_id), hasIssue(shot.shot_id) ? 'ring-2 ring-inset ring-red-500' : '']"
            @click="openShot(shot.shot_id)"
          >
            <span class="block truncate px-1.5 text-left text-[11px] font-semibold leading-tight">{{ shot.shot_id }}</span>
            <span class="block truncate px-1.5 text-left text-[10px] leading-tight opacity-80 tabular-nums">{{ format(shot.duration_sec) }}s</span>
          </button>
          <span v-if="barScale > check.total" class="rounded-md border border-dashed border-slate-300 dark:border-slate-600" :style="{ flexGrow: barScale - check.total, flexBasis: 0 }" aria-hidden="true" />
        </div>
        <span class="target-marker" :style="{ left: `${(check.target / barScale) * 100}%` }" aria-hidden="true" />
      </div>
      <div class="mt-4 grid grid-cols-[repeat(auto-fit,minmax(9.5rem,1fr))] gap-2">
        <div class="stat"><span><PhImage :size="13" />{{ t('previewSpent') }}</span><strong>{{ money(estimates.preview_spent_credits) }}<small>credits</small></strong></div>
        <div class="stat"><span><PhFilmSlate :size="13" />{{ t('videoEstimate') }}</span><strong>{{ money(check.video) }}<small>credits</small></strong></div>
        <div class="stat"><span><PhCoins :size="13" />{{ t('totalSpent') }}</span><strong>{{ money(estimates.spent_credits) }}<small>credits</small></strong></div>
      </div>
      <p class="mt-2.5 text-[11px] leading-relaxed text-slate-400">{{ t('costNote') }}{{ demo ? ` ${t('demoNote')}` : '' }}</p>
    </div>

    <details v-if="story.story" class="group mt-4 rounded-xl border border-slate-200 px-4 py-3 text-sm dark:border-slate-700">
      <summary class="flex cursor-pointer list-none items-center gap-2 text-slate-700 dark:text-slate-200">
        <PhCaretDown :size="14" class="text-slate-400 transition-transform group-open:rotate-180" />
        <span class="font-medium">{{ t('storyStyle') }}</span>
        <span class="min-w-0 flex-1 truncate text-slate-500">{{ story.story.logline }}</span>
      </summary>
      <p class="mt-3 whitespace-pre-wrap leading-relaxed text-slate-600 dark:text-slate-300">{{ story.story.synopsis }}</p>
      <div class="mt-3 flex flex-wrap gap-1.5">
        <span v-for="item in styleChips" :key="item" class="chip">{{ item }}</span>
      </div>
    </details>

    <!-- characters -->
    <section v-if="story.characters?.length" class="mt-7" :aria-label="t('characters')">
      <div class="section-head">
        <h4><PhUsers :size="16" />{{ t('characters') }}<span class="count">{{ story.characters.length }}</span></h4>
        <p>{{ t('charactersHint') }}</p>
      </div>
      <div class="mt-3 grid grid-cols-[repeat(auto-fill,minmax(min(19rem,100%),1fr))] gap-3">
        <article v-for="character in characterDraft" :key="character.character_id" class="panel">
          <div class="flex gap-3">
            <div class="relative h-28 w-24 flex-none overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-800">
              <AuthedImage v-if="characterImage(character)" :src="characterImage(character)" :alt="character.name" class="h-full w-full object-cover" />
              <span v-else class="flex h-full w-full flex-col items-center justify-center gap-1 text-[11px] text-slate-400"><PhUserFocus :size="22" />{{ t('waitingPortrait') }}</span>
            </div>
            <div class="min-w-0 flex-1">
              <p class="font-medium text-slate-900 dark:text-slate-100">{{ character.name }}</p>
              <p class="mt-0.5 text-xs text-slate-500">{{ character.role }}</p>
              <div class="mt-2 flex flex-wrap gap-1.5">
                <span class="chip">{{ t(`source.${character.reference?.source || 'generate'}`) }}</span>
                <span class="state-chip" :class="previewTone(previews.characters?.[character.character_id], character.reference?.source !== 'generate')">{{ previewLabel(previews.characters?.[character.character_id], character.reference?.source !== 'generate') }}</span>
              </div>
              <p v-if="previews.characters?.[character.character_id]?.error" class="mt-2 text-xs text-red-600">{{ errorText(previews.characters[character.character_id].error) }}</p>
            </div>
          </div>
          <label class="field-label mt-3">{{ t('lockDescription') }}<textarea v-model="character.lock_description" class="field" rows="3" maxlength="600" :readonly="!canEditCharacters" /></label>
          <label v-if="character.reference?.source === 'generate' && canEditCharacters" class="field-label mt-2">{{ t('portraitPrompt') }}<textarea v-model="character.reference.generate_prompt" class="field" rows="3" maxlength="2000" /></label>
          <p v-else-if="character.reference?.generate_prompt" class="mt-2 line-clamp-3 text-xs leading-relaxed text-slate-500" :title="character.reference.generate_prompt">{{ character.reference.generate_prompt }}</p>
          <button v-if="character.reference?.source === 'generate' && reviewable" type="button" class="ghost-btn mt-3" :disabled="locked || dirty || charactersDirty" @click="askRegenerate('character', character.character_id, character.reference.generate_prompt)"><PhArrowClockwise :size="14" />{{ t('regenPortrait') }}</button>
        </article>
      </div>
      <div v-if="status === 'awaiting_characters'" class="action-bar mt-4">
        <p class="min-w-0 flex-1 text-xs text-slate-500 dark:text-slate-400">{{ charactersDirty ? t('charactersDirtyHint') : charactersIncomplete ? t('charactersBlockedHint') : t('charactersReadyHint') }}</p>
        <div class="flex flex-wrap gap-2">
          <button type="button" class="ghost-btn" :disabled="locked" @click="confirmReject">{{ t('reject') }}</button>
          <button v-if="charactersDirty" type="button" class="secondary-btn" :disabled="locked" @click="characterDraft = clone(story.characters || [])"><PhArrowCounterClockwise :size="14" />{{ t('undoCharacters') }}</button>
          <button type="button" class="primary-btn" :disabled="locked || charactersIncomplete || charactersInvalid" @click="submitCharacters">{{ charactersDirty ? t('saveCharacters') : t('approveCharacters') }}</button>
        </div>
      </div>
    </section>

    <!-- shots -->
    <section class="mt-7" :aria-label="t('shots')">
      <div class="section-head">
        <h4><PhFilmSlate :size="16" />{{ t('shots') }}<span class="count">{{ t('shotCount', { n: localPlan.shots.length, max: maxShots }) }}</span></h4>
      </div>
      <ol class="mt-3 grid grid-cols-[repeat(auto-fill,minmax(min(15rem,100%),1fr))] gap-3">
        <li v-for="shot in timelineShots" :key="shot.shot_id" class="shot" :class="hasIssue(shot.shot_id) ? 'border-red-300 dark:border-red-900' : ''">
          <button type="button" class="relative block aspect-video w-full overflow-hidden bg-slate-100 dark:bg-slate-800" :aria-label="`${t('viewShot')} ${shot.shot_id}`" @click="openShot(shot.shot_id)">
            <AuthedImage v-if="frameImage(shot)" :src="frameImage(shot)" :alt="shot.shot_id" class="h-full w-full object-cover" />
            <span v-else class="flex h-full w-full flex-col items-center justify-center gap-1.5 px-4 text-center text-xs text-slate-400">
              <PhArrowBendDownRight v-if="shot.first_frame.method === 'tail_frame'" :size="22" />
              <PhImage v-else :size="22" />
              {{ shot.first_frame.method === 'tail_frame' ? t('tailPending') : t('awaitingKeyframe') }}
            </span>
            <span class="overlay left-2 top-2 font-semibold">{{ shot.shot_id }}</span>
            <span class="overlay bottom-2 right-2 tabular-nums">{{ format(shot.start) }}–{{ format(shot.end) }}s</span>
            <span v-if="shot.first_frame.method !== 'tail_frame'" class="state-chip absolute right-2 top-2 shadow-sm" :class="previewTone(previews.keyframes?.[shot.shot_id], shot.first_frame.method === 'user_image', true)">{{ keyframeLabel(shot) }}</span>
          </button>
          <div class="flex flex-1 flex-col p-3">
            <div class="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span class="transition-chip" :class="`transition-${shot.transition_in}`"><component :is="transitionIcon[shot.transition_in] || PhPlay" :size="12" />{{ t(`transition.${shot.transition_in}`) }}</span>
              <span class="chip">{{ t('seconds', { n: format(shot.duration_sec) }) }}</span>
            </div>
            <button type="button" class="mt-2 line-clamp-3 text-left text-sm leading-relaxed text-slate-800 hover:text-blue-700 dark:text-slate-100 dark:hover:text-blue-300" :title="shot.summary" @click="openShot(shot.shot_id)">{{ shot.summary }}</button>
            <p class="mt-2 truncate text-xs text-slate-500" :title="`${shot.framing} · ${shot.motion.model_id}`">{{ shot.framing }} · {{ shot.motion.model_id }} · {{ money(priceFor(models, shot.motion.model_id, shot.duration_sec, 'second')) }} credits</p>
            <p v-if="shot.character_ids.length" class="mt-1 flex items-center gap-1 truncate text-xs text-slate-500"><PhUsers :size="12" class="flex-none" />{{ shot.character_ids.map(characterName).join('、') }}</p>
            <p v-if="previews.keyframes?.[shot.shot_id]?.error" class="mt-1 text-xs text-red-600">{{ errorText(previews.keyframes[shot.shot_id].error) }}</p>
            <div class="mt-auto flex flex-wrap gap-1.5 pt-3">
              <button type="button" class="ghost-btn" :disabled="locked" @click="openShot(shot.shot_id)"><component :is="canEdit ? PhPencilSimple : PhEye" :size="14" />{{ canEdit ? t('editShot') : t('viewShot') }}</button>
              <button v-if="canEdit && shot.first_frame.method === 'generate'" type="button" class="ghost-btn" :disabled="locked || dirty" @click="askRegenerate('keyframe', shot.shot_id, shot.first_frame.prompt)"><PhArrowClockwise :size="14" />{{ t('regenKeyframe') }}</button>
              <button v-if="canEdit && shot.end_frame?.method === 'generate'" type="button" class="ghost-btn" :disabled="locked || dirty" @click="askRegenerate('end_frame', shot.shot_id, shot.end_frame.prompt)"><PhArrowClockwise :size="14" />{{ t('regenEndFrame') }} · {{ previewLabel(previews.end_frames?.[shot.shot_id]) }}</button>
            </div>
          </div>
        </li>
      </ol>
    </section>

    <div v-if="visibleIssues.length" class="notice notice-amber mt-5 flex-col" role="status">
      <p class="flex items-center gap-1.5 font-medium"><PhWarning :size="16" />{{ t('issuesTitle') }} · <span class="font-normal">{{ dirty || shotDraft ? t('issuesLocal') : t('issuesServer') }}</span></p>
      <ul class="mt-1 space-y-1 text-xs">
        <li v-for="(issue, index) in visibleIssues" :key="`${issue.code}-${index}`" class="flex gap-2">
          <button v-if="issue.shot_id" type="button" class="flex-none font-semibold underline underline-offset-2" @click="openShot(issue.shot_id)">{{ issue.shot_id }}</button>
          <span>{{ issue.message || issue.code }}</span>
        </li>
      </ul>
    </div>

    <footer v-if="status === 'awaiting_storyboard'" class="sticky bottom-0 z-10 -mx-5 -mb-5 mt-5 space-y-2 rounded-b-2xl border-t border-slate-200 bg-white/95 px-5 py-3 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
      <div v-if="dirty" class="notice notice-blue">
        <PhInfo :size="16" class="mt-0.5 flex-none" />
        <span class="min-w-0 flex-1">{{ t('dirtyNotice') }}</span>
      </div>
      <div class="flex flex-wrap items-center justify-end gap-2">
        <p v-if="incomplete.length && !dirty" class="mr-auto min-w-0 flex-1 text-xs text-slate-500">{{ t('incompleteHint', { n: incomplete.length }) }}</p>
        <button type="button" class="ghost-btn" :disabled="locked" @click="confirmReject">{{ t('reject') }}</button>
        <template v-if="dirty">
          <button type="button" class="secondary-btn" :disabled="locked" @click="reload"><PhArrowCounterClockwise :size="14" />{{ t('undoPlan') }}</button>
          <button type="button" class="primary-btn" :disabled="locked" @click="savePlan">{{ t('savePlan') }}</button>
        </template>
        <template v-else>
          <button v-if="stale.length" type="button" class="secondary-btn" :disabled="locked" @click="askStale"><PhArrowClockwise :size="14" />{{ t('regenStale', { n: stale.length, cost: money(staleCost) }) }}</button>
          <button type="button" class="primary-btn" :disabled="locked || incomplete.length > 0 || issues.length > 0" @click="submit('approve_storyboard', { plan_version: baseVersion })"><PhCheckCircle :size="15" />{{ t('approveStoryboard') }}</button>
        </template>
      </div>
    </footer>

    <!-- confirmation modal -->
    <dialog ref="confirmDialog" class="confirm" :aria-label="confirmation?.title" @close="confirmation = null" @click="onConfirmBackdrop">
      <div v-if="confirmation" class="p-5">
        <div class="flex items-start gap-3">
          <span class="icon-tile" :class="confirmation.action === 'reject' ? 'bg-red-50 text-red-600 dark:bg-red-950/50 dark:text-red-400' : ''">
            <PhTrash v-if="confirmation.action === 'reject'" :size="18" /><PhArrowClockwise v-else :size="18" />
          </span>
          <div class="min-w-0">
            <p class="font-semibold text-slate-900 dark:text-white">{{ confirmation.title }}</p>
            <p class="mt-1.5 text-sm leading-relaxed text-slate-600 dark:text-slate-300">{{ confirmation.description }}</p>
            <p v-if="confirmation.cost != null" class="mt-3 flex items-center gap-1.5 rounded-lg bg-slate-50 px-3 py-2 text-sm dark:bg-slate-800"><PhCoins :size="15" class="text-slate-400" />{{ t('costAdd', { cost: money(confirmation.cost) }) }}</p>
            <p v-else-if="confirmation.action !== 'reject'" class="mt-3 text-xs text-slate-500">{{ t('costUnknown') }}</p>
          </div>
        </div>
        <p v-if="actionError" class="mt-3 text-sm text-red-600">{{ actionError }}</p>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="secondary-btn" :disabled="locked" @click="confirmDialog.close()">{{ t('cancel') }}</button>
          <button type="button" :class="confirmation.action === 'reject' ? 'danger-btn' : 'primary-btn'" :disabled="locked" @click="confirmAction">{{ confirmation.action === 'reject' ? t('confirmReject') : t('confirmRegen') }}</button>
        </div>
      </div>
    </dialog>

    <!-- shot drawer -->
    <dialog ref="drawer" class="drawer" @close="closeDrawer" @click="onBackdrop">
      <div v-if="shotDraft" class="flex min-h-full flex-col">
        <div class="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-5 py-3 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
          <div class="min-w-0">
            <h4 class="font-semibold text-slate-900 dark:text-white">{{ canEdit ? t('drawerEdit', { id: shotDraft.shot_id }) : t('drawerView', { id: shotDraft.shot_id }) }}</h4>
            <p class="mt-0.5 truncate text-xs text-slate-500">{{ t('drawerCost', { shot: money(priceFor(models, shotDraft.motion.model_id, shotDraft.duration_sec, 'second')), total: format(check.total), video: money(check.video) }) }}</p>
          </div>
          <button type="button" class="icon-btn" :aria-label="t('close')" @click="drawer.close()"><PhX :size="18" /></button>
        </div>
        <div class="flex-1 space-y-6 px-5 py-4">
          <div v-if="frameImage(shotDraft)" class="overflow-hidden rounded-xl bg-slate-100 dark:bg-slate-800">
            <AuthedImage :src="frameImage(shotDraft)" :alt="shotDraft.shot_id" class="aspect-video w-full object-contain" />
          </div>
          <fieldset class="space-y-3">
            <legend class="drawer-legend">{{ t('sectionScene') }}</legend>
            <label class="field-label">{{ t('summary') }}<textarea v-model="shotDraft.summary" class="field" rows="3" maxlength="300" :readonly="!canEdit" /></label>
            <label class="field-label">{{ t('framing') }}<input v-model="shotDraft.framing" class="field" maxlength="120" :readonly="!canEdit"></label>
          </fieldset>
          <fieldset class="space-y-3">
            <legend class="drawer-legend">{{ t('sectionTiming') }}</legend>
            <div class="grid gap-3 sm:grid-cols-2">
              <label class="field-label">{{ t('durationSec') }}<input v-model.number="shotDraft.duration_sec" type="number" class="field" min="0.01" :step="currentRange?.step || 'any'" :readonly="!canEdit"><span v-if="currentRange" class="font-normal text-slate-400">{{ t('range', { min: currentRange.min, max: currentRange.max, step: currentRange.step || t('anyStep') }) }}</span></label>
              <label class="field-label">{{ t('videoModel') }}<select v-model="shotDraft.motion.model_id" class="field" :disabled="!canEdit"><option v-for="model in optionsFor(shotDraft.motion.mode, shotDraft.motion.model_id)" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option></select></label>
            </div>
            <label class="field-label">{{ t('transitionIn') }}<select :value="shotDraft.transition_in" class="field" :disabled="!canEdit || shotDraft.order === 1 || shotDraft.transition_in === 'keyframe_bridge'" @change="changeTransition($event.target.value)"><option v-if="shotDraft.order === 1" value="start">{{ t('transitionOption.start') }}</option><template v-else><option value="independent">{{ t('transitionOption.independent') }}</option><option value="hard_cut">{{ t('transitionOption.hard_cut') }}</option><option value="tail_frame">{{ t('transitionOption.tail_frame') }}</option><option v-if="shotDraft.transition_in === 'keyframe_bridge'" value="keyframe_bridge">{{ t('transitionOption.keyframe_bridge') }}</option></template></select></label>
            <label v-if="shotDraft.first_frame.method === 'generate'" class="field-label">{{ t('firstFrameModel') }}<select v-model="shotDraft.first_frame.model_id" class="field" :disabled="!canEdit"><option v-for="model in optionsFor(shotDraft.first_frame.image_mode, shotDraft.first_frame.model_id)" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option></select></label>
            <label v-if="shotDraft.end_frame?.method === 'generate'" class="field-label">{{ t('endFrameModel') }}<select v-model="shotDraft.end_frame.model_id" class="field" :disabled="!canEdit"><option v-for="model in optionsFor(shotDraft.end_frame.image_mode, shotDraft.end_frame.model_id)" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option></select></label>
          </fieldset>
          <fieldset class="space-y-3">
            <legend class="drawer-legend">{{ t('sectionPrompts') }}</legend>
            <label v-if="shotDraft.first_frame.method === 'generate'" class="field-label">{{ t('firstFramePrompt') }}<textarea v-model="shotDraft.first_frame.prompt" class="field" rows="6" maxlength="8000" :readonly="!canEdit" /></label>
            <p v-else class="notice notice-slate"><PhInfo :size="15" class="mt-0.5 flex-none" />{{ shotDraft.first_frame.method === 'tail_frame' ? t('inheritedTail') : t('inheritedUser') }}</p>
            <label v-if="shotDraft.end_frame?.method === 'generate'" class="field-label">{{ t('endFramePrompt') }}<textarea v-model="shotDraft.end_frame.prompt" class="field" rows="4" maxlength="8000" :readonly="!canEdit" /></label>
            <label class="field-label">{{ t('motionPrompt') }}<textarea v-model="shotDraft.motion.prompt" class="field" rows="6" maxlength="8000" :readonly="!canEdit" /></label>
          </fieldset>
          <ul v-if="visibleIssues.length" class="notice notice-amber flex-col text-xs" aria-live="polite"><li v-for="(issue, index) in visibleIssues" :key="index">{{ issue.shot_id ? `${issue.shot_id} · ` : '' }}{{ issue.message || issue.code }}</li></ul>
        </div>
        <div v-if="canEdit" class="sticky bottom-0 flex items-center justify-between gap-3 border-t border-slate-200 bg-white/95 px-5 py-3 backdrop-blur dark:border-slate-700 dark:bg-slate-900/95">
          <p class="min-w-0 text-[11px] leading-snug text-slate-500">{{ t('drawerHint') }}</p>
          <button type="button" class="primary-btn flex-none" :disabled="locked" @click="applyShot">{{ t('applyShot') }}</button>
        </div>
      </div>
    </dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PhArrowBendDownRight, PhArrowClockwise, PhArrowCounterClockwise, PhArrowsLeftRight, PhCaretDown, PhCheck, PhCheckCircle,
  PhCircleNotch, PhClock, PhCoins, PhEye, PhFilmSlate, PhFilmStrip, PhGitFork, PhImage, PhInfo, PhPencilSimple, PhPlay,
  PhScissors, PhTrash, PhUserFocus, PhUsers, PhWarning, PhX,
} from '@phosphor-icons/vue'
import AuthedImage from './AuthedImage.vue'
import messages from './storyboard-messages'
import { clone, editedPlan, eligibleModels, incompleteTargets, localPlanCheck, previewFor, priceFor, staleTargets, targetCost, timeline } from './storyboard'

const props = defineProps({
  runId: { type: String, required: true }, plan: { type: Object, required: true }, story: { type: Object, default: () => ({}) },
  planVersion: { type: Number, required: true }, previews: { type: Object, default: () => ({}) }, estimates: { type: Object, default: () => ({}) },
  issues: { type: Array, default: () => [] }, models: { type: Array, default: () => [] }, spec: { type: Object, default: () => ({}) },
  status: { type: String, required: true }, disabled: Boolean, demo: Boolean, durationToleranceRatio: { type: Number, default: 0.1 }, keyframeBridgeEnabled: Boolean, maxShots: { type: Number, default: 30 },
})
const emit = defineEmits(['action', 'refresh'])
const { t, te } = useI18n({ useScope: 'local', messages })
const localPlan = ref(clone(props.plan)), original = ref(JSON.stringify(props.plan)), baseVersion = ref(props.planVersion)
const characterDraft = ref(clone(props.story.characters || [])), characterOriginal = ref(JSON.stringify(props.story.characters || []))
const actionEstimate = ref(null)
const drawer = ref(null), confirmDialog = ref(null), shotDraft = ref(null), savedFrame = ref(null), confirmation = ref(null), actionError = ref(''), pendingEdit = ref(false)
const dirty = computed(() => JSON.stringify(localPlan.value) !== original.value)
const drawerDirty = computed(() => shotDraft.value && JSON.stringify(shotDraft.value) !== JSON.stringify(localPlan.value.shots.find((shot) => shot.shot_id === shotDraft.value.shot_id)))
const charactersDirty = computed(() => JSON.stringify(characterDraft.value) !== characterOriginal.value)
const versionConflict = computed(() => props.planVersion !== baseVersion.value)
const locked = computed(() => props.disabled || versionConflict.value)
const reviewable = computed(() => ['awaiting_characters', 'awaiting_storyboard'].includes(props.status))
const canEdit = computed(() => props.status === 'awaiting_storyboard' && !locked.value)
const canEditCharacters = computed(() => props.status === 'awaiting_characters' && !locked.value)
const transitionIcon = { start: PhPlay, tail_frame: PhArrowBendDownRight, independent: PhGitFork, hard_cut: PhScissors, keyframe_bridge: PhArrowsLeftRight }
const statusText = computed(() => te(`status.${props.status}`) ? t(`status.${props.status}`) : props.status)
const statusTone = computed(() => ({ awaiting_characters: 'tone-amber', awaiting_storyboard: 'tone-amber', storyboard_approved: 'tone-emerald' }[props.status] || 'tone-blue'))
const hasGeneratedCharacters = computed(() => (props.story.characters || []).some((character) => character.reference?.source === 'generate'))
const reviewSteps = computed(() => {
  const order = ['awaiting_characters', 'awaiting_storyboard', 'storyboard_approved']
  const keys = hasGeneratedCharacters.value ? order : order.slice(1)
  const labels = { awaiting_characters: t('stepCharacters'), awaiting_storyboard: t('stepStoryboard'), storyboard_approved: t('stepApproved') }
  // Previewing between the two gates belongs to the storyboard step once characters are settled.
  const position = props.status === 'storyboard_approved' ? keys.length
    : Math.max(0, keys.indexOf(props.status === 'previewing' ? (charactersIncomplete.value && hasGeneratedCharacters.value ? 'awaiting_characters' : 'awaiting_storyboard') : props.status))
  return keys.map((key, index) => ({ key, label: labels[key], state: index < position || (key === 'storyboard_approved' && position === keys.length) ? 'done' : index === position ? 'current' : 'todo' }))
})
const previewPlan = computed(() => shotDraft.value ? editedPlan(localPlan.value, shotDraft.value) : localPlan.value)
const check = computed(() => localPlanCheck(previewPlan.value, props.story, props.models, props.spec, { durationToleranceRatio: props.durationToleranceRatio, keyframeBridgeEnabled: props.keyframeBridgeEnabled, maxShots: props.maxShots }))
const timelineShots = computed(() => timeline(previewPlan.value))
const barScale = computed(() => Math.max(check.value.total, check.value.target + check.value.tolerance, 1))
const sceneIndex = computed(() => Object.fromEntries((previewPlan.value.scenes || []).map((scene, index) => [scene.scene_id, index])))
const SCENE_TONES = ['scene-0', 'scene-1', 'scene-2', 'scene-3', 'scene-4', 'scene-5']
const sceneTone = (sceneId) => SCENE_TONES[(sceneIndex.value[sceneId] ?? 0) % SCENE_TONES.length]
const styleChips = computed(() => [props.story.style?.visual_style, props.story.style?.palette, props.story.style?.lighting, props.story.style?.camera_language].filter(Boolean))
const durationIssue = computed(() => check.value.issues.some((issue) => issue.code === 'DURATION_MISMATCH'))
const visibleIssues = computed(() => {
  const candidates = dirty.value || shotDraft.value ? check.value.issues : [...props.issues, ...check.value.issues]
  return candidates.filter((issue, index) => candidates.findIndex((other) => other.code === issue.code && other.shot_id === issue.shot_id) === index)
})
const hasIssue = (shotId) => visibleIssues.value.some((issue) => issue.shot_id === shotId)
const stale = computed(() => staleTargets(props.plan, props.previews))
const staleCost = computed(() => targetCost(stale.value, props.models, props.previews))
const incomplete = computed(() => incompleteTargets(props.plan, props.previews))
const charactersIncomplete = computed(() => (props.story.characters || []).some((character) => character.reference.source === 'generate' && (props.previews.characters?.[character.character_id]?.status !== 'success' || props.previews.characters?.[character.character_id]?.stale)))
const charactersInvalid = computed(() => characterDraft.value.some((character) => !character.lock_description?.trim() || character.reference.source === 'generate' && !character.reference.generate_prompt?.trim()))
const currentRange = computed(() => props.models.find((model) => model.model_id === shotDraft.value?.motion?.model_id)?.capabilities?.duration)
const format = (value) => Number.isFinite(value) ? String(Math.round(value * 100) / 100) : '—'
const money = (value) => value == null ? t('serverEstimate') : format(value)
const errorText = (value) => typeof value === 'string' ? value : value?.message || value?.summary || value?.code || t('generationFailed')
const characterName = (id) => props.story.characters?.find((character) => character.character_id === id)?.name || id
const isStale = (preview) => preview?.stale || preview?.status === 'stale'
const previewLabel = (preview, supplied = false) => isStale(preview) ? t('preview.stale')
  : ['success', 'failed', 'running', 'pending', 'cancelled'].includes(preview?.status) ? t(`preview.${preview.status}`)
    : supplied ? t('preview.supplied') : t('preview.todo')
// Keyframes are only produced after the character gate, so "queued" would mislead there.
const keyframeLabel = (shot) => {
  const preview = props.previews.keyframes?.[shot.shot_id]
  if (props.status === 'awaiting_characters' && shot.first_frame.method === 'generate' && (!preview || preview.status === 'pending')) return t('afterCharacters')
  return previewLabel(preview, shot.first_frame.method === 'user_image')
}
const previewTone = (preview, supplied = false, overlay = false) => isStale(preview) ? 'state-amber'
  : preview?.status === 'failed' ? 'state-red'
    : preview?.status === 'success' || supplied ? 'state-emerald'
      : preview?.status === 'running' ? 'state-blue' : overlay ? 'state-overlay' : 'state-slate'
const artifactUrl = (id) => id ? `/api/artifacts/${encodeURIComponent(id)}/preview` : null
const characterImage = (character) => props.previews.characters?.[character.character_id]?.preview_url || artifactUrl(character.reference.artifact_ids?.[0])
const frameImage = (shot) => props.previews.keyframes?.[shot.shot_id]?.preview_url || (shot.first_frame.method === 'user_image' ? artifactUrl(shot.first_frame.reference_artifact_ids?.[0]) : null)
function optionsFor(mode, current) {
  const models = eligibleModels(props.models, mode, props.spec)
  return current && !models.some((model) => model.model_id === current) ? [{ model_id: current, display_name: t('currentModel', { id: current }) }, ...models] : models
}
function reset() {
  localPlan.value = clone(props.plan); original.value = JSON.stringify(props.plan); baseVersion.value = props.planVersion
  characterDraft.value = clone(props.story.characters || []); characterOriginal.value = JSON.stringify(props.story.characters || [])
  confirmation.value = null; actionError.value = ''; pendingEdit.value = false
  drawer.value?.close()
}
function reload() { reset(); emit('refresh') }
watch(() => [props.runId, props.planVersion], (next, previous) => {
  if (next[0] !== previous[0] || !dirty.value && !charactersDirty.value && !drawerDirty.value || pendingEdit.value) reset()
})
watch(confirmation, async (value) => {
  await nextTick()
  if (value && !confirmDialog.value?.open) confirmDialog.value?.showModal()
  if (!value && confirmDialog.value?.open) confirmDialog.value.close()
})
async function openShot(id) {
  if (props.disabled) return
  shotDraft.value = clone(localPlan.value.shots.find((shot) => shot.shot_id === id))
  savedFrame.value = shotDraft.value.first_frame.method === 'generate' ? clone(shotDraft.value.first_frame) : null
  await nextTick(); drawer.value?.showModal()
}
function closeDrawer() { shotDraft.value = null; savedFrame.value = null }
function onBackdrop(event) { if (event.target === drawer.value) drawer.value.close() }
function onConfirmBackdrop(event) { if (event.target === confirmDialog.value) confirmDialog.value.close() }
function applyShot() { localPlan.value = editedPlan(localPlan.value, shotDraft.value); drawer.value.close() }
function changeTransition(value) {
  shotDraft.value.transition_in = value
  if (value === 'tail_frame') {
    if (shotDraft.value.first_frame.method === 'generate') savedFrame.value = clone(shotDraft.value.first_frame)
    shotDraft.value.first_frame = { method: 'tail_frame', image_mode: null, model_id: null, prompt: '', reference_artifact_ids: [] }
  } else if (shotDraft.value.first_frame.method === 'tail_frame') {
    const refs = [...new Set(shotDraft.value.character_ids.flatMap((id) => props.story.characters?.find((character) => character.character_id === id)?.reference.artifact_ids || []))]
    const imageMode = refs.length ? 'i2i' : 't2i'
    const prior = localPlan.value.shots.find((shot) => shot.first_frame.method === 'generate' && shot.first_frame.image_mode === imageMode)?.first_frame
    shotDraft.value.first_frame = savedFrame.value || { method: 'generate', image_mode: imageMode, model_id: prior?.model_id || '', prompt: '', reference_artifact_ids: refs }
  }
  shotDraft.value.depends_on = value === 'tail_frame' ? [localPlan.value.shots[shotDraft.value.order - 2]?.shot_id].filter(Boolean) : []
}
function submit(action, payload = {}) {
  if (locked.value) return
  actionError.value = ''; actionEstimate.value = null
  emit('action', { action, payload, onSuccess: (result) => {
    confirmation.value = null
    if (['edit_plan', 'approve_characters'].includes(action)) pendingEdit.value = true
    if (['regenerate', 'regenerate_stale'].includes(action) && Number.isFinite(result?.action_estimated_credits)) actionEstimate.value = result.action_estimated_credits
  }, onError: (error) => { pendingEdit.value = false; actionError.value = error } })
}
function savePlan() { submit('edit_plan', { plan: clone(localPlan.value), base_version: baseVersion.value }) }
function submitCharacters() {
  const edits = characterDraft.value.flatMap((character) => {
    const old = props.story.characters.find((item) => item.character_id === character.character_id)
    const edit = { character_id: character.character_id }
    if (character.lock_description !== old.lock_description) edit.lock_description = character.lock_description
    if (character.reference.generate_prompt !== old.reference.generate_prompt) edit.generate_prompt = character.reference.generate_prompt
    return Object.keys(edit).length > 1 ? [edit] : []
  })
  submit('approve_characters', edits.length ? { edits } : {})
}
function askRegenerate(type, id, prompt) {
  const preview = previewFor(props.previews, type, id)
  const shot = props.plan.shots.find((item) => item.shot_id === id)
  const frame = type === 'keyframe' ? shot?.first_frame : shot?.end_frame
  const affected = type === 'character' ? props.plan.shots.filter((item) => item.character_ids.includes(id) && (item.first_frame.method === 'generate' || item.end_frame?.method === 'generate')).map((item) => item.shot_id) : []
  actionError.value = ''
  confirmation.value = {
    action: 'regenerate', payload: { target_type: type, target_id: id, ...(prompt ? { prompt } : {}) },
    title: t(`regenTitle.${type}`, { name: type === 'character' ? characterName(id) : id }),
    cost: type === 'character' ? (Number.isFinite(preview?.estimated_cost) ? preview.estimated_cost : null) : frame ? targetCost([{ type, id, frame }], props.models, props.previews) : null,
    description: affected.length ? t('regenAffects', { shots: affected.join('、') }) : t('regenOnly'),
  }
}
function askStale() {
  actionError.value = ''
  confirmation.value = { action: 'regenerate_stale', payload: {}, title: t('staleTitle', { n: stale.value.length }), cost: staleCost.value, description: t('staleScope', { list: stale.value.map((item) => `${item.id}${item.type === 'end_frame' ? t('endFrameSuffix') : ''}`).join('、') }) }
}
function confirmReject() { actionError.value = ''; confirmation.value = { action: 'reject', payload: {}, title: t('rejectTitle'), description: t('rejectDesc') } }
function confirmAction() { const value = confirmation.value; submit(value.action, value.payload) }
</script>

<style scoped>
.card { @apply rounded-2xl border border-slate-200 bg-white p-5 text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200; }
.icon-tile { @apply flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400; }
.status-pill { @apply inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium; }
.tone-amber { @apply bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300; }
.tone-emerald { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.tone-blue { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.step { @apply inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1; }
.step-done { @apply border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300; }
.step-current { @apply border-blue-300 bg-blue-50 font-medium text-blue-700 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-300; }
.step-todo { @apply border-slate-200 text-slate-400 dark:border-slate-700; }
.notice { @apply flex gap-2 rounded-xl px-3 py-2.5 text-sm; }
.notice-amber { @apply bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200; }
.notice-red { @apply bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300; }
.notice-emerald { @apply bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200; }
.notice-blue { @apply bg-blue-50 text-blue-800 dark:bg-blue-950/40 dark:text-blue-200; }
.notice-slate { @apply bg-slate-50 text-xs text-slate-600 dark:bg-slate-800/60 dark:text-slate-300; }
.segment { @apply min-w-0 overflow-hidden rounded-md py-1 text-white transition hover:brightness-110 focus:z-10 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-900 focus-visible:ring-offset-1; }
.scene-0 { @apply bg-blue-600; }
.scene-1 { @apply bg-violet-600; }
.scene-2 { @apply bg-teal-600; }
.scene-3 { @apply bg-amber-600; }
.scene-4 { @apply bg-rose-600; }
.scene-5 { @apply bg-sky-600; }
.target-marker { @apply pointer-events-none absolute -bottom-1 -top-1 w-0.5 -translate-x-1/2 rounded-full bg-slate-900 dark:bg-white; }
.stat { @apply flex flex-col gap-1 rounded-lg bg-white px-3 py-2.5 ring-1 ring-slate-200 dark:bg-slate-900 dark:ring-slate-700; }
.stat span { @apply flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400; }
.stat strong { @apply flex items-baseline gap-1 break-words text-base font-semibold tabular-nums text-slate-900 dark:text-white; }
.stat small { @apply text-[11px] font-normal text-slate-400; }
.chip { @apply inline-flex items-center rounded-md bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.state-chip { @apply inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium; }
.state-emerald { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-300; }
.state-amber { @apply bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300; }
.state-red { @apply bg-red-50 text-red-700 dark:bg-red-950/60 dark:text-red-300; }
.state-blue { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/60 dark:text-blue-300; }
.state-slate { @apply bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400; }
.state-overlay { @apply bg-white/90 text-slate-600 dark:bg-slate-900/90 dark:text-slate-300; }
.section-head h4 { @apply flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100; }
.section-head p { @apply mt-1 text-xs text-slate-500 dark:text-slate-400; }
.count { @apply ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400; }
.panel { @apply rounded-xl border border-slate-200 p-3 dark:border-slate-700; }
.action-bar { @apply flex flex-wrap items-center gap-3 rounded-xl bg-slate-50 px-3 py-2.5 dark:bg-slate-800/50; }
.shot { @apply flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white transition hover:shadow-sm dark:border-slate-700 dark:bg-slate-900; }
.overlay { @apply absolute rounded-md bg-slate-900/75 px-1.5 py-0.5 text-[11px] text-white backdrop-blur-sm; }
.transition-chip { @apply inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-medium; }
.transition-start { @apply bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200; }
.transition-tail_frame { @apply bg-violet-50 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300; }
.transition-independent { @apply bg-sky-50 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300; }
.transition-hard_cut { @apply bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.transition-keyframe_bridge { @apply bg-teal-50 text-teal-700 dark:bg-teal-950/50 dark:text-teal-300; }
.field-label { @apply flex flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400; }
.field { @apply w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 read-only:bg-slate-50 disabled:bg-slate-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:read-only:bg-slate-900 dark:disabled:bg-slate-900; }
.primary-btn { @apply inline-flex items-center justify-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.danger-btn { @apply inline-flex items-center justify-center gap-1.5 rounded-xl bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
.ghost-btn { @apply inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-white; }
.icon-btn { @apply flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-white; }
.drawer { @apply fixed inset-y-0 left-auto right-0 m-0 h-full max-h-full w-full max-w-xl overflow-y-auto border-0 bg-white p-0 text-slate-800 shadow-2xl dark:bg-slate-900 dark:text-slate-200; }
.drawer::backdrop, .confirm::backdrop { background: rgb(15 23 42 / 0.5); backdrop-filter: blur(2px); }
.drawer-legend { @apply mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400; }
.confirm { @apply m-auto w-[calc(100%-2rem)] max-w-md rounded-2xl border-0 bg-white p-0 text-slate-800 shadow-2xl dark:bg-slate-900 dark:text-slate-200; }
</style>
