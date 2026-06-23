import { getNews, getHealth, searchNews, isSecurityError, analyzeNews, getNewsScoreSummary, getNewsScoreTrend } from '../../services/apiService'
import { marked } from 'marked'
import * as echarts from 'echarts'
import SecurityAlert from '../SecurityAlert.vue'

export default {
  name: 'NewsPage',
  components: {
    SecurityAlert
  },
  data() {
    return {
      newsList: [],
      loading: false,
      error: null,
      lastUpdate: null,
      countdown: 30,
      countdownInterval: null,
      currentApiPage: 1,
      pageSize: 40,
      hasMore: true,
      total: 0,
      enableNotification: true,
      lastNewsId: null,
      showOnlyImportant: false,
      threadStatus: {},
      healthCheckInterval: null,
      searchKeyword: '',
      searchTimer: null,
      isSearching: false,
      currentSearchPage: 1,
      showBackToTop: false,
      // 新闻AI分析
      analyzingNewsId: null,
      showNewsAnalysisModal: false,
      newsAnalysisResult: null,
      newsAnalysisError: null,
      newsAnalysisDuration: null,
      currentAnalysisNews: null,
      // 日期评分统计（从后端获取）
      scoreSummary: {},
      // 利好利空趋势图
      scoreTrendData: { summary: null },
      scoreTrendChart: null,
      scorePieChart: null,
      // 是否仅显示盘中（隐藏盘前盘后）
      onlyMarketHours: false
    }
  },
  computed: {
    countdownSeconds() {
      return this.countdown.toString().padStart(2, '0')
    },
    filteredNewsList() {
      return this.newsList
    },
    displayNewsList() {
      return this.filteredNewsList
    },
    hasMoreNews() {
      return this.hasMore
    },
    remainingNews() {
      return this.total - this.newsList.length
    },
    renderedNewsAnalysis() {
      if (!this.newsAnalysisResult) return ''
      return marked.parse(this.newsAnalysisResult)
    },
    tendencyClass() {
      const tendency = this.scoreTrendData?.summary?.tendency
      if (tendency === '偏利好') return 'tendency-positive'
      if (tendency === '偏利空') return 'tendency-negative'
      return 'tendency-neutral'
    }
  },
  mounted() {
    this.loadNotificationState()
    this.loadFilterState()
    this.fetchNews()
    this.loadScoreSummary()
    this.loadScoreTrend()
    this.startCountdown()
    this.fetchSystemHealth()
    this.startHealthCheck()
    
    // 监听滚动事件
    window.addEventListener('scroll', this.handleScroll)
    // 监听窗口大小变化，重绘图表
    window.addEventListener('resize', this.handleChartResize)
  },
  beforeUnmount() {
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval)
    }
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval)
    }
    if (this.searchTimer) {
      clearTimeout(this.searchTimer)
    }
    
    // 移除滚动监听
    window.removeEventListener('scroll', this.handleScroll)
    // 移除窗口大小监听
    window.removeEventListener('resize', this.handleChartResize)
    // 销毁图表实例
    if (this.scoreTrendChart) {
      this.scoreTrendChart.dispose()
      this.scoreTrendChart = null
    }
    if (this.scorePieChart) {
      this.scorePieChart.dispose()
      this.scorePieChart = null
    }
  },
  methods: {
    goBack() {
      window.location.href = '/'
    },

    async fetchNews() {
      try {
        this.loading = true
        this.error = null
        this.currentApiPage = 1
        this.newsList = []
        
        const importance = this.showOnlyImportant ? '3' : null
        const response = await getNews(1, this.pageSize, importance)
        if (response.success) {
          const newNews = response.data
          
          if (newNews.length > 0 && this.enableNotification) {
            const latestId = newNews[0]?.id
            if (latestId && latestId !== this.lastNewsId) {
              const latestNews = newNews.find(n => n.id === latestId)
              if (latestNews) {
                this.sendNotification(latestNews)
              }
            }
          }
          
          this.newsList = newNews
          if (newNews.length > 0) {
            this.lastNewsId = newNews[0].id
          }
          
          if (response.pagination) {
            this.total = response.pagination.total
            this.hasMore = response.pagination.has_more
          }
          
          const timestamp = new Date(response.timestamp)
          this.lastUpdate = timestamp.toLocaleString('zh-CN')
        }
      } catch (err) {
        console.error('获取新闻失败:', err)
        this.error = '获取新闻失败: ' + err.message
      } finally {
        this.loading = false
        // 新闻加载完成后更新评分统计和趋势图
        this.loadScoreSummary()
        this.loadScoreTrend()
      }
    },

    retry() {
      this.error = null
      this.fetchNews()
    },

    async loadScoreSummary() {
      try {
        const response = await getNewsScoreSummary()
        if (response.success) {
          this.scoreSummary = response.data
        }
      } catch (err) {
        console.error('获取评分统计失败:', err)
      }
    },

    async loadScoreTrend() {
      try {
        const response = await getNewsScoreTrend()
        if (response.success) {
          this.scoreTrendData = response.data
          // 延迟渲染确保DOM完成布局（修复首次进入饼图不显示）
          setTimeout(() => {
            this.renderScoreTrendChart()
            this.renderScorePieChart()
          }, 100)
        }
      } catch (err) {
        console.error('获取评分趋势数据失败:', err)
      }
    },

    renderScoreTrendChart() {
      const chartDom = this.$refs.scoreTrendChart
      if (!chartDom) return
      
      // 初始化图表
      if (!this.scoreTrendChart) {
        this.scoreTrendChart = echarts.init(chartDom)
      }
      
      const data = this.scoreTrendData
      if (!data || !data.x_axis || data.x_axis.length === 0) {
        this.scoreTrendChart.clear()
        this.scoreTrendChart.setOption({
          title: {
            text: '暂无今日分析数据',
            left: 'center',
            top: 'center',
            textStyle: { color: '#999', fontSize: 14 }
          }
        })
        return
      }
      
      // 过滤盘前盘后（如果开启仅看盘中）
      let xAxisData = data.x_axis
      let positiveData = data.series.positive
      let negativeData = data.series.negative
      let neutralData = data.series.neutral
      
      if (this.onlyMarketHours) {
        const filteredIndices = []
        data.x_axis.forEach((label, idx) => {
          if (label !== '盘前' && label !== '盘后') {
            filteredIndices.push(idx)
          }
        })
        xAxisData = filteredIndices.map(i => data.x_axis[i])
        positiveData = filteredIndices.map(i => data.series.positive[i])
        negativeData = filteredIndices.map(i => data.series.negative[i])
        neutralData = filteredIndices.map(i => data.series.neutral[i])
      }
      
      const option = {
        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },
          formatter: function(params) {
            let result = params[0].axisValue + '<br/>'
            params.forEach(p => {
              result += `${p.marker} ${p.seriesName}: ${p.value}条<br/>`
            })
            return result
          }
        },
        legend: {
          data: ['利好', '利空', '中性'],
          top: 5,
          textStyle: { color: '#ccc' }
        },
        grid: {
          left: '3%',
          right: '4%',
          bottom: '3%',
          top: 40,
          containLabel: true
        },
        xAxis: {
          type: 'category',
          boundaryGap: false,
          data: xAxisData,
          axisLabel: {
            color: '#aaa',
            interval: 0,
            rotate: 45,
            fontSize: 11
          },
          axisLine: { lineStyle: { color: '#444' } }
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: '#aaa' },
          splitLine: { lineStyle: { color: '#222' } }
        },
        series: [
          {
            name: '利好',
            type: 'line',
            stack: 'total',
            areaStyle: { opacity: 0.6, color: '#ef4444' },
            lineStyle: { width: 1, color: '#ef4444' },
            itemStyle: { color: '#ef4444' },
            emphasis: { focus: 'series' },
            data: positiveData
          },
          {
            name: '利空',
            type: 'line',
            stack: 'total',
            areaStyle: { opacity: 0.6, color: '#22c55e' },
            lineStyle: { width: 1, color: '#22c55e' },
            itemStyle: { color: '#22c55e' },
            emphasis: { focus: 'series' },
            data: negativeData
          },
          {
            name: '中性',
            type: 'line',
            stack: 'total',
            areaStyle: { opacity: 0.5, color: '#eab308' },
            lineStyle: { width: 1, color: '#eab308' },
            itemStyle: { color: '#eab308' },
            emphasis: { focus: 'series' },
            data: neutralData
          }
        ]
      }
      
      this.scoreTrendChart.setOption(option, true)
    },

    toggleMarketHours() {
      this.onlyMarketHours = !this.onlyMarketHours
      this.renderScoreTrendChart()
      this.renderScorePieChart()
    },

    // 从趋势数据中提取过滤后的统计（与折线图同步）
    getFilteredPieData() {
      const data = this.scoreTrendData
      if (!data || !data.x_axis || data.x_axis.length === 0) return null

      let positiveTotal = 0
      let negativeTotal = 0
      let neutralTotal = 0

      data.x_axis.forEach((label, idx) => {
        // 如果开启仅看盘中，跳过盘前盘后
        if (this.onlyMarketHours && (label === '盘前' || label === '盘后')) return
        positiveTotal += data.series.positive[idx] || 0
        negativeTotal += data.series.negative[idx] || 0
        neutralTotal += data.series.neutral[idx] || 0
      })

      const total = positiveTotal + negativeTotal + neutralTotal
      return { positive: positiveTotal, negative: negativeTotal, neutral: neutralTotal, total }
    },

    renderScorePieChart() {
      const chartDom = this.$refs.scorePieChart
      if (!chartDom) return
      
      // 强制销毁重建，避免echarts内部状态残留导致数据不更新
      if (this.scorePieChart) {
        this.scorePieChart.dispose()
      }
      this.scorePieChart = echarts.init(chartDom)

      const pieData = this.getFilteredPieData()
      if (!pieData || pieData.total === 0) {
        this.scorePieChart.clear()
        this.scorePieChart.setOption({
          title: {
            text: '暂无数据',
            left: 'center',
            top: 'center',
            textStyle: { color: '#999', fontSize: 14 }
          }
        })
        return
      }

      const option = {
        tooltip: {
          trigger: 'item',
          formatter: '{b}: {c}条 ({d}%)'
        },
        legend: {
          bottom: 5,
          textStyle: { color: '#ccc', fontSize: 12 }
        },
        series: [
          {
            name: '情绪占比',
            type: 'pie',
            radius: ['40%', '70%'],
            center: ['50%', '45%'],
            avoidLabelOverlap: false,
            itemStyle: {
              borderRadius: 6,
              borderColor: 'rgba(0,0,0,0.3)',
              borderWidth: 2
            },
            label: {
              show: true,
              color: '#ccc',
              formatter: '{b}\n{d}%'
            },
            emphasis: {
              label: { show: true, fontSize: 14, fontWeight: 'bold' }
            },
            data: [
              { value: pieData.positive, name: '利好', itemStyle: { color: '#ef4444' } },
              { value: pieData.negative, name: '利空', itemStyle: { color: '#22c55e' } },
              { value: pieData.neutral, name: '中性', itemStyle: { color: '#eab308' } }
            ]
          }
        ]
      }

      this.scorePieChart.setOption(option, true)
    },

    handleChartResize() {
      if (this.scoreTrendChart) {
        this.scoreTrendChart.resize()
      }
      if (this.scorePieChart) {
        this.scorePieChart.resize()
      }
    },

    startCountdown() {
      this.countdownInterval = setInterval(() => {
        if (this.countdown > 0) {
          this.countdown--
        } else {
          // 搜索状态下不刷新新闻
          if (!this.isSearching || !this.searchKeyword.trim()) {
            this.fetchNews()
          }
          this.countdown = 30
        }
      }, 1000)
    },

    loadNotificationState() {
      if (!('Notification' in window)) {
        this.enableNotification = false
        return
      }
      
      const saved = localStorage.getItem('newsNotificationEnabled')
      const browserGranted = Notification.permission === 'granted'
      
      if (saved !== null) {
        this.enableNotification = saved === 'true'
      }
      
      if (browserGranted && !this.enableNotification) {
        this.enableNotification = true
        localStorage.setItem('newsNotificationEnabled', 'true')
      }
      
      if (!browserGranted && this.enableNotification) {
        this.enableNotification = false
        localStorage.setItem('newsNotificationEnabled', 'false')
      }
    },

    loadFilterState() {
      const saved = localStorage.getItem('newsShowOnlyImportant')
      if (saved !== null) {
        this.showOnlyImportant = saved === 'true'
      }
    },

    toggleImportantFilter() {
      this.showOnlyImportant = !this.showOnlyImportant
      localStorage.setItem('newsShowOnlyImportant', this.showOnlyImportant.toString())
      this.fetchNews()
    },

    handleSearch() {
      if (this.searchTimer) {
        clearTimeout(this.searchTimer)
      }
      
      this.searchTimer = setTimeout(() => {
        this.performSearch()
      }, 500)
    },

    async performSearch() {
      if (!this.searchKeyword || !this.searchKeyword.trim()) {
        this.fetchNews()
        return
      }
      
      try {
        this.isSearching = true
        this.loading = true
        this.error = null
        this.currentSearchPage = 1
        this.newsList = []
        
        const importance = this.showOnlyImportant ? '3' : null
        const response = await searchNews(this.searchKeyword, 1, this.pageSize, importance)
        
        if (response.success) {
          this.newsList = response.data
          if (response.pagination) {
            this.total = response.pagination.total
            this.hasMore = response.pagination.has_more
          }
          this.lastUpdate = new Date(response.timestamp).toLocaleString('zh-CN')
        } else {
          this.error = response.message || '搜索失败'
        }
      } catch (err) {
        console.error('搜索新闻失败:', err)
        if (isSecurityError(err)) {
          return
        }
        this.error = '搜索新闻失败: ' + (err.message || '未知错误')
      } finally {
        this.loading = false
        this.isSearching = false
      }
    },

    clearSearch() {
      this.searchKeyword = ''
      this.fetchNews()
    },

    toggleNotification() {
      if (!this.enableNotification) {
        this.enableNotification = true
        localStorage.setItem('newsNotificationEnabled', 'true')
        this.requestNotificationPermission()
      } else {
        this.enableNotification = false
        localStorage.setItem('newsNotificationEnabled', 'false')
      }
    },

    async requestNotificationPermission() {
      if (!('Notification' in window)) {
        alert('您的浏览器不支持系统通知功能')
        this.enableNotification = false
        localStorage.setItem('newsNotificationEnabled', 'false')
        return
      }
      
      if (Notification.permission === 'granted') {
        return
      }
      
      if (Notification.permission === 'denied') {
        const guide = '您之前已禁止通知权限。\n\n请在浏览器地址栏左侧点击"锁"图标，\n找到"通知"选项并选择"允许"，\n然后刷新页面即可。'
        alert(guide)
        this.enableNotification = false
        localStorage.setItem('newsNotificationEnabled', 'false')
        return
      }
      
      const permission = await Notification.requestPermission()
      if (permission === 'granted') {
        try {
          if (typeof Notification === 'function') {
            new Notification('通知已开启', {
              body: '您将收到重要新闻的推送提醒',
              icon: 'https://pic.0vk.top/%E8%82%A1%E7%A5%A8.png'
            })
          }
        } catch (e) {
          console.log('当前浏览器不支持直接创建通知')
        }
      } else if (permission === 'denied') {
        alert('您拒绝了通知权限，如需开启请在浏览器地址栏左侧设置')
        this.enableNotification = false
        localStorage.setItem('newsNotificationEnabled', 'false')
      } else {
        this.enableNotification = false
        localStorage.setItem('newsNotificationEnabled', 'false')
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
          requireInteraction: this.isImportant(news.importance)
        })
        
        notification.onclick = () => {
          window.focus()
          if (news.url) {
            window.open(news.url, '_blank')
          }
          notification.close()
        }
      } catch (e) {
        console.log('发送通知失败，当前浏览器可能不支持:', e.message)
      }
    },

    formatTime(timeStr) {
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

    formatDate(timeStr) {
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
        
        const today = new Date()
        const yesterday = new Date(today)
        yesterday.setDate(yesterday.getDate() - 1)
        
        if (date.toDateString() === today.toDateString()) {
          return '今天'
        } else if (date.toDateString() === yesterday.toDateString()) {
          return '昨天'
        } else {
          return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit'
          })
        }
      } catch (e) {
        return ''
      }
    },

    shouldShowDateDivider(news, index) {
      if (index === 0) return true
      
      const prevNews = this.displayNewsList[index - 1]
      const currentDate = this.getDateString(news.time)
      const prevDate = this.getDateString(prevNews.time)
      
      return currentDate !== prevDate
    },

    getDateScoreSummary(timeStr) {
      const dateStr = this.getDateString(timeStr)
      if (!dateStr) return ''
      
      // 从后端获取的统计数据中查找
      const summary = this.scoreSummary[dateStr]
      return summary ? summary.text : ''
    },

    getDateString(timeStr) {
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
          return ''
        }
        
        // 返回 YYYY-MM-DD 格式，与后端保持一致
        const year = date.getFullYear()
        const month = String(date.getMonth() + 1).padStart(2, '0')
        const day = String(date.getDate()).padStart(2, '0')
        return `${year}-${month}-${day}`
      } catch (e) {
        return ''
      }
    },

    loadMore() {
      if (this.hasMore && !this.loading) {
        this.loadNextPage()
      }
    },
    
    async loadNextPage() {
      if (this.loading || !this.hasMore) {
        return
      }
      
      try {
        this.loading = true
        
        if (this.isSearching && this.searchKeyword && this.searchKeyword.trim()) {
          this.currentSearchPage++
          const importance = this.showOnlyImportant ? '3' : null
          const response = await searchNews(this.searchKeyword, this.currentSearchPage, this.pageSize, importance)
          if (response.success) {
            const newNews = response.data
            this.newsList = [...this.newsList, ...newNews]
            if (response.pagination) {
              this.hasMore = response.pagination.has_more
            }
          }
        } else {
          this.currentApiPage++
          const importance = this.showOnlyImportant ? '3' : null
          const response = await getNews(this.currentApiPage, this.pageSize, importance)
          if (response.success) {
            const newNews = response.data
            this.newsList = [...this.newsList, ...newNews]
            if (response.pagination) {
              this.hasMore = response.pagination.has_more
            }
          }
        }
      } catch (err) {
        console.error('加载更多新闻失败:', err)
        if (this.isSearching && this.searchKeyword && this.searchKeyword.trim()) {
          this.currentSearchPage--
        } else {
          this.currentApiPage--
        }
      } finally {
        this.loading = false
      }
    },

    getNewsSource(news) {
      if (news.content) {
        const patterns = [
          /（([^）]+)）\s*$/,
          /\(([^)]+)\)\s*$/
        ]
        
        for (const pattern of patterns) {
          const match = news.content.match(pattern)
          if (match && match[1]) {
            return match[1]
          }
        }
      }
      
      if (news.source && news.source.trim()) {
        return news.source.trim()
      }
      
      return ''
    },

    getProcessedContent(news) {
      if (!news.content) return ''
      
      let content = news.content
        .replace(/（[^）]+）\s*$/, '')
        .replace(/\([^)]+\)\s*$/, '')
      
      return content.trim()
    },

    isImportant(importance) {
      return importance === '3'
    },

    openNews(url) {
      if (url) {
        window.open(url, '_blank')
      }
    },

    async fetchSystemHealth() {
      try {
        const data = await getHealth()
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
    },

    handleScroll() {
      // 滚动超过500px时显示回到顶部按钮
      this.showBackToTop = window.scrollY > 500
    },

    scrollToTop() {
      window.scrollTo({
        top: 0,
        behavior: 'smooth'
      })
    },

    async analyzeNewsItem(news) {
      // 防止重复点击
      if (this.analyzingNewsId) return
      
      this.currentAnalysisNews = news
      this.newsAnalysisResult = null
      this.newsAnalysisError = null
      this.newsAnalysisDuration = null
      this.showNewsAnalysisModal = true
      
      // 如果新闻已有AI评分（说明已分析过），显示加载缓存状态
      const hasCache = news.ai_score != null
      if (hasCache) {
        this.newsAnalysisResult = '正在加载缓存分析...'
      } else {
        this.analyzingNewsId = news.id
      }
      
      try {
        const response = await analyzeNews(news.title, this.getProcessedContent(news), news.id)
        
        if (response.success) {
          this.newsAnalysisResult = response.analysis
          this.newsAnalysisDuration = response.duration
          
          // 如果是实时分析（非缓存），更新新闻列表中的评分
          if (!response.cached && news.id) {
            const newsItem = this.newsList.find(n => n.id === news.id)
            if (newsItem) {
              // 从分析结果中提取评分和标签
              const scoreMatch = response.analysis.match(/(\d+)\/100/)
              if (scoreMatch) {
                newsItem.ai_score = parseInt(scoreMatch[1])
                newsItem.ai_label = newsItem.ai_score > 50 ? '利好' : (newsItem.ai_score < 50 ? '利空' : '中性')
              }
            }
            // 更新评分统计和趋势图
            this.loadScoreSummary()
            this.loadScoreTrend()
          }
        } else {
          this.newsAnalysisError = response.message || 'AI分析失败'
        }
      } catch (error) {
        this.newsAnalysisError = error.message || 'AI分析请求失败'
      } finally {
        this.analyzingNewsId = null
      }
    },

    closeNewsAnalysisModal() {
      this.showNewsAnalysisModal = false
      this.newsAnalysisResult = null
      this.newsAnalysisError = null
      this.newsAnalysisDuration = null
      this.currentAnalysisNews = null
    },

    getScoreClass(score) {
      if (score == null) return ''
      if (score > 50) return 'score-positive'
      if (score < 50) return 'score-negative'
      return 'score-neutral'
    }
  }
}
