<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[100] flex flex-col bg-white overflow-hidden">

      <!-- ── Header ─────────────────────────────────────────── -->
      <header class="shrink-0 flex items-center justify-between px-8 py-4 border-b border-gray-100 bg-white">
        <div>
          <h2 class="text-base font-bold text-gray-900">{{ t('workflow.wizardTitle') }}</h2>
          <p class="text-xs text-gray-400 mt-0.5">{{ t('workflow.wizardSubtitle') }}</p>
        </div>
        <button
          @click="$emit('close')"
          class="p-2 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
        >
          <PhX class="text-xl" />
        </button>
      </header>

      <!-- ── Step Indicator ──────────────────────────────────── -->
      <div class="shrink-0 bg-gray-50 border-b border-gray-100 px-8 py-4">
        <div class="max-w-2xl mx-auto flex items-center">
          <template v-for="(label, i) in stepLabels" :key="i">
            <div class="flex flex-col items-center min-w-0">
              <div
                class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all duration-200 shrink-0"
                :class="{
                  'bg-green-500 text-white': step > i + 1,
                  'bg-primary text-white shadow shadow-primary/30': step === i + 1,
                  'bg-gray-200 text-gray-500': step < i + 1,
                }"
              >
                <PhCheck v-if="step > i + 1" class="text-sm" />
                <span v-else>{{ i + 1 }}</span>
              </div>
              <span
                class="text-[11px] mt-1 font-medium whitespace-nowrap"
                :class="{
                  'text-primary': step === i + 1,
                  'text-green-600': step > i + 1,
                  'text-gray-400': step < i + 1,
                }"
              >{{ label }}</span>
            </div>
            <div
              v-if="i < stepLabels.length - 1"
              class="flex-1 h-0.5 mx-3 mb-4 rounded transition-colors duration-300"
              :class="step > i + 1 ? 'bg-green-400' : 'bg-gray-200'"
            />
          </template>
        </div>
      </div>

      <!-- ── Body ────────────────────────────────────────────── -->
      <div class="flex-1 overflow-y-auto">
        <div class="max-w-2xl mx-auto px-8 py-8">

          <!-- Step 1: 选择模板 -->
          <div v-if="step === 1" class="space-y-5">
            <div>
              <h3 class="text-base font-bold text-gray-900 mb-0.5">{{ t('workflow.wizardStep1') }}</h3>
              <p class="text-sm text-gray-500">{{ t('workflow.wizardStep1Desc') }}</p>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1.5">{{ t('series.select') }}</label>
              <select
                v-model="selectedSeriesId"
                @change="onSeriesChange"
                class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm bg-white focus:border-primary outline-none transition-colors"
              >
                <option value="">{{ t('workflow.wizardAllSeries') }}</option>
                <option v-for="s in seriesStore.seriesList" :key="s.series_id" :value="s.series_id">
                  {{ s.name }}{{ s.is_default ? ` (${t('series.default')})` : '' }}
                </option>
              </select>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1.5">
                {{ t('template.select') }} <span class="text-red-400">*</span>
              </label>
              <select
                v-model="selectedTemplateId"
                class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm bg-white focus:border-primary outline-none transition-colors"
              >
                <option value="">{{ t('workflow.selectTemplatePlaceholder') }}</option>
                <option v-for="tmpl in filteredTemplates" :key="tmpl.template_id" :value="tmpl.template_id">
                  {{ tmpl.name || tmpl.template_id }}
                </option>
              </select>
              <p v-if="selectedSeriesId && !filteredTemplates.length" class="text-xs text-gray-400 mt-1.5">
                {{ t('workflow.wizardNoTemplates') }}
              </p>
            </div>

            <div v-if="selectedTemplate" class="rounded-xl border border-blue-100 bg-blue-50/40 p-4 space-y-1">
              <div class="text-sm font-semibold text-blue-900">
                {{ selectedTemplate.name || selectedTemplate.template_id }}
              </div>
              <div v-if="selectedTemplate.description" class="text-sm text-blue-700">
                {{ selectedTemplate.description }}
              </div>
              <div class="text-xs text-blue-500 font-mono mt-0.5">{{ selectedTemplate.template_id }}</div>
            </div>

            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1.5">{{ t('workflow.wizardJobName') }}</label>
              <input
                v-model="jobName"
                type="text"
                class="w-full border border-gray-200 rounded-xl px-3.5 py-2.5 text-sm bg-white focus:border-primary outline-none transition-colors"
                :placeholder="t('workflow.wizardJobNamePlaceholder')"
              />
            </div>

            <div v-if="!isAdvancedMode" class="space-y-3">
              <div>
                <h4 class="text-sm font-bold text-gray-900">{{ t('workflow.wizardRunPath') }}</h4>
                <p class="text-xs text-gray-500 mt-0.5">{{ t('workflow.wizardRunPathHelp') }}</p>
              </div>
              <div class="grid grid-cols-1 gap-2">
                <button
                  v-for="route in routeOptions"
                  :key="route.key"
                  type="button"
                  @click="toggleRoute(route.key)"
                  class="text-left border rounded-xl p-3 transition-colors"
                  :class="selectedRouteKeys.includes(route.key)
                    ? 'border-primary bg-blue-50/50'
                    : 'border-gray-200 bg-white hover:bg-gray-50'"
                >
                  <div class="flex items-center justify-between gap-3">
                    <div class="min-w-0">
                      <div class="text-sm font-semibold text-gray-900">{{ route.label }}</div>
                      <div class="text-xs text-gray-500 mt-0.5">{{ route.description }}</div>
                    </div>
                    <span
                      class="w-5 h-5 rounded-full border flex items-center justify-center shrink-0"
                      :class="selectedRouteKeys.includes(route.key) ? 'bg-primary border-primary text-white' : 'border-gray-300 text-transparent'"
                    >
                      <PhCheck class="text-xs" />
                    </span>
                  </div>
                  <div class="mt-2 text-[10px] text-gray-400 font-mono truncate">
                    {{ route.nodes.join(' -> ') }}
                  </div>
                </button>
              </div>
            </div>
          </div>

          <!-- Step 2: 识别输入 -->
          <div v-else-if="step === 2" class="space-y-5">
            <div>
              <h3 class="text-base font-bold text-gray-900 mb-0.5">{{ t('workflow.wizardStep2') }}</h3>
              <p class="text-sm text-gray-500">{{ t('workflow.wizardStep2Desc') }}</p>
            </div>

            <!-- Loading -->
            <div v-if="validating" class="flex flex-col items-center justify-center py-16 gap-4">
              <div class="w-12 h-12 border-4 border-primary/20 border-t-primary rounded-full animate-spin" />
              <div class="text-sm text-gray-500">{{ t('workflow.validating') }}</div>
            </div>

            <!-- Error -->
            <div v-else-if="validateError" class="bg-red-50 border border-red-200 rounded-xl p-5 space-y-3">
              <div class="flex items-center gap-2">
                <PhWarningCircle class="text-red-500 text-lg shrink-0" />
                <span class="text-sm font-semibold text-red-800">{{ t('workflow.wizardDetectionFailed') }}</span>
              </div>
              <p class="text-sm text-red-700 leading-relaxed pl-6">{{ validateError }}</p>
              <button
                @click="runValidation"
                class="ml-6 text-xs text-red-600 underline hover:no-underline font-medium"
              >
                {{ t('workflow.wizardRetry') }}
              </button>
            </div>

            <!-- Success: No inputs needed -->
            <div
              v-else-if="validateResult && !visibleInputs.length"
              class="bg-green-50 border border-green-100 rounded-xl p-5 flex items-center gap-4"
            >
              <div class="w-10 h-10 bg-green-500 rounded-full flex items-center justify-center shrink-0">
                <PhCheck class="text-white text-base" />
              </div>
              <div>
                <div class="text-sm font-semibold text-green-800">{{ t('workflow.wizardNoInputsRequired') }}</div>
                <div class="text-xs text-green-600 mt-0.5">{{ t('workflow.wizardProceedToCreate') }}</div>
              </div>
            </div>

            <!-- Success: Has required inputs -->
            <div v-else-if="validateResult && visibleInputs.length" class="space-y-3">
              <div class="flex items-center gap-2 px-3.5 py-3 bg-blue-50 border border-blue-100 rounded-xl">
                <span class="text-sm text-blue-800 font-medium">
                  {{ t('workflow.wizardInputsDetected', { count: visibleInputs.length }) }}
                </span>
              </div>

              <div
                v-for="inp in visibleInputs"
                :key="inp.key"
                class="flex items-center gap-3 p-3.5 bg-white border border-gray-200 rounded-xl"
              >
                <div
                  class="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                  :class="inp.type === 'video' ? 'bg-blue-100 text-blue-600' : 'bg-purple-100 text-purple-600'"
                >
                  <PhFilmSlate v-if="inp.type === 'video'" class="text-base" />
                  <PhTextT v-else class="text-base" />
                </div>
                <div class="flex-1 min-w-0">
                  <div class="text-sm font-semibold text-gray-900">{{ getInputLabel(inp) }}</div>
                  <div class="text-xs text-gray-400 font-mono mt-0.5">{{ inp.key }}</div>
                </div>
                <span
                  class="text-[11px] px-2 py-0.5 rounded-full border font-medium shrink-0"
                  :class="inp.required
                    ? 'border-red-100 bg-red-50 text-red-600'
                    : 'border-gray-100 bg-gray-50 text-gray-500'"
                >
                  {{ inp.required ? t('common.required') : t('common.optional') }}
                </span>
              </div>
            </div>
          </div>

          <!-- Step 3: 提供输入 -->
          <div v-else-if="step === 3" class="space-y-5">
            <div>
              <h3 class="text-base font-bold text-gray-900 mb-0.5">{{ t('workflow.wizardStep3') }}</h3>
              <p class="text-sm text-gray-500">{{ t('workflow.wizardStep3Desc') }}</p>
            </div>

            <!-- No inputs needed -->
            <div v-if="!visibleInputs.length" class="text-center py-12">
              <div class="w-12 h-12 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-3">
                <PhCheck class="text-green-600 text-xl" />
              </div>
              <p class="text-sm text-gray-400">{{ t('workflow.wizardNoInputsRequired') }}</p>
            </div>

            <!-- Input cards -->
            <div v-for="inp in visibleInputs" :key="inp.key" class="border border-gray-200 rounded-xl overflow-hidden">
              <!-- Card header -->
              <div class="flex items-center gap-2.5 px-5 py-3.5 bg-gray-50 border-b border-gray-100">
                <div
                  class="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
                  :class="inp.type === 'video' ? 'bg-blue-100 text-blue-600' : 'bg-purple-100 text-purple-600'"
                >
                  <PhFilmSlate v-if="inp.type === 'video'" class="text-sm" />
                  <PhTextT v-else class="text-sm" />
                </div>
                <div class="text-sm font-semibold text-gray-900 flex-1 min-w-0">
                  {{ getInputLabel(inp) }}<span v-if="inp.required" class="text-red-400 ml-1">*</span>
                </div>
                <span v-if="isInputReady(inp)" class="text-xs text-green-600 font-medium flex items-center gap-1 shrink-0">
                  <PhCheck class="text-sm" />{{ t('common.provided') }}
                </span>
              </div>

              <!-- Video input: drag-drop upload only -->
              <div v-if="inp.type === 'video'" class="p-5">
                <div
                  class="border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-150 select-none"
                  :class="draggingOver ? 'border-primary bg-blue-50/40' : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50/50'"
                  @dragover.prevent="draggingOver = true"
                  @dragleave.self="draggingOver = false"
                  @drop.prevent="onVideoDrop"
                  @click="triggerVideoInput"
                >
                  <input
                    ref="videoInputRef"
                    type="file"
                    accept=".mp4,.mov,.avi,.mkv,video/*"
                    class="hidden"
                    @change="onVideoFileChange"
                  />
                  <template v-if="videoFile">
                    <PhFilmSlate class="text-4xl text-blue-500 mx-auto mb-2" />
                    <div class="text-sm font-semibold text-gray-800">{{ videoFile.name }}</div>
                    <div class="text-xs text-gray-500 mt-1">
                      {{ formatFileSize(videoFile.size) }} · {{ formatFileType(videoFile) }}
                    </div>
                    <button
                      @click.stop="clearVideoFile"
                      class="mt-3 text-xs text-red-400 hover:text-red-600 underline"
                    >{{ t('common.remove') }}</button>
                  </template>
                  <template v-else>
                    <PhCloudArrowUp class="text-4xl text-gray-400 mx-auto mb-2" />
                    <div class="text-sm text-gray-500 mb-2">{{ t('workflow.wizardDragVideo') }}</div>
                    <div
                      class="inline-block px-4 py-1.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors"
                      @click.stop="triggerVideoInput"
                    >
                      {{ t('workflow.wizardChooseVideo') }}
                    </div>
                    <div class="text-xs text-gray-400 mt-3">{{ t('workflow.wizardVideoAccept') }}</div>
                  </template>
                </div>
              </div>

              <!-- Reference images input -->
              <div v-else-if="inp.type === 'multi_image' || inp.key === 'reference_images'" class="p-5">
                <div
                  class="border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all duration-150 select-none"
                  :class="draggingImagesOver ? 'border-primary bg-blue-50/40' : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50/50'"
                  @dragover.prevent="draggingImagesOver = true"
                  @dragleave.self="draggingImagesOver = false"
                  @drop.prevent="onReferenceImagesDrop"
                  @click="triggerReferenceImageInput"
                >
                  <input
                    ref="referenceImageInputRef"
                    type="file"
                    accept="image/*,.png,.jpg,.jpeg,.webp"
                    multiple
                    class="hidden"
                    @change="onReferenceImagesChange"
                  />
                  <template v-if="referenceImageFiles.length">
                    <PhFile class="text-3xl text-blue-500 mx-auto mb-2" />
                    <div class="text-sm font-semibold text-gray-800">
                      {{ referenceImageFiles.length }} image(s) selected
                    </div>
                    <div class="text-xs text-gray-500 mt-1">
                      {{ referenceImageFiles.map((file) => file.name).join(', ') }}
                    </div>
                    <button
                      @click.stop="clearReferenceImages"
                      class="mt-3 text-xs text-red-400 hover:text-red-600 underline"
                    >{{ t('common.remove') }}</button>
                  </template>
                  <template v-else>
                    <PhCloudArrowUp class="text-3xl text-gray-400 mx-auto mb-2" />
                    <div class="text-sm text-gray-500 mb-2">{{ t('workflow.referenceImages') }}</div>
                    <div class="text-xs text-gray-400 mb-3">
                      Optional. If left empty, the backend samples local project images.
                    </div>
                    <div
                      class="inline-block px-4 py-1.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-600 hover:bg-gray-50 transition-colors"
                      @click.stop="triggerReferenceImageInput"
                    >
                      {{ t('workflow.chooseImages') }}
                    </div>
                  </template>
                </div>
              </div>

              <!-- Prompt input -->
              <div v-else-if="isPromptInput(inp)" class="p-5 space-y-4">
                <!-- Source selector tabs -->
                <div class="flex gap-2 p-1 bg-gray-100 rounded-lg">
                  <button
                    v-for="src in promptSources"
                    :key="src.value"
                    @click="setInputSource(inp.key, src.value)"
                    class="flex-1 py-1.5 px-2 rounded-md text-xs font-medium transition-all duration-150"
                    :class="inputSources[inp.key] === src.value
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'"
                  >
                    {{ src.label }}
                  </button>
                </div>

                <!-- System Prompt Picker -->
                <PromptPicker
                  v-if="inputSources[inp.key] === 'system'"
                  :prompt-type="getPromptType(inp)"
                  :model-value="inputValues[inp.key] || ''"
                  @update:model-value="(v) => { inputValues[inp.key] = v }"
                />

                <!-- Local File -->
                <div v-else-if="inputSources[inp.key] === 'file'" class="space-y-2">
                  <label
                    class="flex items-center gap-3 px-4 py-3 border-2 border-dashed border-gray-200 rounded-xl cursor-pointer hover:border-primary/40 hover:bg-blue-50/20 transition-colors"
                  >
                    <input
                      type="file"
                      accept=".md,.txt"
                      class="hidden"
                      @change="(e) => onPromptFileChange(inp.key, e)"
                    />
                    <PhFile class="text-gray-400 text-xl shrink-0" />
                    <div class="min-w-0">
                      <div class="text-sm text-gray-700 truncate">
                        {{ promptFileNames[inp.key] || t('workflow.wizardChooseFile') }}
                      </div>
                      <div class="text-xs text-gray-400 mt-0.5">{{ t('workflow.wizardFileAccept') }}</div>
                    </div>
                  </label>
                  <div v-if="inputValues[inp.key]" class="bg-gray-50 border border-gray-200 rounded-lg p-3">
                    <div class="text-[10px] text-gray-400 uppercase tracking-wider mb-1.5">{{ t('workflow.wizardPreview') }}</div>
                    <div class="text-xs text-gray-700 font-mono whitespace-pre-wrap max-h-28 overflow-y-auto leading-relaxed">{{ inputValues[inp.key] }}</div>
                  </div>
                </div>

                <!-- Manual Textarea -->
                <textarea
                  v-else
                  :value="inputValues[inp.key] || ''"
                  @input="(e) => { inputValues[inp.key] = e.target.value }"
                  rows="6"
                  class="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm font-mono outline-none focus:border-primary resize-none transition-colors leading-relaxed"
                  :placeholder="t('workflow.wizardManualPlaceholder', { label: getInputLabel(inp) })"
                />
              </div>
            </div>

            <div v-if="needsI2IConfig" class="border border-amber-200 bg-amber-50 rounded-xl p-4 space-y-3">
              <div class="text-xs font-semibold text-amber-700 uppercase tracking-wide">I2I Test Configuration</div>
              <div>
                <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestMode') }}</label>
                <select v-model="i2iConfig.mode" class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white">
                  <option value="couple">{{ t('workflow.i2iTestModeCouple') }} (couple)</option>
                  <option value="single_male">{{ t('workflow.i2iTestModeSingleMale') }} (single_male)</option>
                  <option value="single_female">{{ t('workflow.i2iTestModeSingleFemale') }} (single_female)</option>
                </select>
              </div>
              <div>
                <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestCount') }}</label>
                <input
                  v-model.number="i2iConfig.test_count"
                  type="number"
                  min="1"
                  max="10"
                  class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white"
                />
              </div>
            </div>
          </div>

          <!-- Step 4: 创建作业 -->
          <div v-else-if="step === 4" class="space-y-5">
            <div>
              <h3 class="text-base font-bold text-gray-900 mb-0.5">{{ t('workflow.wizardStep4') }}</h3>
              <p class="text-sm text-gray-500">{{ t('workflow.wizardStep4Desc') }}</p>
            </div>

            <!-- Summary card -->
            <div class="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
              <div class="flex items-center justify-between px-5 py-3.5">
                <span class="text-sm text-gray-500">{{ t('template.select') }}</span>
                <span class="text-sm font-semibold text-gray-900">
                  {{ selectedTemplate?.name || selectedTemplateId }}
                </span>
              </div>
              <div v-if="selectedTemplate?.series_name || selectedSeriesId" class="flex items-center justify-between px-5 py-3.5">
                <span class="text-sm text-gray-500">{{ t('series.select') }}</span>
                <span class="text-sm font-semibold text-gray-900">
                  {{ selectedTemplate?.series_name || selectedSeriesId || '--' }}
                </span>
              </div>
              <div class="flex items-start gap-4 px-5 py-3.5">
                <span class="text-sm text-gray-500 shrink-0 mt-0.5">{{ t('workflow.requiredInputs') }}</span>
                <div class="flex-1 space-y-1.5 text-right">
                  <div v-if="!requiredInputs.length" class="text-sm text-gray-400">
                    {{ t('workflow.noRequiredInputs') }}
                  </div>
                  <div v-for="inp in requiredInputs" :key="inp.key" class="flex items-center justify-end gap-2">
                    <span class="text-sm" :class="isInputReady(inp) ? 'text-gray-700' : 'text-red-400'">
                      {{ getInputLabel(inp) }}
                    </span>
                    <div
                      class="w-2 h-2 rounded-full shrink-0"
                      :class="isInputReady(inp) ? 'bg-green-500' : 'bg-red-400'"
                    />
                  </div>
                </div>
              </div>
            </div>

            <div v-if="configurableWorkflowNodes.length" class="rounded-xl border border-blue-100 bg-blue-50/30 p-4 space-y-3">
              <div>
                <div class="text-sm font-bold text-gray-900">Workflow Defaults</div>
                <div class="text-xs text-gray-500 mt-0.5">
                  Defaults are inherited from Workflow Nodes. Adjustments here apply only to this Job.
                </div>
              </div>
              <div class="space-y-3">
                <div
                  v-for="node in configurableWorkflowNodes"
                  :key="node.node_key"
                  class="bg-white border border-blue-100 rounded-xl p-3 space-y-3"
                >
                  <div class="flex items-center justify-between gap-3">
                    <div class="min-w-0">
                      <div class="text-sm font-semibold text-gray-900 truncate">
                        {{ node.display_name || node.node_key }}
                      </div>
                      <div class="text-[11px] text-gray-400 font-mono truncate">{{ node.node_key }}</div>
                    </div>
                    <span class="text-[11px] px-2 py-0.5 rounded-full bg-gray-50 border border-gray-100 text-gray-500 shrink-0">
                      {{ node.branch_key || 'core' }}
                    </span>
                  </div>
                  <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <label class="block">
                      <span class="text-xs text-gray-500 block mb-1">Model</span>
                      <select
                        :value="nodeModelOverrides[node.node_key] || ''"
                        class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white"
                        @change="onWizardNodeModelChange(node, $event.target.value)"
                      >
                        <option value="">Use backend default</option>
                        <option v-for="model in modelOptionsForNode(node)" :key="model.model_id" :value="model.model_id">
                          {{ model.display_name || model.model_id }}
                        </option>
                      </select>
                    </label>
                    <template v-for="entry in paramSchemaEntriesForNode(node)" :key="`${node.node_key}:${entry.key}`">
                      <label class="block">
                        <span class="text-xs text-gray-500 block mb-1">{{ entry.schema.label || entry.key }}</span>
                        <select
                          v-if="entry.schema.enum?.length"
                          :value="nodeParamValue(node.node_key, entry.key)"
                          class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white"
                          @change="setNodeParamValue(node.node_key, entry.key, $event.target.value)"
                        >
                          <option v-for="option in entry.schema.enum" :key="option" :value="option">{{ option }}</option>
                        </select>
                        <label v-else-if="entry.schema.type === 'boolean'" class="flex items-center gap-2 border border-gray-200 rounded-lg px-2.5 py-2 bg-white">
                          <input
                            type="checkbox"
                            :checked="!!nodeParamValue(node.node_key, entry.key)"
                            @change="setNodeParamValue(node.node_key, entry.key, $event.target.checked)"
                          />
                          <span class="text-sm text-gray-700">{{ nodeParamValue(node.node_key, entry.key) ? 'Enabled' : 'Disabled' }}</span>
                        </label>
                        <input
                          v-else-if="entry.schema.type === 'integer' || entry.schema.type === 'number'"
                          :type="'number'"
                          :step="entry.schema.type === 'integer' ? 1 : 0.1"
                          :min="entry.schema.min"
                          :max="entry.schema.max"
                          :value="nodeParamValue(node.node_key, entry.key)"
                          class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white"
                          @input="setNodeParamValue(node.node_key, entry.key, coerceParamValue(entry.schema, $event.target.value))"
                        />
                        <input
                          v-else
                          :value="nodeParamValue(node.node_key, entry.key)"
                          class="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm bg-white"
                          @input="setNodeParamValue(node.node_key, entry.key, $event.target.value)"
                        />
                      </label>
                    </template>
                  </div>
                </div>
              </div>
            </div>

            <!-- Mode selector -->
            <div class="rounded-xl border border-gray-200 p-4">
              <div class="text-sm font-medium text-gray-700 mb-3">{{ t('workflow.wizardMode') }}</div>
              <div class="grid grid-cols-2 gap-2">
                <button
                  @click="createMode = 'run'"
                  class="py-2.5 rounded-xl text-sm font-medium border transition-all duration-150"
                  :class="createMode === 'run'
                    ? 'bg-primary text-white border-primary shadow-sm'
                    : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'"
                >
                  {{ t('workflow.createAndRun') }}
                </button>
                <button
                  @click="createMode = 'create'"
                  class="py-2.5 rounded-xl text-sm font-medium border transition-all duration-150"
                  :class="createMode === 'create'
                    ? 'bg-primary text-white border-primary shadow-sm'
                    : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'"
                >
                  {{ t('workflow.createOnly') }}
                </button>
              </div>
            </div>

            <!-- Missing required inputs warning -->
            <div v-if="missingRequiredInputs.length" class="bg-orange-50 border border-orange-200 rounded-xl p-4 space-y-2">
              <div class="flex items-center gap-2">
                <PhWarningCircle class="text-orange-500 text-base shrink-0" />
                <span class="text-sm font-semibold text-orange-800">{{ t('workflow.wizardMissingInputs') }}</span>
              </div>
              <ul class="list-disc list-inside space-y-0.5 pl-1">
                <li v-for="inp in missingRequiredInputs" :key="inp.key" class="text-sm text-orange-700">
                  {{ getInputLabel(inp) }}
                </li>
              </ul>
              <p class="text-xs text-orange-600 mt-1">
                <button @click="step = 3" class="underline hover:no-underline">{{ t('workflow.wizardGoBack') }}</button>
              </p>
            </div>
          </div>

        </div>
      </div>

      <!-- ── Footer ───────────────────────────────────────────── -->
      <footer class="shrink-0 border-t border-gray-100 bg-gray-50 px-8 py-4 flex items-center justify-between">
        <button
          v-if="step > 1"
          @click="step--"
          :disabled="validating"
          class="px-5 py-2.5 border border-gray-200 rounded-xl text-sm font-medium text-gray-600 bg-white hover:bg-gray-50 disabled:opacity-50 transition-colors"
        >
          {{ t('workflow.wizardPrev') }}
        </button>
        <div v-else />

        <div class="flex items-center gap-3">
          <button
            @click="$emit('close')"
            class="px-4 py-2.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
          >
            {{ t('common.cancel') }}
          </button>

          <button
            v-if="step < 4"
            @click="nextStep"
            :disabled="!canGoNext || validating"
            class="px-6 py-2.5 bg-primary text-white rounded-xl text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center gap-2"
          >
            <span v-if="validating" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            {{ validating ? t('workflow.validating') : t('workflow.wizardNext') }}
          </button>

          <button
            v-else
            @click="submitJob"
            :disabled="creatingJob || missingRequiredInputs.length > 0"
            class="px-6 py-2.5 bg-primary text-white rounded-xl text-sm font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors flex items-center gap-2"
          >
            <span v-if="creatingJob" class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            {{ creatingJob
              ? t('workflow.creatingJob')
              : (createMode === 'run' ? t('workflow.createAndRun') : t('workflow.createOnly')) }}
          </button>
        </div>
      </footer>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { PhX, PhCheck, PhWarningCircle, PhFilmSlate, PhTextT, PhCloudArrowUp, PhFile } from '@phosphor-icons/vue'
