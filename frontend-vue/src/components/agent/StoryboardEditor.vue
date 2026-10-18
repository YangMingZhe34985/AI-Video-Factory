<template>
  <section class="card min-w-0" data-testid="storyboard-editor">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div><h3 class="font-semibold text-slate-900 dark:text-white">{{ plan.title || '分镜板' }}</h3><p class="mt-1 text-xs text-slate-500">审核 A · 版本 {{ baseVersion }} · 只生成预览图片，视频生产在下一阶段开放</p></div>
      <span class="tag">{{ statusText }}</span>
    </header>
    <div v-if="versionConflict" role="alert" class="mt-4 rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
      服务器计划已更新，当前编辑基于旧版本。<button type="button" class="ml-2 underline" @click="reload">刷新为最新版本（放弃本地修改）</button>
    </div>
    <p v-if="actionError" role="alert" class="mt-3 break-words text-sm text-red-600">{{ actionError }}</p>
    <p v-if="status === 'storyboard_approved'" class="mt-4 rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300">分镜已确认。本阶段停在这里，未提交视频模型任务。</p>
    <div class="mt-5 flex flex-wrap items-baseline justify-between gap-2 text-sm">
      <span><strong class="tabular-nums">{{ format(check.total) }} 秒</strong> / 目标 {{ check.target }} 秒</span>
      <span :class="durationIssue ? 'text-red-600' : 'text-slate-500'">容差 ±{{ format(check.tolerance) }} 秒</span>
    </div>
    <div class="mt-2 flex h-9 gap-0.5 overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-800" aria-label="镜头时长分布">
      <button v-for="(shot, index) in timelineShots" :key="shot.shot_id" type="button" :title="`${shot.shot_id}：${format(shot.duration_sec)} 秒，${shot.summary}`" :style="{ flexGrow: Math.max(shot.duration_sec || 0, 0.1), flexBasis: 0 }" class="min-w-0 overflow-hidden text-xs font-semibold text-white focus:z-10 focus:outline focus:outline-2 focus:outline-blue-900" :class="index % 2 ? 'bg-blue-400' : 'bg-blue-600'" @click="openShot(shot.shot_id)"><span class="block truncate px-1">{{ shot.shot_id }}</span></button>
    </div>
    <div class="mt-4 grid gap-2 text-sm sm:grid-cols-3">
      <div class="cost"><span>预览已花</span><strong>{{ money(estimates.preview_spent_credits) }} credits</strong></div>
      <div class="cost"><span>视频预计 · 按秒</span><strong>{{ money(check.video) }} credits</strong></div>
      <div class="cost"><span>累计已花 · 含规划</span><strong>{{ money(estimates.spent_credits) }} credits</strong></div>
    </div>
    <p class="mt-2 text-xs text-slate-400">本地估算与检查供编辑参考；模型能力、预算、时长容差以服务器最终校验为准。{{ demo ? 'Mock 模式：模型单价与素材均为演示数据。' : '' }}</p>
    <details v-if="story.story" class="mt-4 text-sm">
      <summary class="cursor-pointer text-slate-600 dark:text-slate-300">故事与风格 · {{ story.story.logline }}</summary>
      <p class="mt-2 whitespace-pre-wrap text-slate-600 dark:text-slate-300">{{ story.story.synopsis }}</p>
      <p class="mt-2 text-xs text-slate-500">{{ [story.style?.visual_style, story.style?.palette, story.style?.lighting, story.style?.camera_language].filter(Boolean).join(' · ') }}</p>
    </details>

    <section v-if="story.characters?.length" class="mt-6" aria-label="角色定妆">
      <h4 class="text-sm font-semibold">角色一致性</h4>
      <div class="mt-3 grid gap-3 xl:grid-cols-2">
        <article v-for="character in characterDraft" :key="character.character_id" class="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
          <div class="flex items-start gap-3">
            <AuthedImage v-if="characterImage(character)" :src="characterImage(character)" :alt="`${character.name}参考图`" class="h-20 w-20 flex-none rounded-lg bg-slate-100 object-contain dark:bg-slate-800" />
            <div v-else class="flex h-20 w-20 flex-none items-center justify-center rounded-lg bg-slate-100 text-xs text-slate-400 dark:bg-slate-800">等待定妆图</div>
            <div class="min-w-0"><p class="font-medium">{{ character.name }}</p><p class="mt-1 text-xs text-slate-500">{{ sourceLabels[character.reference?.source] }} · {{ character.role }}</p><p class="mt-1 text-xs" :class="previewTone(previews.characters?.[character.character_id])">{{ previewLabel(previews.characters?.[character.character_id], character.reference?.source !== 'generate') }}</p></div>
          </div>
          <label class="field-label mt-3">外观锁定描述<textarea v-model="character.lock_description" class="field" rows="3" maxlength="600" :readonly="!canEditCharacters" /></label>
          <label v-if="character.reference?.source === 'generate' && canEditCharacters" class="field-label mt-2">定妆提示词<textarea v-model="character.reference.generate_prompt" class="field" rows="3" maxlength="2000" /></label>
          <p v-else-if="character.reference?.generate_prompt" class="mt-2 text-xs text-slate-500">{{ character.reference.generate_prompt }}</p>
          <p v-if="previews.characters?.[character.character_id]?.error" class="mt-2 text-xs text-red-600">{{ errorText(previews.characters[character.character_id].error) }}</p>
          <button v-if="character.reference?.source === 'generate' && reviewable" type="button" class="secondary-btn mt-3" :disabled="locked || dirty || charactersDirty && !canEditCharacters" @click="askRegenerate('character', character.character_id, character.reference.generate_prompt)">重做定妆图</button>
        </article>
      </div>
      <div v-if="status === 'awaiting_characters'" class="mt-4 flex flex-wrap gap-3">
        <button type="button" class="primary-btn" :disabled="locked || charactersIncomplete || charactersInvalid" @click="submitCharacters">确认角色并生成关键帧</button>
        <button type="button" class="secondary-btn" :disabled="locked" @click="confirmReject">放弃计划</button>
      </div>
      <p v-if="status === 'awaiting_characters'" class="mt-2 text-xs text-slate-500">请先重做失败的定妆图。确认后会按图片模型计费生成关键帧。</p>
    </section>

    <section class="mt-6" aria-label="镜头时间线">
      <h4 class="text-sm font-semibold">镜头时间线 · {{ localPlan.shots.length }} 个镜头</h4>
      <ol class="mt-3 space-y-3">
        <li v-for="shot in timelineShots" :key="shot.shot_id" class="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
          <div class="flex flex-col gap-3 sm:flex-row">
            <button type="button" class="relative flex h-24 w-full flex-none items-center justify-center overflow-hidden rounded-lg bg-slate-100 text-xs text-slate-500 sm:w-36 dark:bg-slate-800" :aria-label="`查看镜头 ${shot.shot_id}`" @click="openShot(shot.shot_id)">
              <AuthedImage v-if="frameImage(shot)" :src="frameImage(shot)" :alt="`${shot.shot_id}关键帧`" class="h-full w-full object-contain" />
              <span v-else>{{ shot.first_frame.method === 'tail_frame' ? '等待上一镜头尾帧' : '等待关键帧' }}</span>
              <span class="absolute bottom-1 right-1 rounded bg-slate-900/80 px-1.5 py-0.5 text-white">{{ format(shot.duration_sec) }} 秒</span>
            </button>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center gap-2 text-xs"><strong>{{ shot.shot_id }}</strong><span class="text-slate-400 tabular-nums">{{ format(shot.start) }}–{{ format(shot.end) }} 秒</span><span class="tag">{{ transitionLabels[shot.transition_in] || shot.transition_in }}</span><span :class="previewTone(previews.keyframes?.[shot.shot_id])">{{ shot.first_frame.method === 'tail_frame' ? '视频生产阶段取尾帧 · 串行' : previewLabel(previews.keyframes?.[shot.shot_id], shot.first_frame.method === 'user_image') }}</span></div>
              <button type="button" class="mt-2 block w-full text-left text-sm font-medium hover:text-blue-600" @click="openShot(shot.shot_id)">{{ shot.summary }}</button>
              <p class="mt-1 text-xs text-slate-500">{{ shot.framing }} · {{ shot.motion.model_id }} · {{ money(priceFor(models, shot.motion.model_id, shot.duration_sec, 'second')) }} credits</p>
              <p v-if="shot.character_ids.length" class="mt-1 text-xs text-slate-500">角色：{{ shot.character_ids.map(characterName).join('、') }} · 复用锁定外观与参考图</p>
              <p v-if="previews.keyframes?.[shot.shot_id]?.error" class="mt-1 text-xs text-red-600">{{ errorText(previews.keyframes[shot.shot_id].error) }}</p>
              <div class="mt-2 flex flex-wrap gap-2">
                <button type="button" class="secondary-btn" :disabled="locked" @click="openShot(shot.shot_id)">{{ canEdit ? '编辑镜头' : '查看镜头' }}</button>
                <button v-if="canEdit && shot.first_frame.method === 'generate'" type="button" class="secondary-btn" :disabled="locked || dirty" @click="askRegenerate('keyframe', shot.shot_id, shot.first_frame.prompt)">重做关键帧</button>
                <button v-if="canEdit && shot.end_frame?.method === 'generate'" type="button" class="secondary-btn" :disabled="locked || dirty" @click="askRegenerate('end_frame', shot.shot_id, shot.end_frame.prompt)">重做尾帧 · {{ previewLabel(previews.end_frames?.[shot.shot_id]) }}</button>
              </div>
            </div>
          </div>
        </li>
      </ol>
    </section>

    <div v-if="visibleIssues.length" class="mt-4 rounded-lg bg-amber-50 p-3 dark:bg-amber-950/40" role="status">
      <p class="text-sm font-medium text-amber-800 dark:text-amber-300">计划检查 · {{ dirty || shotDraft ? '本地修改预检，保存后由服务器重新校验' : '审核前需处理' }}</p>
      <ul class="mt-2 space-y-1 text-xs text-amber-800 dark:text-amber-300"><li v-for="(issue, index) in visibleIssues" :key="`${issue.code}-${index}`">{{ issue.shot_id ? `${issue.shot_id} · ` : '' }}{{ issue.message || issue.code }}</li></ul>
    </div>
    <footer v-if="status === 'awaiting_storyboard'" class="mt-5 space-y-3">
      <div v-if="dirty" class="flex flex-wrap items-center gap-3 rounded-lg bg-blue-50 p-3 dark:bg-blue-950/40">
        <span class="text-sm">存在未保存修改。保存会新建版本，受影响的提示词由 Agent 重写；旧预览保留并标记过期，不自动重做。</span>
        <button type="button" class="primary-btn" :disabled="locked" @click="savePlan">保存计划修改</button><button type="button" class="secondary-btn" :disabled="locked" @click="reload">撤销本地修改</button>
      </div>
      <div class="flex flex-wrap gap-3">
        <button v-if="stale.length" type="button" class="secondary-btn" :disabled="locked || dirty" @click="askStale">重新生成过期关键帧（{{ stale.length }} 张，约 {{ money(staleCost) }} credits）</button>
        <button type="button" class="primary-btn" :disabled="locked || dirty || incomplete.length > 0 || issues.length > 0" @click="submit('approve_storyboard', { plan_version: baseVersion })">确认分镜</button>
        <button type="button" class="secondary-btn" :disabled="locked" @click="confirmReject">放弃计划</button>
      </div>
      <p v-if="incomplete.length" class="text-xs text-slate-500">还有 {{ incomplete.length }} 张预览未完成或已过期；先处理后再确认分镜。仅重做失败/过期图片，不重跑其他已完成镜头。</p>
    </footer>
    <div v-if="confirmation" class="mt-4 rounded-xl border border-blue-300 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950/40" role="alertdialog" aria-label="确认本次操作">
      <p class="text-sm font-medium">{{ confirmation.title }}</p><p class="mt-2 text-sm text-slate-600 dark:text-slate-300">{{ confirmation.description }}</p>
      <p v-if="confirmation.cost != null" class="mt-2 text-sm">预计增加 {{ money(confirmation.cost) }} credits；服务器会再次检查剩余预算。</p>
      <p v-else-if="confirmation.action !== 'reject'" class="mt-2 text-xs text-slate-500">本地无法准确计算本次费用，将由服务器做预算校验。</p>
      <div class="mt-3 flex gap-3"><button type="button" class="primary-btn" :disabled="locked" @click="confirmAction">确认{{ confirmation.action === 'reject' ? '放弃' : '重做' }}</button><button type="button" class="secondary-btn" :disabled="locked" @click="confirmation = null">取消</button></div>
    </div>

    <dialog ref="drawer" class="drawer" @close="closeDrawer" @click="onBackdrop">
      <div v-if="shotDraft" class="p-5">
        <div class="flex items-center justify-between gap-3"><h4 class="font-semibold">{{ shotDraft.shot_id }} · {{ canEdit ? '编辑镜头' : '镜头详情' }}</h4><button type="button" class="secondary-btn" @click="drawer.close()">关闭</button></div>
        <p class="mt-2 text-xs text-slate-500">本镜头 {{ money(priceFor(models, shotDraft.motion.model_id, shotDraft.duration_sec, 'second')) }} credits；全片 {{ format(check.total) }} 秒，视频预计 {{ money(check.video) }} credits。</p>
        <div class="mt-4 space-y-3">
          <label class="field-label">画面内容<textarea v-model="shotDraft.summary" class="field" rows="3" maxlength="300" :readonly="!canEdit" /></label>
          <label class="field-label">景别 / 构图<input v-model="shotDraft.framing" class="field" maxlength="120" :readonly="!canEdit" /></label>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="field-label">时长（秒）<input v-model.number="shotDraft.duration_sec" type="number" class="field" min="0.01" :step="currentRange?.step || 'any'" :readonly="!canEdit" /><span v-if="currentRange">能力范围 {{ currentRange.min }}–{{ currentRange.max }} 秒，步长 {{ currentRange.step || '不限' }}</span></label>
            <label class="field-label">视频模型<select v-model="shotDraft.motion.model_id" class="field" :disabled="!canEdit"><option v-for="model in optionsFor(shotDraft.motion.mode, shotDraft.motion.model_id)" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option></select></label>
          </div>
          <label class="field-label">衔接方式<select :value="shotDraft.transition_in" class="field" :disabled="!canEdit || shotDraft.order === 1 || shotDraft.transition_in === 'keyframe_bridge'" @change="changeTransition($event.target.value)"><option v-if="shotDraft.order === 1" value="start">起始镜头</option><template v-else><option value="independent">独立镜头 · 可并行</option><option value="hard_cut">硬切 · 可并行</option><option value="tail_frame">承接上一镜头尾帧 · 串行</option><option v-if="shotDraft.transition_in === 'keyframe_bridge'" value="keyframe_bridge">首尾帧衔接 · 候选方式</option></template></select></label>
          <template v-if="shotDraft.first_frame.method === 'generate'">
            <label class="field-label">首帧模型<select v-model="shotDraft.first_frame.model_id" class="field" :disabled="!canEdit"><option v-for="model in optionsFor(shotDraft.first_frame.image_mode, shotDraft.first_frame.model_id)" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option></select></label>
            <label class="field-label">首帧提示词 · 静态画面<textarea v-model="shotDraft.first_frame.prompt" class="field" rows="6" maxlength="8000" :readonly="!canEdit" /></label>
          </template>
          <p v-else class="text-xs text-slate-500">首帧使用{{ shotDraft.first_frame.method === 'tail_frame' ? '上一个镜头的尾帧，须等它完成视频生成' : '用户上传图片' }}。</p>
          <template v-if="shotDraft.end_frame?.method === 'generate'">
            <label class="field-label">尾帧模型<select v-model="shotDraft.end_frame.model_id" class="field" :disabled="!canEdit"><option v-for="model in optionsFor(shotDraft.end_frame.image_mode, shotDraft.end_frame.model_id)" :key="model.model_id" :value="model.model_id">{{ model.display_name || model.model_id }}</option></select></label>
            <label class="field-label">尾帧提示词<textarea v-model="shotDraft.end_frame.prompt" class="field" rows="4" maxlength="8000" :readonly="!canEdit" /></label>
          </template>
          <label class="field-label">动作提示词 · 动态与运镜<textarea v-model="shotDraft.motion.prompt" class="field" rows="6" maxlength="8000" :readonly="!canEdit" /></label>
          <ul v-if="visibleIssues.length" class="space-y-1 text-xs text-amber-700 dark:text-amber-300" aria-live="polite"><li v-for="(issue, index) in visibleIssues" :key="index">{{ issue.shot_id }} {{ issue.message || issue.code }}</li></ul>
          <p class="text-xs text-slate-500">只修改当前镜头。保存计划后由 Agent 重写受影响的提示词并检查角色引用；图片重做仍需单独确认。</p>
          <button v-if="canEdit" type="button" class="primary-btn" :disabled="locked" @click="applyShot">应用到本地计划</button>
        </div>
      </div>
    </dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import AuthedImage from './AuthedImage.vue'
