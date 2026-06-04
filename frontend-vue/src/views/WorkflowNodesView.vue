<template>
  <div class="h-screen flex overflow-hidden bg-gray-50">
    <AppSidebar />
    <main class="flex-1 flex flex-col h-screen overflow-hidden relative">
      <header class="bg-white px-8 py-5 flex items-center justify-between border-b border-gray-100 z-10 shrink-0">
        <div>
          <h1 class="text-2xl font-bold text-gray-900">{{ t('workflow.title') }}</h1>
          <p class="text-sm text-gray-500 mt-1">{{ t('workflow.subtitle') }}</p>
        </div>
        <div class="flex items-center gap-3">
          <button
            @click="openCreateJobPanel"
            class="px-4 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 flex items-center shadow-sm"
          >
            <PhPlus class="mr-1.5" /> {{ t('workflow.createJob') }}
          </button>
          <button
            @click="refreshNodes"
            class="px-4 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 flex items-center shadow-sm"
          >
            <PhArrowsClockwise class="mr-1.5" /> {{ t('workflow.refresh') }}
          </button>
        </div>
      </header>

      <div class="flex-1 flex overflow-hidden min-h-0">
        <section class="flex-1 flex flex-col min-w-0 bg-white border-r border-gray-100">
          <div class="px-5 py-3 border-b border-gray-100 shrink-0 bg-gray-50/50">
            <div class="flex items-center gap-3">
              <div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-100 shadow-sm">
                <span class="w-2 h-2 rounded-full bg-gray-300" />
                <span class="text-xs text-gray-500">{{ t('workflow.totalNodes') }}</span>
                <span class="text-sm font-bold text-gray-800 ml-0.5">{{ store.nodes.length }}</span>
              </div>
              <div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-emerald-50 border border-emerald-100 shadow-sm">
                <span class="w-2 h-2 rounded-full bg-emerald-400" />
                <span class="text-xs text-emerald-700">{{ t('workflow.enabled') }}</span>
                <span class="text-sm font-bold text-emerald-700 ml-0.5">{{ store.enabledNodes.length }}</span>
              </div>
              <div class="flex items-center gap-2 px-3 py-2 rounded-lg bg-white border border-gray-100 shadow-sm">
                <span class="w-2 h-2 rounded-full bg-gray-300" />
                <span class="text-xs text-gray-400">{{ t('workflow.disabled') }}</span>
                <span class="text-sm font-bold text-gray-500 ml-0.5">{{ store.disabledNodes.length }}</span>
              </div>
              <div class="ml-auto hidden xl:flex items-center gap-2">
                <span v-for="c in branchLegend" :key="c.key" class="flex items-center gap-1 text-[11px] text-gray-500">
                  <span class="w-2 h-2 rounded-full" :style="{ background: c.hex }"></span>{{ c.label }}
                </span>
              </div>
            </div>
          </div>

          <div ref="canvasContainer" class="flex-1 overflow-auto bg-dot-grid">
            <div
              class="relative"
              :style="{ width: `${canvasWidth}px`, height: `${canvasHeight}px` }"
            >
              <div
                v-for="lane in lanes"
                :key="lane.key"
                class="absolute left-3 right-3 rounded-2xl"
                :style="{
                  top: `${lane.y - 30}px`,
                  height: `${lane.height + 10}px`,
                  background: `${lane.color}09`,
                  border: `1px solid ${lane.color}22`,
                  borderLeft: `3px solid ${lane.color}55`,
                }"
              >
                <div class="absolute left-4 top-2.5 flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full" :style="{ background: lane.color }" />
                  <span
                    class="text-[10px] font-semibold uppercase tracking-[0.12em]"
                    :style="{ color: lane.color + 'bb' }"
                  >{{ lane.label }}</span>
                </div>
              </div>

              <svg
                class="absolute inset-0 pointer-events-none"
                :width="canvasWidth"
                :height="canvasHeight"
                :viewBox="`0 0 ${canvasWidth} ${canvasHeight}`"
              >
                <defs>
                  <!-- Refined small arrow for active edges -->
                  <marker id="wf-arrow-active" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto" markerUnits="strokeWidth">
                    <path d="M0 0 L5 2.5 L0 5 Z" fill="currentColor" />
                  </marker>
                  <!-- Gray arrow for disabled edges -->
                  <marker id="wf-arrow-muted" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto" markerUnits="strokeWidth">
                    <path d="M0 0 L5 2.5 L0 5 Z" fill="#cbd5e1" />
                  </marker>
                </defs>
                <!-- Inactive / background edges first (no overlap on active) -->
                <path
                  v-for="edge in connectionPaths.filter(e => !e.highlight && !e.dashed === false)"
                  :key="`bg-${edge.id}`"
                  :d="edge.path"
                  fill="none"
                  :stroke="edge.stroke"
                  :stroke-width="edge.strokeWidth"
                  :stroke-opacity="edge.opacity"
                  :stroke-dasharray="edge.dashed ? '5 4' : ''"
                  stroke-linecap="round"
                  marker-end="url(#wf-arrow-muted)"
                />
                <!-- Active edges -->
                <path
                  v-for="edge in connectionPaths.filter(e => !e.dashed)"
                  :key="`active-${edge.id}`"
                  :d="edge.path"
                  fill="none"
                  :stroke="edge.stroke"
                  :stroke-width="edge.strokeWidth"
                  :stroke-opacity="edge.opacity"
                  stroke-linecap="round"
                  marker-end="url(#wf-arrow-active)"
                />
                <!-- Highlighted edges on top -->
                <path
                  v-for="edge in connectionPaths.filter(e => e.highlight)"
                  :key="`hl-${edge.id}`"
                  :d="edge.path"
                  fill="none"
                  :stroke="edge.stroke"
                  :stroke-width="edge.strokeWidth + 1"
                  stroke-opacity="1"
                  stroke-linecap="round"
                  marker-end="url(#wf-arrow-active)"
                />
              </svg>

              <button
                v-for="node in layoutNodes"
                :key="node.node_key"
                class="absolute text-left bg-white rounded-xl border transition-all duration-150 overflow-hidden"
                :class="[
                  selectedKey === node.node_key
                    ? 'border-primary/60 shadow-lg shadow-blue-100/60 ring-2 ring-primary/25 ring-offset-1'
                    : 'border-gray-100 shadow-sm hover:shadow-md hover:-translate-y-px hover:border-gray-200',
                  !node.enabled ? 'opacity-45' : '',
                ]"
                :style="{ left: `${node.position.x}px`, top: `${node.position.y}px`, width: `${cardW}px`, height: `${cardH}px` }"
                @click="selectNode(node)"
              >
                <!-- Colored accent stripe at top -->
                <div
                  class="absolute top-0 left-0 right-0 h-[3px]"
                  :style="{ background: node.enabled ? getBranchColor(node.branch_key).hex : '#e2e8f0' }"
                />

                <div class="p-3 pt-[14px] h-full flex flex-col">
                  <!-- Row 1: sequence badge + status badge -->
                  <div class="flex items-center justify-between mb-1.5">
                    <div
                      class="w-5 h-5 rounded-full text-white text-[10px] font-bold flex items-center justify-center shrink-0"
                      :style="{ background: node.enabled ? getBranchColor(node.branch_key).hex : '#94a3b8' }"
                    >
                      {{ sequenceLabel(node) }}
                    </div>
                    <span
                      class="text-[9px] px-1.5 py-0.5 rounded font-semibold tracking-wide"
                      :class="node.enabled
                        ? 'bg-emerald-50 text-emerald-600 border border-emerald-100'
                        : 'bg-gray-50 text-gray-400 border border-gray-100'"
                    >
                      {{ node.enabled ? t('workflow.enabledValue') : t('workflow.disabledValue') }}
                    </span>
                  </div>

                  <!-- Row 2: display name (primary) -->
                  <div
                    class="text-[13px] font-semibold text-gray-800 leading-snug truncate"
                    :title="node.display_name || node.node_key"
                  >
                    {{ node.display_name || node.node_key }}
                  </div>

                  <!-- Row 3: node key (secondary) -->
                  <div class="text-[10px] text-gray-400 font-mono truncate mt-0.5">
                    {{ node.node_key }}
                  </div>
                  <div
                    class="text-[10px] text-gray-500 truncate mt-1"
                    :title="nodeDescription(node)"
                  >
                    {{ nodeBrief(node) }}
                  </div>

                  <!-- Row 4: branch label + dep count -->
                  <div class="flex items-center justify-between mt-auto pt-1.5">
                    <span
                      class="text-[10px] font-medium truncate"
                      :style="{ color: node.enabled ? getBranchColor(node.branch_key).hex + 'dd' : '#94a3b8' }"
                    >
                      {{ BRANCH_LABELS[node.branch_key] || node.branch_key }}
                    </span>
                    <span v-if="(node.depends_on || []).length" class="text-[9px] text-gray-300 shrink-0 ml-1">
                      {{ (node.depends_on || []).length }}↑
                    </span>
                  </div>
                </div>
              </button>

              <div v-if="store.loading" class="absolute inset-0 bg-white/70 backdrop-blur-[1px] flex items-center justify-center">
                <div class="text-sm text-gray-500">{{ t('workflow.loadingNodes') }}</div>
              </div>
            </div>
          </div>

          <div class="px-4 py-2.5 shrink-0 border-t border-gray-100 bg-gray-50/80">
            <div class="text-xs text-gray-400 flex items-center gap-1.5">
              <PhInfo class="text-gray-400 shrink-0" />
              <span>{{ t('workflow.notice') }}</span>
            </div>
          </div>
        </section>

        <!-- Drag handle for right panel (left edge of aside) -->
        <div
          v-if="panelVisible"
          class="w-1 shrink-0 cursor-col-resize bg-gray-100 hover:bg-primary/30 transition-colors z-10 relative group"
          @mousedown.prevent="startPanelDrag"
        >
          <div class="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[3px] h-10 rounded-full bg-transparent group-hover:bg-primary/50 transition-colors" />
        </div>

        <!-- Floating "show panel" button when panel is hidden -->
        <button
          v-if="!panelVisible"
          @click="showPanel"
          class="absolute right-4 top-4 z-20 bg-white border border-gray-200 rounded-lg px-3 py-2 text-xs text-gray-600 shadow-sm hover:shadow-md hover:border-primary hover:text-primary flex items-center gap-1.5 transition-all"
        >
          <PhSidebar class="text-base" />
          {{ t('workflow.showPanel') }}
        </button>

        <aside
          v-if="panelVisible"
          class="bg-white border-l border-gray-100 flex flex-col shrink-0 relative"
          :style="{ width: `${panelWidth}px` }"
        >
          <div class="px-4 py-3 border-b border-gray-100 bg-gray-50/50 flex items-center justify-between">
            <h2 class="font-bold text-xs text-gray-600 uppercase tracking-wide">{{ t('workflow.nodeDetails') }}</h2>
            <button
              @click="hidePanel"
              class="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              :title="t('workflow.hidePanel')"
            >
              <PhSidebar class="text-base" />
            </button>
          </div>
          <div class="flex-1 overflow-y-auto p-5">
            <div v-if="!selectedNode" class="flex flex-col items-center justify-center h-full text-center">
              <div class="w-12 h-12 rounded-xl bg-gray-100 flex items-center justify-center mb-3">
                <PhCursorClick class="text-2xl text-gray-400" />
              </div>
              <p class="text-sm text-gray-400">{{ t('workflow.selectHint') }}</p>
            </div>
            <div v-else class="space-y-4">
              <!-- Node header card -->
              <div class="rounded-xl border overflow-hidden" :class="getBranchColor(selectedNode.branch_key).border">
                <div class="h-1" :style="{ background: getBranchColor(selectedNode.branch_key).hex }" />
                <div class="p-4">
                  <div class="flex items-start justify-between mb-3">
                    <div class="flex items-center gap-2 min-w-0">
                      <div
                        class="w-8 h-8 rounded-full text-white flex items-center justify-center font-bold text-sm shrink-0"
                        :style="{ background: getBranchColor(selectedNode.branch_key).hex }"
                      >
                        {{ sequenceLabel(selectedNode) }}
                      </div>
                      <div class="min-w-0">
                        <div class="text-sm font-bold text-gray-900 truncate">
                          {{ selectedNode.display_name || selectedNode.node_key }}
                        </div>
                        <div class="text-[11px] text-gray-400 font-mono truncate">{{ selectedNode.node_key }}</div>
                      </div>
                    </div>
                    <StatusBadge :status="selectedNode.enabled ? 'success' : 'cancelled'" />
                  </div>
                  <div class="flex flex-wrap gap-1.5">
                    <span class="text-[10px] px-2 py-0.5 rounded-full border font-medium"
                      :style="{ color: getBranchColor(selectedNode.branch_key).hex, borderColor: getBranchColor(selectedNode.branch_key).hex + '44', background: getBranchColor(selectedNode.branch_key).hex + '11' }">
                      {{ BRANCH_LABELS[selectedNode.branch_key] || selectedNode.branch_key }}
                    </span>
                    <span class="text-[10px] px-2 py-0.5 rounded-full bg-gray-50 border border-gray-100 text-gray-500 font-mono">
                      seq={{ selectedNode.sequence }}
                    </span>
                  </div>
                </div>
              </div>

              <div class="rounded-xl border border-gray-100 bg-gray-50/80 p-4">
                <div class="text-xs text-gray-500 mb-2">{{ descriptionLabel }}</div>
                <p class="text-sm text-gray-700 leading-relaxed whitespace-pre-line">
                  {{ nodeDescription(selectedNode) }}
                </p>
              </div>

              <div class="border-t border-gray-100 pt-5">
                <div class="text-xs text-gray-500 mb-2">{{ t('workflow.dependsOn') }}</div>
                <div v-if="selectedDependencies.length" class="flex flex-wrap gap-2">
                  <button
                    v-for="dep in selectedDependencies"
                    :key="dep.node_key"
                    class="px-2.5 py-1 rounded border border-gray-200 bg-gray-50 text-xs font-mono text-gray-700 hover:bg-white"
                    @click="selectNode(dep)"
                  >
                    {{ dep.node_key }}
                  </button>
                </div>
                <div v-else class="text-sm text-gray-400">{{ t('workflow.none') }}</div>
              </div>

              <div class="border-t border-gray-100 pt-5">
                <div class="text-xs text-gray-500 mb-2">{{ t('workflow.downstreamNodes') }}</div>
                <div v-if="selectedDependents.length" class="flex flex-wrap gap-2">
                  <button
                    v-for="dep in selectedDependents"
                    :key="dep.node_key"
                    class="px-2.5 py-1 rounded border border-gray-200 bg-gray-50 text-xs font-mono text-gray-700 hover:bg-white"
                    @click="selectNode(dep)"
                  >
                    {{ dep.node_key }}
                  </button>
                </div>
                <div v-else class="text-sm text-gray-400">{{ t('workflow.none') }}</div>
              </div>

              <!-- I2I Test Batch specific configuration -->
              <div v-if="selectedNode.node_key === 'prepare_i2i_test_batch'" class="border-t border-gray-100 pt-4">
                <div class="text-xs text-gray-500 mb-3 font-semibold uppercase tracking-wide">{{ t('workflow.i2iTestConfig') }}</div>
                <div class="space-y-3">
                  <div class="bg-amber-50 border border-amber-100 rounded-lg px-3 py-2 text-xs text-amber-700">
                    {{ t('workflow.i2iTestNote') }}
                  </div>

                  <!-- Mode -->
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestMode') }}</label>
                    <select v-model="i2iTestConfig.mode" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none bg-white focus:border-primary">
                      <option value="single_male">{{ t('workflow.i2iTestModeSingleMale') }}</option>
                      <option value="single_female">{{ t('workflow.i2iTestModeSingleFemale') }}</option>
                      <option value="couple">{{ t('workflow.i2iTestModeCouple') }}</option>
                    </select>
                  </div>

                  <!-- Test Count -->
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestCount') }}</label>
                    <input
                      v-model.number="i2iTestConfig.test_count"
                      type="number"
                      min="1"
                      max="10"
                      class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary"
                    />
                  </div>

                  <!-- Test I2I Image Model -->
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">I2I Image Model</label>
                    <select v-model="i2iTestConfig.image_model" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none bg-white focus:border-primary">
                      <option v-for="m in i2iTestImageModels" :key="m.model_id" :value="m.model_id">
                        {{ m.display_name || m.model_id }}
                      </option>
                    </select>
                    <p class="text-[10px] text-gray-400 mt-0.5">Used only for I2I test first-frame generation.</p>
                  </div>

                  <!-- Test I2V Model -->
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestI2vModel') }}</label>
                    <select v-model="i2iTestConfig.i2v_model" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none bg-white focus:border-primary">
                      <option v-for="m in i2iTestModels" :key="m.model_id" :value="m.model_id">
                        {{ m.display_name || m.model_id }}
                      </option>
                    </select>
                    <p class="text-[10px] text-gray-400 mt-0.5">{{ t('workflow.i2iTestModelNote') }}</p>
                  </div>

                  <!-- Optional dataset dirs -->
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestMaleDir') }} <span class="text-gray-300">({{ t('common.optional') }})</span></label>
                    <input v-model="i2iTestConfig.male_dataset_dir" type="text" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" placeholder="workspace/personas/male" />
                  </div>
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestFemaleDir') }} <span class="text-gray-300">({{ t('common.optional') }})</span></label>
                    <input v-model="i2iTestConfig.female_dataset_dir" type="text" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" placeholder="workspace/personas/female" />
                  </div>

                  <button
                    @click="saveI2ITestConfig"
                    :disabled="savingI2IConfig"
                    class="w-full py-2 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-sm font-medium disabled:opacity-60"
                  >
                    {{ savingI2IConfig ? t('workflow.saving') : t('workflow.saveModelConfig') }}
                  </button>
                </div>
              </div>

              <div class="border-t border-gray-100 pt-5">
                <div class="flex items-center justify-between mb-3">
                  <div class="text-xs text-gray-500">{{ t('workflow.modelConfiguration') }}</div>
                  <span v-if="selectedTaskType" class="text-[11px] px-2 py-0.5 rounded bg-gray-100 text-gray-600 font-mono">
                    {{ selectedTaskType }}
                  </span>
                </div>

                <div v-if="!selectedTaskType" class="text-sm text-gray-400 bg-gray-50 border border-gray-100 rounded-lg p-3">
                  {{ t('workflow.noDirectModelTask') }}
                </div>

                <div v-else class="space-y-4">
                  <div>
                    <label class="text-xs text-gray-500 mb-1 block">{{ t('workflow.model') }}</label>
                    <select
                      v-model="nodeModelId"
                      class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none bg-white focus:border-primary"
                      @change="onNodeModelChange"
                    >
                      <option value="">{{ t('workflow.useBackendDefault') }}</option>
                      <option v-for="m in availableModels" :key="m.model_id" :value="m.model_id">
                        {{ m.display_name || m.model_id }}
                      </option>
                    </select>
                  </div>

                  <div v-if="!availableModels.length && !modelStore.loading" class="text-sm text-gray-400 bg-gray-50 border border-gray-100 rounded-lg p-3">
                    {{ t('workflow.noModelsForTask') }}
                  </div>

                  <div v-for="(schema, paramKey) in currentParamSchema" :key="paramKey">
                    <label class="text-xs text-gray-500 mb-1 block">{{ schema.label || paramKey }}</label>
                    <select
                      v-if="schema.enum"
                      v-model="nodeModelParams[paramKey]"
                      class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none bg-white focus:border-primary"
                    >
                      <option v-for="opt in schema.enum" :key="opt" :value="opt">{{ opt }}</option>
                    </select>
                    <label
                      v-else-if="schema.type === 'boolean'"
                      class="flex items-center justify-between border border-gray-200 rounded-lg px-3 py-2 bg-white"
                    >
                      <span class="text-sm text-gray-700">{{ nodeModelParams[paramKey] ? t('workflow.enabledValue') : t('workflow.disabledValue') }}</span>
                      <input v-model="nodeModelParams[paramKey]" type="checkbox" class="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary" />
                    </label>
                    <input
                      v-else-if="schema.type === 'integer' || schema.type === 'number'"
                      v-model.number="nodeModelParams[paramKey]"
                      type="number"
                      :min="schema.min"
                      :max="schema.max"
                      class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary"
                    />
                    <input
                      v-else
                      v-model="nodeModelParams[paramKey]"
                      type="text"
                      class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary"
                    />
                  </div>

                  <button
                    @click="saveNodeConfig"
                    :disabled="savingConfig"
                    class="w-full py-2.5 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-60"
                  >
                    {{ savingConfig ? t('workflow.saving') : t('workflow.saveModelConfig') }}
                  </button>
                </div>
              </div>

              <div class="border-t border-gray-100 pt-5">
                <div class="flex items-center justify-between bg-gray-50/80 p-3 rounded-lg border border-gray-100">
                  <span class="text-sm font-medium text-gray-800">{{ t('workflow.enableNode') }}</span>
                  <ToggleSwitch
                    :id="`toggle-${selectedNode.node_key}`"
                    :model-value="selectedNode.enabled"
                    @update:model-value="(v) => toggleNode(selectedNode.node_key, v)"
                  />
                </div>
                <button
                  @click="toggleNode(selectedNode.node_key, !selectedNode.enabled)"
                  class="w-full py-2.5 border rounded-lg text-sm font-medium flex items-center justify-center transition-colors mt-3"
                  :class="selectedNode.enabled ? 'border-red-200 text-red-500 hover:bg-red-50' : 'border-green-200 text-green-600 hover:bg-green-50'"
                >
                  <PhProhibit v-if="selectedNode.enabled" class="mr-1.5 text-lg" />
                  <PhCheckCircle v-else class="mr-1.5 text-lg" />
                  {{ selectedNode.enabled ? t('workflow.disable') : t('workflow.enable') }}
                </button>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </main>
    <ToastContainer />

    <!-- Workflow Job Wizard -->
    <WorkflowJobWizard v-if="showCreateJobPanel" mode="advanced" @close="showCreateJobPanel = false" />
  </div>
