import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'

const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

request.interceptors.request.use((config) => {
  const authStore = useAuthStore()
  if (authStore.accessToken) {
    config.headers.Authorization = `Bearer ${authStore.accessToken}`
  }
  return config
})

let isRefreshing = false
let failedQueue = []

function processQueue(error, token = null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) {
      reject(error)
    } else {
      resolve(token)
    }
  })
  failedQueue = []
}

request.interceptors.response.use(
  (response) => response.data.data || response.data,
  async (error) => {
    const originalRequest = error.config
    const authStore = useAuthStore()
    const toastStore = useToastStore()

    if (error.response?.status === 401 && !originalRequest._retry && authStore.refreshToken) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        })
          .then(() => {
            originalRequest.headers.Authorization = `Bearer ${authStore.accessToken}`
            return request(originalRequest)
          })
          .catch((err) => Promise.reject(err))
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const res = await axios.post('/api/auth/refresh', {}, {
          headers: { Authorization: `Bearer ${authStore.refreshToken}` },
        })
        const newToken = res.data.data?.access_token
        if (newToken) {
          authStore.accessToken = newToken
          processQueue(null, newToken)
          originalRequest.headers.Authorization = `Bearer ${newToken}`
          return request(originalRequest)
        }
      } catch {
        processQueue(new Error('refresh_failed'))
        authStore.logout()
        window.location.href = '/login'
        return Promise.reject(new Error('Session expired. Please login again.'))
      } finally {
        isRefreshing = false
      }
    }

    const message = error.response?.data?.error?.message || error.message || 'Request failed'
    if (error.response?.status !== 401) {
      toastStore.show(message, 'error')
    }
    return Promise.reject(error)
  },
)

export default request