import * as echarts from 'echarts'
import { formatFlow } from '../../utils/formatters'
import { getCurrentFlow, getHistoryData, getMinuteData, getNews, getAccumulatedFlow, getSectorStocks, getHealth, resetCrawler } from '../../services/apiService'
import { generateChartOption, generateSeries } from '../../services/chartService'
import '../../styles/App.css'
import SecurityAlert from '../SecurityAlert.vue'

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
      enableNotification: true,
      lastNewsId: null,
      showStockModal: false,
      selectedSector: null,
      sectorStocks: [],
      loadingStocks: false,
      stocksError: null,
      stockSortField: 'change',
      stockSortOrder: 'desc'
    }
  },
  computed: {
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
    healthErrors() {
      const errors = []
      const labels = {
        'ths_news': '同花顺新闻',
        'ths_sector': '同花顺板块资金'
      }
      for (const [key, value] of Object.entries(this.healthStatus)) {
        if (value.status === 'error' || value.status === 'partial') {
          errors.push({
            key,
            label: labels[key] || key,
            error: value.status === 'partial' ? '个股详情异常' : value.error,
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
    }
  },
  mounted() {
    this.loadNotificationState()
    this.initChart()
    this.fetchDataByTimeRange()
    this.startCountdown()
    this.fetchLatestNews()
    this.startNewsRotation()
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.handleResize)
    if (this.chartInstance) {
      this.chartInstance.dispose()
      this.chartInstance = null
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
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval)
    }
  },
  methods: {
    initChart() {
      this.$nextTick(() => {
        this.chartInstance = echarts.init(this.$refs.chart)
      })
    },

    handleResize() {
      if (this.chartInstance) {
        this.chartInstance.resize()
      }
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

    async fetchCurrentData() {
      try {
        const response = await getCurrentFlow()
        if (response.success) {
          this.currentData = response.data
          const timestamp = new Date(response.timestamp)
          this.lastUpdate = timestamp.toLocaleString('zh-CN')
          
          if (this.selectedTimeRange === 'today') {
            await this.fetchMinuteData()
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
          
          this.updateChart()
        }
      } catch (err) {
        this.error = '获取历史数据失败: ' + err.message
      }
    },

    async fetchMinuteData() {
      try {
        const response = await getMinuteData(24)
        if (response.success) {
          this.minuteData = response.data
          this.updateChart()
        }
      } catch (err) {
        this.error = '获取分钟数据失败: ' + err.message
      }
    },

    async fetchDataByTimeRange() {
      await this.doHealthCheck()
      
      this.loading = true
      this.error = null
      try {
        if (this.selectedTimeRange === 'today') {
          this.accumulatedData = []
          await this.fetchCurrentData()
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
      }
    },

    async fetchData() {
      await this.doHealthCheck()
      
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
        if (this.countdown > 0) {
          this.countdown--
        } else {
          this.fetchData()
          this.countdown = 300
        }
      }, 1000)
    },

    updateChart() {
      if (!this.chartInstance) {
        console.log('图表实例不存在，重新初始化')
        this.initChart()
        return
      }

      const oldOption = this.chartInstance.getOption()
      const oldSelected = oldOption?.legend?.[0]?.selected || {}

      let timeData, allData

      if (this.selectedTimeRange === 'today') {
        timeData = Object.keys(this.minuteData).sort()
        allData = this.minuteData
      } else {
        timeData = Object.keys(this.historyData).sort()
        allData = {}
        timeData.forEach(date => {
          const sectorList = this.historyData[date]
          if (Array.isArray(sectorList)) {
            allData[date] = { data: sectorList }
          } else {
            allData[date] = sectorList
          }
        })
      }

      let option
      if (timeData.length === 0) {
        option = {
          tooltip: {
            trigger: 'item',
            backgroundColor: 'rgba(20,25,45,0.95)',
            borderColor: '#3a4a6b',
            borderWidth: 1
          },
          legend: {
            data: [],
            textStyle: {
              color: '#8ba4c7'
            }
          },
          grid: {
            left: '3%',
            right: '4%',
            bottom: '15%',
            top: '15%',
            containLabel: true
          },
          xAxis: {
            type: 'category',
            boundaryGap: false,
            data: ['暂无数据'],
            axisLabel: {
              color: '#8ba4c7'
            }
          },
          yAxis: {
            type: 'value',
            name: '资金流入',
            axisLabel: {
              color: '#8ba4c7',
              formatter: (value) => {
                if (value >= 100000000) {
                  return (value / 100000000).toFixed(1) + '亿'
                }
                if (value >= 10000) {
                  return (value / 10000).toFixed(0) + '万'
                }
                return value
              }
            }
          },
          series: []
        }
      } else {
        const isToday = this.selectedTimeRange === 'today'
        let topSectors
        
        if (isToday && this.currentData.length > 0) {
          topSectors = this.currentData.slice(0, 10).map(s => s.name)
        } else if (!isToday && this.accumulatedData.length > 0) {
          topSectors = this.accumulatedData.slice(0, 10).map(s => s.name)
        } else {
          topSectors = this.getTopSectors(timeData, allData, isToday)
        }
        
        // 过滤掉没有数据的板块
        const validTopSectors = topSectors.filter(sectorName => {
          return timeData.some(timeKey => {
            const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
            return timeDataItem.some(s => s.name === sectorName && s.flow !== undefined && s.flow !== null)
          })
        })
        
        const series = generateSeries(validTopSectors, timeData, allData, this.colors, isToday)
        option = generateChartOption(timeData, series, validTopSectors, oldSelected, this.colors, isToday)
      }

      try {
        this.chartInstance.setOption(option, { notMerge: true })
      } catch (e) {
        console.error('setOption 失败:', e)
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

    async fetchLatestNews() {
      try {
        const response = await getNews(1, 5)
        if (response.success) {
          const newNews = response.data
          
          if (newNews.length > 0 && this.enableNotification) {
            const latestId = newNews[0]?.id
            if (latestId && latestId !== this.lastNewsId && this.lastNewsId !== null) {
              const latestNewsItem = newNews.find(n => n.id === latestId)
              if (latestNewsItem) {
                this.sendNotification(latestNewsItem)
              }
            }
          }
          
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

    loadNotificationState() {
      if (!('Notification' in window)) {
        this.enableNotification = false
        return
      }
      
      const saved = localStorage.getItem('homeNewsNotificationEnabled')
      const browserGranted = Notification.permission === 'granted'
      
      if (saved !== null) {
        this.enableNotification = saved === 'true'
      } else {
        this.enableNotification = true
        localStorage.setItem('homeNewsNotificationEnabled', 'true')
      }
      
      if (browserGranted && !this.enableNotification) {
        this.enableNotification = true
        localStorage.setItem('homeNewsNotificationEnabled', 'true')
      }
      
      if (!browserGranted && this.enableNotification) {
        this.enableNotification = false
        localStorage.setItem('homeNewsNotificationEnabled', 'false')
      }
    },

    toggleNotification() {
      this.enableNotification = !this.enableNotification
      
      if (this.enableNotification) {
        localStorage.setItem('homeNewsNotificationEnabled', 'true')
        this.requestNotificationPermission()
      } else {
        localStorage.setItem('homeNewsNotificationEnabled', 'false')
      }
    },

    async requestNotificationPermission() {
      if (!('Notification' in window)) {
        alert('您的浏览器不支持系统通知功能')
        this.enableNotification = false
        localStorage.setItem('homeNewsNotificationEnabled', 'false')
        return
      }
      
      if (Notification.permission === 'granted') {
        return
      }
      
      if (Notification.permission === 'denied') {
        const guide = '您之前已禁止通知权限。\n\n请在浏览器地址栏左侧点击"锁"图标，\n找到"通知"选项并选择"允许"，\n然后刷新页面即可。'
        alert(guide)
        this.enableNotification = false
        localStorage.setItem('homeNewsNotificationEnabled', 'false')
        return
      }
      
      const permission = await Notification.requestPermission()
      if (permission === 'granted') {
        try {
          if (typeof Notification === 'function') {
            new Notification('通知已开启', {
              body: '您将收到最新新闻的推送提醒',
              icon: 'https://pic.0vk.top/%E8%82%A1%E7%A5%A8.png'
            })
          }
        } catch (e) {
          console.log('当前浏览器不支持直接创建通知')
        }
      } else if (permission === 'denied') {
        alert('您拒绝了通知权限，如需开启请在浏览器地址栏左侧设置')
        this.enableNotification = false
        localStorage.setItem('homeNewsNotificationEnabled', 'false')
      } else {
        this.enableNotification = false
        localStorage.setItem('homeNewsNotificationEnabled', 'false')
      }
    },

    async openStockModal(sector) {
      if (!sector.sector_url) {
        alert('该板块暂无个股详情链接')
        return
      }
      
      this.showStockModal = true
      this.selectedSector = sector
      this.loadingStocks = true
      this.stocksError = null
      this.sectorStocks = []
      
      try {
        const response = await getSectorStocks(sector.sector_url)
        
        if (response.success) {
          this.sectorStocks = response.data
          this.sortStocks()
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

    sendNotification(news) {
      if (!('Notification' in window) || Notification.permission !== 'granted') {
        return
      }
      
      try {
        const title = news.title
        let body = news.content || ''
        if (body.length > 100) {
          body = body.substring(0, 100) + '...'
        }
        
        const notification = new Notification(title, {
          body: body,
          icon: 'https://pic.0vk.top/%E8%82%A1%E7%A5%A8.png',
          tag: news.id,
          requireInteraction: news.importance === '3'
        })
        
        notification.onclick = () => {
          window.focus()
          if (news.url) {
            window.open(news.url, '_blank')
          }
          notification.close()
        }
      } catch (e) {
        console.log('发送通知失败:', e)
      }
    },

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
        if (err.code === 'ECONNABORTED' || err.message.includes('timeout')) {
          this.healthStatus = {
            ths_news: { status: 'error', error: '网络超时' },
            ths_sector: { status: 'error', error: '网络超时' }
          }
        } else {
          this.healthStatus = {
            ths_news: { status: 'error', error: '网络异常' },
            ths_sector: { status: 'error', error: '网络异常' }
          }
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
        'ths_sector': 'sector_flow'
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

    getMonitorRowClass(healthKey, healthItem) {
      const crawlerStatus = this.getCrawlerStatus(healthKey)
      if (crawlerStatus === 'checking') {
        return 'monitor-checking'
      }
      if (crawlerStatus === 'failed') {
        return 'monitor-failed'
      }
      if (healthItem.status === 'ok') {
        return 'monitor-ok'
      }
      if (healthItem.status === 'partial') {
        return 'monitor-partial'
      }
      if (healthItem.status === 'error') {
        return 'monitor-error'
      }
      return 'monitor-unknown'
    },

    getMonitorStatusText(healthKey, healthItem) {
      const crawlerStatus = this.getCrawlerStatus(healthKey)
      const crawlerMessage = this.getCrawlerMessage(healthKey)
      
      if (crawlerStatus === 'checking') {
        return '检测中...'
      }
      if (crawlerStatus === 'failed') {
        return crawlerMessage || '已停止'
      }
      if (healthItem.status === 'ok') {
        return '正常'
      }
      if (healthItem.status === 'error') {
        return healthItem.error || '异常'
      }
      return '检测中'
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
        'ths_sector': '板块资金'
      }
      return labels[key] || key
    },
    
    getMonitorStatusText(key, item) {
      if (!item) return '检测中...'
      
      if (item.status === 'ok') {
        return '正常'
      }
      
      if (item.status === 'partial') {
        return '板块正常，个股异常'
      }
      
      if (item.status === 'checking') {
        return '检测中...'
      }
      
      return item.error || '异常'
    },

    getThreadTitle(key, thread) {
      const label = this.getThreadLabel(key)
      if (thread.status === 'running') {
        return `${label}运行正常`
      }
      return `${label}已停止`
    }
  }
}
