import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: 'PyrePress' },
  },
  {
    path: '/post/:slug',
    name: 'post',
    component: () => import('@/views/PostView.vue'),
    props: true,
  },
  {
    path: '/compose',
    name: 'compose',
    component: () => import('@/views/ComposeView.vue'),
    meta: { title: 'Compose · PyrePress', requiresAuthor: true },
  },
  {
    path: '/edit/:slug',
    name: 'edit',
    component: () => import('@/views/ComposeView.vue'),
    props: true,
    meta: { title: 'Edit · PyrePress', requiresAuthor: true },
  },
  {
    path: '/moderate',
    name: 'moderate',
    component: () => import('@/views/ModerateView.vue'),
    meta: { title: 'Moderate · PyrePress', requiresAuthor: true },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: 'Sign in · PyrePress' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior(_to, _from, saved) {
    return saved ?? { top: 0 }
  },
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuthor && !auth.isAuthor) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  return true
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || 'PyrePress'
  document.title = title
})

export default router
