<template>
  <div class="global-market-page">
    <header class="gm-header">
      <button @click="goBack" class="gm-back-button">← 返回</button>
      <h1>🌍 全球股市指数实时地图</h1>
      <div class="gm-header-right">
        <span class="gm-source-tag" v-if="data && data.source">
          数据源：{{ data.source === 'eastmoney' ? '东方财富' : '新浪财经' }}
        </span>
        <span class="gm-update" v-if="data && data.update_time">更新：{{ data.update_time }}</span>
        <button @click="fetchData(true)" class="gm-refresh-btn" :disabled="loading">
          <IconRefresh v-if="!loading" />
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </div>
    </header>

    <!-- 全球市场环境观察:美元/原油/美债 → 外部环境对A股的参考信号(前端JSONP直连东财) -->
    <div class="gm-env-strip" v-if="envItems.length" :class="envOverallClass">
      <div class="gm-env-head">
        <span class="gm-env-title">全球市场环境</span>
        <span class="gm-env-verdict">{{ envOverallText }}</span>
      </div>
      <div class="gm-env-items">
        <div class="gm-env-item" v-for="e in envItems" :key="e.key" :title="e.hint">
          <span class="gm-env-name">{{ e.name }}</span>
          <span class="gm-env-price">{{ e.price }}</span>
          <span class="gm-env-chg" :class="e.chg >= 0 ? 'up' : 'down'">
            {{ e.chg >= 0 ? '+' : '' }}{{ e.chg.toFixed(2) }}%
          </span>
          <span class="gm-env-note">{{ e.note }}</span>
        </div>
      </div>
      <div class="gm-env-desc">{{ envDescText }}</div>
    </div>

    <div class="gm-body">
      <div class="gm-chart-wrapper">
        <div class="gm-region-filter">
          <button
            v-for="r in regionFilters"
            :key="r.key"
            class="gm-region-btn"
            :class="{ active: regionFilter === r.key }"
            @click="setRegionFilter(r.key)"
          >{{ r.label }}</button>
        </div>
        <div ref="chartEl" class="gm-chart"></div>
        <div class="gm-legend">
          <span class="legend-item"><i class="dot up"></i>上涨</span>
          <span class="legend-item"><i class="dot down"></i>下跌</span>
          <span class="legend-tip">气泡大小=涨跌幅 · 颜色深浅=幅度 · 滚轮缩放 · 拖动平移</span>
        </div>
      </div>

      <div class="gm-intraday-section">
        <div class="gi-section-head">
          <h3>📊 全球主要指数</h3>
          <span class="gi-update" v-if="intradayUpdatedAt">分时更新：{{ intradayUpdatedAt }}</span>
          <span class="gi-loading" v-if="intradayLoading">分时加载中…</span>
          <div class="gm-matrix-controls">
            <button
              v-for="c in matrixFilters"
              :key="c.key"
              class="gm-region-btn"
              :class="{ active: matrixFilter === c.key }"
              @click="matrixFilter = c.key"
            >{{ c.label }}</button>
          </div>
        </div>
        <div class="gm-intraday" v-if="matrixCards.length">
          <div class="gi-card" v-for="ix in matrixCards" :key="ix.code" :class="ix.change >= 0 ? 'up' : 'down'">
            <div class="gi-head">
              <span class="gi-name">{{ ix.name }}</span>
              <span class="gi-chg" :class="ix.change >= 0 ? 'up' : 'down'">{{ formatChange(ix.change) }}</span>
            </div>
            <svg v-if="ix.series && ix.series.length >= 2" class="gi-spark" viewBox="0 0 100 36" preserveAspectRatio="none">
              <path v-if="sparkArea(ix)" :d="sparkArea(ix)" :fill="ix.change >= 0 ? 'rgba(240,82,95,0.16)' : 'rgba(16,185,129,0.16)'" stroke="none" />
              <path :d="sparkPath(ix)" :stroke="ix.change >= 0 ? '#F0525F' : '#10B981'" stroke-width="1.5" fill="none" vector-effect="non-scaling-stroke" />
            </svg>
            <div v-else class="gi-noline">暂无分时</div>
            <div class="gi-foot">
              <span class="gi-region">{{ ix.region }}</span>
              <span class="gi-price">{{ formatPrice(ix.price) }}</span>
            </div>
          </div>
        </div>
        <div class="gi-empty" v-else-if="!intradayLoading">暂无数据</div>
      </div>
    </div>

    <div class="gm-footer">数据来源：东方财富 / 新浪财经（双源容错）· 仅供投资参考，不构成建议</div>
    <SecurityAlert />
  </div>
</template>

<script>
import * as echarts from 'echarts'
// echarts 实例须 markRaw,避免 Vue3 深度代理破坏 echarts 内部 === 身份判断
import { markRaw } from 'vue'
import SecurityAlert from './components/SecurityAlert.vue'
import { getGlobalIndices } from './services/apiService'

