import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as workflowApi from '@/api/workflow'

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
  }
})
