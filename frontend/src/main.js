import { createApp } from 'vue'
import Root from './Root.vue'
import router from './router'
import IconRefresh from './components/icons/IconRefresh.vue'
import IconTreemap from './components/icons/IconTreemap.vue'

const app = createApp(Root)
app.use(router)
// 全局图标组件：任意模板可直接 <IconRefresh/> / <IconTreemap/> 使用，无需逐页注册
app.component('IconRefresh', IconRefresh)
app.component('IconTreemap', IconTreemap)
app.mount('#app')
