<template>
  <div class="news-page">
    <header class="news-page-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>📰 实时新闻</h1>
      <div class="header-spacer"></div>
    </header>
    
    <div class="news-controls">
      <button 
        class="filter-toggle"
        :class="{ 'active': showOnlyImportant }"
        @click="toggleImportantFilter"
        :title="showOnlyImportant ? '显示全部新闻' : '仅显示重要新闻'"
      >
        {{ showOnlyImportant ? '⭐ 仅重要' : '📰 全部' }}
      </button>
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

<script src="./components/NewsPage/NewsPage.script.js"></script>
<style scoped src="./components/NewsPage/NewsPage.style.css"></style>
