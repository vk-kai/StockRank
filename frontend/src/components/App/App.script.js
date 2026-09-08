import * as echarts from 'echarts'
import { marked } from 'marked'
import { formatFlow, formatNetFlow } from '../../utils/formatters'
import { getCurrentFlow, getHistoryData, getMinuteData, getMinuteDataByDate, getNews, getAccumulatedFlow, getSectorStocks, getHealth, resetCrawler, getMarketSummary, startAnalyzeDailyFlow, getAnalyzeDailyFlowStatus, getAuthSession, getAnomalyAlerts, getAiChain, getGlobalIndices, getMarketMarginTotal, testPushService as testPushServiceApi } from '../../services/apiService'
import { generateLiveReplayChartOption, buildReplaySectorOrder } from '../../services/chartService'
import '../../styles/App.css'
import SecurityAlert from '../SecurityAlert.vue'

// 格式化日期为 YYYY-MM-DD
function formatDate(date) {
  return date.toISOString().split('T')[0]
}

// 获取最近的交易日（跳过周末，回退到周五）
function getLatestWeekday(date) {
  const d = new Date(date)
  const day = d.getDay()
  if (day === 0) { // 周日 -> 回退2天到周五
    d.setDate(d.getDate() - 2)
  } else if (day === 6) { // 周六 -> 回退1天到周五
    d.setDate(d.getDate() - 1)
  }
  return formatDate(d)
}

// 判断是否为交易日（周一到周五）
function isTradingDay(date) {
  const day = new Date(date).getDay()
  return day !== 0 && day !== 6
}

