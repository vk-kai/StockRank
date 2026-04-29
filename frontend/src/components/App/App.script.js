import * as echarts from 'echarts'
import { formatFlow } from '../../utils/formatters'
import { getCurrentFlow, getHistoryData, getMinuteData, getNews, getSystemHealth, getAccumulatedFlow, getSectorStocks } from '../../services/apiService'
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
      healthCheckInterval: null,
      enableNotification: true,
      lastNewsId: null,
      showSectorModal: false,
      selectedSectorName: '',
      sectorStocks: [],
      loadingSectorStocks: false
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
    }
  },
  mounted() {
    this.loadNotificationState()
    this.initChart()
    this.fetchDataByTimeRange()
    this.startCountdown()
    this.fetchLatestNews()
    this.startNewsRotation()
    this.fetchSystemHealth()
    this.startHealthCheck()
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
        this.chartInstance.on('click', (params) => {
          if (params.componentType === 'series' && params.seriesName) {
            this.showSectorStocks(params.seriesName)
          }
        })
      })
    },

    handleResize() {
      if (this.chartInstance) {
        this.chartInstance.resize()
      }
    },

    highlightSector(sectorName) {
      if (!this.chartInstance) return
            
      this.chartInstance.dispatchAction({
        type: 'highlight',
        seriesName: sectorName
      })
      
      const option = this.chartInstance.getOption()
      if (option.series) {
        option.series.forEach((series) => {
          if (series.name !== sectorName) {
            this.chartInstance.dispatchAction({
              type: 'downplay',
              seriesName: series.name
            })
          }
        })
      }
    },

    unhighlightSector() {
      if (!this.chartInstance) return
      
      this.chartInstance.dispatchAction({
        type: 'downplay'
      })
    },

    async showSectorStocks(sectorName) {
      this.selectedSectorName = sectorName
      this.showSectorModal = true
      this.loadingSectorStocks = true
      this.sectorStocks = []
      
      try {
        const response = await getSectorStocks(sectorName)
        if (response.success && response.data) {
          this.sectorStocks = response.data.stocks || []
        }
      } catch (error) {
        console.error('获取板块个股数据失败:', error)
      } finally {
        this.loadingSectorStocks = false
      }
    },

    closeSectorModal() {
      this.showSectorModal = false
      this.selectedSectorName = ''
      this.sectorStocks = []
    },

    formatStockFlow(value) {
      if (value === 0) return '0'
      const absValue = Math.abs(value)
      if (absValue >= 100000000) {
        return (value / 100000000).toFixed(2) + '亿'
      } else if (absValue >= 10000) {
        return (value / 10000).toFixed(2) + '万'
      }
      return value.toFixed(2)
    },

    async fetchCurrentData() {
      try {
        this.loading = true
        this.error = null
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
      } finally {
        this.loading = false
      }
    },

    async fetchHistoryData(days) {
      this.loading = true
      this.error = null
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
      } finally {
        this.loading = false
      }
    },

    async fetchMinuteData() {
      this.loading = true
      this.error = null
      try {
        const response = await getMinuteData(24)
        if (response.success) {
          this.minuteData = response.data
          this.updateChart()
        }
      } catch (err) {
        this.error = '获取分钟数据失败: ' + err.message
      } finally {
        this.loading = false
      }
    },

    async fetchDataByTimeRange() {
      if (this.selectedTimeRange === 'today') {
        this.accumulatedData = []
        await this.fetchCurrentData()
        await this.fetchMinuteData()
      } else {
        this.currentData = []
        await this.fetchAccumulatedData(this.selectedTimeRange)
        await this.fetchHistoryData(this.selectedTimeRange)
      }
    },

    async fetchData() {
      if (this.selectedTimeRange === 'today') {
        await this.fetchCurrentData()
        await this.fetchMinuteData()
      } else {
        await this.fetchAccumulatedData(this.selectedTimeRange)
        await this.fetchHistoryData(this.selectedTimeRange)
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
      }
    },

    retry() {
      this.error = null
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
        console.log('没有数据，显示空图表')
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
                  return (value / 10000).toFixed(1) + '万'
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
        
        const series = generateSeries(topSectors, timeData, allData, this.colors, isToday)
        option = generateChartOption(timeData, series, topSectors, oldSelected, this.colors, isToday)
      }

      this.chartInstance.setOption(option)
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

    async fetchSystemHealth() {
      try {
        const data = await getSystemHealth()
        if (data.threads) {
          this.threadStatus = data.threads
        }
      } catch (err) {
        console.error('获取服务状态失败:', err)
      }
    },

    startHealthCheck() {
      this.healthCheckInterval = setInterval(() => {
        this.fetchSystemHealth()
      }, 30000)
    },

    refreshHealth() {
      this.fetchSystemHealth()
    },

    getThreadLabel(key) {
      const labels = {
        'data_collector': '板块资金采集',
        'news_collector': '同花顺新闻采集'
      }
      return labels[key] || key
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
