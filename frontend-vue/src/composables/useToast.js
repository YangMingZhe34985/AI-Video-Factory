import { useToastStore } from '@/stores/toast'

export function useToast() {
  const toastStore = useToastStore()
  return {
    success: (msg) => toastStore.show(msg, 'success'),
    error: (msg) => toastStore.show(msg, 'error'),
    warning: (msg) => toastStore.show(msg, 'warning'),
    info: (msg) => toastStore.show(msg, 'info'),
  }
}