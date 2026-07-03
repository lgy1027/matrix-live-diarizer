import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from './stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/live',
  },
  {
    path: '/live',
    name: 'live',
    component: () => import('./views/LiveView.vue'),
    meta: { crumb: 'nav.live' },
  },
  {
    path: '/library',
    name: 'library',
    component: () => import('./views/LibraryView.vue'),
    meta: { crumb: 'nav.library' },
  },
  {
    path: '/voice',
    name: 'voice',
    component: () => import('./views/VoiceView.vue'),
    meta: { crumb: 'nav.voice' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('./views/SettingsView.vue'),
    meta: { crumb: 'nav.settings' },
  },
  {
    path: '/login',
    name: 'login',
    // 静态 login.html, 不进 SPA 路由, 但需要 history catch-all 时回退
    component: () => import('./views/LoginView.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/live',
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

// 鉴权守卫: 无 token 跳 /login
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name !== 'login' && !auth.isLoggedIn) {
    return { name: 'login', query: { next: to.fullPath } }
  }
})
