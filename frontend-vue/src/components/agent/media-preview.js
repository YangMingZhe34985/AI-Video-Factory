// A source change or unmount invalidates pending bytes before an object URL exists.
export function createPreviewLoader(loadBlob, update, urls = URL) {
  let generation = 0, disposed = false, loading = false, url = '', controller = null
  function clear(notify) {
    generation++
    controller?.abort()
    controller = null
    loading = false
    if (url) urls.revokeObjectURL(url)
    url = ''
    if (notify) update({ url: '', loading: false, failed: false })
  }
  return {
    async load(src) {
      if (disposed || loading) return
      const token = ++generation
      controller = new AbortController()
      loading = true
      update({ loading: true, failed: false })
      try {
        const blob = await loadBlob(src, controller.signal)
        if (disposed || token !== generation) return
        if (url) urls.revokeObjectURL(url)
        url = urls.createObjectURL(blob)
        update({ url })
      } catch {
        if (!disposed && token === generation) update({ failed: true })
      } finally {
        if (!disposed && token === generation) {
          controller = null
          loading = false
          update({ loading: false })
        }
      }
    },
    reset() { if (!disposed) clear(true) },
    dispose() { disposed = true; clear(false) },
  }
}