// 全球指数配置：展示名 / 东财 secid / 经纬度 / 区域。
// 快照与分时都在前端直连东财（CORS 已开放），服务器不再碰东财，规避反爬封禁。
const GLOBAL_INDICES = [
  { name: '上证指数',     secid: '1.000001',  lat: 31.23,  lng: 121.47, region: '中国' },
  { name: '沪深300',      secid: '1.000300',  lat: 39.90,  lng: 116.40, region: '中国' },
  { name: '恒生指数',     secid: '100.HSI',   lat: 22.32,  lng: 114.17, region: '香港' },
  { name: '台湾加权',     secid: '100.TWII',  lat: 25.03,  lng: 121.57, region: '台湾' },
  { name: '日经225',      secid: '100.N225',  lat: 35.68,  lng: 139.69, region: '日本' },
  { name: '韩国KOSPI',    secid: '100.KS11',  lat: 37.57,  lng: 126.98, region: '韩国' },
  { name: '富时马来西亚', secid: '100.KLSE',  lat: 3.14,   lng: 101.69, region: '马来西亚' },
  { name: '印尼综合',     secid: '100.JKSE',  lat: -6.21,  lng: 106.85, region: '印尼' },
  { name: '越南胡志明',   secid: '100.VNINDEX', lat: 10.78, lng: 106.70, region: '越南' },
  { name: '印度SENSEX',  secid: '100.SENSEX', lat: 19.08,  lng: 72.88, region: '印度' },
  { name: '澳大利亚ASX200', secid: '100.AS51', lat: -33.87, lng: 151.21, region: '澳大利亚' },
  { name: '道琼斯',       secid: '100.DJIA',  lat: 38.90,  lng: -77.04, region: '美国' },
  { name: '纳斯达克',     secid: '100.NDX',   lat: 40.71,  lng: -74.01, region: '美国' },
  { name: '标普500',      secid: '100.SPX',   lat: 41.80,  lng: -87.65, region: '美国' },
  { name: '巴西BOVESPA', secid: '100.BVSP',  lat: -23.55, lng: -46.63, region: '巴西' },
  { name: '英国富时100', secid: '100.FTSE',  lat: 51.51,  lng: -0.13,  region: '英国' },
  { name: '德国DAX30',   secid: '100.GDAXI', lat: 50.11,  lng: 8.68,   region: '德国' },
  { name: '法国CAC40',   secid: '100.FCHI',  lat: 48.86,  lng: 2.35,   region: '法国' },
  { name: '荷兰AEX',     secid: '100.AEX',   lat: 52.37,  lng: 4.90,   region: '荷兰' },
  { name: '瑞士SMI',     secid: '100.SSMI',  lat: 47.37,  lng: 8.54,   region: '瑞士' },
  { name: '俄罗斯RTS',   secid: '100.RTS',   lat: 55.75,  lng: 37.62,  region: '俄罗斯' }
]

// 东财 push2 接口对 fetch/XHR 跨域会带 Origin 头触发 WAF 掐连（ERR_EMPTY_RESPONSE），
// 但对 <script> JSONP 放行（其自家网页小组件即此机制）。故用 JSONP 取数。
function jsonp(url, timeout = 12000) {
  return new Promise((resolve, reject) => {
    const cbName = '__gmcb_' + Math.random().toString(36).slice(2)
    const script = document.createElement('script')
    let done = false
    const cleanup = () => {
      done = true
      try { delete window[cbName] } catch (e) { window[cbName] = undefined }
      if (script.parentNode) script.parentNode.removeChild(script)
    }
    const timer = setTimeout(() => { if (!done) { cleanup(); reject(new Error('JSONP 超时')) } }, timeout)
    window[cbName] = (data) => { clearTimeout(timer); cleanup(); resolve(data) }
    script.onerror = () => { clearTimeout(timer); cleanup(); reject(new Error('JSONP 加载失败')) }
    // 关键：script 本就不发 Origin；再加 no-referrer 去掉 Referer，避免东财 WAF 因
    // 第三方站点来源头（0vk.top）掐连（ERR_EMPTY_RESPONSE）
    script.referrerPolicy = 'no-referrer'
    script.src = url + (url.includes('?') ? '&' : '?') + 'cb=' + cbName
    document.head.appendChild(script)
  })
}