export default {
  name: 'App',
  components: {
    SecurityAlert
  },
  data() {
    return {
      selectedTimeRange: 'today',
      currentData: [],
      accumulatedData: [],
      historyData: {},
      minuteData: {},
      chartInstance: null,
      // 折线图横屏全屏（移动端）：独立 echarts 实例，避免干扰内联图表
      chartFullscreen: false,
      fullscreenChart: null,
      // 横屏画布像素尺寸（视口长边×短边），显式设置到 DOM 后再 init echarts，避免“只铺一部分”
      landscapeSize: { w: 0, h: 0 },
      loading: false,
      error: null,
      lastUpdate: null,
      colors: [
        '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
        '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#ff5722',
        '#00bcd4', '#8bc34a', '#ffc107', '#9c27b0', '#3f51b5'
      ],
      countdown: 300,
      countdownInterval: null,
      latestNews: [],
      latestNewsCount: 0,
      currentNewsIndex: 0,
      newsRotationInterval: null,
      newsScrollInterval: null,
      threadStatus: {},
      healthStatus: {},
      crawlerStatus: {},
      healthChecking: false,
      healthCheckInterval: null,
      lastNewsId: null,
      anomalyWatchInterval: null,
      lastAnomalyTimestamp: '',
      hasUnreadAnomaly: false,
      // 资金异动速览弹窗（首页一键瞄一眼，深入看跳 /flow-alert）
      showFlowAlertModal: false,
      flowAlertLoading: false,
      flowAlertList: [],
      flowAlertSummary: { total: 0, sectors: 0, latest: '--' },
      showStockModal: false,
      selectedSector: null,
      sectorStocks: [],
      loadingStocks: false,
      stocksError: null,
      stockSortField: 'change',
      stockSortOrder: 'desc',
      isReplayingToday: false,
      replayCursor: null,
      replayTimer: null,
      replaySpeed: 200,
      replayTopSectors: [],
      replayDate: formatDate(new Date()),
      todayDate: formatDate(new Date()),
      hasBootstrappedTodayReplay: false,
      historicalMinuteData: null,
      lastTimeKeys: [],
      autoGrowCursor: null,
      autoGrowTimer: null,
      autoGrowSpeed: 200,
      // 多日模式(7/15/30天)逐日生长动画:切到多日后曲线按日期一天天长出来
      multiDayCursor: null,
      multiDayTimer: null,
      marketSummary: null,
      marketSummaryError: null,
      kospiIndex: null,
      marginTotal: null,
      marginTotalModalOpen: false,
      marginTotalChart: null,
      marketSummaryInterval: null,
      aiChainSummary: null,
      aiChainInterval: null,
      aiAnalyzing: false,
      showMoreMenu: false,
      showAIAnalysisModal: false,
      aiAnalysisResult: null,
      aiAnalysisError: null,
      aiAnalysisDate: null,
      aiAnalysisProgress: 0,
      aiAnalysisStep: '',
      aiAnalysisPollTimer: null,
      needsAuth: false,
      isAdmin: false
    }
  },
  computed: {
    minReplayDate() {
      const date = new Date()
      date.setDate(date.getDate() - 30)
      return formatDate(date)
    },
    countdownMinutes() {
      return Math.floor(this.countdown / 60).toString().padStart(2, '0')
    },
    countdownSeconds() {
      return (this.countdown % 60).toString().padStart(2, '0')
    },
    importantNews() {
      return this.latestNews.filter(news => 
        news.importance === '3' || (news.ai_analysis && news.ai_analysis.level === '重大')
      ).slice(0, 10)
    },
    currentNewsItem() {
      if (this.latestNews.length === 0) return null
      return this.latestNews[this.currentNewsIndex] || this.latestNews[0]
    },
    marketIndexCards() {
      const indices = this.marketSummary?.indices || {}
      const fallbackMainIndex = this.marketSummary?.main_index || {}
      const indexMap = {
        '000001': indices['000001'] || fallbackMainIndex,
        '399001': indices['399001'] || {},
        '399006': indices['399006'] || {}
      }

      const cards = [
        { ...indexMap['000001'], code: '000001', name: indexMap['000001'].name || '上证指数' },
        { ...indexMap['399001'], code: '399001', name: indexMap['399001'].name || '深证成指' },
        { ...indexMap['399006'], code: '399006', name: indexMap['399006'].name || '创业板' }
      ]
      if (this.kospiIndex) {
        cards.push({ ...this.kospiIndex, code: '100.KS11' })
      }
      return cards
    },
    aiChainOverallClass() {
      const s = this.aiChainSummary?.overall
      if (s === '偏多') return 'ai-bull'
      if (s === '偏空') return 'ai-bear'
      return 'ai-neutral'
    },
    aiChainOverallText() {
      return this.aiChainSummary?.overall || '加载中'
    },
    aiChainSubText() {
      const s = this.aiChainSummary
      if (!s) return ''
      return `需求${s.demand_signal} · 宏观${s.macro_signal}`
    },
    healthDisplayItems() {
      // 服务监控卡片要展示的行：合并后的「同花顺数据」+「消息推送服务」
      const rows = []
      const news = this.healthStatus.news
      const sector = this.healthStatus.sector
      if (news || sector) {
        rows.push({
          key: 'ths_data',
          label: '同花顺数据',
          kind: 'ths',
          item: this.combineThsHealth(news, sector),
        })
      }
      const push = this.healthStatus.push
      if (push) {
        rows.push({
          key: 'push',
          label: '消息推送服务',
          kind: 'push',
          item: push,
        })
      }
      return rows
    },
    healthErrors() {
      const errors = []
      const labels = {
        ths_news: '同花顺新闻',
        ths_sector: '同花顺板块资金'
      }
      for (const [key, value] of Object.entries(this.healthStatus)) {
        if (value.status === 'error' || value.status === 'partial') {
          errors.push({
            key,
            label: labels[key] || key,
            error: value.status === 'partial' ? '板块明细异常' : value.error,
            lastCheck: value.last_check
          })
        }
      }
      return errors
    },
    hasHealthErrors() {
      return this.healthErrors.length > 0
    },
    crawlerAlerts() {
      const alerts = []
      const labels = {
        'sector_flow': '板块资金',
        'news': '新闻'
      }
      for (const [key, value] of Object.entries(this.crawlerStatus)) {
        if (value.status === 'checking' || value.status === 'failed') {
          alerts.push({
            key,
            label: labels[key] || key,
            status: value.status,
            message: value.message,
            retrying: value.retrying,
            retryCount: value.retry_count
          })
        }
      }
      return alerts
    },
    hasCrawlerAlerts() {
      return this.crawlerAlerts.length > 0
    },
    healthToCrawlerMap() {
      return {
        'ths_news': 'news',
        'ths_sector': 'sector_flow'
      }
    },
    isAfterMarketClose() {
      const now = new Date()
      const hours = now.getHours()
      const minutes = now.getMinutes()
      return hours > 15 || (hours === 15 && minutes >= 0)
    },
    hasReplayData() {
      if (this.selectedTimeRange !== 'today') return false
      
      if (this.replayDate === this.todayDate) {
        return Object.keys(this.minuteData).length > 1
      }
      
      return true
    },
    chartHasData() {
      return Object.keys(this.minuteData).length > 0 || Object.keys(this.historyData).length > 0
    },
    showChartLoading() {
      return (this.loading || this.healthChecking) && !this.chartHasData
    },
    replayTop10Sectors() {
      if (this.selectedTimeRange !== 'today') return []

      let items = []
      const timeKeys = Object.keys(this.minuteData).sort()

      if (timeKeys.length > 0) {
        const latestKey = timeKeys[timeKeys.length - 1]
        items = this.minuteData[latestKey]?.data || this.minuteData[latestKey] || []
      } else if (this.currentData.length > 0) {
        items = this.currentData
      }

      const groupedItems = [...items]
        .filter(item => item && item.name)
        .reduce((groups, item) => {
          const netFlow = item.net_flow ?? item.flow ?? item.total_flow ?? 0
          const group = item.flow_group || (netFlow < 0 ? 'net_out' : 'net_in')
          if (group === 'net_out') {
            groups.out.push(item)
          } else {
            groups.in.push(item)
          }
          return groups
        }, { in: [], out: [] })

      const netValue = item => Number(item.net_flow ?? item.flow ?? 0) || 0
      const inflowItems = groupedItems.in
        .sort((a, b) => netValue(b) - netValue(a))
        .slice(0, 5)
      const outflowItems = groupedItems.out
        .sort((a, b) => netValue(a) - netValue(b))
        .slice(0, 5)
      const maxInflow = Math.max(...inflowItems.map(item => Math.abs(netValue(item))), 1)
      const maxOutflow = Math.max(...outflowItems.map(item => Math.abs(netValue(item))), 1)
      const rankGroup = (list, direction, maxValue) => list.map((item, index) => {
        const strength = Math.max(0.2, Math.min(1, Math.abs(netValue(item)) / maxValue))
        return {
          ...item,
          rank: index + 1,
          flow_direction: direction,
          flow_strength: strength,
          // 流入/流出越大越浓：抬高上限拉开梯度（TOP1 明显比 TOP5 红/绿）
          flow_alpha: (0.18 + strength * 0.5).toFixed(3),
          flow_deep_alpha: (0.22 + strength * 0.55).toFixed(3),
          flow_border_alpha: (0.28 + strength * 0.6).toFixed(3)
        }
      })

      return [
        ...rankGroup(inflowItems, 'in', maxInflow),
        ...rankGroup(outflowItems, 'out', maxOutflow)
      ]
    },
    replayTop10Title() {
      if (this.selectedTimeRange !== 'today') return ''
      return this.replayDate === this.todayDate
        ? '今日净流入TOP5 / 净流出TOP5'
        : `${this.replayDate}净流入TOP5 / 净流出TOP5`
    },
    // 多日模式(7/15/30天)榜单:窗口累计净流入TOP5 + 净流出TOP5,
    // 卡片结构/着色变量与当天模式 replayTop10Sectors 完全同款。
    accumulatedTop10Sectors() {
      if (this.selectedTimeRange === 'today') return []
      const items = this.accumulatedData.filter(item => item && item.name)
      const netValue = item => Number(item.total_net_flow ?? item.net_flow ?? item.flow ?? 0) || 0

      const grouped = items.reduce((groups, item) => {
        const group = item.flow_group || (netValue(item) < 0 ? 'net_out' : 'net_in')
        ;(group === 'net_out' ? groups.out : groups.in).push(item)
        return groups
      }, { in: [], out: [] })

      const inflowItems = grouped.in
        .sort((a, b) => netValue(b) - netValue(a))
        .slice(0, 5)
      const outflowItems = grouped.out
        .sort((a, b) => netValue(a) - netValue(b))
        .slice(0, 5)
      const maxInflow = Math.max(...inflowItems.map(item => Math.abs(netValue(item))), 1)
      const maxOutflow = Math.max(...outflowItems.map(item => Math.abs(netValue(item))), 1)
      const rankGroup = (list, direction, maxValue) => list.map((item, index) => {
        const strength = Math.max(0.2, Math.min(1, Math.abs(netValue(item)) / maxValue))
        return {
          ...item,
          rank: index + 1,
          flow_direction: direction,
          flow_strength: strength,
          flow_alpha: (0.18 + strength * 0.5).toFixed(3),
          flow_deep_alpha: (0.22 + strength * 0.55).toFixed(3),
          flow_border_alpha: (0.28 + strength * 0.6).toFixed(3)
        }
      })

      return [
        ...rankGroup(inflowItems, 'in', maxInflow),
        ...rankGroup(outflowItems, 'out', maxOutflow)
      ]
    },
    accumulatedTitle() {
      if (this.selectedTimeRange === 'today') return ''
      return `近${this.selectedTimeRange}天累计净流入TOP5 / 净流出TOP5`
    },
    renderedAIAnalysis() {
      if (!this.aiAnalysisResult) return ''
      return marked.parse(this.aiAnalysisResult)
    }
  },
  async mounted() {
    window.addEventListener('auth-required', this.onAuthRequired)
    window.addEventListener('auth-login-success', this.onAuthLogin)
    window.addEventListener('auth-logout', this.onAuthLogout)

    this.initChart()
    window.addEventListener('resize', this.handleResize)
    this.$nextTick(() => {
      this.updateLayoutHeight()
    })

    // 先检查登录态：未登录则不发起数据请求（避免一进首页就触发 401 弹框）
    try {
      const session = await getAuthSession()
      this.isAdmin = !!(session && session.is_admin)
      if (session && session.authenticated) {
        this.needsAuth = false
        this.bootstrapData()
      } else {
        this.needsAuth = true
      }
    } catch (e) {
      this.needsAuth = true
    }
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.handleResize)
    window.removeEventListener('auth-required', this.onAuthRequired)
    window.removeEventListener('auth-login-success', this.onAuthLogin)
    window.removeEventListener('auth-logout', this.onAuthLogout)
    if (this.chartInstance) {
      this.chartInstance.dispose()
      this.chartInstance = null
    }
    if (this.fullscreenChart) {
      try { this.fullscreenChart.dispose() } catch (e) { /* noop */ }
      this.fullscreenChart = null
    }
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval)
    }
    if (this.newsRotationInterval) {
      clearInterval(this.newsRotationInterval)
    }
    if (this.newsScrollInterval) {
      clearInterval(this.newsScrollInterval)
    }
    if (this.anomalyWatchInterval) {
      clearInterval(this.anomalyWatchInterval)
    }
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval)
    }
    if (this.replayTimer) {
      clearInterval(this.replayTimer)
    }
    if (this.autoGrowTimer) {
      clearInterval(this.autoGrowTimer)
    }
    if (this.multiDayTimer) {
      clearInterval(this.multiDayTimer)
    }
    if (this.marketSummaryInterval) {
      clearInterval(this.marketSummaryInterval)
    }
    if (this.aiChainInterval) {
      clearTimeout(this.aiChainInterval)
    }
    if (this.aiAnalysisPollTimer) {
      clearInterval(this.aiAnalysisPollTimer)
    }
  },
  methods: {
    // 登录态变化回调
    onAuthRequired() {
      this.needsAuth = true
      this.isAdmin = false
      this.loading = false
    },
    onAuthLogin() {
      // 登录成功后刷新 admin 标志（vk 登录才显示体验码菜单）
      this.refreshIsAdmin()
      if (this.needsAuth) {
        this.needsAuth = false
        this.error = null
        this.bootstrapData()
      }
      // 登录后监控卡/新闻条会出现，需重新计算图表高度，避免布局错乱
      this.$nextTick(() => this.updateLayoutHeight())
    },
    async refreshIsAdmin() {
      try {
        const session = await getAuthSession()
        this.isAdmin = !!(session && session.is_admin)
      } catch (e) {
        this.isAdmin = false
      }
    },
    onAuthLogout() {
      this.needsAuth = true
      this.isAdmin = false
      // 清空已有数据，回到登录提示态
      this.currentData = []
      this.accumulatedData = []
      this.historyData = {}
      this.minuteData = {}
      this.latestNews = []
      this.marketSummary = null
      this.marketSummaryError = null
      if (this.chartInstance) {
        this.chartInstance.clear()
      }
      // 登出后监控卡/新闻条会消失，重新计算图表高度
      this.$nextTick(() => this.updateLayoutHeight())
    },
    // 已登录后拉取首页全部数据（从原 mounted 拆出）
    bootstrapData() {
      this.fetchDataByTimeRange()
      this.startCountdown()
      this.fetchLatestNews()
      this.startNewsRotation()
      this.startAnomalyWatch()
      this.fetchHealthStatus()
      this.fetchMarketSummary()
      this.startMarketSummaryRefresh()
      this.fetchAiChain()
      this.startAiChainRefresh()
      this.checkAIAnalysisStatus()
    },
    // 点击数据相关按钮时，如未登录则唤起登录框
    requireAuthOrPrompt() {
      if (this.needsAuth) {
        window.dispatchEvent(new CustomEvent('auth-request-login'))
        return true
      }
      return false
    },
    formatMarketAmount(value, showSign = true) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '--'
      const amount = Number(value)
      const sign = showSign ? (amount > 0 ? '+' : amount < 0 ? '-' : '') : ''
      const absAmount = Math.abs(amount)
      if (absAmount >= 1000000000000) {
        return `${sign}${(absAmount / 1000000000000).toFixed(2)}万亿`
      }
      if (absAmount >= 100000000) {
        return `${sign}${(absAmount / 100000000).toFixed(0)}亿`
      }
      return `${sign}${absAmount.toFixed(0)}`
    },

    formatMarketNumber(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '--'
      return Number(value).toLocaleString('zh-CN', {
        maximumFractionDigits: 2
      })
    },

    formatMarketPercent(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '--'
      const percent = Number(value) * 100
      return `${percent > 0 ? '+' : ''}${percent.toFixed(2)}%`
    },

    formatMarketSignedNumber(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '--'
      const number = Number(value)
      return `${number > 0 ? '+' : ''}${number.toFixed(2)}`
    },

    getBreadthPercent(type) {
      const upCount = Number(this.marketSummary?.breadth?.up_count) || 0
      const downCount = Number(this.marketSummary?.breadth?.down_count) || 0
      const total = upCount + downCount
      if (total <= 0) return type === 'up' ? '50%' : '50%'

      const value = type === 'up' ? upCount : downCount
      return `${Math.max(8, Math.min(92, (value / total) * 100))}%`
    },

    formatTurnoverCompare(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return '较上日 --'
      }
      const amount = Number(value)
      if (amount > 0) {
        return `较上日增加${this.formatMarketAmount(amount, false)}`
      }
      if (amount < 0) {
        return `较上日减少${this.formatMarketAmount(amount, false)}`
      }
      return '较上日持平'
    },

    getValueTrendClass(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return ''
      const number = Number(value)
      if (number > 0) return 'market-up'
      if (number < 0) return 'market-down'
      return ''
    },

    async fetchMarketSummary() {
      // market-summary 单独请求(同花顺/东财,快),绝不被 KOSPI/融资余额等慢接口拖慢
      try {
        const response = await getMarketSummary()
        if (response.success) {
          this.marketSummary = response.data
          this.marketSummaryError = null
        } else {
          this.marketSummaryError = response.message || '获取大盘摘要失败'
        }
      } catch (err) {
        console.error('获取大盘摘要失败:', err)
        this.marketSummaryError = err.message
      }
      // KOSPI / 融资余额独立异步获取(各自可能慢或失败,不阻塞 market-summary,互不影响)
      this.fetchKospi()
      this.fetchMarginTotal()
    },
    async fetchKospi() {
      try {
        const resp = await getGlobalIndices()
        const kospi = resp?.data?.['100.KS11'] || resp?.['100.KS11']
        this.kospiIndex = (kospi && kospi.price != null)
          ? { price: kospi.price, change: kospi.change, name: kospi.name || '韩国KOSPI' }
          : null
      } catch (e) {
        this.kospiIndex = null
      }
    },
    async fetchMarginTotal() {
      try {
        const resp = await getMarketMarginTotal()
        const md = resp?.data
        this.marginTotal = (md && md.latest_total != null) ? md : null
      } catch (e) {
        this.marginTotal = null
      }
    },

    formatMarginDate(d) {
      const s = String(d || '')
      return s.length === 8 ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}` : s
    },

    getMarketSummaryRefreshDelay() {
      const now = new Date()
      const hour = now.getHours()
      const minute = now.getMinutes()
      const inTradingTime = isTradingDay(now) && (
        (hour === 9 && minute >= 30) ||
        (hour >= 10 && hour < 11) ||
        (hour === 11 && minute <= 30) ||
        (hour >= 13 && hour < 15) ||
        (hour === 15 && minute === 0)
      )
      return inTradingTime ? 15000 : 60000
    },

    startMarketSummaryRefresh() {
      const scheduleNextRefresh = () => {
        this.marketSummaryInterval = setTimeout(async () => {
          await this.fetchMarketSummary()
          scheduleNextRefresh()
        }, this.getMarketSummaryRefreshDelay())
      }
      scheduleNextRefresh()
    },

    async fetchAiChain() {
      try {
        const response = await getAiChain()
        if (response.success) {
          this.aiChainSummary = response.data?.summary || null
        }
      } catch (err) {
        console.error('获取AI产业链指标失败:', err)
      }
    },

    startAiChainRefresh() {
      const scheduleNext = () => {
        // 外部指标无需高频，且避免东财反爬：固定60s
        this.aiChainInterval = setTimeout(async () => {
          await this.fetchAiChain()
          scheduleNext()
        }, 60000)
      }
      scheduleNext()
    },

    openMarginTotalModal() {
      this.marginTotalModalOpen = true
      this.$nextTick(() => this.renderMarginTotalChart())
    },
    closeMarginTotalModal() {
      this.marginTotalModalOpen = false
      if (this.marginTotalChart) {
        try { this.marginTotalChart.dispose() } catch (e) { /* ignore */ }
        this.marginTotalChart = null
      }
    },
    renderMarginTotalChart() {
      if (!this.$refs.marginTotalChartEl || !this.marginTotal || !this.marginTotal.history) return
      if (!this.marginTotalChart) {
        this.marginTotalChart = echarts.init(this.$refs.marginTotalChartEl, null, { renderer: 'canvas' })
      }
      const history = this.marginTotal.history
      const toYi = (v) => (v == null ? 0 : v / 1e8)
      const fmtDate = (d) => {
        const s = String(d || '')
        return s.length === 8 ? s.slice(4, 6) + '-' + s.slice(6, 8) : s
      }
      this.marginTotalChart.setOption({
        backgroundColor: 'transparent',
        grid: { left: 55, right: 20, top: 20, bottom: 30 },
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'line' },
          appendTo: document.body,
          formatter: (params) => {
            const p = params[0]
            if (!p) return ''
            const orig = history[p.dataIndex] ? String(history[p.dataIndex].date) : ''
            const full = orig.length === 8 ? orig.slice(0,4)+'-'+orig.slice(4,6)+'-'+orig.slice(6,8) : (p.axisValue || '')
            const yi = p.value == null ? '--' : (p.value / 1e8).toFixed(2)
            return `${full}<br/>融资余额: <b>${yi}</b> 亿`
          }
        },
        xAxis: { type: 'category', data: history.map(h => fmtDate(h.date)), axisLabel: { color: '#9aa3b2' } },
        yAxis: {
          type: 'value', scale: true,
          axisLabel: { color: '#9aa3b2', formatter: (v) => toYi(v).toFixed(0) + '亿' },
          splitLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } }
        },
        series: [{
          type: 'line', smooth: true, symbol: 'none',
          data: history.map(h => h.total),
          lineStyle: { color: '#4f9dff', width: 2 },
          areaStyle: { color: 'rgba(79,157,255,0.12)' }
        }]
      })
    },

    initChart() {
      if (this.chartInstance) {
        return
      }
      
      this.$nextTick(() => {
        try {
          this.chartInstance = echarts.init(this.$refs.chart, null, {
            renderer: 'canvas'
          })
          this.updateLayoutHeight()
          if (this.currentData.length > 0 || Object.keys(this.minuteData).length > 0 || Object.keys(this.historyData).length > 0) {
            this.updateChart()
          }
        } catch (e) {
          console.error('echarts.init 错误:', e)
          return
        }
      })
    },

    handleResize() {
      if (this.chartInstance) {
        this.chartInstance.resize()
      }
      this.updateLayoutHeight()
      // 横屏全屏开启时，窗口/方向变化（含系统横屏生效后）要重算尺寸并重排全屏图表
      if (this.chartFullscreen && this.fullscreenChart) {
        this.landscapeSize = this.getLandscapeSize()
        this.applyLandscapeSizeToDom()
        this.$nextTick(() => {
          if (this.fullscreenChart) this.fullscreenChart.resize()
        })
      }
    },

    updateLayoutHeight() {
      const monitorCard = this.$refs.monitorCard
      const chartContainer = this.$refs.chartContainer
      const sectorList = this.$refs.sectorList
      if (!monitorCard || !chartContainer) return

      const topBlocks = [
        monitorCard,
        this.$el.querySelector('.news-ticker-container'),
        this.$el.querySelector('.market-summary-panel')
      ].filter(Boolean)
      const topBlocksBottom = Math.max(...topBlocks.map(el => el.getBoundingClientRect().bottom))
      const remainingHeight = window.innerHeight - topBlocksBottom

      const isMobile = window.innerWidth <= 768
      // 先给TOP10分配30%，再给折线图分配70%
      const chartTotalSpace = remainingHeight * 0.7

      // chart-container的height需要减去padding和border（content-box模型）
      const chartStyle = getComputedStyle(chartContainer)
      const chartPaddingY = (parseFloat(chartStyle.paddingTop) || 0) + (parseFloat(chartStyle.paddingBottom) || 0)
      const chartBorderY = (parseFloat(chartStyle.borderTopWidth) || 0) + (parseFloat(chartStyle.borderBottomWidth) || 0)

      chartContainer.style.height = isMobile
        ? '460px'
        : (chartTotalSpace - chartPaddingY - chartBorderY) + 'px'

      if (sectorList) {
        sectorList.style.height = 'auto'
        sectorList.style.overflowY = 'visible'
      }

      // 高度变化后重新调整echarts尺寸
      this.$nextTick(() => {
        if (this.chartInstance) {
          this.chartInstance.resize()
        }
      })
    },

    // ===== 折线图横屏全屏（移动端） =====
    toggleChartFullscreen() {
      if (this.chartFullscreen) {
        this.closeChartFullscreen()
      } else {
        this.openChartFullscreen()
      }
    },
    // 取横屏画布像素尺寸：视口的“长边×短边”（横屏时长边作宽、短边作高，铺满屏幕）
    getLandscapeSize() {
      const w = window.innerWidth
      const h = window.innerHeight
      const longEdge = Math.max(w, h)
      const shortEdge = Math.min(w, h)
      return { w: longEdge, h: shortEdge }
    },
    openChartFullscreen() {
      // 尝试唤起系统横屏（部分浏览器支持，失败无碍——用 CSS 旋转兜底）
      this.tryLockOrientation('landscape')
      this.landscapeSize = this.getLandscapeSize()
      this.chartFullscreen = true
      this.$nextTick(() => {
        // 先把画布撑到目标像素尺寸，再 init echarts —— 否则 echarts 读到的是
        // 旋转前的内联尺寸，渲染出的 canvas 偏小，导致“只铺了一部分”
        this.applyLandscapeSizeToDom()
        this.renderFullscreenChart()
      })
    },
    closeChartFullscreen() {
      this.tryLockOrientation('portrait')
      this.chartFullscreen = false
      if (this.fullscreenChart) {
        try { this.fullscreenChart.dispose() } catch (e) { /* noop */ }
        this.fullscreenChart = null
      }
    },
    applyLandscapeSizeToDom() {
      const el = this.$refs.chartFullscreenEl
      if (!el) return
      const { w, h } = this.landscapeSize
      if (!w || !h) return
      // 显式像素尺寸覆盖 CSS，确保 echarts.init 时容器已是横向铺满的真实大小
      el.style.width = w + 'px'
      el.style.height = h + 'px'
    },
    tryLockOrientation(orientation) {
      // 异步且尽力而为；任何错误（不支持/非 HTTPS/无权限）都静默忽略
      try {
        const lock = window.screen && window.screen.orientation && window.screen.orientation.lock
        if (lock) {
          const p = lock.call(window.screen.orientation, orientation)
          if (p && typeof p.catch === 'function') p.catch(() => {})
        }
      } catch (e) { /* noop */ }
    },
    renderFullscreenChart() {
      const el = this.$refs.chartFullscreenEl
      if (!el) return
      if (!this.chartInstance) return

      if (this.fullscreenChart) {
        try { this.fullscreenChart.dispose() } catch (e) { /* noop */ }
        this.fullscreenChart = null
      }

      try {
        this.fullscreenChart = echarts.init(el, null, { renderer: 'canvas' })
      } catch (e) {
        console.error('横屏图表初始化失败:', e)
        return
      }

      // 取当前内联图表的 option，增强可读性后应用到横屏全屏实例。
      // 注意：不能用 JSON.parse(JSON.stringify(...)) —— option 里的坐标轴 / 提示框
      // formatter 是函数，序列化会丢失，导致“X亿”格式化失效。这里只做浅拷贝并
      // 单独克隆被改写的 axis/legend/series 配置，函数引用得以保留。
      const baseOption = this.chartInstance.getOption()
      const option = { ...baseOption }
      option.xAxis = Array.isArray(baseOption.xAxis) ? baseOption.xAxis.map(a => ({ ...a })) : { ...baseOption.xAxis }
      option.yAxis = Array.isArray(baseOption.yAxis) ? baseOption.yAxis.map(a => ({ ...a })) : { ...baseOption.yAxis }
      option.legend = Array.isArray(baseOption.legend) ? baseOption.legend.map(l => ({ ...l })) : { ...baseOption.legend }
      option.series = Array.isArray(baseOption.series) ? baseOption.series.map(s => ({ ...s })) : []

      // 横屏空间更宽，放大坐标轴与末端标签字体，便于辨认行业
      this.applyLandscapeReadability(option)

      this.fullscreenChart.setOption(option, true)
      this.$nextTick(() => {
        if (this.fullscreenChart) this.fullscreenChart.resize()
      })
    },
    applyLandscapeReadability(option) {
      // 横屏空间更宽，给图例腾位置，使行业名清晰可见
      const series = Array.isArray(option.series) ? option.series : []
      const seriesNames = series.map(s => s.name).filter(Boolean)

      let legend
      if (option.legend) {
        legend = Array.isArray(option.legend) ? option.legend[0] : option.legend
      } else if (seriesNames.length) {
        // 今日实时图原本没有图例（移动端靠 endLabel 标注）——横屏全屏补一个图例
        legend = { type: 'plain' }
        option.legend = legend
      }
      if (legend) {
        legend.show = true
        legend.top = 4
        legend.type = legend.type || 'scroll'
        legend.textStyle = { ...(legend.textStyle || {}), fontSize: 13, color: '#cbd5e1' }
        if (seriesNames.length) legend.data = seriesNames
      }

      // 末端标签 / 坐标轴字号放大
      series.forEach((s) => {
        if (s.endLabel) {
          s.endLabel.show = true
          s.endLabel.fontSize = 13
        }
      })
      // 横屏顶部留出图例空间，避免遮挡曲线
      const bumpGrid = (g) => {
        if (!g) return
        if (typeof g.top === 'number') g.top = Math.max(g.top, 34)
        else if (g.top === undefined || g.top === '') g.top = 34
      }
      if (option.grid) {
        const grids = Array.isArray(option.grid) ? option.grid : [option.grid]
        grids.forEach(bumpGrid)
      }
      const bumpAxis = (axis) => {
        if (!axis) return
        axis.axisLabel = axis.axisLabel || {}
        axis.axisLabel.fontSize = 12
      }
      bumpAxis(Array.isArray(option.xAxis) ? option.xAxis[0] : option.xAxis)
      bumpAxis(Array.isArray(option.yAxis) ? option.yAxis[0] : option.yAxis)
    },

    highlightSector(sectorName) {
      if (!this.chartInstance) return
      
      const option = this.chartInstance.getOption()
      if (!option || !option.series) return
      
      const seriesNames = option.series.map(s => s.name)
      if (!seriesNames.includes(sectorName)) return
      
      this.chartInstance.dispatchAction({
        type: 'highlight',
        seriesName: sectorName
      })
      
      option.series.forEach((series) => {
        if (series.name && series.name !== sectorName) {
          this.chartInstance.dispatchAction({
            type: 'downplay',
            seriesName: series.name
          })
        }
      })
    },

    unhighlightSector() {
      if (!this.chartInstance) return
      
      try {
        this.chartInstance.dispatchAction({
          type: 'downplay'
        })
      } catch (e) {
        console.warn('unhighlightSector error:', e)
      }
    },

    async fetchCurrentData(options = {}) {
      const { skipMinuteData = false } = options

      if (this.isReplayingToday) return

      // 非交易日：先展示当天（空数据），再自动跳转到最近周五
      if (!isTradingDay(new Date())) {
        // 先设置为今天日期（展示空数据状态）
        this.replayDate = formatDate(new Date())
        this.minuteData = {}
        this.currentData = []
        this.lastUpdate = this.replayDate
        this.updateChart()
        // 自动模拟点击最近周五，加载周五数据
        this.replayDate = getLatestWeekday(new Date())
        await this.loadReplayDateData()
        const timeKeys = Object.keys(this.minuteData).sort()
        if (timeKeys.length > 0) {
          const lastKey = timeKeys[timeKeys.length - 1]
          this.currentData = this.minuteData[lastKey]?.data || []
        }
        this.lastUpdate = this.replayDate
        return
      }

      try {
        const response = await getCurrentFlow()
        
        if (response.success) {
          this.currentData = response.data
          const timestamp = new Date(response.timestamp)
          this.lastUpdate = timestamp.toLocaleString('zh-CN')
          
          if (this.selectedTimeRange === 'today') {
            if (skipMinuteData) {
              this.updateChart()
            } else {
              await this.fetchMinuteData()
            }
          } else {
            this.updateChart()
          }
        }
      } catch (err) {
        console.error('获取当前数据失败:', err)
        this.error = '获取当前数据失败: ' + err.message
      }
    },

    async fetchHistoryData(days) {
      try {
        const response = await getHistoryData(days)
        if (response.success) {
          this.historyData = response.data

          const dates = Object.keys(this.historyData).sort()
          if (dates.length > 0) {
            const latestDate = dates[dates.length - 1]
            this.currentData = this.historyData[latestDate] || []
          }

          // 逐日生长动画(与当天 autoGrow 同款);日期不足2天则直接整图渲染
          this.startMultiDayGrow()
        }
      } catch (err) {
        this.error = '获取历史数据失败: ' + err.message
      }
    },

    async fetchMinuteData() {
      if (this.isReplayingToday) return

      try {
        const response = await getMinuteData(24)
        if (response.success) {
          const newTimeKeys = Object.keys(response.data).sort()
          const oldTimeKeys = this.lastTimeKeys
          
          this.minuteData = response.data
          
          if (this.isReplayingToday) {
            this.stopTodayReplay(false)
          }
          
          if (oldTimeKeys.length === 0) {
            this.lastTimeKeys = newTimeKeys
            this.updateChart()
            return
          }
          
          const newKeys = newTimeKeys.filter(key => !oldTimeKeys.includes(key))
          
          if (newKeys.length === 0) {
            this.updateChart()
            return
          }
          
          this.lastTimeKeys = newTimeKeys
          
          if (this.autoGrowTimer) {
            clearInterval(this.autoGrowTimer)
            this.autoGrowTimer = null
          }
          
          const startIndex = newTimeKeys.indexOf(oldTimeKeys[oldTimeKeys.length - 1])
          this.autoGrowCursor = startIndex >= 0 ? startIndex : newTimeKeys.length - 1
          
          this.autoGrowTimer = setInterval(() => {
            if (this.autoGrowCursor === null) {
              this.autoGrowCursor = 0
            }
            
            if (this.autoGrowCursor >= newTimeKeys.length - 1) {
              clearInterval(this.autoGrowTimer)
              this.autoGrowTimer = null
              this.autoGrowCursor = null
              return
            }
            
            this.autoGrowCursor += 1
            this.updateChart()
          }, this.autoGrowSpeed)
        }
      } catch (err) {
        console.error('获取分钟数据失败:', err)
        this.error = '获取分钟数据失败: ' + err.message
      }
    },

    async fetchDataByTimeRange() {
      // 未登录时不发起数据请求，直接唤起登录框（满足"所有按钮未登录都先登录"）
      if (this.requireAuthOrPrompt()) return
      await this.fetchHealthStatus()
      
      this.loading = true
      this.error = null
      
      if (this.autoGrowTimer) {
        clearInterval(this.autoGrowTimer)
        this.autoGrowTimer = null
        this.autoGrowCursor = null
      }
      this.stopMultiDayGrow()

      if (this.selectedTimeRange !== 'today') {
        this.stopTodayReplay(false)
        this.replayCursor = null
        this.replayTopSectors = []
      }
      try {
        if (this.selectedTimeRange === 'today') {
          this.accumulatedData = []
          if (!this.hasBootstrappedTodayReplay && isTradingDay(new Date())) {
            this.hasBootstrappedTodayReplay = true
            this.replayDate = '2099-12-31'
            await this.$nextTick()
            await this.fetchCurrentData({ skipMinuteData: true })
            this.replayDate = this.todayDate
            await this.$nextTick()
            await this.onReplayDateChange()
          } else {
            await this.fetchCurrentData()
          }
        } else {
          this.currentData = []
          await this.fetchAccumulatedData(this.selectedTimeRange)
          await this.fetchHistoryData(this.selectedTimeRange)
        }
      } catch (err) {
        console.error('获取数据失败:', err)
        this.error = '获取数据失败: ' + err.message
      } finally {
        this.loading = false
        this.$nextTick(() => {
          this.updateLayoutHeight()
        })
      }
    },

    async fetchData() {
      if (this.isReplayingToday) {
        this.countdown = 300
        return
      }

      await this.fetchHealthStatus()
      
      this.loading = true
      this.error = null
      try {
        if (this.selectedTimeRange === 'today') {
          await this.fetchCurrentData()
        } else {
          await this.fetchAccumulatedData(this.selectedTimeRange)
          await this.fetchHistoryData(this.selectedTimeRange)
        }
      } catch (err) {
        console.error('获取数据失败:', err)
        this.error = '获取数据失败: ' + err.message
      } finally {
        this.loading = false
      }
    },

    async fetchAccumulatedData(days) {
      try {
        const response = await getAccumulatedFlow(days)
        if (response.success) {
          this.accumulatedData = response.data
        }
      } catch (err) {
        console.error('获取累计流入数据失败:', err)
        this.error = '获取累计流入数据失败: ' + err.message
      }
    },

    retry() {
      this.error = null
      this.loading = true
      this.fetchDataByTimeRange()
    },

    startCountdown() {
      this.countdownInterval = setInterval(() => {
        if (this.isReplayingToday) {
          this.countdown = 300
          return
        }

        if (!isTradingDay(new Date())) {
          this.countdown = 300
          return
        }

        if (this.countdown > 0) {
          this.countdown--
        } else {
          window.location.reload()
        }
      }, 1000)
    },

    updateChart() {
      if (!this.chartInstance) {
        this.initChart()
        return
      }

      if (this.selectedTimeRange === 'today') {
        if (this.replayDate === this.todayDate && !this.isReplayingToday) {
          this.replayTopSectors = []
        }

        const allTimeKeys = Object.keys(this.minuteData).sort()
        // 过滤掉非5分钟间隔的异常时间点
        const timeData = allTimeKeys.filter(key => {
          const parts = key.split(':')
          if (parts.length !== 2) return false
          const minute = parseInt(parts[1], 10)
          return minute % 5 === 0
        })
        
        let cursor = null
        if (this.isReplayingToday) {
          cursor = this.replayCursor
        } else if (this.autoGrowCursor !== null) {
          cursor = this.autoGrowCursor
        }

        // 非今天或非交易日时当作回放模式
        const isReplayMode = this.replayDate !== this.todayDate || !isTradingDay(new Date())
        const fixedTopSectors = (isReplayMode || this.isReplayingToday) && this.replayTopSectors.length > 0
          ? this.replayTopSectors
          : null

        const option = generateLiveReplayChartOption(
          timeData,
          this.minuteData,
          this.colors,
          cursor,
          10,
          fixedTopSectors,
          isReplayMode
        )

        try {
          this.chartInstance.setOption(option, {
            replaceMerge: ['series', 'legend', 'xAxis', 'yAxis', 'tooltip'],
            lazyUpdate: true
          })
        } catch (e) {
          console.error('setOption 失败:', e)
        }
        return
      }

      // 多日累计模式(7/15/30天):2026-09-08 起与当天模式共用同一图表实现
      // (断轴/末端标签/十字光标/移动端适配全部同款),曲线值取窗口累计净流入
      // (cum_net_flow),支持逐日生长动画(multiDayCursor)。替换掉原先独立的
      // generateChartOption 路径——该路径在负值场景下渲染异常(坐标轴消失)。
      const timeData = Object.keys(this.historyData).sort()
      const fixedTopSectors = this.accumulatedTop10Sectors.map(s => s.name)

      const option = generateLiveReplayChartOption(
        timeData,
        this.historyData,
        this.colors,
        this.multiDayCursor,
        10,
        fixedTopSectors.length > 0 ? fixedTopSectors : null,
        false,
        // 生长动画进行中(multiDayCursor !== null)禁用 echarts 动画:
        // 每 tick 瞬间渲染当前前缀,否则入场动画反复被打断重播,像"抽搐"
        { valueMode: 'cum', animate: this.multiDayCursor === null }
      )

      try {
        this.chartInstance.setOption(option, {
          replaceMerge: ['series', 'legend', 'xAxis', 'yAxis', 'tooltip'],
          lazyUpdate: true
        })
      } catch (e) {
        console.error('setOption 失败:', e)
      }
    },

    // 多日模式逐日生长动画:切到 7/15/30 天后曲线按日期一天天长出来,
    // 与当天模式的 autoGrow 同款体验、同款速度。
    startMultiDayGrow() {
      this.stopMultiDayGrow()
      const dates = Object.keys(this.historyData).sort()
      if (dates.length <= 1) {
        this.updateChart()
        return
      }
      this.multiDayCursor = 0
      this.updateChart()   // 先渲染第1天,此后每个 tick 增加一天(原实现首帧直接跳到第2天)
      this.multiDayTimer = setInterval(() => {
        if (this.multiDayCursor === null) {
          this.multiDayCursor = 0
          return
        }
        if (this.multiDayCursor >= Object.keys(this.historyData).length - 1) {
          clearInterval(this.multiDayTimer)
          this.multiDayTimer = null
          this.multiDayCursor = null
          return
        }
        this.multiDayCursor += 1
        this.updateChart()
      }, this.autoGrowSpeed)
    },

    stopMultiDayGrow() {
      if (this.multiDayTimer) {
        clearInterval(this.multiDayTimer)
        this.multiDayTimer = null
      }
      this.multiDayCursor = null
    },

    async startTodayReplay() {
      if (!this.hasReplayData) return

      if (this.replayDate !== this.todayDate && !this.historicalMinuteData) {
        try {
          await this.loadHistoricalDataForReplay()
        } catch (error) {
          console.error('无法加载历史数据，回放取消')
          return
        }
      }

      const timeKeys = Object.keys(this.minuteData).sort()
      this.replayTopSectors = buildReplaySectorOrder(timeKeys, this.minuteData, 10)

      if (this.replayTimer) {
        clearInterval(this.replayTimer)
        this.replayTimer = null
      }

      if (this.autoGrowTimer) {
        clearInterval(this.autoGrowTimer)
        this.autoGrowTimer = null
        this.autoGrowCursor = null
      }

      this.isReplayingToday = true
      this.replayCursor = timeKeys.length - 1
      
      this.updateChart()

      const replayDuration = Math.max(8000, timeKeys.length * 200)
      
      this.replayTimer = setTimeout(() => {
        this.replayTimer = null
        this.stopTodayReplay(true)
      }, replayDuration)
    },

    stopTodayReplay(resetToLive = false) {
      if (this.replayTimer) {
        clearTimeout(this.replayTimer)
        this.replayTimer = null
      }

      this.isReplayingToday = false

      if (resetToLive) {
        this.replayCursor = null
        this.replayTopSectors = []
        this.updateChart()
        if (this.chartInstance) {
          this.chartInstance.dispatchAction({
            type: 'hideTip'
          })
        }
      }
    },

    onReplayDateChange() {
      // 未登录时不加载回放数据，唤起登录框
      if (this.requireAuthOrPrompt()) return
      // 如果选择的是非交易日（周末），自动跳转到对应的周五
      if (!isTradingDay(this.replayDate)) {
        this.replayDate = getLatestWeekday(this.replayDate)
      }
      return this.loadReplayDateData()
    },

    async loadReplayDateData() {
      if (this.isReplayingToday) {
        this.stopTodayReplay(false)
      }

      if (this.autoGrowTimer) {
        clearInterval(this.autoGrowTimer)
        this.autoGrowTimer = null
        this.autoGrowCursor = null
      }

      // 今天是交易日且选的是今天：用实时分钟数据
      if (this.replayDate === this.todayDate && isTradingDay(new Date())) {
        this.historicalMinuteData = null
        this.lastTimeKeys = []
        await this.fetchMinuteData()
        return
      }

      // 非交易日或选了历史日期：用 minute-by-date 接口
      this.historicalMinuteData = null
      this.minuteData = {}
      this.lastTimeKeys = []
      
      try {
        await this.loadHistoricalDataForReplay()
        this.updateChart()
      } catch (error) {
        console.error('加载历史数据失败:', error)
        this.updateChart()
      }
    },

    async loadHistoricalDataForReplay() {
      if (this.replayDate === this.todayDate && isTradingDay(new Date())) {
        return
      }

      try {
        const response = await getMinuteDataByDate(this.replayDate)
        if (response.success) {
          this.historicalMinuteData = response.data
          this.minuteData = response.data
          this.lastTimeKeys = Object.keys(response.data).sort()
        } else {
          console.error('加载历史数据失败:', response.message)
          this.historicalMinuteData = null
          throw new Error(response.message)
        }
      } catch (error) {
        console.error('加载历史数据失败:', error)
        this.historicalMinuteData = null
        throw error
      }
    },

    getTopSectors(timeData, allData, isToday) {
      if (isToday) {
        const sectorFlows = {}
        
        timeData.forEach(timeKey => {
          const data = allData[timeKey]?.data || []
          data.forEach(item => {
            if (!sectorFlows[item.name]) {
              sectorFlows[item.name] = []
            }
            if (item.flow !== null && item.flow !== undefined) {
              sectorFlows[item.name].push(item.flow)
            }
          })
        })

        const avgFlows = Object.entries(sectorFlows).map(([name, flows]) => {
          if (flows.length === 0) return { name, avgFlow: 0 }
          const avg = flows.reduce((a, b) => a + b, 0) / flows.length
          return { name, avgFlow: avg }
        })

        avgFlows.sort((a, b) => b.avgFlow - a.avgFlow)
        
        return avgFlows.slice(0, 10).map(s => s.name)
      } else {
        const sectorStats = {}
        
        timeData.forEach(timeKey => {
          const data = allData[timeKey]?.data || allData[timeKey] || []
          data.forEach(item => {
            if (!sectorStats[item.name]) {
              sectorStats[item.name] = {
                totalFlow: 0,
                appearances: 0
              }
            }
            if (item.total_flow !== undefined) {
              sectorStats[item.name].totalFlow = item.total_flow
            }
            if (item.appearances !== undefined) {
              sectorStats[item.name].appearances = item.appearances
            }
          })
        })

        const sortedSectors = Object.entries(sectorStats)
          .map(([name, stats]) => ({ name, totalFlow: stats.totalFlow }))
          .sort((a, b) => b.totalFlow - a.totalFlow)
        
        return sortedSectors.slice(0, 15).map(s => s.name)
      }
    },

    formatFlow(value) {
      return formatFlow(value)
    },

    formatNetFlow(value) {
      return formatNetFlow(value)
    },

    async fetchLatestNews() {
      try {
        const response = await getNews(1, 5)
        if (response.success) {
          const newNews = response.data
          
          // 桌面通知改由全局 notificationManager 统一负责（任意页面都提醒），这里只更新首页滚动条展示
          const previousFirstId = this.latestNews.length > 0 ? this.latestNews[0].id : null
          this.latestNews = newNews
          this.latestNewsCount = response.pagination?.total || 0
          
          if (newNews.length > 0) {
            this.lastNewsId = newNews[0].id
            if (previousFirstId !== newNews[0].id) {
              this.currentNewsIndex = 0
            }
          }
        }
      } catch (err) {
        console.error('获取最新新闻失败:', err)
      }
    },

    startNewsRotation() {
      this.newsScrollInterval = setInterval(() => {
        if (this.latestNews.length > 0) {
          this.currentNewsIndex = (this.currentNewsIndex + 1) % Math.min(this.latestNews.length, 5)
        }
      }, 4000)
      
      this.newsRotationInterval = setInterval(() => {
        this.fetchLatestNews()
      }, 30000)
    },

    goToNews() {
      this.$router.push('/news')
    },

    goToConfig() {
      this.$router.push('/config')
    },

    goToLogs() {
      this.$router.push('/logs')
    },

    goToHouseKline() {
      this.$router.push('/house-kline')
    },

    goToIndustryCycle() {
      this.$router.push('/industry-cycle')
    },

    openQuantSystem() {
      const baseUrl = window.location.origin
      // 携带 tz_gate 特征：StockRank nginx 据此放行并下发 cookie，直接复制裸 URL 访问会被踢回首页
      const quantUrl = `${baseUrl}/TrendZen/?tz_gate=vK-TzGate-9f2c7a1e`
      window.open(quantUrl, '_blank')
    },

    openDapanYuntu() {
      window.open('https://dapanyuntu.com/', '_blank')
    },

    goToMarketMap() {
      this.$router.push('/market-map')
    },

    goToGlobalMarket() {
      this.$router.push('/global-market')
    },

    // 唤起登录框（Root.vue 监听 auth-request-login）
    promptLogin() {
      window.dispatchEvent(new CustomEvent('auth-request-login'))
    },

    // 未登录时拦截的数据相关操作包装：未登录则弹登录框，已登录透传到原方法
    guardedGoToConfig() { if (this.requireAuthOrPrompt()) return; this.goToConfig() },
    guardedGoToLogs() { if (this.requireAuthOrPrompt()) return; this.goToLogs() },
    guardedGoToHouseKline() { if (this.requireAuthOrPrompt()) return; this.goToHouseKline() },
    guardedGoToIndustryCycle() { if (this.requireAuthOrPrompt()) return; this.goToIndustryCycle() },
    guardedGoToRedeemCode() { if (this.requireAuthOrPrompt()) return; this.$router.push('/redeem-code') },
    guardedGoToMpAdmin() { if (this.requireAuthOrPrompt()) return; this.$router.push('/mp-admin') },
    guardedGotoMarketMap() { if (this.requireAuthOrPrompt()) return; this.goToMarketMap() },
    guardedGotoFlowAlert() { if (this.requireAuthOrPrompt()) return; this.$router.push('/flow-alert') },
    guardedGotoGlobalMarket() { if (this.requireAuthOrPrompt()) return; this.goToGlobalMarket() },
    guardedGotoAiChain() { if (this.requireAuthOrPrompt()) return; this.$router.push('/ai-chain') },
    guardedGotoIntradayTimeline() { if (this.requireAuthOrPrompt()) return; this.goToIntradayTimeline() },
    guardedOpenQuantSystem() { if (this.requireAuthOrPrompt()) return; this.openQuantSystem() },
    async guardedAnalyzeDailyFlow() { if (this.requireAuthOrPrompt()) return; this.analyzeDailyFlow() },

    async openStockModal(sector) {
      let sectorUrl = sector.sector_url
      
      if (!sectorUrl) {
        const timeKeys = Object.keys(this.minuteData).sort()
        if (timeKeys.length > 0) {
          const latestTimeKey = timeKeys[timeKeys.length - 1]
          const latestData = this.minuteData[latestTimeKey]?.data || []
          const sectorData = latestData.find(s => s.name === sector.name)
          if (sectorData && sectorData.sector_url) {
            sectorUrl = sectorData.sector_url
          }
        }
      }
      
      if (!sectorUrl) {
        alert('该板块暂无个股详情链接')
        return
      }
      
      this.showStockModal = true
      this.selectedSector = { ...sector, sector_url: sectorUrl }
      this.loadingStocks = true
      this.stocksError = null
      this.sectorStocks = []

      // 前端缓存：同一板块 5 分钟内秒开（配合后端缓存，重复点击即时响应）
      if (!this._sectorStocksCache) this._sectorStocksCache = {}
      const _cachedStocks = this._sectorStocksCache[sectorUrl]
      if (_cachedStocks && Date.now() - _cachedStocks.t < 300000) {
        this.sectorStocks = _cachedStocks.data
        this.sortStocks()
        this.loadingStocks = false
        return
      }

      try {
        const response = await getSectorStocks(sectorUrl)
        
        if (response.success) {
          this.sectorStocks = response.data
          this.sortStocks()
          if (!this._sectorStocksCache) this._sectorStocksCache = {}
          this._sectorStocksCache[sectorUrl] = { t: Date.now(), data: response.data }
        } else {
          this.stocksError = response.message || '获取个股数据失败'
        }
      } catch (err) {
        console.error('获取个股数据失败:', err)
        this.stocksError = '获取个股数据失败: ' + err.message
      } finally {
        this.loadingStocks = false
      }
    },

    closeStockModal() {
      this.showStockModal = false
      this.selectedSector = null
      this.sectorStocks = []
      this.stocksError = null
    },

    openXueqiuStock(code) {
      let prefix = code.startsWith('6') ? 'SH' : 'SZ'
      let url = `https://xueqiu.com/S/${prefix}${code}`
      window.open(url, '_blank')
    },

    sortStocks() {
      if (!this.sectorStocks || this.sectorStocks.length === 0) return
      
      const sorted = [...this.sectorStocks].sort((a, b) => {
        let valueA = a[this.stockSortField]
        let valueB = b[this.stockSortField]
        
        if (typeof valueA === 'string') {
          valueA = parseFloat(valueA.replace(/[^\d.-]/g, '')) || 0
          valueB = parseFloat(valueB.replace(/[^\d.-]/g, '')) || 0
        }
        
        if (this.stockSortOrder === 'desc') {
          return valueB - valueA
        } else {
          return valueA - valueB
        }
      })
      
      this.sectorStocks = sorted
    },

    toggleSort(field) {
      if (this.stockSortField === field) {
        this.stockSortOrder = this.stockSortOrder === 'desc' ? 'asc' : 'desc'
      } else {
        this.stockSortField = field
        this.stockSortOrder = 'desc'
      }
      this.sortStocks()
    },

    // ===== 资金异动未读红点轮询（桌面通知已交由全局 notificationManager 统一负责）=====
    startAnomalyWatch() {
      this.fetchAnomalyForNotify(true)   // 首次只记录基线，不弹窗
      this.anomalyWatchInterval = setInterval(() => {
        this.fetchAnomalyForNotify(false)
      }, 60000)
    },

    async fetchAnomalyForNotify(isInitial) {
      try {
        const res = await getAnomalyAlerts()
        if (!res.success || !res.data) return
        const alerts = res.data                 // 已按 timestamp 倒序
        if (!alerts.length) return
        const newest = alerts[0].timestamp || ''
        // 首次只记录基线（当前最新一条的 timestamp），不弹窗，避免启动时刷屏
        if (isInitial) {
          this.lastAnomalyTimestamp = newest
          return
        }
        // 用单调递增的 timestamp 水位判新：后端每 5 分钟一批，同一批记录共用一个
        // timestamp（now 一次性生成），只有跨批次的新推送 timestamp 才更大。
        // 这样即便旧记录仍被后端返回（最近 200 条），也不会被重复当成新异动弹窗。
        if (!newest || newest <= this.lastAnomalyTimestamp) return
        const fresh = alerts.filter(a => (a.timestamp || '') > this.lastAnomalyTimestamp)
        this.lastAnomalyTimestamp = newest
        // 有新异动就亮未读红点（桌面通知已交由全局 notificationManager 统一负责）
        if (fresh.length) this.hasUnreadAnomaly = true
      } catch (e) {
        console.log('异动通知轮询失败:', e)
      }
    },

    // ===== 资金异动速览弹窗（首页一键瞄一眼，深入看跳 /flow-alert）=====
    openFlowAlertModal() {
      if (this.requireAuthOrPrompt()) return
      this.hasUnreadAnomaly = false   // 打开速览即视为已读
      this.showFlowAlertModal = true
      this.refreshFlowAlertModal()
    },
    closeFlowAlertModal() {
      this.showFlowAlertModal = false
    },
    async refreshFlowAlertModal() {
      this.flowAlertLoading = true
      try {
        // 只看今日已推送的异动（与桌面通知同源），最新 10 条 + 简要统计
        const d = new Date()
        const todayStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        const res = await getAnomalyAlerts(todayStr)
        const alerts = (res && res.success && Array.isArray(res.data)) ? res.data : []
        this.flowAlertList = alerts.slice(0, 10)
        const sectors = new Set(alerts.map(a => a.sector).filter(Boolean))
        const latest = alerts[0]
        this.flowAlertSummary = {
          total: alerts.length,
          sectors: sectors.size,
          latest: latest ? `${latest.date} ${latest.time}` : '--'
        }
      } catch (e) {
        console.log('异动速览加载失败:', e)
        this.flowAlertList = []
        this.flowAlertSummary = { total: 0, sectors: 0, latest: '--' }
      } finally {
        this.flowAlertLoading = false
      }
    },
    gotoFlowAlertPage() {
      this.closeFlowAlertModal()
      this.$router.push('/flow-alert')
    },
    faNet(v) { return (v == null || isNaN(v)) ? '--' : Number(v).toFixed(2) },
    faPct(v) { return (v == null || isNaN(v)) ? '--' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) },

    openNews(url) {
      if (url) {
        window.open(url, '_blank')
      }
    },

    isImportant(importance) {
      return importance === '3'
    },

    formatNewsTime(timeStr) {
      if (!timeStr) return ''
      
      try {
        let date
        if (typeof timeStr === 'number') {
          date = new Date(timeStr * 1000)
        } else if (typeof timeStr === 'string') {
          if (/^\d+$/.test(timeStr)) {
            date = new Date(parseInt(timeStr) * 1000)
          } else {
            date = new Date(timeStr)
          }
        } else {
          return ''
        }
        
        if (isNaN(date.getTime())) {
          return timeStr
        }
        
        return date.toLocaleString('zh-CN', {
          hour: '2-digit',
          minute: '2-digit'
        })
      } catch (e) {
        return timeStr
      }
    },

    async fetchHealthStatus(triggerCheck = false) {
      try {
        const response = await getHealth(triggerCheck)
        if (response.threads) {
          this.threadStatus = response.threads
        }
        if (response.health) {
          this.healthStatus = response.health
        }
        if (response.crawler) {
          this.crawlerStatus = response.crawler
        }
      } catch (err) {
        console.error('获取健康状态失败:', err)
        const msg = (err.code === 'ECONNABORTED' || (err.message && err.message.includes('timeout'))) ? '网络超时' : '网络异常'
        this.healthStatus = {
          news: { status: 'error', error: msg },
          sector: { status: 'error', error: msg },
          push: { status: 'error', error: msg, clients: (this.healthStatus.push && this.healthStatus.push.clients) || 0 }
        }
      }
    },

    async resetCrawlerStatus(crawlerName) {
      try {
        await resetCrawler(crawlerName)
        await this.fetchHealthStatus()
      } catch (err) {
        console.error('重置爬虫状态失败:', err)
      }
    },

    getCrawlerKey(healthKey) {
      const map = {
        'ths_news': 'news',
        'ths_sector': 'sector_flow',
        'news': 'news',
        'sector': 'sector_flow'
      }
      return map[healthKey] || healthKey
    },

    getCrawlerStatus(healthKey) {
      const crawlerKey = this.getCrawlerKey(healthKey)
      return this.crawlerStatus[crawlerKey]?.status || 'idle'
    },

    getCrawlerMessage(healthKey) {
      const crawlerKey = this.getCrawlerKey(healthKey)
      return this.crawlerStatus[crawlerKey]?.message || ''
    },

    // 合并 news + sector 为「同花顺数据」的整体健康状态
    combineThsHealth(news, sector) {
      const a = news && news.status
      const b = sector && sector.status
      let status = 'ok'
      let error = null
      if ((a === 'error' || a === 'partial') && (b === 'error' || b === 'partial')) {
        status = 'error'
        error = (news && news.error) || (sector && sector.error) || '采集异常'
      } else if (a === 'error' || a === 'partial' || b === 'error' || b === 'partial') {
        status = 'partial'
        error = (a === 'error' || a === 'partial') ? (news && news.error) : (sector && sector.error)
      }
      const lastCheck = (news && sector)
        ? ((news.last_check || '') >= (sector.last_check || '') ? news.last_check : sector.last_check)
        : ((news && news.last_check) || (sector && sector.last_check))
      const rt = (news && sector && news.response_time && sector.response_time)
        ? Math.max(news.response_time, sector.response_time)
        : ((news && news.response_time) || (sector && sector.response_time) || null)
      return { status, error, last_check: lastCheck, response_time: rt }
    },

    // 「同花顺数据」合并行：news 或 sector_flow 采集器是否处于 failed
    thsCrawlerFailed() {
      const news = this.crawlerStatus.news && this.crawlerStatus.news.status === 'failed'
      const sf = this.crawlerStatus.sector_flow && this.crawlerStatus.sector_flow.status === 'failed'
      return !!(news || sf)
    },
    thsCrawlerChecking() {
      const news = this.crawlerStatus.news && this.crawlerStatus.news.status === 'checking'
      const sf = this.crawlerStatus.sector_flow && this.crawlerStatus.sector_flow.status === 'checking'
      return !!(news || sf)
    },
    async resetThsCrawler() {
      try {
        if (this.crawlerStatus.news && this.crawlerStatus.news.status === 'failed') {
          await resetCrawler('news')
        }
        if (this.crawlerStatus.sector_flow && this.crawlerStatus.sector_flow.status === 'failed') {
          await resetCrawler('sector_flow')
        }
        await this.fetchHealthStatus()
      } catch (err) {
        console.error('重置采集器失败:', err)
      }
    },
    async testPushService() {
      // 手动测试消息推送服务：后端走真实 WebSocket 发测试消息，前端弹桌面通知作为反馈
      if (typeof Notification === 'undefined' || Notification.permission !== 'granted') {
        alert('请先在配置页授权桌面通知权限')
        return
      }
      try {
        await testPushServiceApi()
      } catch (err) {
        console.error('推送服务测试失败:', err)
        alert('推送测试失败：' + (err.message || err))
      }
    },

    getMonitorRowClass(row) {
      if (!row || !row.item) return ''
      if (row.kind === 'ths') {
        if (this.thsCrawlerChecking()) return 'monitor-checking'
        if (this.thsCrawlerFailed()) return 'monitor-failed'
      }
      const st = row.item.status
      if (st === 'ok') return 'monitor-ok'
      if (st === 'partial' || st === 'no_client') return 'monitor-partial'
      if (st === 'error') return 'monitor-error'
      if (st === 'checking') return 'monitor-checking'
      return 'monitor-unknown'
    },

    getMonitorStatusText(row) {
      if (!row || !row.item) return '检测中...'
      const it = row.item
      if (row.kind === 'ths') {
        if (this.thsCrawlerChecking()) return '检测中...'
        if (this.thsCrawlerFailed()) {
          const cs = this.crawlerStatus
          return (cs.sector_flow && cs.sector_flow.message) || (cs.news && cs.news.message) || '已停止'
        }
        if (it.status === 'ok') return '正常'
        if (it.status === 'partial') return '部分异常'
        return it.error || '异常'
      }
      // push
      if (it.status === 'ok') return `正常（${it.clients || 0} 个连接）`
      if (it.status === 'no_client') return '无连接'
      if (it.status === 'checking') return '检测中...'
      return it.error || '异常'
    },

    async doHealthCheck() {
      await this.fetchHealthStatus(true)
    },

    async refreshHealth() {
      if (this.healthChecking) return
      this.healthChecking = true
      try {
        await this.doHealthCheck()
      } finally {
        this.healthChecking = false
      }
    },

    getThreadLabel(key) {
      const labels = {
        'data_collector': '板块资金采集',
        'news_collector': '同花顺新闻采集'
      }
      return labels[key] || key
    },

    getHealthLabel(key) {
      const labels = {
        'ths_news': '同花顺新闻',
        'ths_sector': '板块资金',
        'news': '同花顺新闻',
        'sector': '板块资金'
      }
      return labels[key] || key
    },

    getThreadTitle(key, thread) {
      const label = this.getThreadLabel(key)
      if (thread.status === 'running') {
        return `${label}运行正常`
      }
      return `${label}已停止`
    },

    async analyzeDailyFlow() {
      if (this.aiAnalyzing) return
      
      this.aiAnalyzing = true
      this.aiAnalysisResult = null
      this.aiAnalysisError = null
      this.aiAnalysisDate = null
      this.aiAnalysisProgress = 0
      this.aiAnalysisStep = '检查历史结果...'
      
      try {
        // 先查询是否有历史结果
        const statusResponse = await getAnalyzeDailyFlowStatus()
        
        // 如果有今天的已完成结果，直接显示
        if (statusResponse.status === 'completed' && statusResponse.success) {
          const today = new Date().toISOString().split('T')[0]
          if (statusResponse.date === today) {
            this.aiAnalysisProgress = 100
            this.aiAnalysisStep = '完成'
            this.aiAnalysisResult = statusResponse.analysis
            this.aiAnalysisDate = statusResponse.date
            this.showAIAnalysisModal = true
            this.aiAnalyzing = false
            return
          }
        }
        
        // 没有今天的结果，开始新分析
        await this._startNewAnalysis()
        
      } catch (error) {
        this.aiAnalysisError = error.message || 'AI分析请求失败'
        this.showAIAnalysisModal = true
        this.aiAnalyzing = false
        this.aiAnalysisProgress = 0
        this.aiAnalysisStep = ''
      }
    },

    async reanalyzeDailyFlow() {
      if (this.aiAnalyzing) return
      
      this.aiAnalyzing = true
      this.aiAnalysisResult = null
      this.aiAnalysisError = null
      this.aiAnalysisDate = null
      this.aiAnalysisProgress = 0
      this.aiAnalysisStep = ''
      
      try {
        await this._startNewAnalysis()
      } catch (error) {
        this.aiAnalysisError = error.message || 'AI分析请求失败'
        this.showAIAnalysisModal = true
        this.aiAnalyzing = false
        this.aiAnalysisProgress = 0
        this.aiAnalysisStep = ''
      }
    },

    async _startNewAnalysis() {
      // 发起分析任务
      const startResponse = await startAnalyzeDailyFlow()
      
      if (!startResponse.success) {
        this.aiAnalysisError = startResponse.message || '启动分析失败'
        this.showAIAnalysisModal = true
        this.aiAnalyzing = false
        this.aiAnalysisProgress = 0
        this.aiAnalysisStep = ''
        return
      }
      
      // 启动轮询跟踪状态
      this.startAIAnalysisPolling()
    },

    closeAIAnalysisModal() {
      this.showAIAnalysisModal = false
    },

    async checkAIAnalysisStatus() {
      // 初次进入页面时检查上次任务状态
      try {
        const statusResponse = await getAnalyzeDailyFlowStatus()
        
        if (statusResponse.status === 'running') {
          // 上次任务还在运行，禁用按钮，开始跟踪
          this.aiAnalyzing = true
          this.aiAnalysisProgress = statusResponse.progress || 0
          this.aiAnalysisStep = statusResponse.step || '处理中...'
          this.startAIAnalysisPolling()
        } else if (statusResponse.status === 'completed' && statusResponse.success) {
          // 上次任务已完成，检查是否是今天的结果
          const today = new Date().toISOString().split('T')[0]
          if (statusResponse.date === today) {
            this.aiAnalysisProgress = 100
            this.aiAnalysisStep = '完成'
            this.aiAnalysisResult = statusResponse.analysis
            this.aiAnalysisDate = statusResponse.date
          }
        } else if (statusResponse.status === 'failed') {
          // 上次任务失败：在按钮上提示"上次失败"，允许重新点击重试
          this.aiAnalysisError = statusResponse.message || '上次AI分析失败'
        }
      } catch (error) {
        // 检查失败，忽略
      }
    },

    startAIAnalysisPolling() {
      // 每5秒轮询一次状态
      if (this.aiAnalysisPollTimer) {
        clearInterval(this.aiAnalysisPollTimer)
      }
      
      this.aiAnalysisPollTimer = setInterval(async () => {
        try {
          const statusResponse = await getAnalyzeDailyFlowStatus()
          
          if (statusResponse.status === 'running') {
            this.aiAnalysisProgress = statusResponse.progress || 0
            this.aiAnalysisStep = statusResponse.step || '处理中...'
          } else if (statusResponse.status === 'completed') {
            clearInterval(this.aiAnalysisPollTimer)
            this.aiAnalysisPollTimer = null
            this.aiAnalysisProgress = 100
            this.aiAnalysisStep = '完成'
            if (statusResponse.success) {
              this.aiAnalysisResult = statusResponse.analysis
              this.aiAnalysisDate = statusResponse.date
              this.showAIAnalysisModal = true
            } else {
              this.aiAnalysisError = statusResponse.message || 'AI分析失败'
              this.showAIAnalysisModal = true
            }
            this.aiAnalyzing = false
          } else if (statusResponse.status === 'failed') {
            clearInterval(this.aiAnalysisPollTimer)
            this.aiAnalysisPollTimer = null
            this.aiAnalysisError = statusResponse.message || 'AI分析失败'
            this.showAIAnalysisModal = true
            this.aiAnalyzing = false
            this.aiAnalysisProgress = 0
            this.aiAnalysisStep = ''
          }
        } catch (error) {
          // 轮询失败，继续
        }
      }, 5000)
    }
  }
}