import PromptPicker from './PromptPicker.vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useSeriesStore } from '@/stores/series'
import { useTemplateStore } from '@/stores/templates'
import { useModelStore } from '@/stores/models'
import { useToast } from '@/composables/useToast'
import { setRecentJob } from '@/composables/useRecentJob'
import { validateRun } from '@/api/workflow'
import { createJob, runFull } from '@/api/jobs'

const props = defineProps({
  mode: { type: String, default: 'quick' },
  defaultTemplateId: { type: String, default: '' },
  defaultSeriesId: { type: String, default: '' },
  defaultRouteKeys: { type: Array, default: () => ['main_i2v'] },
})
const emit = defineEmits(['close', 'created'])
const { t } = useI18n()
const router = useRouter()
const workflowStore = useWorkflowStore()
const seriesStore = useSeriesStore()
const templateStore = useTemplateStore()
const modelStore = useModelStore()
const toast = useToast()

// ── Wizard state ──────────────────────────────────────────────────

const step = ref(1)
const stepLabels = computed(() => [
  t('workflow.wizardStep1'),
  t('workflow.wizardStep2'),
  t('workflow.wizardStep3'),
  t('workflow.wizardStep4'),
])

// Step 1
const selectedSeriesId = ref('')
const selectedTemplateId = ref('')
const jobName = ref('')