import { clone, editedPlan, eligibleModels, incompleteTargets, localPlanCheck, previewFor, priceFor, staleTargets, targetCost, timeline } from './storyboard'

const props = defineProps({
  runId: { type: String, required: true }, plan: { type: Object, required: true }, story: { type: Object, default: () => ({}) },
  planVersion: { type: Number, required: true }, previews: { type: Object, default: () => ({}) }, estimates: { type: Object, default: () => ({}) },
  issues: { type: Array, default: () => [] }, models: { type: Array, default: () => [] }, spec: { type: Object, default: () => ({}) },
  status: { type: String, required: true }, disabled: Boolean, demo: Boolean, durationToleranceRatio: { type: Number, default: 0.1 }, keyframeBridgeEnabled: Boolean,
})
const emit = defineEmits(['action', 'refresh'])
const localPlan = ref(clone(props.plan)), original = ref(JSON.stringify(props.plan)), baseVersion = ref(props.planVersion)
const characterDraft = ref(clone(props.story.characters || [])), characterOriginal = ref(JSON.stringify(props.story.characters || []))
const drawer = ref(null), shotDraft = ref(null), savedFrame = ref(null), confirmation = ref(null), actionError = ref(''), pendingEdit = ref(false)
const dirty = computed(() => JSON.stringify(localPlan.value) !== original.value)
const charactersDirty = computed(() => JSON.stringify(characterDraft.value) !== characterOriginal.value)
const versionConflict = computed(() => props.planVersion !== baseVersion.value)
const locked = computed(() => props.disabled || versionConflict.value)
const reviewable = computed(() => ['awaiting_characters', 'awaiting_storyboard'].includes(props.status))
const canEdit = computed(() => props.status === 'awaiting_storyboard' && !locked.value)
const canEditCharacters = computed(() => props.status === 'awaiting_characters' && !locked.value)
const sourceLabels = { research: '检索资料', attachment: '用户附件', generate: '定妆生成' }
const transitionLabels = { start: '● 起始', tail_frame: '→ 尾帧承接', independent: '⑂ 独立并行', hard_cut: '│ 硬切并行', keyframe_bridge: '⇢ 首尾帧衔接' }
const statusText = computed(() => ({ planning: '规划中', previewing: '预览生成中', awaiting_characters: '等待确认角色', awaiting_storyboard: '等待确认分镜', storyboard_approved: '分镜已确认' }[props.status] || props.status))
const previewPlan = computed(() => shotDraft.value ? editedPlan(localPlan.value, shotDraft.value) : localPlan.value)
const check = computed(() => localPlanCheck(previewPlan.value, props.story, props.models, props.spec, { durationToleranceRatio: props.durationToleranceRatio, keyframeBridgeEnabled: props.keyframeBridgeEnabled }))
const timelineShots = computed(() => timeline(previewPlan.value))
const durationIssue = computed(() => check.value.issues.some((issue) => issue.code === 'DURATION_MISMATCH'))
const visibleIssues = computed(() => {
  const candidates = dirty.value || shotDraft.value ? check.value.issues : [...props.issues, ...check.value.issues]
  return candidates.filter((issue, index) => candidates.findIndex((other) => other.code === issue.code && other.shot_id === issue.shot_id) === index)
})
const stale = computed(() => staleTargets(props.plan, props.previews))
const staleCost = computed(() => targetCost(stale.value, props.models))
const incomplete = computed(() => incompleteTargets(props.plan, props.previews))
const charactersIncomplete = computed(() => (props.story.characters || []).some((character) => character.reference.source === 'generate' && (props.previews.characters?.[character.character_id]?.status !== 'success' || props.previews.characters?.[character.character_id]?.stale)))
const charactersInvalid = computed(() => characterDraft.value.some((character) => !character.lock_description?.trim() || character.reference.source === 'generate' && !character.reference.generate_prompt?.trim()))
const currentRange = computed(() => props.models.find((model) => model.model_id === shotDraft.value?.motion?.model_id)?.capabilities?.duration)
const format = (value) => Number.isFinite(value) ? String(Math.round(value * 100) / 100) : '—'
const money = (value) => value == null ? '待服务器估算' : format(value)
const errorText = (value) => typeof value === 'string' ? value : value?.message || value?.code || '生成失败'
const characterName = (id) => props.story.characters?.find((character) => character.character_id === id)?.name || id
const previewLabel = (preview, supplied = false) => preview?.stale || preview?.status === 'stale' ? '已过期' : ({ success: '已完成', failed: '失败 · 可局部重做', running: '生成中', pending: '排队中', cancelled: '已取消' }[preview?.status] || (supplied ? '已有参考图' : '待生成'))
const previewTone = (preview) => preview?.stale || preview?.status === 'stale' ? 'text-amber-600' : preview?.status === 'failed' ? 'text-red-600' : 'text-slate-500'
const artifactUrl = (id) => id ? `/api/artifacts/${encodeURIComponent(id)}/preview` : null
const characterImage = (character) => props.previews.characters?.[character.character_id]?.preview_url || artifactUrl(character.reference.artifact_ids?.[0])
const frameImage = (shot) => props.previews.keyframes?.[shot.shot_id]?.preview_url || (shot.first_frame.method === 'user_image' ? artifactUrl(shot.first_frame.reference_artifact_ids?.[0]) : null)
function optionsFor(mode, current) {
  const models = eligibleModels(props.models, mode, props.spec)
  return current && !models.some((model) => model.model_id === current) ? [{ model_id: current, display_name: `${current}（当前值，需服务器校验）` }, ...models] : models
}
function reset() {
  localPlan.value = clone(props.plan); original.value = JSON.stringify(props.plan); baseVersion.value = props.planVersion
  characterDraft.value = clone(props.story.characters || []); characterOriginal.value = JSON.stringify(props.story.characters || [])
  confirmation.value = null; actionError.value = ''; pendingEdit.value = false
  drawer.value?.close()
}
function reload() { reset(); emit('refresh') }
watch(() => [props.runId, props.planVersion], (next, previous) => {
  if (next[0] !== previous[0] || !dirty.value && !charactersDirty.value || pendingEdit.value) reset()
})
async function openShot(id) {
  if (props.disabled) return
  shotDraft.value = clone(localPlan.value.shots.find((shot) => shot.shot_id === id))
  savedFrame.value = shotDraft.value.first_frame.method === 'generate' ? clone(shotDraft.value.first_frame) : null
  await nextTick(); drawer.value?.showModal()
}
function closeDrawer() { shotDraft.value = null; savedFrame.value = null }
function onBackdrop(event) { if (event.target === drawer.value) drawer.value.close() }
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
  actionError.value = ''
  emit('action', { action, payload, onSuccess: () => { confirmation.value = null; if (['edit_plan', 'approve_characters'].includes(action)) pendingEdit.value = true }, onError: (error) => { pendingEdit.value = false; actionError.value = error } })
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
  const affected = type === 'character' ? props.plan.shots.filter((item) => item.character_ids.includes(id)).map((item) => item.shot_id) : []
  confirmation.value = { action: 'regenerate', payload: { target_type: type, target_id: id, ...(prompt ? { prompt } : {}) }, title: `重做${type === 'character' ? '角色定妆图' : type === 'keyframe' ? '关键帧' : '尾帧'} ${type === 'character' ? characterName(id) : id}`, cost: preview?.estimated_cost ?? (frame ? priceFor(props.models, frame.model_id, 1, 'image') : null), description: affected.length ? `会使 ${affected.join('、')} 的角色关联关键帧过期。旧图保留，不自动重做其他图片，后续需单独确认费用。${charactersDirty.value ? '卡片里的外观锁定修改尚未保存；本次只提交定妆提示词。' : ''}` : '仅重做这张预览图片，旧产物保留。不会提交任何视频生成任务。' }
}
function askStale() { confirmation.value = { action: 'regenerate_stale', payload: {}, title: `重做 ${stale.value.length} 张过期关键帧`, cost: staleCost.value, description: `范围：${stale.value.map((item) => `${item.id}${item.type === 'end_frame' ? ' 尾帧' : ''}`).join('、')}。其他已完成预览保持可用。` } }
function confirmReject() { confirmation.value = { action: 'reject', payload: {}, title: '放弃此计划', description: '将取消本次创作。已有预览与消费记录保留。' } }
function confirmAction() { const value = confirmation.value; submit(value.action, value.payload) }
</script>

<style scoped>
.card { @apply rounded-2xl border border-slate-200 bg-white p-5 text-slate-800 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200; }
.tag { @apply rounded-md bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.cost { @apply flex flex-col gap-1 rounded-lg bg-slate-50 p-3 dark:bg-slate-800/60; }
.cost span { @apply text-xs text-slate-500 dark:text-slate-400; }
.cost strong { @apply break-words tabular-nums; }
.field-label { @apply flex flex-col gap-1 text-xs font-medium text-slate-500 dark:text-slate-400; }
.field { @apply w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 read-only:bg-slate-50 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100 dark:read-only:bg-slate-900; }
.primary-btn { @apply rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary-btn { @apply rounded-xl border border-slate-300 px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
.drawer { @apply fixed inset-y-0 left-auto right-0 m-0 h-full max-h-full w-full max-w-xl overflow-y-auto border-0 bg-white text-slate-800 shadow-xl dark:bg-slate-900 dark:text-slate-200; }
.drawer::backdrop { background: rgb(15 23 42 / 0.5); }
</style>
