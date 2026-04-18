<template>
  <div class="news-page">
    <header class="news-page-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>📰 实时新闻</h1>
      <div class="news-controls">
        <button 
          class="notification-toggle" 
          :class="{ 'active': enableNotification }"
          @click="toggleNotification"
          :title="enableNotification ? '关闭新闻提醒' : '开启新闻提醒'"
        >
          {{ enableNotification ? '🔔 提醒已开启' : '🔕 提醒已关闭' }}
        </button>
        <div class="last-update" v-if="lastUpdate">
          最后更新: {{ lastUpdate }}
        </div>
        <div class="countdown">
          下次刷新: {{ countdownSeconds }}秒
        </div>
      </div>
    </header>

    <div class="news-list" v-if="displayNewsList.length > 0">
      <template v-for="(news, index) in displayNewsList" :key="news.id">
        <div 
          v-if="shouldShowDateDivider(news, index)"
          class="date-divider"
        >
          {{ formatDate(news.time) }}
        </div>
        <div 
          class="news-item"
          :class="{ 'is-important': isImportant(news.importance) }"
        >
          <div class="news-time">{{ formatTime(news.time) }}</div>
          <div class="news-content">
            <div class="news-header">
              <div class="news-title" @click="openNews(news.url)">
                {{ news.title }}
              </div>
              <div class="news-source-badge" v-if="getNewsSource(news)">
                {{ getNewsSource(news) }}
              </div>
            </div>
            <div class="news-preview">{{ getProcessedContent(news) }}</div>
          </div>
        </div>
      </template>
    </div>

    <div class="load-more-container" v-if="hasMoreNews && !loading">
      <button @click="loadMore" class="load-more-btn">加载更多 ({{ remainingNews }}条剩余)</button>
    </div>

    <div class="loading-more" v-if="loading && newsList.length > 0">
      <div class="spinner-small"></div>
      <p>加载中...</p>
    </div>

    <div class="loading" v-if="loading && newsList.length === 0">
      <div class="spinner"></div>
      <p>加载新闻中...</p>
    </div>

    <div class="error" v-if="error">
      <p>{{ error }}</p>
      <button @click="retry">重试</button>
    </div>

    <div class="no-news" v-if="!loading && newsList.length === 0">
      <p>暂无新闻数据</p>
    </div>
  </div>
</template>

<script>
import { getNews } from './services/apiService'

export default {
  name: 'NewsPage',
  data() {
    return {
      newsList: [],
      loading: false,
      error: null,
      lastUpdate: null,
      countdown: 15,
      countdownInterval: null,
      currentPage: 1,
      pageSize: 20,
      enableNotification: true,
      lastNewsId: null
    }
  },
  computed: {
    countdownSeconds() {
      return this.countdown.toString().padStart(2, '0')
    },
    displayNewsList() {
      return this.newsList.slice(0, this.currentPage * this.pageSize)
    },
    hasMoreNews() {
      return this.currentPage * this.pageSize < this.newsList.length
    },
    remainingNews() {
      return this.newsList.length - this.currentPage * this.pageSize
    }
  },
  mounted() {
    this.loadNotificationState()
    this.fetchNews()
    this.startCountdown()
  },
  beforeUnmount() {
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval)
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
              const importantNews = newNews.find(n => n.id === latestId && this.isImportant(n.importance))
              if (importantNews) {
                this.sendNotification(importantNews)
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
          this.countdown = 15
        }
      }, 1000)
    },

    loadNotificationState() {
      const saved = localStorage.getItem('newsNotificationEnabled')
      if (saved !== null) {
        this.enableNotification = saved === 'true'
      }
      if (this.enableNotification) {
        this.requestNotificationPermission()
      }
    },

    toggleNotification() {
      this.enableNotification = !this.enableNotification
      localStorage.setItem('newsNotificationEnabled', this.enableNotification.toString())
      if (this.enableNotification) {
        this.requestNotificationPermission()
      }
    },

    async requestNotificationPermission() {
      if (!('Notification' in window)) {
        alert('您的浏览器不支持系统通知功能')
        this.enableNotification = false
        localStorage.setItem('newsNotificationEnabled', 'false')
        return
      }
      
      if (Notification.permission === 'denied') {
        alert('您已禁止通知权限，请在浏览器设置中允许通知')
        this.enableNotification = false
        localStorage.setItem('newsNotificationEnabled', 'false')
        return
      }
      
      if (Notification.permission === 'default') {
        const permission = await Notification.requestPermission()
        if (permission !== 'granted') {
          alert('需要允许通知权限才能启用新闻提醒')
          this.enableNotification = false
          localStorage.setItem('newsNotificationEnabled', 'false')
          return
        }
      }
    },

    sendNotification(news) {
      if (!('Notification' in window) || Notification.permission !== 'granted') {
        return
      }
      
      const notification = new Notification('重要新闻提醒', {
        body: news.title,
        icon: '/favicon.ico',
        tag: news.id,
        requireInteraction: true
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
    }
  }
}
</script>

<style scoped>
.news-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #1a1f35 0%, #2d3561 100%);
  padding: 20px;
}

.news-page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
  padding-bottom: 20px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.1);
}