const filteredTemplates = computed(() => {
  const all = templateStore.templates
  if (!selectedSeriesId.value) return all
  return all.filter((tmpl) => {
    const s = tmpl.series_id || tmpl.series || 'default'
    return s === selectedSeriesId.value
  })
})

const selectedTemplate = computed(() =>
  templateStore.templates.find((tmpl) => tmpl.template_id === selectedTemplateId.value) ?? null
)

// Step 2
const validating = ref(false)
const validateResult = ref(null)
const validateError = ref('')

const requiredInputs = computed(() => validateResult.value?.required_inputs ?? [])
const optionalInputs = computed(() => validateResult.value?.optional_inputs ?? [])
const visibleInputs = computed(() => {
  const byKey = new Map()
  requiredInputs.value.forEach((inp) => byKey.set(inp.key, inp))
  optionalInputs.value.forEach((inp) => {
    if (!byKey.has(inp.key)) byKey.set(inp.key, { ...inp, required: false })
  })
  return [...byKey.values()]
})

// Step 3
const inputSources = reactive({})   // key → 'system' | 'file' | 'manual'
const inputValues = reactive({})    // key → string content
const promptFileNames = reactive({})// key → filename string
const videoFile = ref(null)
const videoInputRef = ref(null)
const referenceImageFiles = ref([])
const referenceImageInputRef = ref(null)
const draggingOver = ref(false)
const draggingImagesOver = ref(false)
const i2iConfig = reactive({
  mode: 'couple',
  test_count: 3,
})
const nodeModelOverrides = reactive({})
const nodeParamOverrides = reactive({})

