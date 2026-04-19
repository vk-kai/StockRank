import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import NewsPage from './NewsPage.vue'
import ConfigPage from './ConfigPage.vue'
import LogPage from './LogPage.vue'

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
  },
  {
    path: '/config',
    name: 'Config',
    component: ConfigPage
  },
  {
    path: '/logs',
    name: 'Logs',
    component: LogPage
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
