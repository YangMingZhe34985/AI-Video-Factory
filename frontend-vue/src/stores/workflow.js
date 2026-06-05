import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as workflowApi from '@/api/workflow'

export const WORKFLOW_PATHS = [
  {
    key: 'core',
    labelZh: '核心提示词路径',
    labelEn: 'Core Prompt Path',
    nodes: ['reverse_prompts', 'rewrite_prompts'],
    color: '#6366f1',
  },
  {
    key: 'first_i2v',
    labelZh: '首帧图 + I2V',
    labelEn: 'First Frame + I2V',
    nodes: ['submit_first_frame_image', 'poll_first_frame_image', 'submit_i2v', 'poll_i2v'],
    color: '#0ea5e9',
  },
  {
    key: 'i2i_test',
    labelZh: 'I2I Test 路径',
    labelEn: 'I2I Test',
    nodes: ['rewrite_t2i_to_i2i', 'prepare_i2i_test_batch', 'submit_i2i_test_image', 'poll_i2i_test_image', 'submit_i2i_test_i2v', 'poll_i2i_test_i2v'],
    color: '#f59e0b',
  },
  {
    key: 't2v',
    labelZh: 'T2V 可选分支',
    labelEn: 'T2V',
    nodes: ['submit_t2v', 'poll_t2v'],
    color: '#10b981',
  },
  {
    key: 'r2v_flash',
    labelZh: 'R2V 可选分支',
    labelEn: 'R2V',
    nodes: ['reverse_prompts4r2v', 'submit_r2v_flash', 'poll_r2v_flash'],
    color: '#8b5cf6',
  },
]

export const useWorkflowStore = defineStore('workflow', () => {
  const nodes = ref([])
  const loading = ref(false)

  const enabledNodes = computed(() => nodes.value.filter((n) => n.enabled))
  const disabledNodes = computed(() => nodes.value.filter((n) => !n.enabled))
  const nodesByBranch = computed(() => {
    const groups = {}
    nodes.value.forEach((n) => {
      const branch = n.branch_key || 'core'
      if (!groups[branch]) groups[branch] = []
      groups[branch].push(n)
    })
    return groups
  })

  async function fetchNodes() {
    loading.value = true
    try {
      const data = await workflowApi.getNodes()
      nodes.value = Array.isArray(data) ? data : (data.nodes || [])
    } catch {
      nodes.value = []
    } finally {
      loading.value = false
    }
  }

  async function enableNode(nodeKey) {
    await workflowApi.enableNode(nodeKey)
    const n = nodes.value.find((n2) => n2.node_key === nodeKey)
    if (n) n.enabled = true
  }

  async function disableNode(nodeKey) {
    await workflowApi.disableNode(nodeKey)
    const n = nodes.value.find((n2) => n2.node_key === nodeKey)
    if (n) n.enabled = false
  }

  async function updateNodeConfig(nodeKey, config) {
    const updated = await workflowApi.updateNodeConfig(nodeKey, config)
    const index = nodes.value.findIndex((n) => n.node_key === nodeKey)
    if (index >= 0) nodes.value[index] = updated
    return updated
  }

  async function validateRun(payload) {
    return workflowApi.validateRun(payload)
  }

  async function enablePath(nodeKeys) {
    for (const key of nodeKeys) {
      await workflowApi.enableNode(key)
      const n = nodes.value.find((n2) => n2.node_key === key)
      if (n) n.enabled = true
    }
  }

  async function disablePath(nodeKeys) {
    for (const key of nodeKeys) {
      await workflowApi.disableNode(key)
      const n = nodes.value.find((n2) => n2.node_key === key)
      if (n) n.enabled = false
    }
  }

  return {
    nodes,
    loading,
    enabledNodes,
    disabledNodes,
    nodesByBranch,
    fetchNodes,
    enableNode,
    disableNode,
    updateNodeConfig,
    validateRun,
    enablePath,
    disablePath,
  }
})
