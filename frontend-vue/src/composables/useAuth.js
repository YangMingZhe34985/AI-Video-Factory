import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth'

export function useAuth() {
  const authStore = useAuthStore()
  return {
    isAuthenticated: computed(() => authStore.isAuthenticated),
    user: computed(() => authStore.user),
    username: computed(() => authStore.username),
    login: authStore.login,
    register: authStore.register,
    logout: authStore.logout,
    fetchUser: authStore.fetchUser,
  }
}