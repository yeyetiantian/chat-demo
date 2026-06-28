import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/',
      redirect: '/chat',
    },
    {
      path: '/chat',
      name: 'Chat',
      component: () => import('../pages/ChatPage.vue'),
    },
    {
      path: '/pivot',
      name: 'Pivot',
      component: () => import('../pages/PivotPage.vue'),
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('../pages/DashboardPage.vue'),
    },
    {
      path: '/trace',
      name: 'Trace',
      component: () => import('../pages/TracePage.vue'),
    },
  ],
})

export default router
