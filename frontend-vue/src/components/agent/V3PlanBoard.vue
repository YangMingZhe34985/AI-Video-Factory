<template>
  <section class="panel v3-plan" data-testid="v3-plan-board">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 items-start gap-3">
        <span class="icon-tile"><PhFilmStrip :size="18" /></span>
        <div class="min-w-0">
          <h3 class="text-[15px] font-semibold leading-snug text-slate-900 dark:text-white">{{ run.plan?.title || '创作计划' }}</h3>
          <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">计划版本 {{ version || '—' }} · {{ v3StatusLabel(run.status) }}</p>
        </div>
      </div>
      <span v-if="run.experimental" class="pill tone-amber"><PhFlask :size="13" />实验性组合计划</span>
    </header>
    <p v-if="run.plan?.goal" class="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-slate-700 dark:text-slate-200">{{ run.plan.goal }}</p>
    <div class="mt-4 grid grid-cols-[repeat(auto-fit,minmax(min(9.5rem,100%),1fr))] gap-2.5">
      <div class="stat"><dt><PhClock :size="13" />交付总时长</dt><dd><strong>{{ secondsLabel(totals.deliveredSeconds) }}</strong></dd></div>
      <div class="stat"><dt><PhFilmSlate :size="13" />累计生成视频时长</dt><dd><strong>{{ secondsLabel(totals.generatedSeconds) }}</strong></dd></div>
      <div class="stat"><dt><PhCoins :size="13" />本计划估价</dt><dd><strong>{{ creditLabel(totals.credits) }}</strong><small v-if="totals.credits !== null"> credits</small></dd></div>
    </div>
    <div v-if="constraints.visible" class="constraints" role="group" aria-label="需求约束" data-testid="plan-constraints">
      <span class="constraints-label">需求约束</span>
      <span v-if="constraints.duration" class="constraint" :data-state="constraints.duration.state">
        <PhTarget :size="14" class="flex-none text-slate-400" />
        <span>目标时长 <strong>{{ durationTargetLabel(constraints.duration) }}</strong></span>
        <span class="pill pill-sm" :class="`tone-${durationTone}`">{{ durationStateLabel(constraints.duration) }}</span>
      </span>
      <span v-if="constraints.aspect" class="constraint">
        <PhFrameCorners :size="14" class="flex-none text-slate-400" />
        <span>画面比例 <strong>{{ constraints.aspect }}</strong></span>
        <span class="text-[11px] text-slate-400">拼接与质检按此校验</span>
      </span>
    </div>
    <p class="mt-2 text-[11px] leading-relaxed text-slate-400">费用为服务器演示估价；图像按张、视频按秒，部分变换按输入视频 + 完整输出秒数。交付时长不能直接当作计费时长。</p>
    <p v-if="run.mock" class="notice notice-amber mt-3"><PhInfo :size="15" class="mt-0.5 flex-none" />Mock 演示素材不代表真实生成质量或账单。</p>
    <div v-if="issues.length" class="notice notice-red mt-3 flex-col" aria-label="计划问题" role="group">
      <p class="flex items-center gap-1.5 font-medium"><PhWarning :size="15" />计划问题 · {{ issues.length }}</p>
      <ul class="space-y-1 text-xs"><li v-for="(issue, index) in issues" :key="index"><strong v-if="issue.node_id">{{ issue.node_id }}：</strong>{{ issue.message || issue.code || '计划需要修订' }}</li></ul>
    </div>

    <section v-for="group in groups" :key="group.id" class="mt-6">
      <h4 class="sub-title">{{ group.label }}<span class="count">{{ group.nodes.length }} 个节点</span></h4>
      <div class="grid grid-cols-[repeat(auto-fill,minmax(min(21rem,100%),1fr))] gap-3">
        <article v-for="row in group.nodes" :key="row.id" class="node" :class="`edge-${statusTone(row.status)}`" :data-node-id="row.id">
          <header class="flex items-start justify-between gap-2">
            <div class="flex min-w-0 items-start gap-2.5">
              <span class="tool-icon"><component :is="toolIcon(row.tool)" :size="16" /></span>
              <div class="min-w-0"><strong class="block truncate text-sm text-slate-900 dark:text-slate-100" :title="row.id">{{ row.id }}</strong><p class="text-xs text-slate-500">{{ toolLabel(row.tool) }}</p></div>
            </div>
            <span class="pill pill-sm" :class="`tone-${statusTone(row.status)}`">{{ v3StatusLabel(row.status) }}</span>
          </header>
          <p v-if="row.rationale" class="mt-2.5 text-[13px] leading-relaxed text-slate-700 dark:text-slate-200">{{ row.rationale }}</p>
          <p class="mt-2 flex items-center gap-1.5 text-xs text-slate-500" :data-readiness="readiness(row).kind"><PhGitBranch :size="13" class="flex-none" />{{ readiness(row).label }}</p>
          <p v-if="row.depends_on.length" class="mt-1 text-[11px] leading-relaxed text-slate-400">前置节点：{{ row.depends_on.join('、') }}；全部就绪后才能执行 {{ row.id }}。</p>
          <p v-if="row.retained" class="notice notice-amber mt-2 text-xs">保留旧结果{{ row.source_plan_version ? `（来源版本 ${row.source_plan_version}）` : '' }}；本次不重生成，可能保留历史衔接。</p>
          <p v-else-if="row.reused_from_task_id" class="mt-1.5 flex items-center gap-1 text-[11px] text-emerald-700 dark:text-emerald-400"><PhRecycle :size="12" />复用已验证产物{{ row.source_plan_version ? ` · 来源版本 ${row.source_plan_version}` : '' }}</p>
          <dl class="node-stats">
            <div><dt>模型</dt><dd>{{ row.model_id || (['generate_image', 'generate_video', 'animate_shot', 'transform_video'].includes(row.tool) ? '待服务器选型' : '无需模型') }}</dd></div>
            <div><dt>服务器估价</dt><dd>{{ creditLabel(row.estimated_cost) }}<small v-if="row.estimated_cost !== null"> credits</small></dd></div>
            <div v-if="row.duration !== null"><dt>{{ row.tool === 'retain_video_segment' ? '原片保留时长' : '生成输出时长' }}</dt><dd>{{ secondsLabel(row.duration) }}</dd></div>
            <div v-if="row.input_video_seconds > 0"><dt>计费输入视频</dt><dd>{{ secondsLabel(row.input_video_seconds) }}</dd></div>
          </dl>
          <p v-if="row.gate === 'preview'" class="gate" :class="row.gate_approved ? 'tone-emerald' : 'tone-blue'"><PhEye :size="13" class="flex-none" />{{ row.gate_approved ? '预览已确认' : row.status === 'success' ? '等待确认预览；后续依赖暂不执行' : '此节点生成后需要确认预览' }}</p>
          <p v-if="row.gate === 'choice'" class="gate" :class="row.gate_approved ? 'tone-emerald' : 'tone-blue'"><PhCursorClick :size="13" class="flex-none" />{{ row.gate_approved ? `已选择：${row.choice?.selected || '已确认候选'}` : '请选择一张候选，再确认用于后续生成。选择本身免费，所有候选的生成费已计入计划。' }}</p>
          <p v-if="row.error" class="notice notice-red mt-2 text-xs" role="alert">{{ row.error }}</p>
          <details class="details" @toggle="setExpanded(row.id, $event.target.open)">
            <summary><PhCaretRight :size="12" class="chev" />提示词、参数与输入引用</summary>
            <div v-if="expanded[row.id]" class="details-body">
              <p v-if="row.inputs?.prompt" class="prompt">{{ row.inputs.prompt }}</p>
              <p class="label">模型参数</p><pre>{{ readableJson(row.params) }}</pre>
              <p class="label">工具输入（含媒体引用）</p><pre>{{ readableJson(row.inputs) }}</pre>
              <p v-if="row.job_id" class="text-[11px] text-slate-400">任务 {{ row.job_id }} · 第 {{ row.attempt || 1 }} 次尝试</p>
            </div>
          </details>
          <div v-if="row.assets.length && (expanded[row.id] || waitingGate(row))" class="mt-3 grid gap-2">
            <figure v-for="asset in row.assets" :key="asset.artifact_id" class="min-w-0">
              <AuthedImage v-if="asset.kind === 'image' && asset.preview" :key="`${run.run_id}:${asset.artifact_id}`" :src="asset.preview" :alt="`${row.id} 的预览`" class="node-media" />
              <AuthedVideo v-else-if="asset.kind === 'video' && asset.preview" :key="`${run.run_id}:${asset.artifact_id}`" :src="asset.preview" label="加载节点视频" loading-label="正在加载…" error-label="无法加载，请重试" class="node-media" />
              <p v-else class="text-xs text-slate-400">{{ asset.kind === 'file' ? '文件产物，下载见交付结果区' : '预览地址不可用' }}</p>
              <figcaption class="mt-1 truncate text-[11px] text-slate-400">{{ asset.file_name || asset.artifact_id }}</figcaption>
            </figure>
          </div>
          <fieldset v-if="row.gate === 'choice' && waitingGate(row)" class="choice-list" :disabled="locked">
            <legend>选择后续使用的图片（必选）</legend>
            <div class="grid grid-cols-[repeat(auto-fill,minmax(min(8.5rem,100%),1fr))] gap-2">
              <label v-for="(asset, index) in row.choice.candidates" :key="asset.artifact_id" class="choice-item">
                <span class="relative block">
                  <input v-model="selections[row.id]" type="radio" class="choice-radio" :name="`choice-${run.run_id}-${row.id}`" :value="asset.artifact_id" :aria-label="`候选 ${index + 1}`" />
                  <AuthedImage v-if="asset.kind === 'image' && asset.preview" :src="asset.preview" :alt="`候选 ${index + 1}`" class="aspect-square w-full rounded-lg bg-slate-100 object-cover dark:bg-slate-800" />
                  <span v-else class="flex aspect-square items-center justify-center rounded-lg bg-slate-100 px-2 text-center text-[11px] text-slate-400 dark:bg-slate-800">预览暂不可用，请确认图片内容后再选择。</span>
                  <span class="choice-badge"><PhCheck :size="11" weight="bold" /></span>
                </span>
                <span class="mt-1.5 block text-xs font-medium text-slate-700 dark:text-slate-200">候选 {{ index + 1 }}</span>
                <span class="block truncate text-[11px] text-slate-400">{{ asset.file_name || asset.artifact_id }}</span>
              </label>
            </div>
          </fieldset>
          <div v-if="waitingGate(row) && row.gate === 'choice'" class="mt-3 flex flex-wrap gap-2">
            <button type="button" class="primary" :disabled="!canAction('approve_gate', choiceValues(row))" @click="submit('approve_gate', choiceValues(row))">确认所选图片</button>
            <button type="button" class="secondary" :disabled="locked" @click="selectGateRevision(row.id)">候选都不满意</button>
          </div>
          <div v-if="waitingGate(row) && row.gate === 'preview'" class="mt-3 flex flex-wrap gap-2">
            <button type="button" class="primary" :disabled="!canAction('approve_gate', { gateNodeId: row.id })" @click="submit('approve_gate', { gateNodeId: row.id })">确认此预览</button>
            <button type="button" class="secondary" :disabled="locked" @click="selectGateRevision(row.id)">提出修改</button>
          </div>
        </article>
      </div>
    </section>
    <p v-if="!rows.length" class="empty"><PhHourglass :size="20" />计划尚未提交，Agent 正在理解需求或准备草稿。</p>
    <p v-else class="mt-4 text-[11px] leading-relaxed text-slate-400">节点按阶段展示；执行顺序取服务器编译后的依赖。无依赖代表可并行候选，不代表已获批准或立即开工。</p>

    <section v-if="run.status === 'awaiting_plan_review'" class="action-box">
      <h4 class="sub-title"><PhCheckCircle :size="16" />确认计划并开始执行</h4>
      <label class="field-label">自动局部修复预授权（可选，credits）<input v-model.number="repairCredits" type="number" min="0" step="0.01" inputmode="decimal" :disabled="locked" placeholder="0" class="field max-w-[16rem]" /></label>
      <p class="text-[11px] leading-relaxed text-slate-500">用于满足受控条件的小范围修复，不会因新版本自动补满；未填写为 0。超出预授权的修改仍需确认。</p>
      <p class="text-sm">本次计划 + 修复预留：<strong class="tabular-nums">{{ creditLabel(approvalCost) }}</strong><small v-if="approvalCost !== null"> credits</small></p>
      <p v-if="approvalIssue" class="notice notice-amber text-xs">{{ approvalIssue }}</p>
      <div><button type="button" class="primary" :disabled="Boolean(approvalIssue) || locked" @click="submit('approve_plan', { repairCredits })">批准版本 {{ version }} 并执行</button></div>
    </section>

    <form v-if="canShowRevision || selectedGate" class="action-box" @submit.prevent="submitRevision">
      <h4 class="sub-title"><PhPencilSimple :size="16" />{{ selectedGate ? `修改预览 ${selectedGate}` : '告诉 Agent 如何修改' }}</h4>
      <p class="text-[11px] leading-relaxed text-slate-500">{{ selectedGate ? '保留这次反馈，再由 Agent 提出局部补丁。' : '只需描述修改意图；模型、时长与依赖调整将重新核验。' }} 原用户硬约束保持不变。</p>
      <label class="field-label">修改意图<textarea v-model="revisionMessage" rows="3" maxlength="4000" :disabled="locked" class="field" placeholder="例如：保留主角外观，让结尾更轻松；先给我审核新的局部方案。" /></label>
      <div class="flex flex-wrap gap-2"><button type="submit" class="primary" :disabled="!canAction('revise_plan', { message: revisionMessage, gateNodeId: selectedGate })">提交修改意图</button><button v-if="selectedGate" type="button" class="secondary" :disabled="locked" @click="selectedGate = ''">取消本次反馈</button></div>
    </form>
    <p v-if="run.action_pending" class="notice notice-blue mt-3" role="status"><PhCircleNotch :size="15" class="mt-0.5 flex-none animate-spin" />审核动作已入队，正在由服务端处理。</p>
    <p v-if="actionError" class="notice notice-red mt-3" role="alert"><PhWarning :size="15" class="mt-0.5 flex-none" />{{ actionError }}</p>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import AuthedImage from './AuthedImage.vue'
