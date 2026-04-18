import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import NewsPage from './NewsPage.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: App
  },
  {
    path: '/news',
    name: 'News',
    component: NewsPage
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
