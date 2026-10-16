<template>
  <DefaultLayout title="Agent Studio" :subtitle="t('subtitle')">
    <div class="max-w-7xl mx-auto space-y-5">
      <p v-if="enabled === false" class="panel">{{ t('disabled') }}</p>
      <template v-else-if="enabled">
        <div class="grid lg:grid-cols-[300px_1fr] gap-5">
          <aside class="space-y-5">
            <form class="panel space-y-4" @submit.prevent="create">
              <h2 class="font-semibold">{{ t('newProject') }}</h2>
              <label class="block text-sm">{{ t('creationMode') }}
                <select v-model="form.mode" class="field mt-2"><option value="from_scratch">{{ t('fromScratch') }}</option><option value="remix">{{ t('remix') }}</option></select>
              </label>
              <div v-if="form.mode === 'remix'" class="space-y-2">
                <label class="block text-sm">{{ t('uploadSource') }}
                  <input type="file" accept=".mp4,.mov,.mkv,.webm" class="field mt-2" :disabled="uploading || busy" @change="upload" />
                </label>
                <p v-if="uploading" class="text-xs text-gray-500">{{ t('uploading') }}</p>
                <p v-if="uploadedSource" class="text-xs text-gray-500">{{ uploadedSource.file_name }} · {{ uploadedSource.duration }}s · {{ uploadedSource.width }}×{{ uploadedSource.height }}</p>
                <p class="text-xs text-gray-500">{{ t('remixHint') }}</p>
              </div>
              <label class="block text-sm">{{ t('goal') }}
                <textarea v-model="form.goal" required maxlength="8000" rows="5" class="field mt-2" :placeholder="t('placeholder')" />
              </label>
              <label class="block text-sm">{{ t('modelPreference') }}
                <input v-model="form.video_model_preference" maxlength="120" class="field mt-2" :placeholder="t('modelPlaceholder')" />
              </label>
              <div class="grid grid-cols-2 gap-3">
                <label class="text-sm">{{ t('shots') }}<input v-model.number="form.shot_count" class="field mt-2" type="number" min="1" max="20" required /></label>
                <label class="text-sm">{{ t('budget') }}<input v-model.number="form.budget_limit" class="field mt-2" type="number" :min="form.mode === 'remix' ? 3 : estimate" max="500" required /></label>
              </div>
              <p class="text-xs text-gray-500">{{ t(form.mode === 'remix' ? 'remixEstimate' : 'estimate', { count: estimate }) }}</p>
              <button class="primary w-full" :disabled="busy || uploading || !form.goal.trim() || (form.mode === 'remix' && !uploadedSource)">{{ t('plan') }}</button>
            </form>
            <section class="panel space-y-3">
              <h2 class="font-semibold">{{ t('history') }}</h2>
              <button v-for="item in runs" :key="item.run_id" class="block w-full text-left rounded-lg p-3 border dark:border-gray-600" :class="selected?.run_id === item.run_id ? 'border-blue-500 bg-blue-50 dark:bg-gray-700' : ''" @click="select(item.run_id)">
                <span class="block text-sm truncate">{{ item.snapshot?.plan?.title || item.request.goal }}</span>
                <span class="text-xs text-gray-500">{{ statusLabel(item.status) }}</span>
              </button>
              <p v-if="!runs.length" class="text-sm text-gray-500">{{ t('noHistory') }}</p>
            </section>
          </aside>
          <main class="min-w-0 space-y-5">
            <div v-if="!selected" class="panel py-16 text-center text-gray-500">{{ t('welcome') }}</div>
            <template v-else>
              <section class="panel space-y-4">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <h2 class="text-xl font-semibold">{{ selected.snapshot?.plan?.title || selected.request.goal }}</h2>
                  <span class="px-3 py-1 bg-blue-50 text-blue-700 rounded-full text-sm">{{ statusLabel(selected.status) }}</span>
                </div>
                <p class="text-sm text-gray-500">{{ t('progress', selected.summary) }} · {{ t('spent', { spent: selected.estimated_spent, budget: selected.request.budget_limit }) }}</p>
                <div v-if="modelPolicy" class="rounded-lg bg-blue-50 dark:bg-gray-900 p-3 text-sm space-y-1">
                  <p class="font-medium">{{ t('videoModelRule') }} · {{ modelPolicy.source === 'user' ? t('userModelRule') : t('defaultModelRule') }}</p>
                  <p v-if="modelPolicy.requested.length">{{ modelPolicy.requested.join(' + ') }}</p>
                  <p v-if="modelPolicy.excluded?.length">{{ t('excludedModels') }}: {{ modelPolicy.excluded.join(', ') }}</p>
                  <p class="text-xs text-gray-500">{{ t('modelRuleHint') }}</p>
                </div>
                <p v-if="mode !== 'real'" class="text-sm text-amber-700">{{ mode === 'mock' ? t('mock') : t('auto') }}</p>
                <p v-if="selected.status === 'queued'" class="text-sm text-gray-500">{{ t('queueHint') }}</p>
                <p v-if="selected.error" role="alert" class="text-sm text-red-600 break-words">{{ selected.error.code }}: {{ selected.error.message }}</p>
                <p v-if="error" role="alert" class="text-sm text-red-600">{{ error }}</p>
                <div class="flex flex-wrap gap-3">
                  <button v-if="selected.status === 'awaiting_approval'" class="primary" :disabled="actionDisabled" @click="act('approve')">{{ t('approve') }}</button>
                  <button v-if="selected.status === 'awaiting_approval'" class="secondary" :disabled="actionDisabled" @click="act('reject')">{{ t('reject') }}</button>
                  <button v-if="selected.status === 'awaiting_delivery'" class="primary" :disabled="actionDisabled" @click="act('deliver')">{{ t('deliver') }}</button>
                  <button v-if="selected.status === 'needs_attention' && selected.resume_count < 2" class="secondary" :disabled="actionDisabled" @click="act('resume')">{{ t('resume') }}</button>
                  <span v-if="selected.command" class="text-sm text-gray-500 self-center">{{ t('pendingAction') }}</span>
                </div>
              </section>
              <section v-if="selected.request.source" class="panel space-y-3">
                <h3 class="font-semibold">{{ t('sourceVideo') }} · {{ selected.request.source.file_name }}</h3>
                <video controls preload="metadata" :src="selected.request.source.preview_url" class="w-full max-h-64 bg-black rounded-lg" />
                <details v-if="selected.snapshot?.analysis"><summary class="cursor-pointer text-sm">{{ t('sourceAnalysis') }}</summary>
                  <p class="text-sm whitespace-pre-wrap mt-2">{{ selected.snapshot.analysis.content }}</p>
                  <p class="text-xs text-gray-500 mt-2">{{ t('analysisVersion') }}: {{ selected.snapshot.analysis.prompt_id }}</p>
                </details>
                <router-link v-if="selected.snapshot?.analysis_job_id" :to="`/jobs/${selected.snapshot.analysis_job_id}`" class="text-sm text-blue-600">{{ t('analysisJob') }} ↗</router-link>
              </section>
              <section v-if="draft" class="space-y-4">
                <div class="panel space-y-2">
                  <h3 class="font-semibold">{{ t('storyboard') }}</h3>
                  <p class="text-sm text-gray-500 whitespace-pre-wrap">{{ draft.style_notes }}</p>
                  <p class="text-xs text-gray-500">{{ t('editHint') }}</p>
                  <p v-if="draft.mode === 'remix'" class="text-xs text-gray-500">{{ t('rangeHint') }}</p>
                  <div v-for="(issue, index) in selected.snapshot?.plan_issues || []" :key="index" role="alert" class="text-sm text-red-600">
                    {{ t('invalidDraft') }} {{ issue.shot_id }}: {{ issue.message }}
                    <p v-for="detail in issue.errors || []" :key="detail">{{ detail }}</p>
                  </div>
                </div>
                <article v-for="shot in draft.shots" :key="shot.shot_id" class="panel space-y-4">
                  <div class="flex justify-between gap-3">
                    <h3 class="font-semibold">{{ shot.shot_id }}</h3>
                    <router-link v-if="shotState(shot).job_id" :to="`/jobs/${shotState(shot).job_id}`" class="text-sm text-blue-600">{{ t('job') }} ↗</router-link>
                  </div>
                  <div v-if="draft.mode === 'remix'" class="space-y-3">
                    <div class="grid md:grid-cols-3 gap-3">
                      <label class="text-sm">{{ t('editAction') }}<select v-model="shot.action" :disabled="!editable" class="field mt-2"><option value="keep">{{ t('keep') }}</option><option value="regenerate">{{ t('regenerate') }}</option></select></label>
                      <label class="text-sm">{{ t('sourceStart') }}<input v-model.number="shot.source_start" :readonly="!editable" class="field mt-2" type="number" min="0" :max="selected.request.source.duration" step="0.01" /></label>
                      <label class="text-sm">{{ t('sourceEnd') }}<input v-model.number="shot.source_end" :readonly="!editable" class="field mt-2" type="number" min="0" :max="selected.request.source.duration" step="0.01" /></label>
                    </div>
                    <label v-if="shot.action === 'regenerate'" class="block text-sm">{{ t('frameStrategy') }}<select v-model="shot.first_frame_mode" :disabled="!editable" class="field mt-2"><option value="source">{{ t('sourceFrame') }}</option><option value="generate">{{ t('newFrame') }}</option></select></label>
                    <label class="block text-sm">{{ t('editReason') }}<textarea v-model="shot.edit_reason" :readonly="!editable" class="field mt-2" rows="2" maxlength="2000" /></label>
                  </div>
                  <div v-if="shot.action !== 'keep'" class="grid md:grid-cols-2 gap-4">
                    <label class="text-sm">{{ t('generatedDuration') }}
                      <input v-model.number="shot.video_params.duration" :readonly="!editable" class="field mt-2" type="number" min="0" step="any" />
                    </label>
                    <label v-if="!shot.first_frame_mode || shot.first_frame_mode === 'generate'" class="text-sm">{{ t('frame') }} · {{ stage(shot, 'poll_first_frame_image') }}
                      <textarea v-model="shot.first_frame_prompt" :readonly="!editable" class="field mt-2" rows="4" maxlength="8000" />
                    </label>
                    <label class="text-sm">{{ t('video') }} · {{ stage(shot, 'poll_i2v') }}
                      <textarea v-model="shot.i2v_prompt" :readonly="!editable" class="field mt-2" rows="4" maxlength="8000" />
                    </label>
                  </div>
                  <p v-if="shot.action !== 'keep'" class="text-xs text-gray-500">{{ shot.first_frame_mode === 'source' ? t('sourceFrame') : shot.image_model_id }} → {{ shot.video_model_id || t('defaultModelRule') }}</p>
                  <details v-if="shot.action !== 'keep'" class="text-sm">
                    <summary>{{ t('generationSettings') }}</summary>
                    <div v-for="kind in (shot.first_frame_mode === 'source' ? ['video'] : ['image', 'video'])" :key="kind" class="space-y-2 mt-2">
                      <label class="block">{{ kind }} model<input v-model="shot[`${kind}_model_id`]" :readonly="!editable" class="field" /></label>
                      <label class="block">{{ kind }} parameters (JSON)<textarea :value="JSON.stringify(shot[`${kind}_params`], null, 2)" :readonly="!editable" class="field" rows="4" @input="editParams(shot, kind, $event.target.value)" /></label>
                      <p v-if="parameterErrors[`${shot.shot_id}:${kind}`]" role="alert" class="text-red-600">{{ t('invalidParams') }}</p>
                    </div>
                  </details>
                  <button v-if="canRevise" class="secondary" :disabled="actionDisabled" @click="revise(shot)">{{ t('reviseShot', { cost: shotCost(shot) }) }}</button>
                  <details v-if="selected.snapshot?.shot_history?.[shot.shot_id]?.length" class="text-sm">
                    <summary class="cursor-pointer">{{ t('shotHistory') }}</summary>
                    <div v-for="(previous, index) in selected.snapshot.shot_history[shot.shot_id]" :key="index" class="mt-2 space-y-1">
                      <p>{{ index + 1 }} · {{ previous.plan.edit_reason }} · {{ statusLabel(previous.result.status) }}</p>
                      <router-link v-if="previous.result.job_id" :to="`/jobs/${previous.result.job_id}`" class="text-blue-600">{{ t('job') }} ↗</router-link>
                      <a v-for="asset in previous.result.artifacts || []" :key="asset.artifact_id" :href="asset.download_url" class="block text-blue-600" download>{{ t('download') }} · {{ asset.artifact_type }}</a>
                    </div>
                  </details>
                  <p v-if="shotState(shot).error" class="text-sm text-red-600">{{ shotState(shot).error.summary }}</p>
                  <p v-for="message in shotState(shot).validation?.errors || []" :key="message" class="text-sm text-red-600">{{ message }}</p>
                  <div class="grid md:grid-cols-2 gap-4">
                    <div v-for="artifact in media(shot)" :key="artifact.artifact_id" class="rounded-lg overflow-hidden border dark:border-gray-600">
                      <div v-if="selected.snapshot.mock && artifact.mime_type?.startsWith('video/') && artifact.artifact_type !== 'retained_video'" class="p-8 bg-gray-100 dark:bg-gray-900 text-sm text-gray-500">{{ t('mockVideo') }}</div>
                      <video v-else-if="artifact.mime_type?.startsWith('video/')" controls preload="metadata" :src="artifact.preview_url" class="w-full max-h-64 bg-black" />
                      <img v-else :src="artifact.preview_url" :alt="shot.shot_id" class="w-full max-h-64 object-contain bg-gray-100" />
                      <a :href="artifact.download_url" class="block p-2 text-sm text-blue-600" download>{{ t('download') }} · {{ artifact.artifact_type }}</a>
                    </div>
                  </div>
                </article>
              </section>
              <section v-if="selected.snapshot?.packages?.length" class="panel space-y-3">
                <h3 class="font-semibold">{{ t('packages') }}</h3>
                <p class="text-sm text-gray-500">{{ t('packageHint') }}</p>
                <a v-for="pack in selected.snapshot.packages" :key="pack.artifact_id" :href="pack.download_url" class="block text-blue-600 text-sm" download>{{ t('download') }} ZIP · {{ pack.job_id }}</a>
                <p v-for="issue in selected.snapshot.package_errors || []" :key="issue.job_id" class="text-red-600 text-sm">{{ issue.job_id }}: {{ issue.message }}</p>
              </section>
            </template>
          </main>
        </div>
      </template>
      <p v-if="error && !selected" role="alert" class="text-red-600">{{ error }}</p>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { listAgentRuns, getAgentRun, createAgentRun, actOnAgentRun, uploadAgentSource, reviseAgentShot } from '@/api/agent'

