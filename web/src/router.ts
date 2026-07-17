import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('./views/HomeView.vue'),
  },
  {
    path: '/live',
    name: 'live',
    component: () => import('./views/LiveView.vue'),
    meta: { crumb: 'nav.live' },
  },
  { path: '/tasks', redirect: '/meetings' },
  {
    path: '/meetings', name: 'meetings', component: () => import('./views/MeetingsView.vue'),
  },
  {
    path: '/meetings/:id', name: 'meeting-detail', component: () => import('./views/MeetingDetailView.vue'),
  },
  {
    path: '/people', name: 'people', component: () => import('./views/PeopleView.vue'),
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
    path: '/:pathMatch(.*)*', redirect: '/',
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})

// 本机默认可直接使用；远程访问由 API 的 401 响应统一引导到登录页。
