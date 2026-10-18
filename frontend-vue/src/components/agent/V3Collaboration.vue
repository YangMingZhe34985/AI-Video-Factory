<template>
  <section class="v3-collaboration" data-testid="v3-collaboration">
    <header><div><h3>Agent 协作</h3><p>角色委派与公开步骤摘要；不展示完整模型提示词。</p></div><button type="button" :disabled="state.loading || !run.run_id" @click="refresh++">刷新步骤</button></header>
    <div class="collaboration-grid">
      <section aria-label="委派关系">
        <h4>委派关系</h4>
        <ol v-if="tree.length" class="agents">
          <li v-for="agent in tree" :key="agent.delegation_id" :style="{ marginInlineStart: `${Math.min(agent.depth, 3) * 0.65}rem` }" class="agent">
            <div class="agent-title"><strong>{{ agent.label }}</strong><span>{{ v3StatusLabel(agent.status) }}</span></div>
            <p>{{ agent.task_summary || '暂无任务摘要' }}</p>
            <p class="small">{{ agent.parent_id ? `来自委派 #${agent.parent_id} · ` : '主协调 · ' }}委派 #{{ agent.delegation_id }}{{ agent.detached ? '（关系信息不完整）' : '' }}</p>
            <p class="small">{{ agent.steps ?? '—' }} 轮 · 本角色费用 {{ creditLabel(agent.credits) }} credits</p>
          </li>
        </ol>
        <p v-else class="empty">等待创建规划任务。</p>
      </section>
      <section aria-label="公开步骤记录" :aria-busy="state.loading">
        <h4>步骤记录</h4>
        <p v-if="state.loading" class="empty" role="status">正在读取第 {{ page }} 页…</p>
        <p v-if="state.error" class="error" role="alert">{{ state.error }}</p>
        <ol v-else-if="state.items.length" class="steps">
          <li v-for="(step, index) in state.items" :key="`${page}:${index}:${step.at || ''}`">
            <div class="agent-title"><strong>{{ agentLabel(step.agent) }}</strong><time>{{ timeLabel(step.at) }}</time></div>
            <p>{{ step.summary || '运行步骤' }}<span v-if="step.tool"> · {{ step.tool }}</span></p>
            <p class="small">{{ step.kind || 'step' }} · {{ creditLabel(step.credits) }} credits</p>
          </li>
        </ol>
        <p v-else-if="!state.loading" class="empty">本页暂无步骤。</p>
        <nav class="pagination" aria-label="步骤分页">
          <button type="button" :disabled="page <= 1 || state.loading" @click="page--">上一页</button>
          <span>第 {{ page }} 页<span v-if="!state.error"> / {{ totalPages }} · {{ state.total }} 条</span></span>
          <button type="button" :disabled="page >= totalPages || state.loading || Boolean(state.error)" @click="page++">下一页</button>
        </nav>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { listAgentV3Steps } from '@/api/agent'
import { creditLabel, v3StatusLabel } from './v3-actions.js'
import { agentLabel, agentTree, createStepPager } from './v3-plan.js'

const props = defineProps({ run: { type: Object, required: true } })
const page = ref(1), refresh = ref(0)
const state = reactive({ items: [], total: 0, page: 1, loading: false, error: '' })
const tree = computed(() => agentTree(props.run.agents))
const totalPages = computed(() => Math.max(1, Math.ceil(state.total / 30)))
const activity = computed(() => [props.run.updated_at || '', ...(props.run.agents || []).map((item) => `${item.delegation_id}:${item.status}:${item.steps}`)].join('|'))
const pager = createStepPager(listAgentV3Steps, (update) => Object.assign(state, update))
watch(() => props.run.run_id, () => { page.value = 1 }, { flush: 'sync' })
watch([() => props.run.run_id, () => page.value, () => activity.value, () => refresh.value], ([id, currentPage], _previous, onCleanup) => {
  pager.load(id, currentPage)
  // Vue 3.4-compatible cleanup; invalidate late responses as well as aborting transport.
  onCleanup(() => pager.cancel())
}, { immediate: true })
onUnmounted(() => pager.dispose())
function timeLabel(value) {
  if (!value) return '—'
  const time = new Date(value)
  return Number.isNaN(time.getTime()) ? '—' : time.toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.v3-collaboration { --border:#e2e8f0; --subtle:#f8fafc; --muted:#64748b; --ink:#0f172a; min-width:0; color:var(--ink); overflow-wrap:anywhere; }
:global(.dark) .v3-collaboration { --border:#334155; --subtle:#172033; --muted:#a1afc3; --ink:#e2e8f0; }
header,.agent-title,.pagination { display:flex; flex-wrap:wrap; justify-content:space-between; gap:.5rem; align-items:center; }
h3,h4,p,ol { margin:0; } h3 { font-size:1.05rem; } h4 { font-size:.9rem; margin-bottom:.6rem; } header p,.small,.empty { color:var(--muted); font-size:.76rem; line-height:1.65; }
.collaboration-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(20rem,100%),1fr)); gap:1rem; margin-top:1rem; } .collaboration-grid>section { min-width:0; }
ol { list-style:none; padding:0; } .agent { border:1px solid var(--border); border-left-width:3px; border-radius:.6rem; padding:.7rem; margin-bottom:.6rem; min-width:0; }
.agent-title strong { font-size:.82rem; } .agent-title span,.agent-title time { color:var(--muted); font-size:.72rem; } .agent p,.steps p { font-size:.78rem; line-height:1.65; margin-top:.3rem; }
.steps { max-height:28rem; overflow-y:auto; overflow-x:hidden; border:1px solid var(--border); border-radius:.6rem; } .steps li { padding:.7rem; border-bottom:1px solid var(--border); min-width:0; } .steps li:last-child { border-bottom:0; }
.empty,.error { padding:.75rem 0; } .error { color:#dc2626; font-size:.8rem; } :global(.dark) .error { color:#fca5a5; }
.pagination { margin-top:.7rem; font-size:.72rem; color:var(--muted); }
button { min-height:2.2rem; max-width:100%; border:1px solid var(--border); border-radius:.4rem; padding:.4rem .65rem; background:var(--subtle); color:var(--ink); font-size:.76rem; cursor:pointer; }
button:disabled { opacity:.45; cursor:not-allowed; } button:focus-visible { outline:2px solid #3b82f6; outline-offset:2px; }
@media(max-width:450px) { .collaboration-grid { grid-template-columns:1fr; } .pagination { justify-content:flex-start; } .pagination span { flex:1 1 6rem; text-align:center; } }
</style>