import AuthedVideo from './AuthedVideo.vue'
import { creditLabel, v3StatusLabel } from './v3-actions.js'
import { statusTone } from './v3-tones'
import { PhCaretRight, PhCheck, PhCheckCircle, PhCircleNotch, PhClock, PhCoins, PhCursorClick, PhEye, PhFile, PhFilmReel, PhFilmSlate, PhFilmStrip, PhFlask, PhFrameCorners, PhGitBranch, PhHourglass, PhImage, PhInfo, PhMagicWand, PhPencilSimple, PhRecycle, PhScissors, PhSealCheck, PhTarget, PhVideoCamera, PhWarning } from '@phosphor-icons/vue'
import { buildPlanAction, choiceIdentity, dependencyState, gateReady, initialApprovalCost, planGroups, planRows, planTotals, planVersion, readableJson, secondsLabel, toolLabel } from './v3-plan.js'
import { durationStateLabel, durationTargetLabel, planConstraints } from './v3-constraints.js'

const props = defineProps({ run: { type: Object, required: true }, disabled: { type: Boolean, default: false } })
const emit = defineEmits(['action'])
const repairCredits = ref(''), revisionMessage = ref(''), selectedGate = ref(''), actionError = ref('')
const expanded = reactive({})
const selections = reactive({}), choiceKeys = reactive({})
const version = computed(() => planVersion(props.run))
const rows = computed(() => planRows(props.run))
const groups = computed(() => planGroups(props.run, rows.value))
const totals = computed(() => planTotals(props.run))
const issues = computed(() => Array.isArray(props.run.plan_issues) ? props.run.plan_issues : [])
const constraints = computed(() => planConstraints(props.run))
const durationTone = computed(() => ({ ok: 'emerald', mismatch: 'red' })[constraints.value.duration?.state] || 'slate')
const locked = computed(() => props.disabled || props.run.action_pending === true)
const canShowRevision = computed(() => ['awaiting_plan_review', 'awaiting_result_review', 'attention'].includes(props.run.status) && version.value)
const approvalCost = computed(() => { try { return initialApprovalCost(props.run, repairCredits.value) } catch { return null } })
const approvalIssue = computed(() => {
  if (locked.value) return ''
  try { buildPlanAction(props.run, 'approve_plan', { expectedVersion: version.value, repairCredits: repairCredits.value }); return '' }
  catch (error) { return error.message }
})
watch([() => props.run.run_id, () => version.value], () => {
  repairCredits.value = ''; revisionMessage.value = ''; selectedGate.value = ''; actionError.value = ''
  for (const key of Object.keys(expanded)) delete expanded[key]
  for (const key of Object.keys(selections)) delete selections[key]
  for (const key of Object.keys(choiceKeys)) delete choiceKeys[key]
})
watch(() => rows.value.map((row) => [row.id, choiceIdentity(row)]), (keys) => {
  const current = Object.fromEntries(keys)
  for (const id of Object.keys(selections)) if (!current[id] || current[id] !== choiceKeys[id]) delete selections[id]
  for (const id of Object.keys(choiceKeys)) if (!(id in current)) delete choiceKeys[id]
  Object.assign(choiceKeys, current)
}, { immediate: true })
watch(() => props.run.status, (status) => { if (status !== 'awaiting_gate') selectedGate.value = '' })
const TOOL_ICONS = { generate_image: PhImage, select_image: PhCursorClick, animate_shot: PhVideoCamera, generate_video: PhVideoCamera,
  transform_video: PhMagicWand, extract_frame: PhScissors, retain_video_segment: PhScissors, compose_video: PhFilmReel,
  probe_media: PhSealCheck, qc_video: PhSealCheck, package_story: PhFile }
