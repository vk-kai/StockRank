import { createRouter, createWebHistory } from 'vue-router'

const App = () => import('./App.vue')
const NewsPage = () => import('./NewsPage.vue')
const ConfigPage = () => import('./ConfigPage.vue')
const LogPage = () => import('./LogPage.vue')
const DailyReport = () => import('./DailyReport.vue')
const HouseKline = () => import('./HouseKline.vue')
const GlobalMarket = () => import('./GlobalMarket.vue')
const MarketMap = () => import('./MarketMap.vue')
const FlowAlert = () => import('./FlowAlert.vue')

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
    path: '/daily-report',
    name: 'DailyReport',
    component: DailyReport
  },
  {
    path: '/house-kline',
    name: 'HouseKline',
    component: HouseKline
  },
  {
    path: '/global-market',
    name: 'GlobalMarket',
    component: GlobalMarket
  },
  {
    path: '/market-map',
    name: 'MarketMap',
    component: MarketMap
  },
  {
    path: '/flow-alert',
    name: 'FlowAlert',
    component: FlowAlert
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