// 英文国家名 → 中文映射（覆盖世界地图主要国家）
const COUNTRY_ZH_MAP = {
  'China': '中国', 'Russia': '俄罗斯', 'Mongolia': '蒙古',
  'India': '印度', 'Japan': '日本', 'South Korea': '韩国', 'North Korea': '朝鲜',
  'Thailand': '泰国', 'Vietnam': '越南', 'Myanmar': '缅甸', 'Malaysia': '马来西亚',
  'Indonesia': '印度尼西亚', 'Philippines': '菲律宾', 'Pakistan': '巴基斯坦',
  'Kazakhstan': '哈萨克斯坦', 'Iran': '伊朗', 'Saudi Arabia': '沙特阿拉伯',
  'Iraq': '伊拉克', 'Turkey': '土耳其', 'United Arab Emirates': '阿联酋',
  'Afghanistan': '阿富汗', 'Israel': '以色列',
  'United States': '美国', 'Canada': '加拿大', 'Mexico': '墨西哥',
  'Brazil': '巴西', 'Argentina': '阿根廷', 'Chile': '智利', 'Colombia': '哥伦比亚',
  'Peru': '秘鲁', 'Venezuela': '委内瑞拉', 'Bolivia': '玻利维亚',
  'United Kingdom': '英国', 'France': '法国', 'Germany': '德国', 'Italy': '意大利',
  'Spain': '西班牙', 'Portugal': '葡萄牙', 'Netherlands': '荷兰', 'Belgium': '比利时',
  'Switzerland': '瑞士', 'Austria': '奥地利', 'Sweden': '瑞典', 'Norway': '挪威',
  'Finland': '芬兰', 'Denmark': '丹麦', 'Poland': '波兰', 'Greece': '希腊',
  'Ireland': '爱尔兰', 'Czech Republic': '捷克', 'Ukraine': '乌克兰', 'Romania': '罗马尼亚',
  'Hungary': '匈牙利', 'Croatia': '克罗地亚', 'Bulgaria': '保加利亚', 'Serbia': '塞尔维亚',
  'Egypt': '埃及', 'South Africa': '南非', 'Nigeria': '尼日利亚', 'Morocco': '摩洛哥',
  'Algeria': '阿尔及利亚', 'Kenya': '肯尼亚', 'Ethiopia': '埃塞俄比亚', 'Ghana': '加纳',
  'Australia': '澳大利亚', 'New Zealand': '新西兰', 'Papua New Guinea': '巴布亚新几内亚',
  'Somalia': '索马里', 'Sudan': '苏丹', 'Libya': '利比亚', 'Tanzania': '坦桑尼亚',
  'Angola': '安哥拉', 'Mali': '马里', 'Mozambique': '莫桑比克', 'Namibia': '纳米比亚',
  'Madagascar': '马达加斯加', 'Zimbabwe': '津巴布韦', 'Senegal': '塞内加尔', 'Cameroon': '喀麦隆',
  'Chad': '乍得', 'Tunisia': '突尼斯', 'Zambia': '赞比亚', 'Uganda': '乌干达',
  'Iceland': '冰岛', 'Belarus': '白俄罗斯', 'Latvia': '拉脱维亚', 'Lithuania': '立陶宛',
  'Estonia': '爱沙尼亚', 'Slovakia': '斯洛伐克', 'Moldova': '摩尔多瓦', 'Albania': '阿尔巴尼亚',
  'Macedonia': '马其顿', 'Slovenia': '斯洛文尼亚', 'Montenegro': '黑山',
  'Ecuador': '厄瓜多尔', 'Paraguay': '巴拉圭', 'Uruguay': '乌拉圭',
  'Guyana': '圭亚那', 'Suriname': '苏里南', 'Cuba': '古巴', 'Guatemala': '危地马拉',
  'Honduras': '洪都拉斯', 'Nicaragua': '尼加拉瓜', 'Panama': '巴拿马', 'Jamaica': '牙买加',
  'Korea': '韩国', 'Laos': '老挝', 'Cambodia': '柬埔寨', 'Bangladesh': '孟加拉国',
  'Nepal': '尼泊尔', 'Sri Lanka': '斯里兰卡', 'Yemen': '也门', 'Oman': '阿曼',
  'Jordan': '约旦', 'Lebanon': '黎巴嫩', 'Syria': '叙利亚', 'Georgia': '格鲁吉亚',
  'Armenia': '亚美尼亚', 'Azerbaijan': '阿塞拜疆', 'Turkmenistan': '土库曼斯坦',
  'Uzbekistan': '乌兹别克斯坦', 'Kyrgyzstan': '吉尔吉斯斯坦', 'Tajikistan': '塔吉克斯坦',
  'Dem. Rep. Congo': '刚果(金)', 'Dem. Rep. Korea': '朝鲜', 'Republic of Korea': '韩国',
  'Czechia': '捷克', 'Bosnia and Herz.': '波黑', 'Dominican Rep.': '多米尼加',
  'S. Sudan': '南苏丹', 'Central African Rep.': '中非', 'Eq. Guinea': '赤道几内亚',
  'W. Sahara': '西撒哈拉', 'Falkland Is.': '福克兰群岛', 'Greenland': '格陵兰',
  'Fr. S. Antarctic Lands': '法兰西南方领地', 'Antarctica': '南极洲',
  'Taiwan': '台湾', 'Hong Kong': '香港',
  'Solomon Is.': '所罗门群岛', 'New Caledonia': '新喀里多尼亚', 'Fiji': '斐济',
  // ── 补全剩余国家/地区(悬停 tooltip 显示中文名) ──
  'Aland': '奥兰群岛', 'American Samoa': '美属萨摩亚', 'Andorra': '安道尔',
  'Antigua and Barb.': '安提瓜和巴布达', 'Bahamas': '巴哈马', 'Bahrain': '巴林',
  'Barbados': '巴巴多斯', 'Belize': '伯利兹', 'Benin': '贝宁', 'Bermuda': '百慕大',
  'Bhutan': '不丹', 'Botswana': '博茨瓦纳', 'Br. Indian Ocean Ter.': '英属印度洋领地',
  'Brunei': '文莱', 'Burkina Faso': '布基纳法索', 'Burundi': '布隆迪',
  'Cape Verde': '佛得角', 'Cayman Is.': '开曼群岛', 'Comoros': '科摩罗',
  'Congo': '刚果(布)', 'Costa Rica': '哥斯达黎加', 'Curaçao': '库拉索',
  'Cyprus': '塞浦路斯', 'Czech Rep.': '捷克', 'Côte d\'Ivoire': '科特迪瓦',
  'Djibouti': '吉布提', 'Dominica': '多米尼克', 'El Salvador': '萨尔瓦多',
  'Eritrea': '厄立特里亚', 'Faeroe Is.': '法罗群岛', 'Fr. Polynesia': '法属波利尼西亚',
  'Gabon': '加蓬', 'Gambia': '冈比亚', 'Grenada': '格林纳达', 'Guam': '关岛',
  'Guinea': '几内亚', 'Guinea-Bissau': '几内亚比绍', 'Haiti': '海地',
  'Heard I. and McDonald Is.': '赫德岛', 'Isle of Man': '马恩岛', 'Jersey': '泽西岛',
  'Kiribati': '基里巴斯', 'Kuwait': '科威特', 'Lao PDR': '老挝', 'Lesotho': '莱索托',
  'Liberia': '利比里亚', 'Liechtenstein': '列支敦士登', 'Luxembourg': '卢森堡',
  'Malawi': '马拉维', 'Malta': '马耳他', 'Mauritania': '毛里塔尼亚',
  'Mauritius': '毛里求斯', 'Micronesia': '密克罗尼西亚', 'Montserrat': '蒙特塞拉特',
  'N. Cyprus': '北塞浦路斯', 'N. Mariana Is.': '北马里亚纳', 'Niger': '尼日尔',
  'Niue': '纽埃', 'Palau': '帕劳', 'Palestine': '巴勒斯坦', 'Puerto Rico': '波多黎各',
  'Qatar': '卡塔尔', 'Rwanda': '卢旺达', 'S. Geo. and S. Sandw. Is.': '南乔治亚岛',
  'Saint Helena': '圣赫勒拿', 'Saint Lucia': '圣卢西亚', 'Samoa': '萨摩亚',
  'Seychelles': '塞舌尔', 'Siachen Glacier': '锡亚琴冰川', 'Sierra Leone': '塞拉利昂',
  'Singapore': '新加坡', 'St. Pierre and Miquelon': '圣皮埃尔和密克隆',
  'St. Vin. and Gren.': '圣文森特', 'Swaziland': '斯威士兰',
  'São Tomé and Principe': '圣多美和普林西比', 'Timor-Leste': '东帝汶', 'Togo': '多哥',
  'Tonga': '汤加', 'Trinidad and Tobago': '特立尼达和多巴哥',
  'Turks and Caicos Is.': '特克斯和凯科斯', 'U.S. Virgin Is.': '美属维尔京群岛',
  'Vanuatu': '瓦努阿图'
}

