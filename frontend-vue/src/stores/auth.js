import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as authApi from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const accessToken = ref(null)
  const refreshToken = ref(null)

  const isAuthenticated = computed(() => !!accessToken.value)
  const username = computed(() => user.value?.username || 'User')

  function setTokens(access, refresh) {
    if (access) accessToken.value = access
    if (refresh) refreshToken.value = refresh
  }

  function clearAuth() {
    user.value = null
    accessToken.value = null
    refreshToken.value = null
  }

  async function login(username, password) {
    const data = await authApi.login(username, password)
    setTokens(data.access_token, data.refresh_token)
    user.value = data.user || null
    return data
  }

  async function register(username, email, password) {
    const data = await authApi.register(username, email, password)
    setTokens(data.access_token, data.refresh_token)
    user.value = data.user || null
    return data
  }

  async function fetchUser() {
    try {
      const data = await authApi.me()
      user.value = data
    } catch {
      user.value = null
    }
  }

  function logout() {
    clearAuth()
    window.location.href = '/login'
  }

  return {
    user,
    accessToken,
    refreshToken,
    isAuthenticated,
    username,
    setTokens,
    clearAuth,
    login,
    register,
    fetchUser,
    logout,
  }
}, {
  persist: {
    key: 'auth',
    storage: localStorage,
    pick: ['user', 'accessToken', 'refreshToken'],
  },
})