const toolIcon = (tool) => TOOL_ICONS[tool] || PhFile
const readiness = (row) => dependencyState(row, rows.value)
const setExpanded = (id, value) => { expanded[id] = value }
const waitingGate = (row) => props.run.status === 'awaiting_gate' && gateReady(row)
const choiceValues = (row) => ({ gateNodeId: row.id, selectedArtifactId: selections[row.id], choiceDigest: row.choice?.digest })
function canAction(action, values) { try { buildPlanAction(props.run, action, { ...values, expectedVersion: version.value }, locked.value); return true } catch { return false } }
function submit(action, values) {
  actionError.value = ''
  try { emit('action', buildPlanAction(props.run, action, { ...values, expectedVersion: version.value }, locked.value)) }
  catch (error) { actionError.value = error.message }
}
function selectGateRevision(id) { if (!locked.value) { selectedGate.value = id; actionError.value = '' } }
function submitRevision() { submit('revise_plan', { message: revisionMessage.value, gateNodeId: selectedGate.value }) }
</script>

<style scoped>
.v3-plan { @apply min-w-0 text-slate-800 dark:text-slate-100; overflow-wrap: anywhere; }
.panel { @apply rounded-2xl border border-slate-200 bg-white p-4 sm:p-5 dark:border-slate-700 dark:bg-slate-900; }
.stat { @apply flex min-w-0 flex-col gap-1 rounded-xl bg-slate-50 px-3.5 py-3 dark:bg-slate-800/60; }
.stat dt { @apply flex items-center gap-1 text-[11px] text-slate-500 dark:text-slate-400; }
.stat dd { @apply flex items-baseline gap-1 tabular-nums; }
.stat dd strong { @apply text-base font-semibold text-slate-900 dark:text-white; }
.stat dd small { @apply text-[11px] text-slate-400; }
.constraints { @apply mt-2.5 flex min-w-0 flex-wrap items-center gap-2 rounded-xl border border-dashed border-slate-200 px-3 py-2 dark:border-slate-700; }
.constraints-label { @apply text-[11px] font-medium text-slate-500 dark:text-slate-400; }
.constraint { @apply inline-flex min-w-0 flex-wrap items-center gap-1.5 rounded-lg bg-slate-50 px-2.5 py-1 text-xs text-slate-600 dark:bg-slate-800/60 dark:text-slate-300; }
.constraint strong { @apply font-semibold text-slate-900 dark:text-white; }
.constraint[data-state="mismatch"] { @apply bg-red-50/70 ring-1 ring-red-200 dark:bg-red-950/30 dark:ring-red-900; }
.sub-title { @apply mb-3 flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100; }
.node { @apply min-w-0 rounded-xl border border-slate-200 bg-white p-3.5 transition hover:shadow-sm dark:border-slate-700 dark:bg-slate-900; border-left-width: 3px; }
.edge-emerald { border-left-color: #10b981; }
.edge-red { border-left-color: #ef4444; }
.edge-amber { border-left-color: #f59e0b; }
.edge-blue { border-left-color: #2563eb; }
.edge-slate { border-left-color: #cbd5e1; }
.tool-icon { @apply flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.pill-sm { @apply px-2 py-0.5 text-[11px]; }
.node-stats { @apply mt-3 grid grid-cols-2 gap-x-3 gap-y-2 rounded-lg bg-slate-50 px-3 py-2.5 dark:bg-slate-800/50; }
.node-stats dt { @apply text-[10px] text-slate-400; }
.node-stats dd { @apply truncate text-xs font-medium tabular-nums text-slate-700 dark:text-slate-200; }
.node-stats dd small { @apply font-normal text-slate-400; }
.gate { @apply mt-2.5 flex items-start gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium leading-relaxed; }
.details { @apply mt-3 border-t border-slate-100 pt-2.5 dark:border-slate-800; }
.details summary { @apply flex cursor-pointer list-none items-center gap-1 text-xs text-slate-500 hover:text-slate-800 dark:hover:text-slate-200; }
.details[open] .chev { transform: rotate(90deg); }
.chev { @apply transition-transform; }
.details-body { @apply min-w-0 pt-2.5; }
.details-body .prompt { @apply whitespace-pre-wrap rounded-lg bg-blue-50/60 px-3 py-2 text-[13px] leading-relaxed text-slate-700 dark:bg-blue-950/20 dark:text-slate-200; }
.details-body .label { @apply mt-2.5 text-[11px] text-slate-400; }
.details-body pre { @apply mt-1 max-w-full whitespace-pre-wrap break-words rounded-lg bg-slate-50 p-2.5 text-[11px] text-slate-600 dark:bg-slate-800/60 dark:text-slate-300; overflow-wrap: anywhere; }
.node-media { @apply max-h-80 w-full rounded-lg bg-slate-100 object-contain dark:bg-slate-800; }
.choice-list { @apply mt-3 min-w-0 rounded-xl border border-blue-200 bg-blue-50/40 p-3 dark:border-blue-900 dark:bg-blue-950/20; }
.choice-list legend { @apply px-1 text-xs font-semibold text-blue-700 dark:text-blue-300; }
.choice-item { @apply block cursor-pointer rounded-xl border-2 border-transparent bg-white p-1.5 transition hover:border-slate-300 dark:bg-slate-900 dark:hover:border-slate-600; }
.choice-item:has(input:checked) { @apply border-blue-500 shadow-sm; }
.choice-radio { @apply absolute left-2 top-2 z-10 h-4 w-4 accent-blue-600; }
.choice-badge { @apply pointer-events-none absolute right-2 top-2 hidden h-5 w-5 items-center justify-center rounded-full bg-blue-600 text-white shadow; }
.choice-item:has(input:checked) .choice-badge { @apply flex; }
.action-box { @apply mt-5 grid min-w-0 gap-3 rounded-xl border border-blue-200 bg-blue-50/40 p-4 dark:border-blue-900 dark:bg-blue-950/20; }
.field-label { @apply grid min-w-0 gap-1.5 text-xs font-medium text-slate-600 dark:text-slate-300; }
.field { @apply w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-950 dark:text-slate-100; }
.empty { @apply mt-4 flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-xs text-slate-400 dark:border-slate-700; }
.icon-tile { @apply flex h-9 w-9 flex-none items-center justify-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400; }
.pill { @apply inline-flex flex-none items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium; }
.tone-emerald { @apply bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300; }
.tone-red { @apply bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300; }
.tone-amber { @apply bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300; }
.tone-blue { @apply bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300; }
.tone-slate { @apply bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300; }
.tone-violet { @apply bg-violet-50 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300; }
.tone-teal { @apply bg-teal-50 text-teal-700 dark:bg-teal-950/50 dark:text-teal-300; }
.tone-sky { @apply bg-sky-50 text-sky-700 dark:bg-sky-950/50 dark:text-sky-300; }
.tone-rose { @apply bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300; }
.tone-orange { @apply bg-orange-50 text-orange-700 dark:bg-orange-950/50 dark:text-orange-300; }
.notice { @apply flex gap-2 rounded-xl px-3 py-2.5 text-sm leading-relaxed; }
.notice-amber { @apply bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200; }
.notice-red { @apply bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300; }
.notice-blue { @apply bg-blue-50 text-blue-800 dark:bg-blue-950/40 dark:text-blue-200; }
.notice-slate { @apply bg-slate-50 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300; }
.section-title { @apply flex items-center gap-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100; }
.count { @apply ml-1 rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-400; }
.primary { @apply inline-flex items-center justify-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50; }
.secondary { @apply inline-flex items-center justify-center gap-1.5 rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-600 dark:text-slate-200 dark:hover:bg-slate-800; }
</style>
