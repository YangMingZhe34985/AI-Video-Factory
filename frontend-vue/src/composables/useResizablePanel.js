import { ref, onMounted, onBeforeUnmount } from 'vue'

/**
 * Composable for a drag-to-resize panel edge.
 * @param {string} storageKey - localStorage key for persistence
 * @param {object} opts - { defaultWidth, minWidth, maxWidth, side: 'left'|'right' }
 */
export function useResizablePanel(storageKey, opts = {}) {
  const {
    defaultWidth = 260,
    minWidth = 180,
    maxWidth = 480,
    side = 'right', // which edge of the panel is draggable
  } = opts

  const savedWidth = Number(localStorage.getItem(storageKey)) || defaultWidth
  const width = ref(Math.min(Math.max(savedWidth, minWidth), maxWidth))

  let dragging = false
  let startX = 0
  let startWidth = 0

  function onMouseMove(e) {
    if (!dragging) return
    const dx = side === 'right' ? e.clientX - startX : startX - e.clientX
    const next = Math.min(Math.max(startWidth + dx, minWidth), maxWidth)
    width.value = next
  }

  function onMouseUp() {
    if (!dragging) return
    dragging = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    localStorage.setItem(storageKey, String(width.value))
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
  }

  function startDrag(e) {
    dragging = true
    startX = e.clientX
    startWidth = width.value
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)
  }

  onBeforeUnmount(() => {
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
  })

  return { width, startDrag }
}

/**
 * Composable for a togglable + resizable panel.
 * Combines width + visibility, both persisted to localStorage.
 */
export function useToggleResizablePanel(storageKey, opts = {}) {
  const { width, startDrag } = useResizablePanel(`${storageKey}:width`, opts)

  const visibleKey = `${storageKey}:visible`
  const isVisible = ref(localStorage.getItem(visibleKey) !== 'false')

  function toggle() {
    isVisible.value = !isVisible.value
    localStorage.setItem(visibleKey, String(isVisible.value))
  }

  function show() {
    if (!isVisible.value) {
      isVisible.value = true
      localStorage.setItem(visibleKey, 'true')
    }
  }

  return { width, startDrag, isVisible, toggle, show }
}