.back-button {
  background: rgba(79, 195, 247, 0.2);
  color: #4fc3f7;
  border: 1px solid #4fc3f7;
  padding: 10px 20px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.3s ease;
}

.back-button:hover {
  background: rgba(79, 195, 247, 0.3);
  transform: translateX(-5px);
}

.news-page-header h1 {
  color: #fff;
  font-size: 28px;
  margin: 0;
  flex: 1;
  text-align: center;
}

.news-controls {
  display: flex;
  gap: 15px;
  align-items: center;
}

.notification-toggle {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: #fff;
  padding: 8px 16px;
  border-radius: 20px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s ease;
  white-space: nowrap;
}

.notification-toggle:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
}

.notification-toggle.active {
  background: rgba(255, 193, 7, 0.3);
  border-color: #ffc107;
  animation: ring 0.5s ease;
}

@keyframes ring {
  0%, 100% { transform: rotate(0deg); }
  10%, 30%, 50%, 70%, 90% { transform: rotate(-10deg); }
  20%, 40%, 60%, 80% { transform: rotate(10deg); }
}

.last-update {
  color: #8ba4c7;
  font-size: 14px;
}

.countdown {
  color: #4fc3f7;
  font-size: 14px;
  font-weight: 500;
}

.news-list {
  max-width: 1200px;
  margin: 0 auto;
}

.date-divider {
  text-align: center;
  padding: 20px 0;
  margin: 10px 0;
  position: relative;
  color: #4fc3f7;
  font-size: 16px;
  font-weight: 600;
}

.date-divider::before,
.date-divider::after {
  content: '';
  position: absolute;
  top: 50%;
  width: 35%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(79, 195, 247, 0.5), transparent);
}

.date-divider::before {
  left: 0;
}

.date-divider::after {
  right: 0;
}

.news-item {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 16px;
  transition: all 0.3s ease;
  border-left: 4px solid transparent;
  display: flex;
  gap: 20px;
  align-items: flex-start;
}

.news-item:hover {
  background: rgba(255, 255, 255, 0.08);
  transform: translateX(5px);
}

.news-item.is-important {
  background: rgba(255, 82, 82, 0.1);
  border-left-color: #ff5252;
}

.news-item.is-important .news-title {
  color: #ff5252;
}

.news-item.is-important .news-preview {
  color: #ff5252;
}

.news-time {
  color: #4fc3f7;
  font-size: 14px;
  font-weight: 500;
  min-width: 120px;
  padding-top: 3px;
}

.news-content {
  flex: 1;
  margin-bottom: 0;
}

.news-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 15px;
  margin-bottom: 12px;
}

.news-title {
  color: #fff;
  font-size: 18px;
  line-height: 1.6;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.3s ease;
  flex: 1;
}

.news-title:hover {
  color: #4fc3f7;
}

.news-source-badge {
  background: rgba(79, 195, 247, 0.2);
  color: #4fc3f7;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  flex-shrink: 0;
}

.news-item.is-important .news-source-badge {
  background: rgba(255, 82, 82, 0.2);
  color: #ff5252;
}

.important-badge {
  background: #ff5252;
  color: #fff;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}

.news-preview {
  color: #b0bec5;
  font-size: 14px;
  line-height: 1.8;
  margin-bottom: 12px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.load-more-container {
  text-align: center;
  padding: 30px;
}

.load-more-btn {
  background: linear-gradient(135deg, #4fc3f7 0%, #29b6f6 100%);
  border: none;
  color: #fff;
  padding: 14px 40px;
  border-radius: 25px;
  cursor: pointer;
  font-size: 16px;
  font-weight: 500;
  transition: all 0.3s ease;
  box-shadow: 0 4px 15px rgba(79, 195, 247, 0.3);
}

.load-more-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(79, 195, 247, 0.4);
}

.loading-more {
  text-align: center;
  padding: 20px;
  color: #8ba4c7;
}

.spinner-small {
  border: 2px solid rgba(255, 255, 255, 0.1);
  border-top: 2px solid #4fc3f7;
  border-radius: 50%;
  width: 30px;
  height: 30px;
  animation: spin 1s linear infinite;
  margin: 0 auto 10px;
}

.loading,
.error,
.no-news {
  text-align: center;
  padding: 60px;
  color: #8ba4c7;
}

.spinner {
  border: 3px solid rgba(255, 255, 255, 0.1);
  border-top: 3px solid #4fc3f7;
  border-radius: 50%;
  width: 50px;
  height: 50px;
  animation: spin 1s linear infinite;
  margin: 0 auto 20px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.error button {
  background: #4fc3f7;
  color: #fff;
  border: none;
  padding: 12px 24px;
  border-radius: 8px;
  cursor: pointer;
  margin-top: 15px;
  transition: background 0.3s ease;
  font-size: 16px;
}

.error button:hover {
  background: #81d4fa;
}

@media (max-width: 768px) {
  .news-page-header {
    flex-direction: column;
    gap: 15px;
    align-items: flex-start;
  }
  
  .news-page-header h1 {
    font-size: 24px;
    text-align: left;
  }
  
  .news-controls {
    width: 100%;
    justify-content: space-between;
  }
  
  .news-item {
    padding: 15px;
  }
  
  .news-title {
    font-size: 16px;
  }
  
  .news-preview {
    font-size: 13px;
  }
}
</style>
