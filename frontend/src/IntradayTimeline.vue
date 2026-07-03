<template>
  <div class="timeline-page">
    <header class="timeline-header">
      <div>
        <button class="timeline-back" @click="goBack">返回</button>
        <h1>盘中事件时间轴</h1>
      </div>
      <div class="timeline-actions">
        <input type="date" v-model="selectedDate" class="timeline-date" />
        <button class="timeline-refresh" :disabled="loading" @click="fetchTimeline">
          {{ loading ? '加载中...' : '刷新' }}
        </button>
      </div>
    </header>

    <main class="timeline-main">
      <div class="timeline-tabs">
        <button
          v-for="item in categories"
          :key="item.value"
          class="timeline-tab"
          :class="{ active: activeCategory === item.value }"
          @click="activeCategory = item.value"
        >
          <span>{{ item.label }}</span>
          <b>{{ categoryCount(item.value) }}</b>
        </button>
      </div>

      <section class="timeline-list">
        <div v-if="loading" class="timeline-state">正在读取盘中事件...</div>
        <div v-else-if="error" class="timeline-state error">{{ error }}</div>
        <div v-else-if="!filteredEvents.length" class="timeline-state">暂无事件</div>
        <article
          v-for="event in filteredEvents"
          :key="event.id"
          class="timeline-item"
          :class="`category-${event.category}`"
        >
          <div class="timeline-time">{{ event.time }}</div>
          <div class="timeline-body">
            <div class="timeline-title-row">
              <span class="timeline-badge">{{ categoryLabel(event.category) }}</span>
              <h2>{{ event.title }}</h2>
              <span class="timeline-importance">重要度 {{ event.importance }}</span>
            </div>
            <p v-if="event.detail">{{ event.detail }}</p>
            <div class="timeline-meta">
              <span>{{ event.source }}</span>
              <span v-if="event.target">{{ event.target }}</span>
              <a v-if="event.url" :href="event.url" target="_blank" rel="noopener noreferrer">打开来源</a>
            </div>
          </div>
        </article>
      </section>
    </main>
  </div>
</template>

<script>
import { getIntradayTimeline } from './services/apiService'

function today() {
  const d = new Date()
  const yyyy = d.getFullYear()
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

export default {
  name: 'IntradayTimeline',
  data() {
    return {
      loading: false,
      error: '',
      selectedDate: today(),
      events: [],
      activeCategory: 'all',
      categories: [
        { value: 'all', label: '全部' },
        { value: 'sector', label: '板块' },
        { value: 'news', label: '新闻' },
        { value: 'market', label: '大盘' },
        { value: 'stock', label: '个股' },
        { value: 'strategy', label: '策略' }
      ]
    }
  },
  computed: {
    filteredEvents() {
      const list = this.activeCategory === 'all'
        ? this.events
        : this.events.filter(item => item.category === this.activeCategory)
      return [...list].sort((a, b) => String(b.time || '').localeCompare(String(a.time || '')))
    }
  },
  mounted() {
    this.fetchTimeline()
  },
  methods: {
    async fetchTimeline() {
      this.loading = true
      this.error = ''
      try {
        const res = await getIntradayTimeline(this.selectedDate)
        if (res && res.success) {
          this.events = Array.isArray(res.events) ? res.events : []
        } else {
          this.error = (res && res.error) || '读取事件失败'
        }
      } catch (err) {
        this.error = '读取事件失败'
      } finally {
        this.loading = false
      }
    },
    categoryCount(category) {
      if (category === 'all') return this.events.length
      return this.events.filter(item => item.category === category).length
    },
    categoryLabel(category) {
      const found = this.categories.find(item => item.value === category)
      return found ? found.label : category
    },
    goBack() {
      this.$router.push('/')
    }
  }
}
</script>

<style scoped>
.timeline-page {
  min-height: 100vh;
  background: #08111f;
  color: #e5edf7;
  padding: 18px;
  box-sizing: border-box;
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-bottom: 16px;
}

.timeline-header h1 {
  margin: 8px 0 0;
  font-size: 24px;
  letter-spacing: 0;
}

.timeline-back,
.timeline-refresh,
.timeline-tab {
  border: 1px solid rgba(111, 142, 190, 0.4);
  background: #121d2e;
  color: #d7e4f5;
  border-radius: 6px;
  padding: 7px 12px;
  cursor: pointer;
}

.timeline-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.timeline-date {
  color: #e5edf7;
  background: #101827;
  border: 1px solid rgba(111, 142, 190, 0.4);
  border-radius: 6px;
  padding: 7px 10px;
}

.timeline-main {
  max-width: 1180px;
  margin: 0 auto;
}

.timeline-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}

.timeline-tab {
  display: inline-flex;
  gap: 8px;
  align-items: center;
}

.timeline-tab.active {
  border-color: #4ea1ff;
  background: #183456;
}

.timeline-tab b {
  color: #7cc4ff;
}

.timeline-list {
  display: grid;
  gap: 8px;
}

.timeline-state {
  padding: 26px;
  text-align: center;
  color: #9db0ca;
  background: #101827;
  border: 1px solid rgba(111, 142, 190, 0.22);
  border-radius: 8px;
}

.timeline-state.error {
  color: #ff8a8a;
}

.timeline-item {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(111, 142, 190, 0.22);
  border-left: 4px solid #6f8ebe;
  border-radius: 8px;
  background: #101827;
}

.timeline-item.category-sector { border-left-color: #4ea1ff; }
.timeline-item.category-news { border-left-color: #f59e0b; }
.timeline-item.category-market { border-left-color: #a78bfa; }
.timeline-item.category-stock { border-left-color: #10b981; }
.timeline-item.category-strategy { border-left-color: #ef4444; }

.timeline-time {
  font-size: 18px;
  font-weight: 700;
  color: #9bd1ff;
}

.timeline-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.timeline-title-row h2 {
  margin: 0;
  font-size: 16px;
  letter-spacing: 0;
}

.timeline-badge {
  color: #06101f;
  background: #9bd1ff;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 12px;
  font-weight: 700;
}

.timeline-importance,
.timeline-meta {
  color: #8fa6c2;
  font-size: 12px;
}

.timeline-body p {
  margin: 7px 0;
  color: #c5d4e8;
  line-height: 1.5;
}

.timeline-meta {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.timeline-meta a {
  color: #7cc4ff;
}
</style>
