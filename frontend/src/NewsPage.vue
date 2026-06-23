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
      <div class="search-box">
        <input 
          type="text" 
          v-model="searchKeyword" 
          :placeholder="isSearching ? '搜索中...' : '搜索新闻...'" 
          class="search-input"
          :class="{ 'searching': isSearching }"
          @input="handleSearch"
          :disabled="isSearching"
        />
        <button 
          v-if="searchKeyword && !isSearching" 
          class="search-clear" 
          @click="clearSearch"
          title="清除搜索"
        >
          ✕
        </button>
        <div v-if="isSearching" class="search-spinner"></div>
      </div>
      <div class="last-update" v-if="lastUpdate">
        最后更新: {{ lastUpdate }}
      </div>
      <div class="countdown">
        下次刷新: {{ countdownSeconds }}秒
      </div>
    </div>

    <!-- 今日利好利空分布图 -->
    <div class="score-trend-section">
      <div class="score-trend-header">
        <h3 class="score-trend-title">📊 今日利好利空分布</h3>
        <div class="score-trend-summary" v-if="scoreTrendData.summary">
          <span class="tendency-badge" :class="tendencyClass">
            {{ scoreTrendData.summary.tendency }}
          </span>
          <span class="summary-item positive">利好 {{ scoreTrendData.summary.total_positive }}</span>
          <span class="summary-item negative">利空 {{ scoreTrendData.summary.total_negative }}</span>
          <span class="summary-item neutral">中性 {{ scoreTrendData.summary.total_neutral }}</span>
          <button 
            class="market-hours-toggle"
            :class="{ 'active': onlyMarketHours }"
            @click="toggleMarketHours"
            :title="onlyMarketHours ? '显示盘前盘后' : '仅看盘中'"
          >
            {{ onlyMarketHours ? '🕐 仅盘中' : '🕐 全部时段' }}
          </button>
        </div>
      </div>
      <div class="score-charts-wrapper">
        <div ref="scoreTrendChart" class="score-trend-chart"></div>
        <div ref="scorePieChart" class="score-pie-chart"></div>
      </div>
    </div>

    <div class="news-list" v-if="displayNewsList.length > 0">
      <template v-for="(news, index) in displayNewsList" :key="news.id">
        <div 
          v-if="shouldShowDateDivider(news, index)"
          class="date-divider"
        >
          <span class="date-text">{{ formatDate(news.time) }}</span>
          <span class="date-summary" v-if="getDateScoreSummary(news.time)">
            {{ getDateScoreSummary(news.time) }}
          </span>
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
              <span 
                v-if="news.ai_score != null" 
                class="news-score-badge" 
                :class="getScoreClass(news.ai_score)"
              >
                {{ news.ai_label }}（{{ news.ai_score }}）
              </span>
              <div class="news-source-badge" v-if="getNewsSource(news)">
                {{ getNewsSource(news) }}
              </div>
              <button 
                class="news-ai-btn" 
                @click.stop="analyzeNewsItem(news)"
                :disabled="analyzingNewsId !== null"
                :title="'AI分析此新闻'"
              >
                <span v-if="analyzingNewsId === news.id" class="ai-btn-spinner"></span>
                <span v-else>🤖</span>
              </button>
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

    <button 
      class="back-to-top" 
      @click="scrollToTop"
      :class="{ 'visible': showBackToTop }"
      title="回到顶部"
    >
      ↑
    </button>

    <!-- 新闻AI分析弹窗 -->
    <div class="news-ai-modal-overlay" v-if="showNewsAnalysisModal" @click.self="closeNewsAnalysisModal">
      <div class="news-ai-modal">
        <div class="news-ai-modal-header">
          <h3>🤖 AI新闻分析</h3>
          <div class="news-ai-header-right">
            <span v-if="newsAnalysisDuration" class="news-ai-duration">耗时 {{ newsAnalysisDuration }}s</span>
            <button class="news-ai-close" @click="closeNewsAnalysisModal">✕</button>
          </div>
        </div>
        <div class="news-ai-modal-source" v-if="currentAnalysisNews">
          {{ currentAnalysisNews.title }}
        </div>
        <div class="news-ai-modal-body">
          <div v-if="analyzingNewsId" class="news-ai-loading">
            <div class="spinner"></div>
            <p>AI正在分析中...</p>
          </div>
          <div v-else-if="newsAnalysisError" class="news-ai-error">
            <p>{{ newsAnalysisError }}</p>
          </div>
          <div v-else-if="newsAnalysisResult && newsAnalysisResult !== '正在加载缓存分析...'" class="news-ai-analysis-content" v-html="renderedNewsAnalysis"></div>
          <div v-else-if="newsAnalysisResult === '正在加载缓存分析...'" class="news-ai-loading-cache">
            <div class="spinner-small"></div>
            <p>{{ newsAnalysisResult }}</p>
          </div>
        </div>
      </div>
    </div>

    <SecurityAlert />
  </div>
</template>

<script src="./components/NewsPage/NewsPage.script.js"></script>
<style src="./components/NewsPage/NewsPage.style.css"></style>