const { t } = useI18n({ useScope: 'local', messages: {
  zh: {
    creationMode: '创作方式', fromScratch: '从零创作', remix: '原视频二次创作', uploadSource: '上传原视频', uploading: '正在上传并检查视频…',
    remixHint: '支持 MP4 / MOV / MKV / WebM。以原片为参考，保留片段或重新生成镜头。',
    remixEstimate: '分析与规划 3 credits；每个保留镜头 0，复用首帧重生成 10，新首帧重生成 12。全部生成上限约 {count} credits；非实际账单。',
    sourceVideo: '原视频', sourceAnalysis: '原片分析', analysisVersion: '分析 Prompt', analysisJob: '分析任务与日志', analyzing: '分析原视频中',
    rangeHint: '原片开始/结束表示保留或替换的原片范围；原片首帧取该范围起点。生成时长是新片段的独立长度，不必等于原片范围长度。请结合预览确认范围。',
    generatedDuration: '生成片段时长（秒，须符合模型要求）', invalidDraft: '请修改草稿后重新确认：', generationSettings: '模型与生成参数', invalidParams: '参数必须为有效的 JSON 对象。',
    editAction: '处理方式', keep: '保留原片段', regenerate: '重新生成', sourceStart: '原片开始（秒）', sourceEnd: '原片结束（秒）',
    frameStrategy: '首帧来源', sourceFrame: '复用原片首帧', newFrame: '生成新首帧', editReason: '保留或修改说明',
    reviseShot: '确认修改此镜头（预计 {cost} credits）', shotHistory: '历史版本与素材',
    subtitle: '从一个想法开始，规划分镜、生成素材并打包交付', disabled: 'Agent 模式尚未启用。',
    newProject: '开始创作', goal: '描述你的视频', placeholder: '一只橘猫走进雨后的书店，暖色电影感，三个连贯镜头…', shots: '镜头数', budget: '预算上限',
    modelPreference: '视频模型或系列（可选）', modelPlaceholder: '例如 wan2.7；留空则从描述识别',
    videoModelRule: '视频模型约束', userModelRule: '遵循用户指定', defaultModelRule: '沿用服务器默认', excludedModels: '排除',
    modelRuleHint: '约束适用于全部镜头的视频生成；不符合要求时会停止，不切换到其他系列。首帧图像模型不受此约束。',
    estimate: '预计 {count} credits，含规划 2 credits。仅为资源估算，非实际账单。', plan: '生成分镜计划', history: '创作记录', noHistory: '还没有创作记录',
    welcome: '描述一个想法，Director 与 Creative 将为你准备分镜计划。', progress: '共 {total} 个镜头 · 成功 {success} · 失败 {failed} · 待完成 {pending}', spent: '已用 {spent} / {budget} credits',
    mock: '当前为 Mock 演示模式，结果为测试素材。', mockVideo: 'Mock 视频占位文件，可下载检查交付流程，不提供播放。', auto: '当前为自动模式；缺少模型凭据时会使用 Mock 素材。', queueHint: '等待后台创作服务处理。',
    approve: '确认分镜并开始生成', reject: '放弃此计划', deliver: '一键打包可用素材', resume: '恢复执行', pendingAction: '操作已保存，等待处理…',
    storyboard: '分镜计划', editHint: '确认前可修改各镜头的首帧与动作提示词。确认后将按此计划消耗生成预算。', job: '任务详情与日志', frame: '首帧', video: '视频动作', download: '下载',
    packages: '交付素材', packageHint: '每个镜头一个 ZIP，包含视频、图片、提示词与清单。当前不自动拼接成片。',
    waiting: '等待模型结果', submit_unknown: '提交结果待核实',
    queued: '已排队', planning: '规划中', awaiting_approval: '等待确认', producing: '生成中', awaiting_delivery: '可预览与打包', delivering: '打包中', success: '成功', partial_success: '部分成功', failed: '失败', cancelled: '已取消', needs_attention: '需要处理', pending: '待执行', running: '执行中', skipped: '已跳过', path_failed: '上游失败',
  },
  en: {
    creationMode: 'Creation mode', fromScratch: 'From scratch', remix: 'Remix a source video', uploadSource: 'Upload source video', uploading: 'Uploading and checking video…',
    remixHint: 'MP4 / MOV / MKV / WebM. Keep source segments or regenerate selected shots.',
    remixEstimate: 'Analysis and planning: 3 credits. Keep: 0; source-frame regeneration: 10; new-frame regeneration: 12. Up to {count} credits for all new frames; not a provider bill.',
    sourceVideo: 'Source video', sourceAnalysis: 'Source analysis', analysisVersion: 'Analysis prompt', analysisJob: 'Analysis job and logs', analyzing: 'Analyzing source video',
    rangeHint: 'Source start/end identify the original segment to keep or replace. The source frame comes from its start. Generated duration is the independent length of the new clip. Review ranges against the source.',
    generatedDuration: 'Generated clip duration (seconds; model limits apply)', invalidDraft: 'Correct this draft before approval:', generationSettings: 'Model and generation parameters', invalidParams: 'Parameters must be a valid JSON object.',
    editAction: 'Edit action', keep: 'Keep source segment', regenerate: 'Regenerate', sourceStart: 'Source start (s)', sourceEnd: 'Source end (s)',
    frameStrategy: 'First frame', sourceFrame: 'Use source frame', newFrame: 'Generate a new frame', editReason: 'Edit rationale',
    reviseShot: 'Confirm this shot edit (~{cost} credits)', shotHistory: 'Previous versions and assets',
    subtitle: 'Turn an idea into a storyboard, video assets and downloadable packages', disabled: 'Agent mode is not enabled.', newProject: 'Start creating', goal: 'Describe your video', placeholder: 'An orange cat enters a bookstore after the rain, warm cinematic light, three connected shots…', shots: 'Shots', budget: 'Budget limit',
    modelPreference: 'Video model or family (optional)', modelPlaceholder: 'e.g. wan2.7; leave blank to detect from goal',
    videoModelRule: 'Video model constraint', userModelRule: 'User requirement', defaultModelRule: 'Server default', excludedModels: 'Excluded',
    waiting: 'Waiting for model result', submit_unknown: 'Submission needs reconciliation',
    modelRuleHint: 'Applies to video generation in every shot. Incompatible models stop execution rather than switching families. First-frame image models are independent.',
    estimate: 'Estimated {count} credits, including 2 for planning. Resource estimate, not a provider bill.', plan: 'Create storyboard', history: 'Projects', noHistory: 'No projects yet', welcome: 'Describe an idea. Director and Creative will prepare a storyboard.',
    progress: '{total} shots · {success} succeeded · {failed} failed · {pending} pending', spent: '{spent} / {budget} credits used', mock: 'Mock demo mode: results are test assets.', mockVideo: 'Mock video placeholder. Download to inspect delivery; playback is unavailable.', auto: 'Auto mode: models without credentials use mock assets.', queueHint: 'Waiting for the background creation service.',
    approve: 'Approve and generate', reject: 'Reject plan', deliver: 'Package available assets', resume: 'Resume', pendingAction: 'Action saved, awaiting processing…', storyboard: 'Storyboard', editHint: 'Edit frame and motion prompts before approval. Generation consumes the approved budget.', job: 'Job details and logs', frame: 'First frame', video: 'Video motion', download: 'Download', packages: 'Delivery', packageHint: 'One ZIP per shot with video, images, prompts and manifest. Automatic video stitching is not included.',
    queued: 'Queued', planning: 'Planning', awaiting_approval: 'Awaiting approval', producing: 'Producing', awaiting_delivery: 'Ready to preview and package', delivering: 'Packaging', success: 'Success', partial_success: 'Partial success', failed: 'Failed', cancelled: 'Cancelled', needs_attention: 'Needs attention', pending: 'Pending', running: 'Running', skipped: 'Skipped', path_failed: 'Upstream failed',
  },
} })
const route = useRoute()
const router = useRouter()
const enabled = ref(null), mode = ref('auto'), runs = ref([]), selected = ref(null), draft = ref(null), busy = ref(false), error = ref('')
const form = reactive({ goal: '', shot_count: 3, budget_limit: 100, video_model_preference: '', mode: 'from_scratch' })
const uploadedSource = ref(null), uploading = ref(false)
const parameterErrors = ref({})
const modelPolicy = computed(() => selected.value?.request?.video_model_policy || selected.value?.snapshot?.video_model_policy)
const estimate = computed(() => (form.mode === 'remix' ? 3 : 2) + 12 * form.shot_count)
const actionDisabled = computed(() => busy.value || Boolean(selected.value?.command) || Object.keys(parameterErrors.value).length > 0)
const canRevise = computed(() => selected.value?.request.mode === 'remix' && selected.value?.status === 'awaiting_delivery')
const editable = computed(() => (selected.value?.status === 'awaiting_approval' || canRevise.value) && !busy.value && !selected.value?.command)
const shotCost = (shot) => shot.action === 'keep' ? 0 : shot.first_frame_mode === 'source' ? 10 : 12
let timer, disposed = false, selectionVersion = 0, requestKey = null, requestPayload = null
let revisionKey = null, revisionPayload = null
const newRequestKey = () => globalThis.crypto?.randomUUID?.() || `agent-${Date.now()}-${Math.random().toString(36).slice(2)}`
const statusLabel = (status) => t(status || 'pending')
const shotState = (shot) => selected.value?.snapshot?.shots?.[shot.shot_id] || {}
const stage = (shot, key) => statusLabel(shotState(shot).nodes?.find(node => node.node_key === key)?.status || (shotState(shot).status === 'failed' ? 'failed' : 'pending'))
const media = (shot) => (shotState(shot).artifacts || []).filter(item => /^(image|video)\//.test(item.mime_type || ''))
const message = (err) => {
  const failure = err.response?.data?.error
  return failure ? [failure.details?.shot_id, failure.message, ...(failure.details?.errors || []).map(item => typeof item === 'string' ? item : item.msg)].filter(Boolean).join(' · ') : err.message
}
function applyRun(value) {
  if (selected.value?.run_id !== value.run_id || selected.value?.status !== value.status || !draft.value) {
    draft.value = value.snapshot?.plan ? structuredClone(value.snapshot.plan) : null
    parameterErrors.value = {}
  }
  selected.value = value
}
function editParams(shot, kind, text) {
  const key = `${shot.shot_id}:${kind}`
  try {
    const value = JSON.parse(text)
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('object required')
    shot[`${kind}_params`] = value
    delete parameterErrors.value[key]
  } catch { parameterErrors.value[key] = true }
}
async function select(id) {
  const version = ++selectionVersion
  try {
    const value = await getAgentRun(id)
    if (!disposed && version === selectionVersion) {
      applyRun(value)
      await router.replace({ query: { run: id } })
    }
  } catch (err) { error.value = message(err) }
}
async function refresh() {
  try {
    const data = await listAgentRuns()
    if (disposed) return
    runs.value = data.items
    const current = data.items.find(item => item.run_id === selected.value?.run_id)
    if (current) applyRun(current)
    if (!selected.value && data.items.length) await select(route.query.run || data.items[0].run_id)
  } catch (err) { error.value = message(err) }
}
async function create() {
  busy.value = true; error.value = ''
  const input = { ...form, source_artifact_id: form.mode === 'remix' ? uploadedSource.value?.artifact_id : undefined,
    video_model_preference: form.video_model_preference.trim() || undefined }
  const payload = JSON.stringify(input)
  if (payload !== requestPayload) {
    requestPayload = payload
    requestKey = newRequestKey()
  }
  try {
    const value = await createAgentRun({ ...input, request_key: requestKey })
    applyRun(value); await router.replace({ query: { run: value.run_id } }); await refresh()
    requestKey = null; requestPayload = null
  } catch (err) { error.value = message(err) } finally { busy.value = false }
}
async function upload(event) {
  const file = event.target.files?.[0]
  if (!file) return
  uploading.value = true; uploadedSource.value = null; error.value = ''
  try { uploadedSource.value = await uploadAgentSource(file) }
  catch (err) { error.value = message(err) } finally { uploading.value = false }
}
async function revise(shot) {
  busy.value = true; error.value = ''
  const payload = JSON.stringify({ run: selected.value.run_id, shot })
  if (payload !== revisionPayload) { revisionPayload = payload; revisionKey = newRequestKey() }
  try {
    applyRun(await reviseAgentShot(selected.value.run_id, shot, revisionKey)); await refresh()
    revisionKey = null; revisionPayload = null
  }
  catch (err) { error.value = message(err) } finally { busy.value = false }
}
async function act(action) {
  busy.value = true; error.value = ''
  try { applyRun(await actOnAgentRun(selected.value.run_id, action, action === 'approve' ? draft.value : undefined)); await refresh() }
  catch (err) { error.value = message(err) } finally { busy.value = false }
}
async function poll() {
  await refresh()
  if (!disposed) timer = setTimeout(poll, 3000)
}
onMounted(async () => {
  try {
    const response = await fetch('/api/health')
    if (!response.ok) throw new Error(`Health check failed (${response.status})`)
    const data = (await response.json()).data
    enabled.value = Boolean(data.agent_mode); mode.value = data.mode
    if (enabled.value && !disposed) {
      if (route.query.run) await select(route.query.run)
      await poll()
    }
  } catch (err) { error.value = message(err) }
})
onUnmounted(() => { disposed = true; clearTimeout(timer); selectionVersion++ })
</script>

<style scoped>
.panel { @apply bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-xl p-5 text-gray-900 dark:text-gray-100; }
.field { @apply w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 p-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500; }
.primary { @apply rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed; }
.secondary { @apply rounded-lg border border-gray-300 dark:border-gray-600 px-4 py-2.5 text-sm disabled:opacity-50; }
</style>
