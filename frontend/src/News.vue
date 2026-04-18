<template>
  <div class="news-container">
    <div class="news-header">
      <h2>📰 实时新闻</h2>
      <div class="news-controls">
        <div class="last-update" v-if="lastUpdate">
          最后更新: {{ lastUpdate }}
        </div>
        <div class="countdown">
          下次刷新: {{ countdownSeconds }}秒
        </div>
      </div>
    </div>

    <div class="news-list" v-if="newsList.length > 0">
      <div 
        v-for="(news, index) in newsList" 
        :key="news.id"
        class="news-item"
        :class="{ 'is-new': isNewNews(news.timestamp) }"
      >
        <div class="news-time">{{ formatTime(news.time) }}</div>
        <div class="news-content">
          <div class="news-title">{{ news.title }}</div>
          <div class="news-source">来源: {{ news.source }}</div>
        </div>
        <a :href="news.url" target="_blank" class="news-link">查看详情 →</a>
      </div>
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
  name: 'News',
  data() {
    return {
      newsList: [],
      loading: false,
      error: null,
      lastUpdate: null,
      countdown: 15,
      countdownInterval: null
    }
  },
  computed: {
    countdownSeconds() {
      return this.countdown.toString().padStart(2, '0')
    }
  },
  mounted() {
    this.fetchNews()
    this.startCountdown()
  },
  beforeUnmount() {
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval)
    }
  },
  methods: {
    async fetchNews() {
      try {
        this.loading = true
        this.error = null
        const response = await getNews(50)
        if (response.success) {
          this.newsList = response.data
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

    formatTime(timeStr) {
      if (!timeStr) return ''
      
      try {
        const date = new Date(timeStr)
        if (isNaN(date.getTime())) {
          return timeStr
        }
        
        const now = new Date()
        const diff = now - date
        const minutes = Math.floor(diff / 60000)
        const hours = Math.floor(diff / 3600000)
        
        if (minutes < 1) return '刚刚'
        if (minutes < 60) return `${minutes}分钟前`
        if (hours < 24) return `${hours}小时前`
        
        return date.toLocaleString('zh-CN', {
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        })
      } catch (e) {
        return timeStr
      }
    },

    isNewNews(timestamp) {
      if (!timestamp) return false
      
      try {
        const newsTime = new Date(timestamp)
        const now = new Date()
        const diff = now - newsTime
        return diff < 3600000
      } catch (e) {
        return false
      }
    }
  }
}
</script>

<style scoped>
.news-container {
  background: linear-gradient(135deg, #1a1f35 0%, #2d3561 100%);
  border-radius: 12px;
  padding: 20px;
  margin-top: 20px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
}

.news-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 2px solid rgba(255, 255, 255, 0.1);
}

.news-header h2 {
  color: #fff;
  font-size: 24px;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.news-controls {
  display: flex;
  gap: 20px;
  align-items: center;
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
  max-height: 600px;
  overflow-y: auto;
}

.news-list::-webkit-scrollbar {
  width: 8px;
}

.news-list::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 4px;
}

.news-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 4px;
}

.news-list::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.3);
}

.news-item {
  background: rgba(255, 255, 255, 0.05);
  border-radius: 8px;
  padding: 15px;
  margin-bottom: 12px;
  transition: all 0.3s ease;
  border-left: 3px solid transparent;
}

.news-item:hover {
  background: rgba(255, 255, 255, 0.08);
  border-left-color: #4fc3f7;
  transform: translateX(5px);
}

.news-item.is-new {
  background: rgba(79, 195, 247, 0.1);
  border-left-color: #4fc3f7;
}

.news-time {
  color: #4fc3f7;
  font-size: 12px;
  margin-bottom: 8px;
  font-weight: 500;
}

.news-content {
  margin-bottom: 10px;
}

.news-title {
  color: #fff;
  font-size: 16px;
  line-height: 1.5;
  margin-bottom: 8px;
  font-weight: 500;
}

.news-source {
  color: #8ba4c7;
  font-size: 12px;
}

.news-link {
  color: #4fc3f7;
  text-decoration: none;
  font-size: 14px;
  transition: color 0.3s ease;
  display: inline-block;
}

.news-link:hover {
  color: #81d4fa;
  text-decoration: underline;
}

.loading,
.error,
.no-news {
  text-align: center;
  padding: 40px;
  color: #8ba4c7;
}

.spinner {
  border: 3px solid rgba(255, 255, 255, 0.1);
  border-top: 3px solid #4fc3f7;
  border-radius: 50%;
  width: 40px;
  height: 40px;
  animation: spin 1s linear infinite;
  margin: 0 auto 15px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.error button {
  background: #4fc3f7;
  color: #fff;
  border: none;
  padding: 10px 20px;
  border-radius: 5px;
  cursor: pointer;
  margin-top: 10px;
  transition: background 0.3s ease;
}

.error button:hover {
  background: #81d4fa;
}

@media (max-width: 768px) {
  .news-header {
    flex-direction: column;
    gap: 10px;
    align-items: flex-start;
  }
  
  .news-controls {
    width: 100%;
    justify-content: space-between;
  }
  
  .news-item {
    padding: 12px;
  }
  
  .news-title {
    font-size: 14px;
  }
}
</style>
