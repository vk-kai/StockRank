import { createApp } from 'vue'
import Root from './Root.vue'
import router from './router'
import IconRefresh from './components/icons/IconRefresh.vue'
import IconTreemap from './components/icons/IconTreemap.vue'
import { startNotificationManager } from './services/notificationManager'

const app = createApp(Root)
app.use(router)
// 全局图标组件：任意模板可直接 <IconRefresh/> / <IconTreemap/> 使用，无需逐页注册
app.component('IconRefresh', IconRefresh)
app.component('IconTreemap', IconTreemap)
app.mount('#app')

// 启动全局桌面通知管理器：常驻整个会话，与当前路由解耦，
// 只要在站内且已登录，新闻/异动到达即通知（不再只在首页/新闻页才提醒）
startNotificationManager()
