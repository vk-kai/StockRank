import { getNews, getHealth, searchNews, isSecurityError, analyzeNews } from '../../services/apiService'
import { marked } from 'marked'
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
      currentAnalysisNews: null
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
    }
  },
  mounted() {
    this.loadNotificationState()
    this.loadFilterState()
    this.fetchNews()
    this.startCountdown()
    this.fetchSystemHealth()
    this.startHealthCheck()
    
    // 监听滚动事件
    window.addEventListener('scroll', this.handleScroll)
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
      }
    },

    retry() {
      this.error = null
      this.fetchNews()
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
        
        return date.toDateString()
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
      
      // 如果新闻已有AI评分（说明已分析过），直接请求缓存结果
      try {
        const response = await analyzeNews(news.title, this.getProcessedContent(news), news.id)
        
        if (response.success) {
          this.newsAnalysisResult = response.analysis
          this.newsAnalysisDuration = response.duration
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
