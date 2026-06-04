<template>
  <DefaultLayout :title="t('jobCreate.title')" :subtitle="t('jobCreate.subtitle')">
    <div class="max-w-[1600px] mx-auto space-y-6">
      <!-- Step indicator -->
      <div class="bg-white rounded-xl border border-gray-100 p-6 flex items-center justify-between px-16 shadow-sm">
        <div v-for="(step, i) in steps" :key="i" class="flex items-center">
          <div
            :class="currentStep >= i + 1 ? 'bg-primary text-white' : 'border border-gray-300 text-gray-400'"
            class="w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold mr-2"
          >{{ i + 1 }}</div>
          <span :class="currentStep >= i + 1 ? 'text-primary font-medium' : 'text-gray-400'" class="text-sm">{{ step }}</span>
          <div v-if="i < steps.length - 1" class="w-[80px] mx-4 border-t-2 border-dashed border-gray-200"></div>
        </div>
      </div>

      <div class="flex gap-6 items-start">
        <div class="flex-1 space-y-6">
          <!-- Step 1: Select Template -->
          <div v-if="currentStep === 1" class="bg-white rounded-xl border border-gray-100 p-6 shadow-sm">
            <h2 class="text-base font-bold text-gray-900 mb-1">1. {{ t('jobCreate.step1') }}</h2>
            <p class="text-sm text-gray-500 mb-4">{{ t('jobCreate.templateDesc') }}</p>
            <select v-model="form.template_id" class="w-full appearance-none border border-gray-200 rounded-lg pl-4 pr-10 py-2.5 text-sm text-gray-800 outline-none focus:border-primary bg-white font-medium mb-4">
              <option value="">{{ t('jobCreate.selectTemplatePlaceholder') }}</option>
              <option v-for="t in templateStore.templates" :key="t.template_id || t.id" :value="t.template_id || t.id">{{ t.name || t.template_id }}</option>
            </select>
            <label class="block text-xs text-gray-500 mb-1">Job Name</label>
            <input v-model="form.job_name" type="text" class="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-primary" placeholder="Optional display name" />
          </div>

          <!-- Step 2: Upload Source -->
          <div v-if="currentStep === 2" class="bg-white rounded-xl border border-gray-100 p-6 shadow-sm">
            <h2 class="text-base font-bold text-gray-900 mb-1">2. {{ t('jobCreate.step2') }}</h2>
            <p class="text-sm text-gray-500 mb-4">{{ t('jobCreate.uploadDesc') }}</p>
            <div class="border-2 border-dashed border-gray-200 rounded-xl flex flex-col items-center justify-center py-10 mb-4 bg-gray-50/50">
              <PhCloudArrowUp class="text-4xl text-primary mb-3" />
              <div class="text-sm font-bold text-gray-800 mb-1">{{ t('jobCreate.dragDropVideo') }}</div>
              <div class="text-xs text-gray-400 mb-3">{{ t('jobCreate.or') }}</div>
              <label class="px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 shadow-sm cursor-pointer">
                {{ t('jobCreate.chooseFile') }}
                <input type="file" ref="fileInput" accept="video/*" class="hidden" @change="onFileChange" />
              </label>
            </div>
            <div v-if="selectedFile" class="border border-green-200 bg-green-50/30 rounded-lg p-3 flex items-center">
              <div class="w-16 h-10 bg-gray-800 rounded mr-4 flex items-center justify-center shrink-0">
                <PhPlayCircle weight="fill" class="text-white text-xl" />
              </div>
              <div class="flex-1 min-w-0">
                <h4 class="text-sm font-bold text-gray-900 truncate">{{ selectedFile.name }}</h4>
                <p class="text-xs text-gray-500">{{ (selectedFile.size / 1024 / 1024).toFixed(1) }} MB</p>
              </div>
              <PhCheckCircle weight="fill" class="text-green-500 text-lg mr-3" />
              <button @click="selectedFile = null" class="text-gray-400 hover:text-red-500 p-1"><PhTrash class="text-lg" /></button>
            </div>
          </div>

          <!-- Step 3: Configure Workflow -->
          <div v-if="currentStep === 3" class="bg-white rounded-xl border border-gray-100 p-6 shadow-sm">
            <h2 class="text-base font-bold text-gray-900 mb-1">3. {{ t('jobCreate.step3') }}</h2>
            <p class="text-sm text-gray-500 mb-4">{{ t('jobCreate.workflowDesc') }}</p>
            <div v-if="workflowStore.loading" class="text-sm text-gray-500 py-6">{{ t('workflow.loadingNodes') }}</div>
            <div v-else class="space-y-4">
              <div v-for="group in workflowGroups" :key="group.key" class="border border-gray-200 rounded-lg overflow-hidden">
                <div class="px-4 py-2 bg-gray-50 border-b border-gray-100 flex items-center justify-between">
                  <div class="text-sm font-bold text-gray-800">{{ group.label }}</div>
                  <div class="text-xs text-gray-500">{{ t('jobCreate.enabledCount', { enabled: enabledInGroup(group.nodes), total: group.nodes.length }) }}</div>
                </div>
                <div class="divide-y divide-gray-100">
                  <div v-for="node in group.nodes" :key="node.node_key" class="flex items-center justify-between p-3">
                    <div class="min-w-0">
                      <div class="text-sm font-medium text-gray-900 truncate">{{ node.display_name || node.node_key }}</div>
                      <div class="text-xs text-gray-400 font-mono truncate">{{ node.node_key }}</div>
                    </div>
                    <ToggleSwitch
                      :id="`job-node-${node.node_key}`"
                      :model-value="!!form.enabled_nodes[node.node_key]"
                      @update:model-value="(v) => form.enabled_nodes[node.node_key] = v"
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Step 4: Parameters -->
          <div v-if="currentStep === 4" class="bg-white rounded-xl border border-gray-100 p-6 shadow-sm">
            <h2 class="text-base font-bold text-gray-900 mb-1">4. {{ t('jobCreate.step4') }}</h2>
            <p class="text-sm text-gray-500 mb-4">{{ t('jobCreate.parametersDesc') }}</p>

            <!-- Mode toggle -->
            <div class="flex items-center gap-2 mb-5">
              <button @click="configMode = 'form'" :class="configMode === 'form' ? 'bg-primary text-white' : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'" class="px-3 py-1.5 rounded-lg text-sm font-medium">{{ t('jobCreate.formMode') }}</button>
              <button @click="configMode = 'json'" :class="configMode === 'json' ? 'bg-primary text-white' : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'" class="px-3 py-1.5 rounded-lg text-sm font-medium">{{ t('jobCreate.advancedJson') }}</button>
            </div>

            <!-- Form mode -->
            <div v-if="configMode === 'form'" class="space-y-5">
              <div v-if="manualPromptInputs.length" class="border border-blue-200 rounded-lg overflow-hidden">
                <div class="px-4 py-2.5 bg-blue-50 border-b border-blue-100">
                  <div class="text-sm font-bold text-gray-800">Required Manual Inputs</div>
                  <div class="text-xs text-gray-500 mt-0.5">The selected nodes do not generate these prompts in this run.</div>
                </div>
                <div class="p-4 space-y-4">
                  <div v-for="inp in manualPromptInputs" :key="inp.key">
                    <label class="text-xs text-gray-500 block mb-1">{{ inputLabel(inp) }}</label>
                    <textarea
                      v-model="manualInputs[inp.key]"
                      rows="4"
                      class="w-full border border-gray-200 rounded-lg p-2 text-sm outline-none focus:border-primary resize-y bg-white"
                      :placeholder="`Enter ${inputLabel(inp)}`"
                    />
                  </div>
                </div>
              </div>

              <!-- T2V params -->
              <div class="border border-gray-200 rounded-lg overflow-hidden">
                <div class="px-4 py-2.5 bg-gray-50 border-b border-gray-100 text-sm font-bold text-gray-800">{{ t('jobCreate.t2vParameters') }}</div>
                <div class="p-4 grid grid-cols-2 gap-4">
                  <div v-for="f in t2vFields" :key="f.key">
                    <label class="text-xs text-gray-500 block mb-1">{{ f.label }}</label>
                    <select v-if="f.options" v-model="formParams.t2v[f.key]" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none bg-white focus:border-primary">
                      <option v-for="opt in f.options" :key="opt" :value="opt">{{ opt }}</option>
                    </select>
                    <input v-else-if="f.type === 'number'" v-model.number="formParams.t2v[f.key]" type="number" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" :placeholder="String(f.default)" />
                    <label v-else-if="f.type === 'boolean'" class="flex items-center gap-2 mt-1">
                      <input v-model="formParams.t2v[f.key]" type="checkbox" class="rounded" />
                      <span class="text-sm text-gray-700">{{ formParams.t2v[f.key] ? 'Yes' : 'No' }}</span>
                    </label>
                    <input v-else v-model="formParams.t2v[f.key]" type="text" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" :placeholder="String(f.default ?? '')" />
                    <p class="text-xs text-gray-400 mt-0.5">{{ f.hint }}</p>
                  </div>
                </div>
              </div>

              <!-- First Frame Image params -->
              <div class="border border-gray-200 rounded-lg overflow-hidden">
                <div class="px-4 py-2.5 bg-gray-50 border-b border-gray-100 text-sm font-bold text-gray-800">{{ t('jobCreate.firstFrameParameters') }}</div>
                <div class="p-4 grid grid-cols-2 gap-4">
                  <div v-for="f in firstFrameFields" :key="f.key">
                    <label class="text-xs text-gray-500 block mb-1">{{ f.label }}</label>
                    <select v-if="f.options" v-model="formParams.first_frame_image[f.key]" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none bg-white focus:border-primary">
                      <option v-for="opt in f.options" :key="opt" :value="opt">{{ opt }}</option>
                    </select>
                    <input v-else-if="f.type === 'number'" v-model.number="formParams.first_frame_image[f.key]" type="number" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" />
                    <label v-else-if="f.type === 'boolean'" class="flex items-center gap-2 mt-1">
                      <input v-model="formParams.first_frame_image[f.key]" type="checkbox" class="rounded" />
                      <span class="text-sm text-gray-700">{{ formParams.first_frame_image[f.key] ? 'Yes' : 'No' }}</span>
                    </label>
                    <p class="text-xs text-gray-400 mt-0.5">{{ f.hint }}</p>
                  </div>
                </div>
              </div>

              <!-- I2V params -->
              <div class="border border-gray-200 rounded-lg overflow-hidden">
                <div class="px-4 py-2.5 bg-gray-50 border-b border-gray-100 text-sm font-bold text-gray-800">{{ t('jobCreate.i2vParameters') }}</div>
                <div class="p-4 grid grid-cols-2 gap-4">
                  <div v-for="f in i2vFields" :key="f.key">
                    <label class="text-xs text-gray-500 block mb-1">{{ f.label }}</label>
                    <select v-if="f.options" v-model="formParams.i2v[f.key]" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none bg-white focus:border-primary">
                      <option v-for="opt in f.options" :key="opt" :value="opt">{{ opt }}</option>
                    </select>
                    <input v-else-if="f.type === 'number'" v-model.number="formParams.i2v[f.key]" type="number" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" />
                    <label v-else-if="f.type === 'boolean'" class="flex items-center gap-2 mt-1">
                      <input v-model="formParams.i2v[f.key]" type="checkbox" class="rounded" />
                      <span class="text-sm text-gray-700">{{ formParams.i2v[f.key] ? 'Yes' : 'No' }}</span>
                    </label>
                    <p class="text-xs text-gray-400 mt-0.5">{{ f.hint }}</p>
                  </div>
                </div>
              </div>

              <!-- I2I Test params -->
              <div class="border border-amber-200 rounded-lg overflow-hidden">
                <div class="px-4 py-2.5 bg-amber-50 border-b border-amber-100 flex items-center justify-between">
                  <div>
                    <div class="text-sm font-bold text-gray-800">{{ t('jobCreate.i2iTestTitle') }}</div>
                    <div class="text-xs text-gray-500 mt-0.5">{{ t('workflow.i2iTestNote') }}</div>
                  </div>
                  <label class="flex items-center gap-2 text-sm text-gray-700">
                    <input v-model="formParams.i2i_test.enabled" type="checkbox" class="rounded" @change="syncI2ITestNodes" />
                    <span>{{ formParams.i2i_test.enabled ? t('workflow.enabledValue') : t('workflow.disabledValue') }}</span>
                  </label>
                </div>
                <div class="p-4 grid grid-cols-2 gap-4">
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestMode') }}</label>
                    <select v-model="formParams.i2i_test.mode" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none bg-white focus:border-primary">
                      <option value="single_male">{{ t('workflow.i2iTestModeSingleMale') }}</option>
                      <option value="single_female">{{ t('workflow.i2iTestModeSingleFemale') }}</option>
                      <option value="couple">{{ t('workflow.i2iTestModeCouple') }}</option>
                    </select>
                  </div>
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestCount') }}</label>
                    <input v-model.number="formParams.i2i_test.test_count" type="number" min="1" max="10" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" />
                  </div>
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestI2vModel') }}</label>
                    <input v-model="formParams.i2i_test.i2v_model" type="text" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" placeholder="wan2.6-i2v-flash" />
                    <p class="text-xs text-gray-400 mt-0.5">{{ t('workflow.i2iTestModelNote') }}</p>
                  </div>
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestMaleDir') }} <span class="text-gray-300">({{ t('common.optional') }})</span></label>
                    <input v-model="formParams.i2i_test.male_dataset_dir" type="text" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" placeholder="workspace/personas/male" />
                  </div>
                  <div>
                    <label class="text-xs text-gray-500 block mb-1">{{ t('workflow.i2iTestFemaleDir') }} <span class="text-gray-300">({{ t('common.optional') }})</span></label>
                    <input v-model="formParams.i2i_test.female_dataset_dir" type="text" class="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm outline-none focus:border-primary" placeholder="workspace/personas/female" />
                  </div>
                </div>
              </div>
            </div>

            <!-- JSON mode -->
            <div v-else class="space-y-3">
              <div class="flex items-center justify-between">
                <p class="text-xs text-gray-500">{{ t('jobCreate.rawJsonDesc') }}</p>
                <button @click="resetJsonToDefaults" class="text-xs text-primary hover:underline">{{ t('jobCreate.resetDefaults') }}</button>
              </div>
              <textarea v-model="form.jobConfigStr" rows="16" class="w-full border border-gray-200 rounded-lg p-3 text-sm font-mono outline-none focus:border-primary resize-none bg-gray-50"
                @input="onJsonInput" :class="jsonError ? 'border-red-300' : ''"></textarea>
              <p v-if="jsonError" class="text-xs text-red-500">{{ jsonError }}</p>
            </div>

            <div class="mt-4">
              <label class="text-xs text-gray-500 block mb-1">{{ t('jobCreate.noteOptional') }}</label>
              <textarea v-model="form.note" rows="2" class="w-full border border-gray-200 rounded-lg p-3 text-sm outline-none focus:border-primary resize-none bg-gray-50" :placeholder="t('jobCreate.notePlaceholder')"></textarea>
            </div>
          </div>

          <!-- Step 5: Review -->
          <div v-if="currentStep === 5" class="bg-white rounded-xl border border-gray-100 p-6 shadow-sm">
            <h2 class="text-base font-bold text-gray-900 mb-1">5. {{ t('jobCreate.step5') }}</h2>
            <p class="text-sm text-gray-500 mb-4">{{ t('jobCreate.reviewDesc') }}</p>
            <div class="space-y-3 text-sm">
              <div class="flex justify-between"><span class="text-gray-500">{{ t('jobCreate.template') }}</span><span class="font-medium">{{ form.template_id || '--' }}</span></div>
              <div class="flex justify-between"><span class="text-gray-500">{{ t('jobCreate.sourceVideo') }}</span><span class="font-medium">{{ selectedFile?.name || t('jobCreate.none') }}</span></div>
              <div class="flex justify-between"><span class="text-gray-500">{{ t('jobCreate.enabledNodes') }}</span><span class="font-medium">{{ enabledNodeCount }}</span></div>
            </div>
          </div>

          <!-- Navigation -->
          <div class="bg-white rounded-xl border border-gray-100 p-4 shadow-sm flex justify-between items-center">
            <router-link to="/jobs" class="px-5 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50 bg-white">{{ t('common.cancel') }}</router-link>
            <div class="space-x-3 flex">
              <button v-if="currentStep > 1" @click="currentStep--" class="px-5 py-2 border border-gray-200 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50 bg-white">{{ t('common.back') }}</button>
              <button v-if="currentStep < 5" @click="nextStep" :disabled="validatingWorkflow" class="px-5 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 flex items-center disabled:opacity-60">
                {{ validatingWorkflow ? t('common.loading') : t('common.next') }} <PhArrowRight class="ml-1.5" />
              </button>
              <button v-if="currentStep === 5" @click="submitJob" :disabled="submitting" class="px-5 py-2 bg-primary text-white rounded-lg text-sm font-medium hover:bg-blue-700 flex items-center">
                {{ submitting ? t('common.loading') : t('common.finish') }}
              </button>
            </div>
          </div>
        </div>

        <!-- Summary sidebar -->
        <div class="w-[360px] bg-white rounded-xl border border-gray-100 p-6 shadow-sm shrink-0">
          <h3 class="font-bold text-gray-900 text-base mb-5">{{ t('jobCreate.summary') }}</h3>
          <div class="space-y-5">
            <div>
              <div class="text-xs text-gray-500 mb-2">{{ t('jobCreate.template') }}</div>
              <div class="text-sm font-bold text-gray-900">{{ form.template_id || t('jobCreate.notSelected') }}</div>
            </div>
            <div class="border-t border-gray-100 pt-5">
              <div class="text-xs text-gray-500 mb-2">{{ t('jobCreate.sourceVideo') }}</div>
              <div class="text-sm font-bold text-gray-900">{{ selectedFile?.name || t('jobCreate.notUploaded') }}</div>
            </div>
            <div class="border-t border-gray-100 pt-5">
              <div class="text-xs text-gray-500 mb-2">{{ t('jobCreate.workflowMode') }}</div>
              <span class="inline-block bg-green-50 text-green-600 px-2 py-0.5 rounded text-xs font-medium mb-1 border border-green-100">{{ t('jobCreate.nodesEnabled', { count: enabledNodeCount }) }}</span>
            </div>
            <div class="border-t border-gray-100 pt-5">
              <div class="text-xs text-gray-500 mb-2">{{ t('jobCreate.note') }}</div>
              <p class="text-sm text-gray-600">{{ form.note || t('jobCreate.none') }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </DefaultLayout>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import ToggleSwitch from '@/components/common/ToggleSwitch.vue'
import { useTemplateStore } from '@/stores/templates'
import { useJobStore } from '@/stores/jobs'
import { useWorkflowStore } from '@/stores/workflow'
import { useToast } from '@/composables/useToast'
import { setRecentJob } from '@/composables/useRecentJob'
import { BRANCH_LABELS } from '@/utils/constants'
import { PhCloudArrowUp, PhPlayCircle, PhCheckCircle, PhTrash, PhArrowRight } from '@phosphor-icons/vue'

import { useI18n } from 'vue-i18n'

const router = useRouter()
const templateStore = useTemplateStore()
const jobStore = useJobStore()
const workflowStore = useWorkflowStore()
const toast = useToast()
const { t } = useI18n()

const currentStep = ref(1)
const fileInput = ref(null)
const selectedFile = ref(null)
const submitting = ref(false)
const configMode = ref('form')
const jsonError = ref('')
const validatingWorkflow = ref(false)
const validationResult = ref(null)
const manualInputs = reactive({})

const steps = computed(() => [
  t('jobCreate.step1'), t('jobCreate.step2'), t('jobCreate.step3'), t('jobCreate.step4'), t('jobCreate.step5'),
])

const form = reactive({
  template_id: '',
  job_name: '',
  jobConfigStr: '',
  note: '',
  enabled_nodes: {},
})

const DEFAULT_CONFIG = {
  models: {
    video_understanding: 'qwen3.6-plus',
    prompt_rewrite: 'qwen3.5-plus',
    t2v: 'wan2.7-t2v',
    image: 'wan2.6-image',
    main_i2v: 'wan2.7-i2v',
    i2v: 'wan2.7-i2v',
    i2i_test_i2v: 'wan2.6-i2v-flash',
    r2v_flash: 'wan2.6-r2v-flash',
  },
  model_params: {
    t2v: { resolution: '720P', ratio: '9:16', duration: 5, prompt_extend: true, watermark: false, seed: null },
    first_frame_image: { size: '720*1280', n: 1, prompt_extend: true, watermark: false, enable_interleave: false },
    i2v: { resolution: '720P', duration: 5, prompt_extend: true, watermark: false, driving_audio: null },
    i2i_test_i2v: { resolution: '720P', duration: 5, prompt_extend: true, watermark: false, audio: false },
    r2v_flash: { size: '720*1280', duration: 5, audio: false, shot_type: 'single', watermark: false, prompt_extend: true, sample_count: 1 },
  },
  i2i_test: {
    enabled: false,
    mode: 'couple',
    test_count: 3,
    i2v_model: 'wan2.6-i2v-flash',
    male_dataset_dir: 'workspace/personas/male',
    female_dataset_dir: 'workspace/personas/female',
  },
}

form.jobConfigStr = JSON.stringify(DEFAULT_CONFIG, null, 2)

const formParams = reactive({
  t2v: { ...DEFAULT_CONFIG.model_params.t2v },
  first_frame_image: { ...DEFAULT_CONFIG.model_params.first_frame_image },
  i2v: { ...DEFAULT_CONFIG.model_params.i2v },
  r2v_flash: { ...DEFAULT_CONFIG.model_params.r2v_flash },
  i2i_test: { ...DEFAULT_CONFIG.i2i_test },
})

const t2vFields = [
  { key: 'resolution', label: 'Resolution', options: ['480P', '720P', '1080P'], default: '720P', hint: 'Output video resolution' },
  { key: 'ratio', label: 'Ratio', options: ['9:16', '16:9', '1:1', '4:3'], default: '9:16', hint: 'Aspect ratio' },
  { key: 'duration', label: 'Duration (s)', type: 'number', default: 5, hint: 'Video duration in seconds' },
  { key: 'prompt_extend', label: 'Prompt Extend', type: 'boolean', default: true, hint: 'Auto-extend prompt for better quality' },
  { key: 'watermark', label: 'Watermark', type: 'boolean', default: false, hint: 'Add watermark to output' },
]

const firstFrameFields = [
  { key: 'size', label: 'Size', options: ['720*1280', '1280*720', '1024*1024'], default: '720*1280', hint: 'Image dimensions' },
  { key: 'n', label: 'Count', type: 'number', default: 1, hint: 'Number of images to generate' },
  { key: 'prompt_extend', label: 'Prompt Extend', type: 'boolean', default: true, hint: 'Auto-extend prompt' },
  { key: 'watermark', label: 'Watermark', type: 'boolean', default: false, hint: 'Add watermark' },
  { key: 'enable_interleave', label: 'Interleave', type: 'boolean', default: false, hint: 'Enable interleave mode' },
]

const i2vFields = [
  { key: 'resolution', label: 'Resolution', options: ['480P', '720P', '1080P'], default: '720P', hint: 'Output video resolution' },
  { key: 'duration', label: 'Duration (s)', type: 'number', default: 5, hint: 'Video duration in seconds' },
  { key: 'prompt_extend', label: 'Prompt Extend', type: 'boolean', default: true, hint: 'Auto-extend prompt' },
  { key: 'watermark', label: 'Watermark', type: 'boolean', default: false, hint: 'Add watermark' },
]

const I2I_TEST_NODES = [
  'rewrite_t2i_to_i2i',
  'prepare_i2i_test_batch',
  'submit_i2i_test_i2v',
  'poll_i2i_test_i2v',
]

function setI2ITestNodeState(enabled) {
  I2I_TEST_NODES.forEach((nodeKey) => {
    form.enabled_nodes[nodeKey] = enabled
  })
}

function syncI2ITestNodes() {
  setI2ITestNodeState(!!formParams.i2i_test.enabled)
}

function resetJsonToDefaults() {
  form.jobConfigStr = JSON.stringify(DEFAULT_CONFIG, null, 2)
  jsonError.value = ''
}

function onJsonInput() {
  try {
    JSON.parse(form.jobConfigStr)
    jsonError.value = ''
  } catch (e) {
    jsonError.value = `JSON error: ${e.message}`
  }
}

const workflowGroups = computed(() => {
  const groups = {}
  workflowStore.nodes.forEach((node) => {
    const key = node.branch_key || 'core'
    if (!groups[key]) {
      groups[key] = {
        key,
        label: BRANCH_LABELS[key] || key,
        nodes: [],
      }
    }
    groups[key].nodes.push(node)
  })
  return Object.values(groups).map((group) => ({
    ...group,
    nodes: [...group.nodes].sort((a, b) => (a.sequence || 0) - (b.sequence || 0)),
  }))
})

const enabledNodeCount = computed(() => Object.values(form.enabled_nodes).filter(Boolean).length)
const requiredInputs = computed(() => validationResult.value?.required_inputs || [])
const manualPromptInputs = computed(() => requiredInputs.value.filter((inp) => inp.key?.startsWith('prompt:')))

function enabledInGroup(nodes) {
  return nodes.filter((node) => form.enabled_nodes[node.node_key]).length
}

function onFileChange(e) {
  selectedFile.value = e.target.files?.[0] || null
}

function selectedNodeLists() {
  const enabledNodes = []
  const disabledNodes = []
  Object.entries(form.enabled_nodes).forEach(([nodeKey, enabled]) => {
    if (enabled) enabledNodes.push(nodeKey)
    else disabledNodes.push(nodeKey)
  })
  return { enabledNodes, disabledNodes }
}

function inputLabel(inp) {
  const labels = {
    'prompt:first_frame_image': 'T2I / First Frame Image Prompt',
    'prompt:i2v': 'I2V Prompt',
    'prompt:i2i': 'I2I Prompt',
    'prompt:t2v': 'T2V Prompt',
    'prompt:r2v_flash': 'R2V Flash Prompt',
  }
  return labels[inp.key] || inp.label || inp.key
}

function promptTypeFromInputKey(key) {
  return String(key || '').replace(/^prompt:/, '')
}

function buildManualInitialPrompts() {
  const prompts = {}
  manualPromptInputs.value.forEach((inp) => {
    const content = String(manualInputs[inp.key] || '').trim()
    if (!content) return
    prompts[promptTypeFromInputKey(inp.key)] = {
      source: 'manual',
      content,
      prompt_key: 'default',
    }
  })
  return prompts
}

async function validateCurrentWorkflow() {
  validatingWorkflow.value = true
  try {
    const { enabledNodes, disabledNodes } = selectedNodeLists()
    const result = await workflowStore.validateRun({
      template_id: form.template_id,
      enabled_nodes: enabledNodes,
      disabled_nodes: disabledNodes,
      initial_prompts: buildManualInitialPrompts(),
      initial_artifacts: selectedFile.value ? { source_video: { uploaded: true } } : {},
    })
    validationResult.value = result
    ;(result.required_inputs || []).forEach((inp) => {
      if (inp.key?.startsWith('prompt:') && manualInputs[inp.key] === undefined) {
        manualInputs[inp.key] = ''
      }
    })
    if (result.errors?.length) {
      throw new Error(result.errors[0].message || 'Workflow validation failed')
    }
    return result
  } finally {
    validatingWorkflow.value = false
  }
}

async function nextStep() {
  if (currentStep.value === 3 || currentStep.value === 4) {
    try {
      await validateCurrentWorkflow()
      if (currentStep.value === 4) {
        const missingPrompt = manualPromptInputs.value.find((inp) => !String(manualInputs[inp.key] || '').trim())
        if (missingPrompt) {
          toast.error(`Missing required input: ${inputLabel(missingPrompt)}`)
          return
        }
      }
    } catch (e) {
      toast.error(e.message || 'Workflow validation failed')
      return
    }
  }
  currentStep.value += 1
}

async function submitJob() {
  submitting.value = true
  try {
    await validateCurrentWorkflow()
    const missingPrompt = manualPromptInputs.value.find((inp) => !String(manualInputs[inp.key] || '').trim())
    if (missingPrompt) {
      toast.error(`Missing required input: ${inputLabel(missingPrompt)}`)
      return
    }
    let config = { ...DEFAULT_CONFIG }
    if (configMode.value === 'json') {
      try { config = JSON.parse(form.jobConfigStr) } catch {}
    } else {
      // Merge form params into config
      const i2iTest = { ...formParams.i2i_test }
      config = {
        ...DEFAULT_CONFIG,
        models: {
          ...DEFAULT_CONFIG.models,
          main_i2v: DEFAULT_CONFIG.models.main_i2v,
          i2v: DEFAULT_CONFIG.models.main_i2v,
          i2i_test_i2v: i2iTest.i2v_model || DEFAULT_CONFIG.models.i2i_test_i2v,
        },
        model_params: {
          ...DEFAULT_CONFIG.model_params,
          t2v: { ...formParams.t2v },
          first_frame_image: { ...formParams.first_frame_image },
          i2v: { ...formParams.i2v },
          i2i_test_i2v: { ...DEFAULT_CONFIG.model_params.i2i_test_i2v },
        },
        i2i_test: i2iTest,
      }
    }
    if (config?.i2i_test?.enabled) setI2ITestNodeState(true)

    const { enabledNodes, disabledNodes } = selectedNodeLists()

    const fd = new FormData()
    fd.append('template_id', form.template_id)
    if (form.job_name.trim()) fd.append('job_name', form.job_name.trim())
    if (selectedFile.value) fd.append('source_video', selectedFile.value)
    fd.append('enabled_nodes', JSON.stringify(enabledNodes))
    fd.append('disabled_nodes', JSON.stringify(disabledNodes))
    fd.append('job_config', JSON.stringify(config))
    fd.append('initial_prompts', JSON.stringify(buildManualInitialPrompts()))

    const result = await jobStore.createJob(fd)
    toast.success(t('jobCreate.created'))
    const jobId = result.job_id
    if (jobId) {
      setRecentJob(jobId)
      await jobStore.runFull(jobId)
      router.push(`/jobs/${jobId}`)
    } else {
      router.push('/jobs')
    }
  } catch (e) {
    toast.error(e.response?.data?.error?.message || t('common.error'))
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await Promise.all([templateStore.fetchTemplates(), workflowStore.fetchNodes()])
  workflowStore.nodes.forEach((node) => {
    form.enabled_nodes[node.node_key] = !!node.enabled
  })
  formParams.i2i_test.enabled = I2I_TEST_NODES.some((nodeKey) => !!form.enabled_nodes[nodeKey])
})
</script>
