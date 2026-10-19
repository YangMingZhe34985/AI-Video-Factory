<template>
  <section class="v3-plan" data-testid="v3-plan-board">
    <header class="board-header">
      <div><h3>{{ run.plan?.title || '创作计划' }}</h3><p>计划版本 {{ version || '—' }} · {{ v3StatusLabel(run.status) }}</p></div>
      <span v-if="run.experimental" class="tag warning">实验性组合计划</span>
    </header>
    <p v-if="run.plan?.goal" class="goal">{{ run.plan.goal }}</p>
    <div class="metrics">
      <div><span>交付总时长</span><strong>{{ secondsLabel(totals.deliveredSeconds) }}</strong></div>
      <div><span>累计生成视频时长</span><strong>{{ secondsLabel(totals.generatedSeconds) }}</strong></div>
      <div><span>本计划估价</span><strong>{{ creditLabel(totals.credits) }}<small v-if="totals.credits !== null"> credits</small></strong></div>
    </div>
    <p class="hint">费用为服务器演示估价；图像按张、视频按秒，部分变换按输入视频 + 完整输出秒数。交付时长不能直接当作计费时长。</p>
    <p v-if="run.mock" class="notice">Mock 演示素材不代表真实生成质量或账单。</p>
    <ul v-if="issues.length" class="notice error" aria-label="计划问题">
      <li v-for="(issue, index) in issues" :key="index">{{ issue.node_id ? `${issue.node_id}：` : '' }}{{ issue.message || issue.code || '计划需要修订' }}</li>
    </ul>

    <section v-for="group in groups" :key="group.id" class="stage">
      <h4>{{ group.label }} <small>{{ group.nodes.length }} 个节点</small></h4>
      <div class="nodes">
        <article v-for="row in group.nodes" :key="row.id" class="node" :data-node-id="row.id">
          <header class="node-header"><div><strong>{{ row.id }}</strong><p>{{ toolLabel(row.tool) }}</p></div><span class="tag">{{ v3StatusLabel(row.status) }}</span></header>
          <p v-if="row.rationale" class="rationale">{{ row.rationale }}</p>
          <p class="dependency" :data-readiness="readiness(row).kind">{{ readiness(row).label }}</p>
          <p v-if="row.depends_on.length" class="hint">前置节点：{{ row.depends_on.join('、') }}；全部就绪后才能执行 {{ row.id }}。</p>
          <p v-if="row.retained" class="notice warning">保留旧结果{{ row.source_plan_version ? `（来源版本 ${row.source_plan_version}）` : '' }}；本次不重生成，可能保留历史衔接。</p>
          <p v-else-if="row.reused_from_task_id" class="hint">复用已验证产物{{ row.source_plan_version ? ` · 来源版本 ${row.source_plan_version}` : '' }}</p>
          <div class="node-stats">
            <div><span>模型</span><strong>{{ row.model_id || (['generate_image', 'generate_video', 'animate_shot', 'transform_video'].includes(row.tool) ? '待服务器选型' : '无需模型') }}</strong></div>
            <div><span>服务器估价</span><strong>{{ creditLabel(row.estimated_cost) }}<small v-if="row.estimated_cost !== null"> credits</small></strong></div>
            <div v-if="row.duration !== null"><span>{{ row.tool === 'retain_video_segment' ? '原片保留时长' : '生成输出时长' }}</span><strong>{{ secondsLabel(row.duration) }}</strong></div>
            <div v-if="row.input_video_seconds > 0"><span>计费输入视频</span><strong>{{ secondsLabel(row.input_video_seconds) }}</strong></div>
          </div>
          <p v-if="row.gate === 'preview'" class="gate-note">{{ row.gate_approved ? '预览已确认' : row.status === 'success' ? '等待确认预览；后续依赖暂不执行' : '此节点生成后需要确认预览' }}</p>
          <p v-if="row.gate === 'choice'" class="gate-note">{{ row.gate_approved ? `已选择：${row.choice?.selected || '已确认候选'}` : '请选择一张候选，再确认用于后续生成。选择本身免费，所有候选的生成费已计入计划。' }}</p>
          <p v-if="row.error" class="notice error" role="alert">{{ row.error }}</p>
          <details @toggle="setExpanded(row.id, $event.target.open)">
            <summary>提示词、参数与输入引用</summary>
            <div v-if="expanded[row.id]" class="details-body">
              <p v-if="row.inputs?.prompt" class="prompt">{{ row.inputs.prompt }}</p>
              <p class="hint">模型参数</p><pre>{{ readableJson(row.params) }}</pre>
              <p class="hint">工具输入（含媒体引用）</p><pre>{{ readableJson(row.inputs) }}</pre>
              <p v-if="row.job_id" class="hint">任务 {{ row.job_id }} · 第 {{ row.attempt || 1 }} 次尝试</p>
            </div>
          </details>
          <div v-if="row.assets.length && (expanded[row.id] || waitingGate(row))" class="assets">
            <figure v-for="asset in row.assets" :key="asset.artifact_id">
              <AuthedImage v-if="asset.kind === 'image' && asset.preview" :key="`${run.run_id}:${asset.artifact_id}`" :src="asset.preview" :alt="`${row.id} 的预览`" class="node-image" />
              <AuthedVideo v-else-if="asset.kind === 'video' && asset.preview" :key="`${run.run_id}:${asset.artifact_id}`" :src="asset.preview" label="加载节点视频" loading-label="正在加载…" error-label="无法加载，请重试" class="node-video" />
              <p v-else class="hint">{{ asset.kind === 'file' ? '文件产物，下载见交付结果区' : '预览地址不可用' }}</p>
              <figcaption>{{ asset.file_name || asset.artifact_id }}</figcaption>
            </figure>
          </div>
          <fieldset v-if="row.gate === 'choice' && waitingGate(row)" class="choice-list" :disabled="locked">
            <legend>选择后续使用的图片（必选）</legend>
            <label v-for="(asset, index) in row.choice.candidates" :key="asset.artifact_id" class="choice-item">
              <input v-model="selections[row.id]" type="radio" :name="`choice-${run.run_id}-${row.id}`" :value="asset.artifact_id" :aria-label="`候选 ${index + 1}`" />
              <span>候选 {{ index + 1 }}</span>
              <AuthedImage v-if="asset.kind === 'image' && asset.preview" :src="asset.preview" :alt="`候选 ${index + 1}`" class="node-image" />
              <span v-else class="hint">预览暂不可用，请确认图片内容后再选择。</span>
              <span class="hint">{{ asset.file_name || asset.artifact_id }}</span>
            </label>
          </fieldset>
          <div v-if="waitingGate(row) && row.gate === 'choice'" class="actions">
            <button type="button" class="primary" :disabled="!canAction('approve_gate', choiceValues(row))" @click="submit('approve_gate', choiceValues(row))">确认所选图片</button>
            <button type="button" :disabled="locked" @click="selectGateRevision(row.id)">候选都不满意</button>
          </div>
          <div v-if="waitingGate(row) && row.gate === 'preview'" class="actions">
            <button type="button" class="primary" :disabled="!canAction('approve_gate', { gateNodeId: row.id })" @click="submit('approve_gate', { gateNodeId: row.id })">确认此预览</button>
            <button type="button" :disabled="locked" @click="selectGateRevision(row.id)">提出修改</button>
          </div>
        </article>
      </div>
    </section>
    <p v-if="!rows.length" class="hint">计划尚未提交，Agent 正在理解需求或准备草稿。</p>
    <p v-else class="hint">节点按阶段展示；执行顺序取服务器编译后的依赖。无依赖代表可并行候选，不代表已获批准或立即开工。</p>

    <section v-if="run.status === 'awaiting_plan_review'" class="review-box">
      <h4>确认计划并开始执行</h4>
      <label>自动局部修复预授权（可选，credits）<input v-model.number="repairCredits" type="number" min="0" step="0.01" inputmode="decimal" :disabled="locked" placeholder="0" /></label>
      <p class="hint">用于满足受控条件的小范围修复，不会因新版本自动补满；未填写为 0。超出预授权的修改仍需确认。</p>
      <p>本次计划 + 修复预留：<strong>{{ creditLabel(approvalCost) }}<small v-if="approvalCost !== null"> credits</small></strong></p>
      <p v-if="approvalIssue" class="notice warning">{{ approvalIssue }}</p>
      <button type="button" class="primary" :disabled="Boolean(approvalIssue) || locked" @click="submit('approve_plan', { repairCredits })">批准版本 {{ version }} 并执行</button>
    </section>

    <form v-if="canShowRevision || selectedGate" class="review-box" @submit.prevent="submitRevision">
      <h4>{{ selectedGate ? `修改预览 ${selectedGate}` : '告诉 Agent 如何修改' }}</h4>
      <p class="hint">{{ selectedGate ? '保留这次反馈，再由 Agent 提出局部补丁。' : '只需描述修改意图；模型、时长与依赖调整将重新核验。' }} 原用户硬约束保持不变。</p>
      <label>修改意图<textarea v-model="revisionMessage" rows="3" maxlength="4000" :disabled="locked" placeholder="例如：保留主角外观，让结尾更轻松；先给我审核新的局部方案。" /></label>
      <div class="actions"><button type="submit" class="primary" :disabled="!canAction('revise_plan', { message: revisionMessage, gateNodeId: selectedGate })">提交修改意图</button><button v-if="selectedGate" type="button" :disabled="locked" @click="selectedGate = ''">取消本次反馈</button></div>
    </form>
    <p v-if="run.action_pending" class="notice" role="status">审核动作已入队，正在由服务端处理。</p>
    <p v-if="actionError" class="notice error" role="alert">{{ actionError }}</p>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import AuthedImage from './AuthedImage.vue'