// Step 4
const createMode = ref('run')
const creatingJob = ref(false)

// ── Source options ────────────────────────────────────────────────

const promptSources = computed(() => [
  { value: 'system', label: t('workflow.wizardSourceSystem') },
  { value: 'file',   label: t('workflow.wizardSourceFile')   },
  { value: 'manual', label: t('workflow.wizardSourceManual') },
])

const isAdvancedMode = computed(() => props.mode === 'advanced')

const routeOptions = computed(() => [
  {
    key: 'main_i2v',
    label: t('workflow.routeMainI2v'),
    description: t('workflow.routeMainI2vDesc'),
    nodes: ['reverse_prompts', 'rewrite_prompts', 'submit_first_frame_image', 'poll_first_frame_image', 'submit_i2v', 'poll_i2v', 'export_manifest'],
  },
  {
    key: 'prompt_core',
    label: t('workflow.routePromptCore'),
    description: t('workflow.routePromptCoreDesc'),
    nodes: ['reverse_prompts', 'rewrite_prompts', 'rewrite_t2i_to_i2i', 'export_manifest'],
  },
  {
    key: 'i2i_test',
    label: t('workflow.routeI2iTest'),
    description: t('workflow.routeI2iTestDesc'),
    nodes: ['reverse_prompts', 'rewrite_prompts', 'rewrite_t2i_to_i2i', 'prepare_i2i_test_batch', 'submit_i2i_test_image', 'poll_i2i_test_image', 'submit_i2i_test_i2v', 'poll_i2i_test_i2v', 'export_manifest'],
  },
  {
    key: 'i2i_test_image_only',
    label: t('workflow.routeI2iTestImageOnly'),
    description: t('workflow.routeI2iTestImageOnlyDesc'),
    nodes: ['reverse_prompts', 'rewrite_prompts', 'rewrite_t2i_to_i2i', 'prepare_i2i_test_batch', 'submit_i2i_test_image', 'poll_i2i_test_image', 'export_manifest'],
  },
  {
    key: 't2v',
    label: t('workflow.routeT2v'),
    description: t('workflow.routeT2vDesc'),
    nodes: ['reverse_prompts', 'submit_t2v', 'poll_t2v', 'export_manifest'],
  },
  {
    key: 'r2v_flash',
    label: t('workflow.routeR2vFlash'),
    description: t('workflow.routeR2vFlashDesc'),
    nodes: ['reverse_prompts', 'reverse_prompts4r2v', 'submit_r2v_flash', 'poll_r2v_flash', 'export_manifest'],
  },
])
const selectedRouteKeys = ref([...props.defaultRouteKeys])

