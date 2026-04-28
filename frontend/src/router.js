import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import NewsPage from './NewsPage.vue'
import ConfigPage from './ConfigPage.vue'
import LogPage from './LogPage.vue'
import SecurityLogPage from './SecurityLogPage.vue'
import DailyReport from './DailyReport.vue'
import HouseKline from './HouseKline.vue'

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
  },
  {
    path: '/security-logs',
    name: 'SecurityLogs',
    component: SecurityLogPage
  },
  {
    path: '/daily-report',
    name: 'DailyReport',
    component: DailyReport
  },
  {
    path: '/house-kline',
    name: 'HouseKline',
    component: HouseKline
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