</template>

<script setup>
import { computed, defineComponent, h, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppSidebar from '@/components/layout/AppSidebar.vue'
import ToastContainer from '@/components/common/ToastContainer.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ToggleSwitch from '@/components/common/ToggleSwitch.vue'
import WorkflowJobWizard from '@/components/workflow/WorkflowJobWizard.vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useModelStore } from '@/stores/models'
import { useTemplateStore } from '@/stores/templates'
import { useSeriesStore } from '@/stores/series'
import { useToggleResizablePanel } from '@/composables/useResizablePanel'
import { useToast } from '@/composables/useToast'
import { BRANCH_COLORS, BRANCH_LABELS } from '@/utils/constants'
import {
  PhArrowsClockwise, PhCheckCircle, PhInfo, PhCursorClick, PhProhibit, PhPlus, PhSidebar,
} from '@phosphor-icons/vue'

import { useI18n } from 'vue-i18n'

const DetailRow = defineComponent({
  props: {
    label: { type: String, required: true },
    value: { type: String, required: true },
  },
  setup(props) {
    return () => h('div', [
      h('div', { class: 'text-xs text-gray-500 mb-1' }, props.label),
      h('div', { class: 'text-sm font-medium text-gray-900 break-words' }, props.value),
    ])
  },
})

const router = useRouter()
const store = useWorkflowStore()
const modelStore = useModelStore()
const templateStore = useTemplateStore()
const seriesStore = useSeriesStore()
const toast = useToast()
const showCreateJobPanel = ref(false)

// Right panel: resizable + togglable
const {
  width: panelWidth,
  startDrag: startPanelDrag,
  isVisible: panelVisible,
  toggle: togglePanel,
  show: showPanel,
} = useToggleResizablePanel('workflow:detail-panel', {
  defaultWidth: 380,
  minWidth: 300,
  maxWidth: 560,
  side: 'left',
})

function hidePanel() {
  panelVisible.value = false
  localStorage.setItem('workflow:detail-panel:visible', 'false')
}
const { t, locale } = useI18n()


const selectedKey = ref(null)
const canvasContainer = ref(null)
const availableModels = ref([])
const nodeModelId = ref('')
const nodeModelParams = ref({})
const savingConfig = ref(false)

// I2I Test Batch specific config state
const i2iTestConfig = ref({
  mode: 'couple',
  test_count: 3,
  image_model: 'wan2.7-image',
  i2v_model: 'wan2.6-i2v-flash',
  male_dataset_dir: '',
  female_dataset_dir: '',
})
const savingI2IConfig = ref(false)
// Only show flash-speed I2V models for I2I test (NOT main i2v models)
const i2iTestModels = computed(() =>
  withFallbackModel(
    modelStore.models.filter((m) => m.task_type === 'image_to_video'),
    { model_id: 'wan2.6-i2v-flash', display_name: 'Wan 2.6 I2V Flash' }
  )
)
const i2iTestImageModels = computed(() =>
  withFallbackModel(
    modelStore.models.filter((m) => m.task_type === 'text_to_image'),
    { model_id: 'wan2.7-image', display_name: 'Wan 2.7 Image' }
  )
)

const cardW = 224
const cardH = 120
const canvasWidth = 2360
const canvasHeight = 1030

const lanes = computed(() => [
  { key: 'first_i2v', label: t('workflow.laneImageI2v'), y: 88, height: 162, color: BRANCH_COLORS.first_frame_image.hex },
  { key: 'core', label: t('workflow.laneCorePrompt'), y: 288, height: 162, color: BRANCH_COLORS.core.hex },
  { key: 'i2i_test', label: 'I2I Test', y: 488, height: 142, color: BRANCH_COLORS.i2i_test.hex },
  { key: 't2v', label: t('workflow.laneT2v'), y: 660, height: 142, color: BRANCH_COLORS.t2v.hex },
  { key: 'r2v', label: t('workflow.laneR2v'), y: 832, height: 142, color: BRANCH_COLORS.r2v_flash.hex },
])

const branchLegend = computed(() => [
  { key: 'core', label: t('workflow.branchCore'), hex: BRANCH_COLORS.core.hex },
  { key: 'first_frame_image', label: t('workflow.branchFirstFrame'), hex: BRANCH_COLORS.first_frame_image.hex },
  { key: 'i2v', label: 'I2V', hex: BRANCH_COLORS.i2v.hex },
  { key: 'i2i_test', label: 'I2I Test', hex: BRANCH_COLORS.i2i_test.hex },
  { key: 't2v', label: 'T2V', hex: BRANCH_COLORS.t2v.hex },
  { key: 'r2v_flash', label: 'R2V', hex: BRANCH_COLORS.r2v_flash.hex },
])

const fixedPositions = {
  // Core prompt path
  reverse_prompts:    { x: 60,   y: 288 },
  rewrite_prompts:    { x: 340,  y: 288 },
  export_manifest:    { x: 2080, y: 288 },
  // I2I test path
  rewrite_t2i_to_i2i:    { x: 620,  y: 488 },
  prepare_i2i_test_batch:{ x: 860,  y: 488 },
  submit_i2i_test_image: { x: 1100, y: 488 },
  poll_i2i_test_image:   { x: 1340, y: 488 },
  submit_i2i_test_i2v:   { x: 1580, y: 488 },
  poll_i2i_test_i2v:     { x: 1820, y: 488 },
  // First Frame + I2V main path
  submit_first_frame_image: { x: 900,  y: 88 },
  poll_first_frame_image:   { x: 1180, y: 88 },
  submit_i2v:               { x: 1460, y: 88 },
  poll_i2v:                 { x: 1740, y: 88 },
  // T2V optional
  submit_t2v:               { x: 620,  y: 660 },
  poll_t2v:                 { x: 900,  y: 660 },
  // R2V / utility
  reverse_prompts4r2v:      { x: 620,  y: 832 },
  submit_r2v_flash:         { x: 900,  y: 832 },
  poll_r2v_flash:           { x: 1180, y: 832 },
  failure_agent:            { x: 1460, y: 832 },
}

const branchFallbackY = {
  first_frame_image: 88,
  i2v: 88,
  core: 288,
  i2i_test: 488,
  t2v: 660,
  r2v_flash: 832,
}

const nodeMap = computed(() => new Map(store.nodes.map((node) => [node.node_key, node])))

const nodePositions = computed(() => {
  const fallbackCount = {}
  return store.nodes.reduce((positions, node) => {
    if (fixedPositions[node.node_key]) {
      positions[node.node_key] = fixedPositions[node.node_key]
      return positions
    }
    const branch = node.branch_key || 'core'
    const idx = fallbackCount[branch] || 0
    fallbackCount[branch] = idx + 1
    positions[node.node_key] = {
      x: 80 + idx * 280,
      y: branchFallbackY[branch] || 600,
    }
    return positions
  }, {})
})

const layoutNodes = computed(() => (
  [...store.nodes]
    .sort((a, b) => a.sequence - b.sequence)
    .map((node) => ({
      ...node,
      position: nodePositions.value[node.node_key] || { x: 80, y: 260 },
    }))
))

const selectedNode = computed(() => {
  if (!selectedKey.value) return null
  return nodeMap.value.get(selectedKey.value) || null
})

const selectedTaskType = computed(() => {
  if (!selectedNode.value) return ''
  return nodeToTaskType(selectedNode.value)
})

const selectedModel = computed(() => (
  availableModels.value.find((model) => model.model_id === nodeModelId.value) || null
))

const currentParamSchema = computed(() => selectedModel.value?.parameter_schema || {})

const selectedDependencies = computed(() => {
  if (!selectedNode.value) return []
  return (selectedNode.value.depends_on || [])
    .map((key) => nodeMap.value.get(key))
    .filter(Boolean)
})

const selectedDependents = computed(() => {
  if (!selectedNode.value) return []
  return store.nodes.filter((node) => (node.depends_on || []).includes(selectedNode.value.node_key))
})

const descriptionLabel = computed(() =>
  String(locale.value || '').startsWith('zh') ? '说明' : 'Description'
)

const connectionPaths = computed(() => {
  const paths = []
  const producedByResource = {}
  store.nodes.forEach((node) => {
    ;(node.produces || []).forEach((resourceKey) => {
      if (!producedByResource[resourceKey]) producedByResource[resourceKey] = []
      producedByResource[resourceKey].push(node)
    })
  })

  function pushEdge(fromNode, node, edgeKind = 'depends_on') {
    const to = nodePositions.value[node.node_key]
    const from = nodePositions.value[fromNode.node_key]
    if (!from || !to) return

    const fromX = from.x + cardW
    const fromY = from.y + cardH / 2
    const toX = to.x
    const toY = to.y + cardH / 2

    const active = node.enabled && fromNode.enabled
    const highlight = selectedKey.value === node.node_key || selectedKey.value === fromNode.node_key
    const dx = Math.abs(toX - fromX)
    const cpDist = Math.max(dx * 0.45, 80)
    const cx1 = fromX + cpDist
    const cy1 = fromY
    const cx2 = toX - cpDist
    const cy2 = toY
    const isResource = edgeKind === 'resource'
    const strokeColor = active
      ? (highlight ? getBranchColor(node.branch_key).hex : getBranchColor(node.branch_key).hex + (isResource ? '88' : 'cc'))
      : '#cbd5e1'

    paths.push({
      id: `${edgeKind}:${fromNode.node_key}->${node.node_key}`,
      path: `M ${fromX} ${fromY} C ${cx1} ${cy1},${cx2} ${cy2},${toX} ${toY}`,
      stroke: strokeColor,
      strokeWidth: highlight ? 2.5 : active ? (isResource ? 1.4 : 1.8) : 1.2,
      opacity: highlight ? 1 : active ? (isResource ? 0.55 : 0.75) : 0.5,
      dashed: !active || isResource,
      highlight,
      edgeKind,
    })
  }

  store.nodes.forEach((node) => {
    ;(node.depends_on || []).forEach((depKey) => {
      const fromNode = nodeMap.value.get(depKey)
      if (!fromNode) return
      pushEdge(fromNode, node)
    })
    ;(node.required_inputs || []).forEach((resourceKey) => {
      ;(producedByResource[resourceKey] || []).forEach((fromNode) => {
        if (fromNode.node_key === node.node_key) return
        if ((node.depends_on || []).includes(fromNode.node_key)) return
        pushEdge(fromNode, node, 'resource')
      })
    })
  })
  return paths
})

function getBranchColor(branchKey) {
  return BRANCH_COLORS[branchKey] || BRANCH_COLORS.core
}

function sequenceLabel(node) {
  return Math.max(1, Math.floor((node.sequence || 10) / 10))
}

function nodeDescription(node) {
  if (!node) return ''
  const isZh = String(locale.value || '').startsWith('zh')
  return (isZh ? node.description_zh : node.description_en)
    || node.description_en
    || node.description_zh
    || node.display_name
    || node.node_key
}

function nodeBrief(node) {
  const text = nodeDescription(node)
  return text.split(/[。.!?]/)[0] || text
}

function uniqueModelsById(list) {
  const byId = new Map()
  ;(list || []).forEach((model) => {
    const modelId = model.model_id || model.model_key
    if (!modelId || byId.has(modelId)) return
    byId.set(modelId, { ...model, model_id: modelId })
  })
  return [...byId.values()]
}

function withFallbackModel(list, fallback) {
  const models = uniqueModelsById(list)
  if (!models.some((model) => model.model_id === fallback.model_id)) {
    models.push(fallback)
  }
  return models
}

function selectNode(node) {
  selectedKey.value = node.node_key
  // Auto-show panel when a node is clicked
  showPanel()
}

function nodeToTaskType(node) {
  const key = node.node_key
  if (key === 'reverse_prompts') return 'video_understanding'
  if (key === 'rewrite_prompts' || key === 'reverse_prompts4r2v' || key === 'rewrite_t2i_to_i2i' || key === 'failure_agent') return 'prompt_rewrite'
  if (key === 'submit_t2v') return 'text_to_video'
  if (key === 'submit_first_frame_image' || key === 'submit_i2i_test_image') return 'text_to_image'
  if (key === 'submit_i2v' || key === 'submit_i2i_test_i2v') return 'image_to_video'
  if (key === 'submit_r2v_flash') return 'reference_to_video'
  return ''
}

function nodeToTaskTypes(node) {
  if (node.node_key === 'rewrite_prompts' || node.node_key === 'reverse_prompts4r2v' || node.node_key === 'rewrite_t2i_to_i2i') return ['prompt_rewrite', 'text_to_text']
  const taskType = nodeToTaskType(node)
  return taskType ? [taskType] : []
}

function fallbackParamValue(schema) {
  if (schema.default !== undefined) return schema.default
  if (schema.enum?.length) return schema.enum[0]
  if (schema.type === 'boolean') return false
  if (schema.type === 'integer' || schema.type === 'number') return schema.min ?? 0
  return ''
}

function applyModelDefaults(overwrite = false) {
  const model = selectedModel.value
  if (!model) return
  const next = overwrite ? {} : { ...nodeModelParams.value }
  const defaults = model.default_params || {}
  Object.entries(model.parameter_schema || {}).forEach(([key, schema]) => {
    if (overwrite || next[key] === undefined) {
      next[key] = defaults[key] !== undefined ? defaults[key] : fallbackParamValue(schema)
    }
  })
  nodeModelParams.value = next
}

function onNodeModelChange() {
  applyModelDefaults(true)
}

async function loadNodeModelConfig(node) {
  const config = node.config || {}
  nodeModelId.value = config.model_id || ''
  nodeModelParams.value = { ...(config.model_params || {}) }
  availableModels.value = []

  const taskTypes = nodeToTaskTypes(node)
  if (!taskTypes.length) return

  const modelsById = new Map()
  for (const taskType of taskTypes) {
    await modelStore.fetchModels({ task_type: taskType })
    modelStore.models.forEach((model) => modelsById.set(model.model_id, model))
  }
  availableModels.value = uniqueModelsById([...modelsById.values()])
  if (!nodeModelId.value && availableModels.value.length) {
    nodeModelId.value = availableModels.value[0].model_id
  }
  applyModelDefaults(false)
}

async function refreshNodes() {
  await store.fetchNodes()
  if (selectedKey.value && !nodeMap.value.has(selectedKey.value)) {
    selectedKey.value = null
  }
}

async function toggleNode(nodeKey, enable) {
  try {
    if (enable) {
      await store.enableNode(nodeKey)
    } else {
      await store.disableNode(nodeKey)
    }
    toast.success(`${enable ? t('workflow.enabledToast', { key: nodeKey }) : t('workflow.disabledToast', { key: nodeKey })}`)
  } catch (e) {
    toast.error(t('workflow.toggleFailed'))
  }
}

async function saveNodeConfig() {
  if (!selectedNode.value) return
  savingConfig.value = true
  try {
    await store.updateNodeConfig(selectedNode.value.node_key, {
      model_id: nodeModelId.value || null,
      model_params: { ...nodeModelParams.value },
    })
    toast.success(t('workflow.modelConfigSaved'))
  } catch (e) {
    toast.error(t('workflow.modelConfigSaveFailed'))
  } finally {
    savingConfig.value = false
  }
}

watch(selectedNode, async (node) => {
  if (!node) {
    nodeModelId.value = ''
    nodeModelParams.value = {}
    availableModels.value = []
    return
  }
  // Load I2I test batch config when selecting that node
  if (node.node_key === 'prepare_i2i_test_batch') {
    const cfg = (node.config || {}).i2i_test || {}
    i2iTestConfig.value = {
      mode: cfg.mode || 'couple',
      test_count: cfg.test_count ?? 3,
      image_model: cfg.image_model || 'wan2.7-image',
      i2v_model: cfg.i2v_model || 'wan2.6-i2v-flash',
      male_dataset_dir: cfg.male_dataset_dir || '',
      female_dataset_dir: cfg.female_dataset_dir || '',
    }
  }
  try {
    await loadNodeModelConfig(node)
  } catch {
    availableModels.value = []
  }
})

async function saveI2ITestConfig() {
  savingI2IConfig.value = true
  try {
    await store.updateNodeConfig('prepare_i2i_test_batch', {
      i2i_test: { ...i2iTestConfig.value },
    })
    toast.success(t('workflow.modelConfigSaved'))
  } catch {
    toast.error(t('workflow.modelConfigSaveFailed'))
  } finally {
    savingI2IConfig.value = false
  }
}

function openCreateJobPanel() {
  showCreateJobPanel.value = true
}

onMounted(async () => {
  await Promise.all([refreshNodes(), modelStore.fetchModels()])
})
</script>