// ── Helpers ───────────────────────────────────────────────────────

function getInputLabel(inp) {
  const map = {
    'source_video':            t('workflow.sourceVideo'),
    'prompt:t2v':              t('workflow.t2vPrompt'),
    'prompt:i2v':              t('workflow.i2vPrompt'),
    'prompt:first_frame_image':t('workflow.firstFramePrompt'),
    'prompt:r2v_flash':        t('workflow.r2vPrompt'),
    'prompt:i2i':              t('workflow.wizardI2iPrompt'),
    'prompt:t2i':              t('workflow.wizardT2iPrompt'),
  }
  return map[inp.key] || inp.label || inp.key
}

function getPromptType(inp) {
  return inp.key.replace('prompt:', '')
}

function isPromptInput(inp) {
  return !!inp.key?.startsWith('prompt:')
}

function isInputReady(inp) {
  if (inp.type === 'video') return !!videoFile.value
  if (inp.type === 'multi_image' || inp.key === 'reference_images') return referenceImageFiles.value.length > 0
  if (inp.key === 'i2i_test_batch' || inp.type === 'i2i_test') return i2iConfigValid.value
  if (isPromptInput(inp)) return !!String(inputValues[inp.key] || '').trim()
  return false
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatFileType(file) {
  return file?.type || file?.name?.split('.').pop()?.toUpperCase() || 'video'
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

function nodeTaskTypes(nodeKey) {
  if (nodeKey === 'reverse_prompts') return ['video_understanding']
  if (['rewrite_prompts', 'reverse_prompts4r2v', 'rewrite_t2i_to_i2i', 'failure_agent'].includes(nodeKey)) {
    return ['prompt_rewrite', 'text_to_text']
  }
  if (nodeKey === 'submit_t2v') return ['text_to_video']
  if (['submit_first_frame_image', 'submit_i2i_test_image'].includes(nodeKey)) return ['text_to_image']
  if (['submit_i2v', 'submit_i2i_test_i2v'].includes(nodeKey)) return ['image_to_video']
  if (nodeKey === 'submit_r2v_flash') return ['reference_to_video']
  return []
}

function modelOptionsForNode(node) {
  const taskTypes = new Set(nodeTaskTypes(node.node_key))
  return uniqueModelsById(
    modelStore.models.filter((model) => taskTypes.has(model.task_type))
  )
}

function selectedModelForNode(node) {
  const modelId = nodeModelOverrides[node.node_key] || ''
  return modelStore.models.find((model) => model.model_id === modelId) || null
}

function paramSchemaEntriesForNode(node) {
  const model = selectedModelForNode(node)
  if (!model?.parameter_schema) return []
  return Object.entries(model.parameter_schema).map(([key, schema]) => ({ key, schema }))
}

function fallbackParamValue(schema) {
  if (schema.default !== undefined) return schema.default
  if (schema.enum?.length) return schema.enum[0]
  if (schema.type === 'boolean') return false
  if (schema.type === 'integer' || schema.type === 'number') return schema.min ?? 0
  return ''
}

function ensureNodeParamBag(nodeKey) {
  if (!nodeParamOverrides[nodeKey]) nodeParamOverrides[nodeKey] = {}
  return nodeParamOverrides[nodeKey]
}

function initialParamsForNode(node, model) {
  const params = {}
  const defaults = model?.default_params || {}
  Object.entries(model?.parameter_schema || {}).forEach(([key, schema]) => {
    params[key] = defaults[key] !== undefined ? defaults[key] : fallbackParamValue(schema)
  })
  Object.assign(params, node?.config?.model_params || {})
  return params
}

function ensureWorkflowNodeDefaults(overwrite = false) {
  configurableWorkflowNodes.value.forEach((node) => {
    const options = modelOptionsForNode(node)
    const defaultModelId = node.config?.model_id || options[0]?.model_id || ''
    if (overwrite || nodeModelOverrides[node.node_key] === undefined) {
      nodeModelOverrides[node.node_key] = defaultModelId
    }
    const model = modelStore.models.find((item) => item.model_id === nodeModelOverrides[node.node_key])
    if (overwrite || !nodeParamOverrides[node.node_key]) {
      nodeParamOverrides[node.node_key] = initialParamsForNode(node, model)
    }
  })
}

function onWizardNodeModelChange(node, modelId) {
  nodeModelOverrides[node.node_key] = modelId
  const model = modelStore.models.find((item) => item.model_id === modelId)
  nodeParamOverrides[node.node_key] = initialParamsForNode(node, model)
}

function nodeParamValue(nodeKey, key) {
  return ensureNodeParamBag(nodeKey)[key]
}

function setNodeParamValue(nodeKey, key, value) {
  ensureNodeParamBag(nodeKey)[key] = value
}

function coerceParamValue(schema, value) {
  if (schema.type === 'integer') {
    const parsed = Number.parseInt(value, 10)
    return Number.isFinite(parsed) ? parsed : fallbackParamValue(schema)
  }
  if (schema.type === 'number') {
    const parsed = Number.parseFloat(value)
    return Number.isFinite(parsed) ? parsed : fallbackParamValue(schema)
  }
  return value
}

function nonEmptyObject(obj) {
  return Object.fromEntries(
    Object.entries(obj || {}).filter(([, value]) => value !== undefined && value !== null && value !== '')
  )
}

function buildNodeModelConfig() {
  ensureWorkflowNodeDefaults(false)
  const selected = new Set(selectedNodeKeys.value)
  return Object.fromEntries(
    Object.entries(nodeModelOverrides)
      .filter(([nodeKey, modelId]) => selected.has(nodeKey) && modelId)
  )
}

function buildNodeParamConfig() {
  ensureWorkflowNodeDefaults(false)
  const selected = new Set(selectedNodeKeys.value)
  return Object.fromEntries(
    Object.entries(nodeParamOverrides)
      .map(([nodeKey, params]) => [nodeKey, nonEmptyObject(params)])
      .filter(([nodeKey, params]) => selected.has(nodeKey) && Object.keys(params).length)
  )
}

// ── Computed state ────────────────────────────────────────────────

const canGoNext = computed(() => {
  if (step.value === 1) return !!selectedTemplateId.value
  if (step.value === 2) return !!validateResult.value && !validating.value
  return true
})

const missingRequiredInputs = computed(() =>
  requiredInputs.value.filter((inp) => inp.required && !isInputReady(inp))
)

const selectedNodeKeys = computed(() =>
  effectiveEnabledNodeKeys.value
)

const configurableWorkflowNodes = computed(() => {
  const selected = new Set(selectedNodeKeys.value)
  return workflowStore.nodes
    .filter((node) => selected.has(node.node_key) && nodeTaskTypes(node.node_key).length)
    .sort((a, b) => Number(a.sequence || 0) - Number(b.sequence || 0))
})

const needsI2IConfig = computed(() =>
  selectedNodeKeys.value.some((key) =>
    ['prepare_i2i_test_batch', 'submit_i2i_test_image', 'poll_i2i_test_image', 'submit_i2i_test_i2v', 'poll_i2i_test_i2v'].includes(key)
  ) ||
  (validateResult.value?.required_inputs || []).some((inp) =>
    inp.key === 'i2i_test_batch' || inp.type === 'i2i_test'
  )
)

const i2iConfigValid = computed(() => {
  const count = Number(i2iConfig.test_count)
  return ['couple', 'single_male', 'single_female'].includes(i2iConfig.mode)
    && Number.isInteger(count)
    && count >= 1
})

const selectedRouteNodes = computed(() => {
  const keys = new Set()
  const selected = routeOptions.value.filter((route) => selectedRouteKeys.value.includes(route.key))
  selected.forEach((route) => route.nodes.forEach((nodeKey) => keys.add(nodeKey)))
  return [...keys]
})

const effectiveEnabledNodeKeys = computed(() => {
  if (isAdvancedMode.value) return workflowStore.enabledNodes.map((node) => node.node_key)
  return selectedRouteNodes.value
})

const effectiveDisabledNodeKeys = computed(() => {
  if (isAdvancedMode.value) return workflowStore.disabledNodes.map((node) => node.node_key)
  const enabled = new Set(effectiveEnabledNodeKeys.value)
  return workflowStore.nodes
    .map((node) => node.node_key)
    .filter((nodeKey) => !enabled.has(nodeKey))
})

function applyI2INodeDefaults() {
  const node = workflowStore.nodes.find((item) => item.node_key === 'prepare_i2i_test_batch')
  const cfg = node?.config?.i2i_test || {}
  if (['couple', 'single_male', 'single_female'].includes(cfg.mode)) {
    i2iConfig.mode = cfg.mode
  }
  const count = Number(cfg.test_count)
  if (Number.isInteger(count) && count >= 1 && count <= 10) {
    i2iConfig.test_count = count
  }
}

function toggleRoute(key) {
  if (selectedRouteKeys.value.includes(key)) {
    selectedRouteKeys.value = selectedRouteKeys.value.filter((item) => item !== key)
    if (!selectedRouteKeys.value.length) selectedRouteKeys.value = ['prompt_core']
    return
  }
  selectedRouteKeys.value = [...selectedRouteKeys.value, key]
}

// ── Step 1 actions ────────────────────────────────────────────────

function onSeriesChange() {
  selectedTemplateId.value = ''
  const first = filteredTemplates.value[0]
  if (first) selectedTemplateId.value = first.template_id
}

// Reset validation when template changes
watch(selectedTemplateId, () => {
  validateResult.value = null
  validateError.value = ''
})

watch(selectedRouteKeys, () => {
  validateResult.value = null
  validateError.value = ''
  ensureWorkflowNodeDefaults(false)
})

watch(
  () => `${selectedNodeKeys.value.join('|')}::${workflowStore.nodes.length}::${modelStore.models.length}`,
  () => ensureWorkflowNodeDefaults(false)
)

// ── Step 2 actions ────────────────────────────────────────────────

async function runValidation() {
  validating.value = true
  validateResult.value = null
  validateError.value = ''
  try {
    const enabledNodes = effectiveEnabledNodeKeys.value
    const disabledNodes = effectiveDisabledNodeKeys.value
    const result = await validateRun({
      template_id: selectedTemplateId.value,
      enabled_nodes: enabledNodes,
      disabled_nodes: disabledNodes,
      initial_prompts: {},
      initial_artifacts: {},
    })
    validateResult.value = result
  } catch (e) {
    const raw = e?.response?.data?.error?.message || t('workflow.validationFailed')
    validateError.value = friendlyError(raw)
  } finally {
    validating.value = false
  }
}

function friendlyError(msg) {
  if (!msg) return t('workflow.validationFailed')
  // Node dependency errors → user-friendly message
  if (msg.includes('requires') && (msg.includes('_') || msg.includes('node'))) {
    return t('workflow.wizardNodeDependencyError')
  }
  return msg
}

// ── Step 3 actions ────────────────────────────────────────────────

function initInputStates() {
  visibleInputs.value.forEach((inp) => {
    if (isPromptInput(inp) && !inputSources[inp.key]) {
      inputSources[inp.key] = 'manual'
    }
    if (inputValues[inp.key] === undefined) {
      inputValues[inp.key] = ''
    }
  })
}

function setInputSource(key, source) {
  if (inputSources[key] === source) return
  inputSources[key] = source
  inputValues[key] = ''
  promptFileNames[key] = ''
}

function onVideoFileChange(event) {
  videoFile.value = event.target.files?.[0] ?? null
}

function triggerVideoInput() {
  const input = Array.isArray(videoInputRef.value) ? videoInputRef.value[0] : videoInputRef.value
  input?.click()
}

function clearVideoFile() {
  videoFile.value = null
  const input = Array.isArray(videoInputRef.value) ? videoInputRef.value[0] : videoInputRef.value
  if (input) input.value = ''
}

function onReferenceImagesChange(event) {
  referenceImageFiles.value = Array.from(event.target.files || [])
}

function triggerReferenceImageInput() {
  const input = Array.isArray(referenceImageInputRef.value)
    ? referenceImageInputRef.value[0]
    : referenceImageInputRef.value
  input?.click()
}

function clearReferenceImages() {
  referenceImageFiles.value = []
  const input = Array.isArray(referenceImageInputRef.value)
    ? referenceImageInputRef.value[0]
    : referenceImageInputRef.value
  if (input) input.value = ''
}

function onReferenceImagesDrop(event) {
  draggingImagesOver.value = false
  referenceImageFiles.value = Array.from(event.dataTransfer?.files || [])
    .filter((file) => file.type.startsWith('image/'))
}

function onVideoDrop(event) {
  draggingOver.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  const vid = files.find((f) => f.type.startsWith('video/'))
  if (vid) videoFile.value = vid
}

function onPromptFileChange(key, event) {
  const file = event.target.files?.[0]
  if (!file) return
  promptFileNames[key] = file.name
  const reader = new FileReader()
  reader.onload = (e) => {
    inputValues[key] = e.target?.result ?? ''
  }
  reader.onerror = () => {
    toast.error(t('workflow.wizardFileReadError'))
  }
  reader.readAsText(file)
}

// ── Navigation ────────────────────────────────────────────────────

async function nextStep() {
  if (step.value === 1) {
    if (!selectedTemplateId.value) return
    step.value = 2
    await runValidation()
  } else if (step.value === 2) {
    if (!validateResult.value) return
    initInputStates()
    step.value = 3
  } else if (step.value === 3) {
    step.value = 4
  }
}

// ── Submit ────────────────────────────────────────────────────────

async function submitJob() {
  if (!selectedTemplateId.value) {
    toast.error(t('workflow.selectTemplateRequired'))
    return
  }
  if (missingRequiredInputs.value.length) {
    toast.error(t('workflow.wizardMissingRequired'))
    return
  }

  creatingJob.value = true
  try {
    const enabledNodes = effectiveEnabledNodeKeys.value
    const disabledNodes = effectiveDisabledNodeKeys.value
    const startNode = validateResult.value?.start_nodes?.[0] ?? null
    const nodeModels = buildNodeModelConfig()
    const nodeModelParams = buildNodeParamConfig()
    const jobConfig = {
      node_models: nodeModels,
      node_model_params: nodeModelParams,
    }
    if (needsI2IConfig.value) {
      jobConfig.i2i_test = {
        enabled: true,
        mode: i2iConfig.mode,
        test_count: i2iConfig.test_count,
      }
    }

    // Build initial_prompts
    const initialPrompts = {}
    visibleInputs.value.forEach((inp) => {
      if (!isPromptInput(inp)) return
      const content = String(inputValues[inp.key] || '').trim()
      if (!content) return
      const srcMap = { system: 'existing_prompt', file: 'local_file', manual: 'manual' }
      initialPrompts[getPromptType(inp)] = {
        source: srcMap[inputSources[inp.key]] || 'manual',
        content,
        prompt_key: 'default',
      }
    })

    let result
    if (videoFile.value || referenceImageFiles.value.length) {
      const fd = new FormData()
      fd.append('template_id', selectedTemplateId.value)
      if (jobName.value.trim()) fd.append('job_name', jobName.value.trim())
      fd.append('strategy', 'workflow_selection')
      if (startNode) fd.append('start_node', startNode)
      if (videoFile.value) fd.append('source_video', videoFile.value)
      referenceImageFiles.value.forEach((file) => fd.append('reference_images', file))
      fd.append('enabled_nodes', JSON.stringify(enabledNodes))
      fd.append('disabled_nodes', JSON.stringify(disabledNodes))
      fd.append('job_config', JSON.stringify(jobConfig))
      fd.append('initial_prompts', JSON.stringify(initialPrompts))
      fd.append('initial_artifacts', '{}')
      result = await createJob(fd)
    } else {
      result = await createJob({
        template_id: selectedTemplateId.value,
        job_name: jobName.value.trim() || undefined,
        strategy: 'workflow_selection',
        start_node: startNode,
        enabled_nodes: enabledNodes,
        disabled_nodes: disabledNodes,
        initial_prompts: initialPrompts,
        initial_artifacts: {},
        job_config: jobConfig,
      })
    }

    const jobId = result?.job_id
    if (!jobId) throw new Error('No job ID returned')
    setRecentJob(jobId)
    toast.success(t('workflow.jobCreated', { id: jobId }))
    if (createMode.value === 'run') {
      try { await runFull(jobId) } catch { /* ignore */ }
    }
    emit('created', jobId)
    emit('close')
    router.push(`/jobs/${jobId}`)
  } catch (e) {
    toast.error(e?.response?.data?.error?.message || t('workflow.createJobFailed'))
  } finally {
    creatingJob.value = false
  }
}

// ── Init ──────────────────────────────────────────────────────────

onMounted(async () => {
  await Promise.all([
    seriesStore.fetchSeries(),
    templateStore.fetchTemplates(),
    modelStore.fetchModels(),
    workflowStore.nodes.length ? Promise.resolve() : workflowStore.fetchNodes(),
  ])
  applyI2INodeDefaults()
  ensureWorkflowNodeDefaults(false)
  if (props.defaultTemplateId) {
    const tmpl = templateStore.templates.find((item) => item.template_id === props.defaultTemplateId)
    selectedSeriesId.value = props.defaultSeriesId || tmpl?.series_id || tmpl?.series || ''
    selectedTemplateId.value = props.defaultTemplateId
    return
  }
  if (props.defaultSeriesId) {
    selectedSeriesId.value = props.defaultSeriesId
  } else {
    const def = seriesStore.seriesList.find((s) => s.is_default)
    if (def) selectedSeriesId.value = def.series_id
  }
  const first = filteredTemplates.value[0]
  if (first) selectedTemplateId.value = first.template_id
})
</script>