import AuthedVideo from './AuthedVideo.vue'
import { creditLabel, v3StatusLabel } from './v3-actions.js'
import { buildPlanAction, choiceIdentity, dependencyState, gateReady, initialApprovalCost, planGroups, planRows, planTotals, planVersion, readableJson, secondsLabel, toolLabel } from './v3-plan.js'

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
.v3-plan { --border:#e2e8f0; --subtle:#f8fafc; --muted:#64748b; --ink:#0f172a; min-width:0; color:var(--ink); overflow-wrap:anywhere; }
:global(.dark) .v3-plan { --border:#334155; --subtle:#172033; --muted:#a1afc3; --ink:#e2e8f0; }
h3,h4,p,figure { margin:0; } h3 { font-size:1.1rem; } h4 { font-size:.95rem; } small { font-size:.75rem; font-weight:400; }
.board-header,.node-header,.actions { display:flex; flex-wrap:wrap; align-items:flex-start; justify-content:space-between; gap:.65rem; }
.board-header p,.node-header p,.hint,figcaption { color:var(--muted); font-size:.78rem; line-height:1.6; } .goal { margin-top:.75rem; white-space:pre-wrap; }
.metrics,.node-stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(9rem,100%),1fr)); gap:.75rem; margin:.8rem 0; }
.metrics { padding:.85rem; background:var(--subtle); border-radius:.75rem; }
.metrics div,.node-stats div { min-width:0; } .metrics span,.node-stats span { display:block; color:var(--muted); font-size:.72rem; } .metrics strong { display:block; font-size:1rem; margin-top:.25rem; } .node-stats strong { font-size:.8rem; font-weight:500; }
.tag { font-size:.72rem; border:1px solid var(--border); padding:.2rem .5rem; border-radius:999px; } .warning { color:#9a6700; } :global(.dark) .warning { color:#fbbf24; }
.stage { margin-top:1.4rem; } .stage h4 { margin-bottom:.65rem; } .stage h4 small { color:var(--muted); margin-left:.4rem; }
.nodes { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(22rem,100%),1fr)); gap:.75rem; }
.node { min-width:0; border:1px solid var(--border); border-radius:.8rem; padding:.9rem; }
.rationale { font-size:.83rem; margin-top:.7rem; line-height:1.65; } .dependency,.gate-note { font-size:.77rem; margin:.6rem 0 .3rem; color:var(--muted); } .gate-note { font-weight:600; }
.notice { margin:.7rem 0; background:var(--subtle); border-radius:.5rem; padding:.65rem; font-size:.8rem; line-height:1.65; } ul.notice { padding-left:1.7rem; } .error { color:#dc2626; } :global(.dark) .error { color:#fca5a5; }
details { margin-top:.7rem; border-top:1px solid var(--border); padding-top:.65rem; } summary { cursor:pointer; font-size:.8rem; } .details-body { min-width:0; padding-top:.65rem; } .prompt { white-space:pre-wrap; font-size:.82rem; line-height:1.7; }
pre { margin:.3rem 0 .8rem; white-space:pre-wrap; overflow-wrap:anywhere; word-break:break-word; font-size:.72rem; background:var(--subtle); border-radius:.4rem; padding:.6rem; max-width:100%; }
.assets { display:grid; gap:.65rem; margin-top:.7rem; } figure { min-width:0; } .node-image,.node-video { width:100%; max-width:100%; max-height:22rem; object-fit:contain; border-radius:.5rem; background:var(--subtle); } figcaption { margin-top:.25rem; }
.choice-list { min-width:0; border:1px solid var(--border); border-radius:.5rem; margin:.7rem 0 0; padding:.65rem; display:grid; gap:.7rem; }
.choice-list legend { font-size:.8rem; } .choice-item { padding:.5rem; border:1px solid var(--border); border-radius:.4rem; cursor:pointer; }
.choice-item input { width:auto; justify-self:start; } .choice-item:has(input:checked) { border-color:#2563eb; outline:1px solid #2563eb; }
.review-box { margin-top:1rem; border:1px solid var(--border); border-radius:.7rem; padding:1rem; display:grid; gap:.7rem; min-width:0; }
label { display:grid; gap:.4rem; font-size:.8rem; min-width:0; } input,textarea { box-sizing:border-box; min-width:0; width:100%; border:1px solid var(--border); border-radius:.4rem; padding:.6rem; background:var(--subtle); color:var(--ink); font:inherit; } input { max-width:16rem; } textarea { resize:vertical; }
.actions { justify-content:flex-start; margin-top:.65rem; } button { min-height:2.3rem; max-width:100%; border:1px solid var(--border); border-radius:.45rem; padding:.45rem .75rem; font-size:.8rem; color:var(--ink); background:var(--subtle); cursor:pointer; overflow-wrap:anywhere; }
button.primary { color:white; background:#2563eb; border-color:#2563eb; } button:disabled { opacity:.5; cursor:not-allowed; } button:focus-visible,summary:focus-visible,input:focus-visible,textarea:focus-visible { outline:2px solid #3b82f6; outline-offset:2px; }
@media(max-width:450px) { .metrics { grid-template-columns:1fr; } .node { padding:.75rem; } .review-box { padding:.8rem; } .actions button { flex:1 1 9rem; } }
</style>
