<template>
  <section class="panel v3-collaboration" data-testid="v3-collaboration">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 items-start gap-3">
        <span class="icon-tile"><PhUsersThree :size="18" /></span>
        <div class="min-w-0">
          <h3 class="text-[15px] font-semibold text-slate-900 dark:text-white">Agent 协作</h3>
          <p class="mt-0.5 text-xs text-slate-500 dark:text-slate-400">角色委派与公开步骤摘要；不展示完整模型提示词。</p>
        </div>
      </div>
      <button type="button" class="secondary" :disabled="state.loading || !run.run_id" @click="refresh++"><PhArrowClockwise :size="14" :class="state.loading ? 'animate-spin' : ''" />刷新步骤</button>
    </header>
    <div class="mt-4 grid grid-cols-[repeat(auto-fit,minmax(min(20rem,100%),1fr))] gap-4">
      <section aria-label="委派关系" class="min-w-0">
        <h4 class="sub-title">委派关系<span v-if="tree.length" class="count">{{ tree.length }}</span></h4>
        <ol v-if="tree.length" class="tree">
          <li v-for="agent in tree" :key="agent.delegation_id" class="tree-item" :style="{ marginInlineStart: `${Math.min(agent.depth, 3) * 1.25}rem` }">
            <span class="avatar" :class="`tone-${agentTone(agent.agent)}`" aria-hidden="true">{{ (agent.label || '?').slice(0, 1) }}</span>
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-center justify-between gap-2">
                <strong class="text-sm text-slate-900 dark:text-slate-100">{{ agent.label }}</strong>
                <span class="pill pill-sm" :class="`tone-${statusTone(agent.status)}`">{{ v3StatusLabel(agent.status) }}</span>
              </div>
              <p class="mt-1 text-xs leading-relaxed text-slate-600 dark:text-slate-300">{{ agent.task_summary || '暂无任务摘要' }}</p>
              <p class="meta">{{ agent.parent_id ? `来自委派 #${agent.parent_id} · ` : '主协调 · ' }}委派 #{{ agent.delegation_id }}{{ agent.detached ? '（关系信息不完整）' : '' }}</p>
              <p class="meta">{{ agent.steps ?? '—' }} 轮 · 本角色费用 {{ creditLabel(agent.credits) }} credits</p>
            </div>
          </li>
        </ol>
        <p v-else class="empty"><PhHourglass :size="20" />等待创建规划任务。</p>
      </section>
      <section aria-label="公开步骤记录" :aria-busy="state.loading" class="min-w-0">
        <h4 class="sub-title">步骤记录<span v-if="state.total" class="count">{{ state.total }}</span></h4>
        <p v-if="state.loading" class="empty" role="status"><PhCircleNotch :size="18" class="animate-spin" />正在读取第 {{ page }} 页…</p>
        <p v-if="state.error" class="notice notice-red" role="alert"><PhWarning :size="15" class="mt-0.5 flex-none" />{{ state.error }}</p>
        <ol v-else-if="state.items.length" class="steps">
          <li v-for="(step, index) in state.items" :key="`${page}:${index}:${step.at || ''}`" class="step">
            <span class="step-dot" :class="`tone-${agentTone(step.agent)}`" aria-hidden="true" />
            <div class="min-w-0 flex-1">
              <div class="flex flex-wrap items-baseline justify-between gap-2">
                <strong class="text-xs text-slate-900 dark:text-slate-100">{{ agentLabel(step.agent) }}</strong>
                <time class="text-[11px] tabular-nums text-slate-400">{{ timeLabel(step.at) }}</time>
              </div>
              <p class="mt-0.5 text-xs leading-relaxed text-slate-600 dark:text-slate-300">{{ step.summary || '运行步骤' }}<span v-if="step.tool" class="tool-chip">{{ step.tool }}</span></p>
              <p class="meta">{{ step.kind || 'step' }} · {{ creditLabel(step.credits) }} credits</p>
            </div>
          </li>
        </ol>
        <p v-else-if="!state.loading" class="empty">本页暂无步骤。</p>
        <nav class="pagination" aria-label="步骤分页">
          <button type="button" class="secondary" :disabled="page <= 1 || state.loading" @click="page--"><PhCaretLeft :size="14" />上一页</button>
          <span class="tabular-nums">第 {{ page }} 页<span v-if="!state.error"> / {{ totalPages }} · {{ state.total }} 条</span></span>
          <button type="button" class="secondary" :disabled="page >= totalPages || state.loading || Boolean(state.error)" @click="page++">下一页<PhCaretRight :size="14" /></button>
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
import { agentTone, statusTone } from './v3-tones'
import { PhArrowClockwise, PhCaretLeft, PhCaretRight, PhCircleNotch, PhHourglass, PhUsersThree, PhWarning } from '@phosphor-icons/vue'

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
.v3-collaboration { @apply min-w-0 text-slate-800 dark:text-slate-100; overflow-wrap: anywhere; }
.panel { @apply rounded-2xl border border-slate-200 bg-white p-4 sm:p-5 dark:border-slate-700 dark:bg-slate-900; }
.sub-title { @apply mb-3 flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400; }
.tree { @apply relative space-y-2; }
.tree-item { @apply relative flex min-w-0 gap-2.5 rounded-xl border border-slate-200 p-3 dark:border-slate-700; }
.avatar { @apply flex h-8 w-8 flex-none items-center justify-center rounded-full text-xs font-semibold; }
.meta { @apply mt-1 text-[11px] text-slate-400; }
.pill-sm { @apply px-2 py-0.5 text-[11px]; }
.steps { @apply relative max-h-[28rem] space-y-3 overflow-y-auto overflow-x-hidden rounded-xl border border-slate-200 p-3 dark:border-slate-700; }
.step { @apply relative flex min-w-0 gap-2.5; }
.step-dot { @apply mt-1 h-2.5 w-2.5 flex-none rounded-full ring-4 ring-white dark:ring-slate-900; }
.tool-chip { @apply ml-1.5 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500 dark:bg-slate-800 dark:text-slate-400; }
.empty { @apply flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-200 px-4 py-8 text-center text-xs text-slate-400 dark:border-slate-700; }
.pagination { @apply mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500; }
@media (max-width: 450px) { .pagination span { flex: 1 1 6rem; text-align: center; } }
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
