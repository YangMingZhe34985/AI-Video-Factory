import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { guest: true },
  },
  {
    path: '/',
    redirect: '/dashboard',
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('@/views/DashboardView.vue'),
  },
  {
    path: '/templates',
    name: 'Templates',
    component: () => import('@/views/TemplatesView.vue'),
  },
  {
    path: '/prompts',
    name: 'PromptManager',
    component: () => import('@/views/PromptManagerView.vue'),
  },
  {
    path: '/models',
    name: 'ModelRegistry',
    component: () => import('@/views/ModelRegistryView.vue'),
  },
  {
    path: '/jobs',
    name: 'Jobs',
    component: () => import('@/views/JobsView.vue'),
  },
  {
    path: '/jobs/create',
    name: 'JobCreate',
    redirect: '/jobs',
  },
  {
    path: '/jobs/:jobId',
    name: 'JobDetail',
    component: () => import('@/views/JobDetailView.vue'),
  },
  {
    path: '/workflow',
    name: 'WorkflowNodes',
    component: () => import('@/views/WorkflowNodesView.vue'),
  },
  {
    path: '/artifacts',
    name: 'Artifacts',
    component: () => import('@/views/ArtifactsView.vue'),
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/SettingsView.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFoundView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  const authStore = useAuthStore()
  if (to.meta.guest && authStore.isAuthenticated) {
    return next('/dashboard')
  }
  if (!to.meta.guest && !authStore.isAuthenticated) {
    return next('/login')
  }
  next()
})

export default router
