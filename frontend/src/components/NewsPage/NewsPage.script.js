import { getNews, getSystemHealth } from '../../services/apiService'

export default {
  name: 'NewsPage',
  data() {
    return {
      newsList: [],
      loading: false,
      error: null,
      lastUpdate: null,
      countdown: 30,
      countdownInterval: null,
      currentPage: 1,
      pageSize: 20,
      enableNotification: true,
      lastNewsId: null,
      showOnlyImportant: false,
      threadStatus: {},
      healthCheckInterval: null
    }
  },
  computed: {
    countdownSeconds() {
      return this.countdown.toString().padStart(2, '0')
    },
    filteredNewsList() {
      if (this.showOnlyImportant) {
        return this.newsList.filter(news => this.isImportant(news.importance))
      }
      return this.newsList
    },
    displayNewsList() {
      return this.filteredNewsList.slice(0, this.currentPage * this.pageSize)
    },
    hasMoreNews() {
      return this.currentPage * this.pageSize < this.filteredNewsList.length
    },
    remainingNews() {
      return this.filteredNewsList.length - this.currentPage * this.pageSize
    }
  },
  mounted() {
    this.loadNotificationState()
    this.loadFilterState()
    this.fetchNews()
    this.startCountdown()
    this.fetchSystemHealth()
    this.startHealthCheck()
  },
  beforeUnmount() {
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval)
    }
    if (this.healthCheckInterval) {
      clearInterval(this.healthCheckInterval)
    }
  },
  methods: {
    goBack() {
      this.$router.go(-1)
    },

    async fetchNews() {
      try {
        this.loading = true
        this.error = null
        const response = await getNews(200)
        if (response.success) {
          const newNews = response.data
          
          if (this.newsList.length > 0 && this.enableNotification) {
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
          this.fetchNews()
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
      this.currentPage = 1
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
        new Notification('通知已开启', {
          body: '您将收到重要新闻的推送提醒',
          icon: 'https://pic.0vk.top/%E8%82%A1%E7%A5%A8.png'
        })
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
      this.currentPage++
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