export default {
  name: 'GlobalMarket',
  components: { SecurityAlert },
  data() {
    return {
      loading: false,
      data: null,
      chart: null,
      timer: null,
      intraday: [],
      intradayLoading: false,
      intradayUpdatedAt: '',
      intradayTimer: null,
      // 全球市场环境观察:美元指数/NYMEX原油/美债10Y,JSONP 直连东财
      envRaw: [],
      envTimer: null,
      // 地图区域筛选:all=全部,其余按 region 字段前缀匹配
      regionFilter: 'all',
      // 指数矩阵排序:change_desc=涨幅/price=点位/abs=波动幅度
      matrixFilter: 'change_desc'
    }
  },
  computed: {
    indices() {
      return (this.data && this.data.indices) || []
    },
    // ===== 全球市场环境观察 =====
    envItems() {
      // 固定展示顺序:科技风向标 → 流动性 → 通胀 → 利率
      const order = ['ndx', 'udi', 'oil', 'us10y']
      return order.map(k => this.envRaw.find(e => e.key === k)).filter(Boolean)
    },
    // 风险偏好粗判:美元跌+油稳/股涨 → 偏暖;美元大涨/美债利率大动 → 偏冷。仅观察参考,不构成结论。
    envOverallClass() {
      const udi = this.envRaw.find(e => e.key === 'udi')
      const us10y = this.envRaw.find(e => e.key === 'us10y')
      if (!udi) return 'neutral'
      if (udi.chg <= -0.3 && !(us10y && us10y.chg >= 1)) return 'risk-on'
      if (udi.chg >= 0.3 || (us10y && Math.abs(us10y.chg) >= 1)) return 'risk-off'
      return 'neutral'
    },
    envOverallText() {
      const cls = this.envOverallClass
      return cls === 'risk-on' ? '美元走弱 · 风险偏好偏暖' : cls === 'risk-off' ? '美元/利率扰动 · 风险偏好偏冷' : '外部环境中性'
    },
    envDescText() {
      const cls = this.envOverallClass
      if (cls === 'risk-on') return '美元指数走弱通常利于外资流入A股，关注科技/有色等对流动性敏感板块'
      if (cls === 'risk-off') return '美元或美债利率上行压制成长股估值，关注A股高估值板块承压与防御方向'
      return '外部变量波动不大，以A股自身资金面为主'
    },
    // ===== 地图区域筛选 =====
    regionFilters() {
      return [
        { key: 'all', label: '全部' },
        { key: '中国', label: '中国' },
        { key: '亚洲', label: '亚洲' },
        { key: '欧洲', label: '欧洲' },
        { key: '美国', label: '美洲' }
      ]
    },
    // 当前筛选下可见的指数(地图气泡同步显隐)
    filteredIndices() {
      const list = this.indices
      const f = this.regionFilter
      if (f === 'all') return list
      if (f === '中国') return list.filter(i => i.region === '中国' || i.region === '香港' || i.region === '台湾')
      if (f === '亚洲') return list.filter(i => ['中国', '香港', '台湾', '日本', '韩国', '马来西亚', '印尼', '越南', '印度', '澳大利亚'].includes(i.region))
      if (f === '欧洲') return list.filter(i => ['英国', '德国', '法国', '荷兰', '瑞士', '俄罗斯'].includes(i.region))
      if (f === '美国') return list.filter(i => ['美国', '巴西'].includes(i.region))
      return list
    },
    // ===== 指数矩阵(卡片) =====
    matrixFilters() {
      return [
        { key: 'change_desc', label: '涨幅' },
        { key: 'change_asc', label: '跌幅' },
        { key: 'abs', label: '波动' },
        { key: 'price', label: '点位' }
      ]
    },
    // 卡片矩阵:沿用 globalCards(上证/KOSPI/纳指固定前三 + 分时叠加),再按用户选择的排序重排
    matrixCards() {
      const cards = this.globalCards
      const f = this.matrixFilter
      if (f === 'change_asc') return [...cards].sort((a, b) => a.change - b.change)
      if (f === 'abs') return [...cards].sort((a, b) => Math.abs(b.change) - Math.abs(a.change))
      if (f === 'price') return [...cards].sort((a, b) => (b.price || 0) - (a.price || 0))
      return [...cards].sort((a, b) => b.change - a.change)
    },
    // 分时序列按 code 建立查找表（分时接口只返回 series，不含涨跌幅/价格）
    intradaySeriesMap() {
      const m = {}
      this.intraday.forEach(ix => { if (ix && ix.code) m[ix.code] = ix.series })
      return m
    },
    // 卡片基于全球快照（含全部指数涨跌幅/价格，稳定），上证/韩国KOSPI/纳斯达克 固定前三；
    // 分时线从分时接口按 code 叠加，拿不到的卡片只显示涨跌幅不画线
    globalCards() {
      const pin = ['1.000001', '100.KS11', '100.NDX']
      const headSet = new Set(pin)
      const byCode = {}
      this.indices.forEach(i => { byCode[i.code] = i })
      const head = pin.map(c => byCode[c]).filter(Boolean)
      const rest = this.indices.filter(i => !headSet.has(i.code))
      const sm = this.intradaySeriesMap
      return [...head, ...rest].map(i => ({ ...i, series: sm[i.code] || [] }))
    }
  },
  async mounted() {
    await this.loadMap()
    await this.fetchData(true)
    this.timer = setInterval(() => this.fetchData(false), 30000)
    this.fetchIntraday()
    this.intradayTimer = setInterval(() => this.fetchIntraday(), 300000)
    this.fetchEnv()
    this.envTimer = setInterval(() => this.fetchEnv(), 60000)
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    clearInterval(this.timer)
    clearInterval(this.intradayTimer)
    clearInterval(this.envTimer)
    window.removeEventListener('resize', this.handleResize)
    if (this.chart) {
      this.chart.dispose()
      this.chart = null
    }
  },
  methods: {
    goBack() {
      this.$router.push('/')
    },

    // ===== 全球市场环境观察:东财批量实时报价(JSONP,与分时同机制) =====
    async fetchEnv() {
      try {
        const url = 'https://push2.eastmoney.com/api/qt/ulist.np/get?secids=100.UDI,102.CL00Y,171.US10Y,100.NDX&fields=f2,f3,f12,f14&fltt=2'
        const body = await jsonp(url, 8000)
        const diff = body && body.data && body.data.diff
        if (!Array.isArray(diff)) return
        const meta = {
          NDX: { key: 'ndx', name: '纳斯达克', note: '科技风向标', hint: '美股科技股强弱影响A股AI/半导体链情绪(详见首页AI环境条)' },
          UDI: { key: 'udi', name: '美元指数', note: '全球流动性', hint: '美元强弱反映全球流动性松紧,走弱利于新兴市场与A股外资流入' },
          CL00Y: { key: 'oil', name: 'NYMEX原油', note: '通胀与地缘', hint: '原油价格影响通胀预期与能源板块,大涨常伴随地缘风险' },
          US10Y: { key: 'us10y', name: '美债10Y收益率', note: '利率环境', hint: '美债收益率上行压制成长股估值,关注A股高估值板块压力' }
        }
        this.envRaw = diff.filter(d => meta[d.f12]).map(d => ({
          ...meta[d.f12],
          price: Number(d.f2),
          chg: Number(d.f3) || 0
        }))
      } catch (e) {
        // 环境条拿不到就整体隐藏,不影响地图主功能
      }
    },

    // 地图区域筛选:切换时重设气泡数据(echarts notMerge 重渲染)
    setRegionFilter(key) {
      this.regionFilter = key
      this.renderChart()
    },

    // 点击榜单项：缩放到对应国家位置并高亮
    focusIndex(item) {
      if (!this.chart || !item) return
      const lng = item.lng
      const lat = item.lat
      // 缩放并居中到目标坐标
      this.chart.setOption({
        geo: {
          center: [lng, lat],
          zoom: 4
        }
      })
      // 高亮对应的散点并显示 tooltip
      const seriesData = this.chart.getOption().series[0].data
      const idx = seriesData.findIndex(d => d.code === item.code)
      if (idx >= 0) {
        this.chart.dispatchAction({ type: 'highlight', seriesIndex: 0, dataIndex: idx })
        this.chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: idx })
      }
    },

    async loadMap() {
      try {
        const res = await fetch('/world.json')
        const geo = await res.json()
        // 将国家英文名翻译为中文
        if (geo.features) {
          geo.features.forEach(f => {
            const enName = f.properties && f.properties.name
            const zhName = COUNTRY_ZH_MAP[enName]
            if (zhName) {
              f.properties.name = zhName
            }
          })
        }
        echarts.registerMap('world', geo)
      } catch (e) {
        console.error('世界地图加载失败', e)
      }
    },
    async fetchData(showLoading) {
      this.loading = showLoading
      try {
        const data = await this.fetchSnapshot()
        this.data = data
        this.$nextTick(() => this.renderChart())
        // 分时由独立的 5 分钟定时器负责,这里不再顺带抓:原先每次快照刷新(30s)
        // 都拉一轮东财 trends2,分时实际变成 30s 一抓,访客 IP 侧压力放大 10 倍
      } catch (e) {
        console.error('获取全球指数失败', e)
      } finally {
        this.loading = false
      }
    },
    // 快照：走后端 /api/flow/global-indices(后端:有新浪代码的走新浪主源,无代码的保留东财)。
    // 前端不再直连东财,规避反爬。返回 {indices:[...], update_time, source}
    async fetchSnapshot() {
      const resp = await getGlobalIndices()
      const payload = (resp && resp.success && resp.data) || {}
      // 后端返回 {indices: [{code:secid, ...}, ...], update_time, source}
      // 转 secid→item 映射以便按 key 查找
      const list = Array.isArray(payload.indices) ? payload.indices : []
      const map = {}
      for (const it of list) {
        if (it.code) map[it.code] = it
      }
      const indices = []
      for (const c of GLOBAL_INDICES) {
        const it = map[c.secid]
        if (!it || it.price == null || Number.isNaN(Number(it.price))) continue
        indices.push({
          name: c.name, code: c.secid,
          price: Number(it.price),
          change: Number(it.change) || 0,
          change_amount: Number(it.change_amount) || 0,
          lat: c.lat, lng: c.lng, region: c.region,
          source: it.source || 'backend'
        })
      }
      indices.sort((a, b) => b.change - a.change)
      return {
        indices,
        update_time: payload.update_time || new Date().toLocaleString('zh-CN', { hour12: false }),
        source: payload.source || 'backend'
      }
    },
    formatChange(change) {
      if (change === null || change === undefined || Number.isNaN(Number(change))) return '--'
      const pct = (change * 100).toFixed(2)
      return (change >= 0 ? '+' : '') + pct + '%'
    },

    formatPrice(price) {
      if (price === null || price === undefined || Number.isNaN(Number(price))) return '--'
      return Number(price).toLocaleString('en-US', { maximumFractionDigits: 2 })
    },

    async fetchIntraday() {
      const list = this.indices
      if (!list.length) return
      if (this.intradayLoading) return   // 重入保护:上一轮分批抓取未完成时跳过,避免并发互踩状态
      this.intradayLoading = true
      try {
        // 分批并发(每批 4 个)抓东财 trends2:原先逐个串行 + 500ms 间隔要 8s+,
        // 全并发又怕触发 WAF;分批折中,单只失败返回 null 滤掉,不影响其它。
        // 每批完成即合并渲染,先到的指数先画线,不必等全部抓完。
        const fetchOne = async (ix) => {
          try {
            const url = `https://push2his.eastmoney.com/api/qt/stock/trends2/get?secid=${encodeURIComponent(ix.code)}&fields1=f1,f2&fields2=f51,f52,f53,f54,f55,f56,f57,f58&iscr=0&ndays=1`
            const body = await jsonp(url, 8000)
            const trends = body && body.data && body.data.trends
            if (Array.isArray(trends) && trends.length) {
              const series = []
              for (const line of trends) {
                const parts = line.split(',')
                if (parts.length < 2) continue
                const price = parseFloat(parts[1])
                if (Number.isNaN(price)) continue
                const t = parts[0]
                series.push({ t: t.length >= 16 ? t.slice(11, 16) : t, price })
              }
              if (series.length) {
                return { code: ix.code, name: ix.name, region: ix.region, series }
              }
            }
          } catch (e) {
            // 单只失败不影响其它
          }
          return null
        }
        const CONCURRENCY = 4
        const fetched = []
        for (let i = 0; i < list.length; i += CONCURRENCY) {
          const batch = list.slice(i, i + CONCURRENCY)
          fetched.push(...await Promise.all(batch.map(fetchOne)))
          // 渐进渲染:该批成功的结果立刻上屏
          this.intraday = fetched.filter(Boolean)
        }
        this.intradayUpdatedAt = new Date().toLocaleTimeString('zh-CN', { hour12: false })
      } catch (e) {
        console.error('前端获取分时失败', e)
      } finally {
        this.intradayLoading = false
      }
    },

    // 分时 sparkline 折线路径（viewBox 100×36）
    sparkPath(ix) {
      const s = ix && ix.series
      if (!s || s.length < 2) return ''
      const prices = s.map(p => Number(p.price))
      const min = Math.min(...prices)
      const max = Math.max(...prices)
      const range = (max - min) || 1
      const n = prices.length
      return prices.map((p, i) => {
        const x = (i / (n - 1)) * 100
        const y = 33 - ((p - min) / range) * 30   // 上下留 ~3px
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`
      }).join(' ')
    },
    sparkArea(ix) {
      const d = this.sparkPath(ix)
      if (!d) return ''
      return d + ' L100 36 L0 36 Z'
    },
    handleResize() {
      if (this.chart) this.chart.resize()
    },
    renderChart() {
      const list = this.filteredIndices
      const el = this.$refs.chartEl
      if (!el) return
      if (!this.chart) {
        this.chart = markRaw(echarts.init(el))
      }
      if (!list.length) {
        // 筛选后无数据:保留地图本体,但必须显式清空系列数据——
        // 直接 return 会让上一个区域筛选的旧气泡一直残留在图上
        this.chart.setOption({
          series: this.chart.getOption().series.map(s => ({ data: [] }))
        })
        return
      }

      const scatterData = list.map(i => ({
        name: i.name,
        value: [i.lng, i.lat, +(i.change * 100).toFixed(2), i.price, i.region]
      }))

      // 圆圈颜色：基调 涨=红、跌=绿；颜色深浅随涨跌幅变化（幅度越大颜色越深）
      const colorOf = v => {
        const pct = Math.abs(v[2])
        const opacity = Math.min(Math.max(0.5 + (pct / 3) * 0.46, 0.5), 0.97)
        return v[2] >= 0 ? `rgba(240, 82, 95, ${opacity})` : `rgba(16, 185, 129, ${opacity})`
      }
      // 边框：亮红/亮绿，勾出圆圈轮廓
      const borderColorOf = v => v[2] >= 0 ? '#f08a94' : '#5eead4'
      // 圆圈大小：按涨跌幅绝对值，最小30最大60
      const sizeOf = v => Math.min(Math.max(Math.abs(v[2]) * 4 + 30, 30), 60)

      // ── 地图分层配色:有市场的国家"点亮",其余沉入暗处 ──
      // 活跃国家映射:指数的 region 字段 → world.json 里的国家注册名(翻译后的中文名)
      const activeRegions = [...new Set(list.map(i => i.region))]
      const REGION_COUNTRY = {
        '中国': ['中国'], '香港': ['香港'], '台湾': ['台湾'],
        '日本': ['日本'], '韩国': ['韩国'], '马来西亚': ['马来西亚'],
        '印尼': ['印度尼西亚'], '越南': ['越南'], '印度': ['印度'],
        '澳大利亚': ['澳大利亚'], '美国': ['美国'], '巴西': ['巴西'],
        '英国': ['英国'], '德国': ['德国'], '法国': ['法国'],
        '荷兰': ['荷兰'], '瑞士': ['瑞士'], '俄罗斯': ['俄罗斯']
      }
      const activeCountries = new Set()
      for (const r of activeRegions) {
        for (const c of (REGION_COUNTRY[r] || [r])) activeCountries.add(c)
      }

      // regions 数组:活跃国家渐变蓝 + 亮边,其他国家暗底细边
      const regions = []
      for (const c of activeCountries) {
        regions.push({
          name: c,
          itemStyle: {
            areaColor: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [{ offset: 0, color: '#16324f' }, { offset: 1, color: '#0f2338' }] },
            borderColor: '#2f7fd6',
            borderWidth: 1.1,
            shadowColor: 'rgba(47, 127, 214, 0.45)',
            shadowBlur: 10
          },
          emphasis: {
            itemStyle: { areaColor: '#1d4a75', borderColor: '#5aa7f0', borderWidth: 1.4 },
            label: { show: true, color: '#cfe3f7', fontSize: 11, fontWeight: 'bold' }
          }
        })
      }

      this.chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'item',
          backgroundColor: 'rgba(17, 24, 39, 0.95)',
          borderColor: '#253247',
          borderWidth: 1,
          padding: [12, 16],
          textStyle: { color: '#E5EAF2', fontSize: 13 },
          formatter: p => {
            const v = p.value
            const chg = v[2]
            const c = chg >= 0 ? '#F0525F' : '#10B981'
            return `<div style="min-width:170px">
              <div style="font-weight:bold;font-size:14px;border-bottom:1px solid #253247;padding-bottom:6px;margin-bottom:8px">${v[4]} · ${p.name}</div>
              <div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="color:#8795AA">最新价</span><span style="font-weight:500">${v[3]}</span></div>
              <div style="display:flex;justify-content:space-between"><span style="color:#8795AA">涨跌幅</span><span style="color:${c};font-weight:bold">${chg >= 0 ? '+' : ''}${chg}%</span></div>
            </div>`
          }
        },
        geo: {
          map: 'world',
          roam: true,
          zoom: 1.3,
          center: this.regionFilter === 'all' ? null : this.filteredRegionCenter(),
          scaleLimit: { min: 0.8, max: 8 },
          // 基础层:无市场国家沉底(暗),有市场国家由 regions[] 点亮(渐变蓝+发光边)
          itemStyle: {
            areaColor: '#0a111e',
            borderColor: '#17304d',
            borderWidth: 0.5
          },
          // 名单动态:活跃国家渐变蓝底+蓝色发光边;非活跃走默认暗样式
          regions,
          emphasis: {
            label: { show: true, color: '#cfe3f7', fontSize: 10 }
          },
          silent: false
        },
        series: [
          // 0) 脉冲散点(涟漪环)—— 各指数涨跌气泡,常驻脉冲
          {
            type: 'effectScatter',
            coordinateSystem: 'geo',
            data: scatterData,
            symbolSize: v => sizeOf(v),
            rippleEffect: { brushType: 'stroke', scale: 3.2, period: 4 },
            showEffectOn: 'render',
            itemStyle: {
              color: p => colorOf(p.value),
              borderColor: p => borderColorOf(p.value),
              borderWidth: 2.5,
              shadowBlur: 16,
              shadowColor: p => (p.value[2] >= 0 ? 'rgba(240, 82, 95, 0.5)' : 'rgba(16, 185, 129, 0.5)')
            },
            label: {
              show: true,
              formatter: p => { const chg = p.value[2]; return (chg >= 0 ? '+' : '') + chg + '%' },
              color: '#fff',
              fontSize: 12,
              fontWeight: 'bold',
              position: 'inside',
              textShadowColor: 'rgba(0,0,0,0.45)',
              textShadowBlur: 3
            },
            // 亚洲/欧洲密集区气泡标签自动避让,重叠的直接隐藏(悬停仍可见详情)
            labelLayout: {
              hideOverlap: true
            },
            emphasis: {
              scale: 1.5,
              label: { fontSize: 13, show: true }
            },
            zlevel: 2
          },
          // 1) 国名标签(圆圈下方,无散点本体)——同样参与避让
          {
            type: 'scatter',
            coordinateSystem: 'geo',
            data: scatterData,
            symbolSize: 0,
            label: {
              show: true,
              formatter: p => p.data.name,
              color: '#E5EAF2',
              fontSize: 12,
              fontWeight: 'bold',
              position: 'bottom',
              distance: 8,
              textShadowColor: '#000',
              textShadowBlur: 4,
              backgroundColor: 'rgba(13, 21, 36, 0.7)',
              padding: [2, 6],
              borderRadius: 3
            },
            labelLayout: {
              hideOverlap: true
            },
            tooltip: { show: false },
            zlevel: 2
          }
        ]
      }, true)
    },

    // 区域筛选时把地图视野居中到对应区域(经纬度重心)
    filteredRegionCenter() {
      const centers = {
        '中国': [110, 30],
        '亚洲': [110, 25],
        '欧洲': [12, 50],
        '美国': [-70, 5]
      }
      return centers[this.regionFilter] || null
    }
  }
}
</script>

<style scoped>
.global-market-page {
  min-height: 100vh;
  background: #080D18;
  color: #E5EAF2;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.gm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 290px 14px 20px; /* 右侧避让固定北京时间+登录入口 */
  background: #111827;
  border-radius: 10px;
  border: 1px solid #253247;
  margin-bottom: 12px;
}

.gm-header h1 {
  font-size: 1.25rem;
  color: #E5EAF2;
  margin: 0;
  font-weight: 700;
  letter-spacing: 0.5px;
}

.gm-header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.gm-source-tag {
  padding: 4px 12px;
  background: rgba(57, 139, 255, 0.12);
  border: 1px solid rgba(57, 139, 255, 0.35);
  border-radius: 999px;
  font-size: 12px;
  color: #5da2ff;
}

.gm-update {
  font-size: 12px;
  color: #8795AA;
}

.gm-back-button {
  padding: 8px 18px;
  background: #172235;
  border: 1px solid #253247;
  border-radius: 8px;
  color: #E5EAF2;
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 14px;
}

.gm-back-button:hover {
  background: #1d2b40;
  border-color: rgba(135, 149, 170, 0.45);
  transform: translateY(-1px);
}

.gm-refresh-btn {
  padding: 8px 16px;
  background: #398BFF;
  border: 1px solid #5da2ff;
  border-radius: 6px;
  color: #fff;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s ease;
}

.gm-refresh-btn:hover:not(:disabled) {
  background: #5da2ff;
  transform: translateY(-1px);
}

.gm-refresh-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ===== 全球市场环境观察条 ===== */
.gm-env-strip {
  border: 1px solid #253247;
  border-radius: 10px;
  background: #111827;
  padding: 10px 16px;
  margin-bottom: 12px;
}
.gm-env-strip.risk-on { border-color: rgba(240, 82, 95, 0.45); }
.gm-env-strip.risk-off { border-color: rgba(16, 185, 129, 0.45); }

.gm-env-head {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 8px;
}
.gm-env-title {
  font-size: 13px;
  font-weight: 700;
  color: #8795AA;
  letter-spacing: 1px;
}
.gm-env-verdict {
  font-size: 14px;
  font-weight: 800;
}
.gm-env-strip.risk-on .gm-env-verdict { color: #F0525F; }
.gm-env-strip.risk-off .gm-env-verdict { color: #10B981; }
.gm-env-strip.neutral .gm-env-verdict { color: #E5EAF2; }

.gm-env-items {
  display: flex;
  gap: 28px;
  flex-wrap: wrap;
}
.gm-env-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  cursor: default;
}
.gm-env-name {
  font-size: 12px;
  color: #8795AA;
  font-weight: 600;
}
.gm-env-price {
  font-size: 15px;
  font-weight: 700;
  color: #E5EAF2;
  font-variant-numeric: tabular-nums;
}
.gm-env-chg {
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.gm-env-chg.up { color: #F0525F; }
.gm-env-chg.down { color: #10B981; }
.gm-env-note {
  font-size: 11px;
  color: #6b7c93;
  padding: 1px 8px;
  background: rgba(135, 149, 170, 0.08);
  border-radius: 999px;
}

.gm-env-desc {
  margin-top: 8px;
  font-size: 12px;
  color: #8795AA;
  line-height: 1.5;
}

.gm-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

.gm-chart-wrapper {
  position: relative;
  height: 56vh;
  min-height: 340px;
  background: #111827;
  border-radius: 10px;
  border: 1px solid #253247;
  padding: 12px;
  overflow: hidden;
}

/* 区域筛选按钮组(地图左上角悬浮) */
.gm-region-filter {
  position: absolute;
  top: 20px;
  left: 20px;
  z-index: 5;
  display: flex;
  gap: 6px;
  background: rgba(23, 34, 53, 0.85);
  border: 1px solid #253247;
  border-radius: 8px;
  padding: 4px;
  backdrop-filter: blur(6px);
}
.gm-region-btn {
  background: transparent;
  border: none;
  color: #8795AA;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 5px;
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.gm-region-btn:hover { color: #E5EAF2; }
.gm-region-btn.active {
  background: #398BFF;
  color: #fff;
}

.gm-chart {
  width: 100%;
  height: 100%;
  min-height: 320px;
}

/* ===== 指数矩阵 ===== */
.gm-intraday-section {
  background: #111827;
  border-radius: 10px;
  border: 1px solid #253247;
  padding: 14px 16px;
}

.gi-section-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 12px;
}
.gi-section-head h3 {
  margin: 0;
  font-size: 15px;
  color: #E5EAF2;
  font-weight: 700;
}
.gi-update { font-size: 12px; color: #8795AA; }
.gi-loading { font-size: 12px; color: #5da2ff; }

.gm-matrix-controls {
  margin-left: auto;
  display: flex;
  gap: 4px;
  background: rgba(23, 34, 53, 0.6);
  border: 1px solid #253247;
  border-radius: 8px;
  padding: 3px;
}

.gm-intraday {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
  gap: 10px;
}

.gi-card {
  background: #172235;
  border: 1px solid #253247;
  border-left-width: 3px;
  border-radius: 8px;
  padding: 10px 12px;
  transition: border-color 0.15s ease, transform 0.15s ease;
}
.gi-card:hover { transform: translateY(-2px); }
.gi-card.up { border-left-color: #F0525F; }
.gi-card.down { border-left-color: #10B981; }

.gi-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 4px;
}
.gi-name {
  font-size: 13px;
  color: #E5EAF2;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gi-chg { font-size: 13px; font-weight: 800; font-variant-numeric: tabular-nums; }
.gi-chg.up { color: #F0525F; }
.gi-chg.down { color: #10B981; }

.gi-spark {
  display: block;
  width: 100%;
  height: 38px;
}

.gi-noline {
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: #6b7c93;
}

.gi-foot {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  margin-top: 4px;
}
.gi-region { font-size: 11px; color: #8795AA; }
.gi-price { font-size: 12px; color: #E5EAF2; font-variant-numeric: tabular-nums; }

.gi-empty {
  text-align: center;
  color: #8795AA;
  font-size: 13px;
  padding: 24px 0;
}

.gm-legend {
  position: absolute;
  bottom: 20px;
  left: 24px;
  display: flex;
  align-items: center;
  gap: 18px;
  font-size: 12px;
  color: #8795AA;
  pointer-events: none;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
}

.legend-item .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.legend-item .dot.up { background: #F0525F; box-shadow: 0 0 8px rgba(240, 82, 95, 0.6); }
.legend-item .dot.down { background: #10B981; box-shadow: 0 0 8px rgba(16, 185, 129, 0.6); }

.gm-footer {
  text-align: center;
  padding: 14px;
  color: #8795AA;
  font-size: 0.85rem;
  margin-top: 16px;
}

@media (max-width: 768px) {
  .global-market-page {
    padding: 10px;
  }
  .gm-header {
    flex-direction: column;
    gap: 10px;
    text-align: center;
    /* 清除桌面端右内边距避让 */
    padding: 12px;
  }
  .gm-header h1 {
    font-size: 1.1rem;
  }
  /* 移动端:地图高度收紧,环境条与矩阵自适应 */
  .gm-chart-wrapper {
    height: 44vh;
    min-height: 260px;
    padding: 8px;
  }
  .gm-region-filter {
    top: 14px;
    left: 14px;
    flex-wrap: wrap;
  }
  .gm-intraday {
    grid-template-columns: repeat(2, 1fr);
  }
  .gi-section-head {
    flex-wrap: wrap;
    gap: 8px;
  }
  .gm-matrix-controls {
    margin-left: 0;
    flex-basis: 100%;
  }
  .gm-env-items {
    gap: 12px;
  }
}
</style>