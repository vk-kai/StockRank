import * as echarts from 'echarts'
import { formatFlow, formatNetFlow } from '../../utils/formatters'
import { getCurrentFlow, getHistoryData, getMinuteData, getMinuteDataByDate, getNews, getAccumulatedFlow, getSectorStocks, getHealth, resetCrawler } from '../../services/apiService'
import { generateChartOption, generateSeries, collectAllSectors, generateLiveReplayChartOption, buildReplaySectorOrder } from '../../services/chartService'
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
      soundMode: 'all',
      lastNewsId: null,
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
      historicalMinuteData: null,
      lastTimeKeys: [],
      autoGrowCursor: null,
      autoGrowTimer: null,
      autoGrowSpeed: 200
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
    healthDisplayItems() {
      const items = {}
      if (this.healthStatus.news) {
        items.news = this.healthStatus.news
      }
      if (this.healthStatus.sector) {
        items.sector = this.healthStatus.sector
      }
      return items
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
    }
  },
  mounted() {
    this.loadNotificationState()
    this.loadSoundMode()
    this.initChart()
    this.fetchDataByTimeRange()
    this.startCountdown()
    this.fetchLatestNews()
    this.startNewsRotation()
    this.fetchHealthStatus()
    window.addEventListener('resize', this.handleResize)
    this.$nextTick(() => {
      this.updateLayoutHeight()
    })
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
    if (this.replayTimer) {
      clearInterval(this.replayTimer)
    }
    if (this.autoGrowTimer) {
      clearInterval(this.autoGrowTimer)
    }
  },
  methods: {
    initChart() {
      if (this.chartInstance) {
        return
      }
      
      const _this = this
      this.$nextTick(() => {
        try {
          this.chartInstance = echarts.init(this.$refs.chart, null, {
            renderer: 'canvas'
          })
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
    },

    updateLayoutHeight() {
      const monitorCard = this.$refs.monitorCard
      const chartContainer = this.$refs.chartContainer
      const sectorList = this.$refs.sectorList
      if (!monitorCard || !chartContainer) return

      // 从视口底部算到服务监控卡片底部的距离
      const monitorBottom = monitorCard.getBoundingClientRect().bottom
      const remainingHeight = window.innerHeight - monitorBottom

      // 先给TOP10分配30%，再给折线图分配70%
      const sectorTotalSpace = remainingHeight * 0.3
      const chartTotalSpace = remainingHeight * 0.7

      // chart-container的height需要减去padding和border（content-box模型）
      const chartStyle = getComputedStyle(chartContainer)
      const chartPaddingY = (parseFloat(chartStyle.paddingTop) || 0) + (parseFloat(chartStyle.paddingBottom) || 0)
      const chartBorderY = (parseFloat(chartStyle.borderTopWidth) || 0) + (parseFloat(chartStyle.borderBottomWidth) || 0)

      chartContainer.style.height = (chartTotalSpace - chartPaddingY - chartBorderY) + 'px'

      if (sectorList) {
        const sectorStyle = getComputedStyle(sectorList)
        const sectorPaddingY = (parseFloat(sectorStyle.paddingTop) || 0) + (parseFloat(sectorStyle.paddingBottom) || 0)
        const sectorBorderY = (parseFloat(sectorStyle.borderTopWidth) || 0) + (parseFloat(sectorStyle.borderBottomWidth) || 0)

        sectorList.style.height = (sectorTotalSpace - sectorPaddingY - sectorBorderY) + 'px'
        sectorList.style.overflowY = 'hidden'
      }

      // 高度变化后重新调整echarts尺寸
      this.$nextTick(() => {
        if (this.chartInstance) {
          this.chartInstance.resize()
        }
      })
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
      await this.fetchHealthStatus()
      
      this.loading = true
      this.error = null
      
      if (this.autoGrowTimer) {
        clearInterval(this.autoGrowTimer)
        this.autoGrowTimer = null
        this.autoGrowCursor = null
      }
      
      if (this.selectedTimeRange !== 'today') {
        this.stopTodayReplay(true)
      }
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

        // 非交易日不自动刷新
        if (!isTradingDay(new Date())) {
          this.countdown = 300
          return
        }

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
        this.initChart()
        return
      }

      if (this.selectedTimeRange === 'today') {
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

        const option = generateLiveReplayChartOption(
          timeData,
          this.minuteData,
          this.colors,
          cursor,
          10,
          this.replayTopSectors,
          isReplayMode
        )

        try {
          this.chartInstance.setOption(option, {
            replaceMerge: ['series', 'xAxis', 'tooltip'],
            lazyUpdate: true
          })
        } catch (e) {
          console.error('setOption 澶辫触:', e)
        }
        return
      }

      const oldOption = this.chartInstance.getOption()
      const oldSelected = oldOption?.legend?.[0]?.selected || {}

      let timeData, allData

      if (this.selectedTimeRange === 'today') {
        timeData = Object.keys(this.minuteData).sort().filter(key => {
          const parts = key.split(':')
          if (parts.length !== 2) return false
          const minute = parseInt(parts[1], 10)
          return minute % 5 === 0
        })
        allData = this.minuteData
      } else {
        timeData = Object.keys(this.historyData).sort()
        allData = this.historyData
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
            name: '资金流入(亿)',
            axisLabel: {
              color: '#8ba4c7',
              formatter: (value) => {
                if (Math.abs(value) >= 1) {
                  return value.toFixed(1) + '亿'
                }
                return (value * 10000).toFixed(0) + '万'
              }
            }
          },
          series: []
        }
      } else {
        const isToday = this.selectedTimeRange === 'today'
        
        let allSectors
        if (isToday && this.currentData.length > 0) {
          // 使用currentData的前5个板块，与下方TOP10列表保持一致
          allSectors = this.currentData.slice(0, 10).map(s => s.name)
        } else {
          // 从所有时间点数据中收集出现过的板块
          allSectors = collectAllSectors(timeData, allData, isToday)
          // 限制最多5个板块
          allSectors = allSectors.slice(0, 10)
        }
        
        // 生成 series
        const series = generateSeries(allSectors, timeData, allData, this.colors, isToday)
        
        // 使用实际有数据的板块作为最终列表
        const finalTopSectors = series.map(s => s.name)
        
        option = generateChartOption(timeData, series, finalTopSectors, oldSelected, this.colors, isToday)
      }

      try {
        this.chartInstance.setOption(option, {
          replaceMerge: ['series', 'legend', 'xAxis', 'yAxis', 'tooltip'],
          lazyUpdate: true
        })
      } catch (e) {
        console.error('setOption 失败:', e)
      }
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
        this.isReplayingToday = false
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
      }
    },

    onReplayDateChange() {
      // 如果选择的是非交易日（周末），自动跳转到对应的周五
      if (!isTradingDay(this.replayDate)) {
        this.replayDate = getLatestWeekday(this.replayDate)
      }
      this.loadReplayDateData()
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

    loadSoundMode() {
      const saved = localStorage.getItem('newsSoundMode')
      if (saved !== null && ['none', 'important', 'all'].includes(saved)) {
        this.soundMode = saved
      } else {
        this.soundMode = 'all'
        localStorage.setItem('newsSoundMode', 'all')
      }
    },

    saveSoundMode(mode) {
      this.soundMode = mode
      localStorage.setItem('newsSoundMode', mode)
    },

    playSound(type) {
      try {
        const audio = new Audio(`/assets/sounds/${type}.mp3`)
        audio.volume = 0.5
        audio.play().catch(e => {
          console.log('播放音效失败:', e)
        })
      } catch (e) {
        console.log('播放音效失败:', e)
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
      
      try {
        const response = await getSectorStocks(sectorUrl)
        
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
        
        const isImportant = news.importance === '3' || (news.ai_analysis && news.ai_analysis.level === '重大')
        
        if (this.soundMode === 'all') {
          this.playSound(isImportant ? 'important' : 'normal')
        } else if (this.soundMode === 'important' && isImportant) {
          this.playSound('important')
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
        'ths_sector': '板块资金',
        'news': '同花顺新闻',
        'sector': '板块资金'
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

