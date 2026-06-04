import { ref, onUnmounted } from 'vue'

export function useSSE(jobId) {
  const events = ref([])
  const connected = ref(false)
  let eventSource = null

  function connect() {
    const token = localStorage.getItem('access_token')
    const url = `/api/jobs/${jobId}/stream`
    eventSource = new EventSource(url)
    connected.value = true

    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'stream_closed') {
          close()
          return
        }
        events.value.push(data)
      } catch {
        // ignore parse errors
      }
    }

    eventSource.onerror = () => {
      close()
    }
  }

  function close() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
    connected.value = false
  }

  onUnmounted(() => close())

  return { events, connected, connect, close }
}