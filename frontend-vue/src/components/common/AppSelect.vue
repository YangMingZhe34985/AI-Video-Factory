<template>
  <div class="relative" ref="rootRef">
    <button
      type="button"
      class="w-full flex items-center justify-between gap-2 px-3 py-2 text-sm rounded-lg border bg-white transition-colors outline-none"
      :class="[
        isOpen
          ? 'border-primary ring-2 ring-primary/20'
          : 'border-gray-200 hover:border-gray-300',
        disabled ? 'opacity-50 cursor-not-allowed bg-gray-50' : 'cursor-pointer',
        error ? 'border-red-400 ring-2 ring-red-200' : '',
      ]"
      :disabled="disabled"
      @click="toggle"
    >
      <span class="truncate" :class="selectedLabel ? 'text-gray-800' : 'text-gray-400'">
        {{ selectedLabel || placeholder || t('appSelect.selectPlaceholder') }}
      </span>
      <span class="flex items-center gap-1 shrink-0">
        <button
          v-if="clearable && modelValue && modelValue !== ''"
          type="button"
          class="text-gray-300 hover:text-gray-500 p-0.5 rounded"
          @click.stop="clearValue"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <path d="M9 3L3 9M3 3l6 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </button>
        <svg
          width="14" height="14" viewBox="0 0 14 14" fill="none"
          class="transition-transform duration-150"
          :class="isOpen ? 'rotate-180' : ''"
        >
          <path d="M3.5 5.25L7 8.75L10.5 5.25" stroke="#9ca3af" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </span>
    </button>

    <!-- Dropdown -->
    <Teleport to="body">
      <div
        v-if="isOpen"
        ref="dropdownRef"
        class="fixed z-[9999] bg-white border border-gray-200 rounded-xl shadow-xl overflow-hidden"
        :style="dropdownStyle"
      >
        <!-- Search -->
        <div v-if="searchable" class="p-2 border-b border-gray-100">
          <input
            ref="searchInput"
            v-model="searchQuery"
            type="text"
            class="w-full text-sm px-2 py-1.5 rounded-lg border border-gray-200 outline-none focus:border-primary bg-gray-50"
            :placeholder="t('appSelect.searchPlaceholder')"
          />
        </div>

        <ul class="overflow-y-auto max-h-[240px] py-1">
          <!-- Empty placeholder option -->
          <li
            v-if="!required && placeholder !== false"
            class="px-3 py-2 text-sm cursor-pointer transition-colors"
            :class="(!modelValue || modelValue === '') ? 'bg-primary/8 text-primary font-medium' : 'text-gray-400 hover:bg-gray-50'"
            @click="selectOption('')"
          >
            {{ placeholder || t('appSelect.allOption') }}
          </li>

          <!-- Options -->
          <template v-if="filteredOptions.length">
            <li
              v-for="opt in filteredOptions"
              :key="opt.value"
              class="px-3 py-2 text-sm cursor-pointer flex items-center justify-between transition-colors"
              :class="opt.value === modelValue
                ? 'bg-primary/8 text-primary font-medium'
                : 'text-gray-700 hover:bg-gray-50'"
              @click="selectOption(opt.value)"
            >
              <span class="truncate">{{ opt.label }}</span>
              <svg v-if="opt.value === modelValue" width="14" height="14" viewBox="0 0 14 14" fill="none" class="shrink-0 ml-2">
                <path d="M2.5 7L5.5 10L11.5 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </li>
          </template>
          <li v-else class="px-3 py-4 text-sm text-gray-400 text-center">
            {{ t('appSelect.noOptions') }}
          </li>
        </ul>
      </div>
    </Teleport>

    <p v-if="error" class="mt-1 text-xs text-red-500">{{ error }}</p>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] }, // [{ label, value }] or strings
  placeholder: { type: [String, Boolean], default: null },
  disabled: { type: Boolean, default: false },
  clearable: { type: Boolean, default: false },
  searchable: { type: Boolean, default: false },
  required: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'change'])

const rootRef = ref(null)
const dropdownRef = ref(null)
const searchInput = ref(null)
const isOpen = ref(false)
const searchQuery = ref('')
const dropdownStyle = ref({})

const normalizedOptions = computed(() =>
  props.options.map((opt) =>
    typeof opt === 'string' || typeof opt === 'number'
      ? { label: String(opt), value: opt }
      : opt
  )
)

const filteredOptions = computed(() => {
  if (!props.searchable || !searchQuery.value) return normalizedOptions.value
  const q = searchQuery.value.toLowerCase()
  return normalizedOptions.value.filter((o) => o.label.toLowerCase().includes(q))
})

const selectedLabel = computed(() => {
  if (props.modelValue === '' || props.modelValue === null || props.modelValue === undefined) return ''
  const found = normalizedOptions.value.find((o) => String(o.value) === String(props.modelValue))
  return found?.label ?? String(props.modelValue)
})

function computeDropdownStyle() {
  const el = rootRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const winH = window.innerHeight
  const dropH = 280
  const below = rect.bottom + dropH < winH
  dropdownStyle.value = {
    left: `${rect.left}px`,
    top: below ? `${rect.bottom + 4}px` : `${rect.top - dropH - 4}px`,
    width: `${Math.max(rect.width, 180)}px`,
    minWidth: '180px',
  }
}

function toggle() {
  if (props.disabled) return
  if (isOpen.value) {
    isOpen.value = false
  } else {
    computeDropdownStyle()
    isOpen.value = true
    searchQuery.value = ''
    if (props.searchable) {
      nextTick(() => searchInput.value?.focus())
    }
  }
}

function selectOption(value) {
  emit('update:modelValue', value)
  emit('change', value)
  isOpen.value = false
}

function clearValue() {
  emit('update:modelValue', '')
  emit('change', '')
}

function onClickOutside(e) {
  if (
    !rootRef.value?.contains(e.target) &&
    !dropdownRef.value?.contains(e.target)
  ) {
    isOpen.value = false
  }
}

onMounted(() => document.addEventListener('mousedown', onClickOutside))
onBeforeUnmount(() => document.removeEventListener('mousedown', onClickOutside))
</script>
