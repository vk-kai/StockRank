<template>
  <div class="dashboard">
    <header class="header">
      <h1>A股板块资金流入统计</h1>
      <div class="controls">
        <div class="time-selector">
          <label>时间跨度：</label>
          <select v-model="selectedTimeRange" @change="fetchDataByTimeRange">
            <option :value="'today'">当天</option>
            <option :value="7">最近7天</option>
            <option :value="15">最近15天</option>
            <option :value="30">最近30天</option>
          </select>
        </div>
        <div class="last-update" v-if="lastUpdate">
          最后更新: {{ lastUpdate }}
        </div>
        <div class="countdown">
          下次刷新: {{ countdownMinutes }}:{{ countdownSeconds }}
        </div>
        <button class="config-button" @click="goToConfig">
          ⚙️ 配置
        </button>
        <button class="log-button" @click="goToLogs">
          📋 日志
        </button>
      </div>
    </header>

    <div class="monitor-card-container" @click="refreshHealth">
      <div class="monitor-card-header">
        <span class="monitor-card-label">📡 服务监控</span>
      </div>
      <div class="monitor-card-body">
        <div 
          v-for="(thread, key) in threadStatus" 
          :key="key" 
          class="monitor-card-row"
          :class="thread.status === 'running' ? 'monitor-ok' : 'monitor-error'"
        >
          <span class="monitor-dot"></span>
          <span class="monitor-name">{{ getThreadLabel(key) }}</span>
          <span class="monitor-text">{{ thread.status === 'running' ? '运行正常' : '已停止' }}</span>
        </div>
        <div v-if="Object.keys(threadStatus).length === 0" class="monitor-card-row monitor-loading">
          <span class="monitor-dot"></span>
          <span class="monitor-text">检测中...</span>
        </div>
      </div>
    </div>

    <div class="news-ticker-container" v-if="latestNews.length > 0">
      <div class="news-ticker-header">
        <span class="ticker-label">📰 最新新闻</span>
        <button class="view-more-news" @click="goToNews">更多 →</button>
      </div>
      <div class="news-ticker-content">
        <transition name="fade" mode="out-in">
          <div 
            :key="currentNewsIndex" 
            class="ticker-item" 
            @click="openNews(latestNews[currentNewsIndex].url)"
          >
            <div class="news-time">{{ formatNewsTime(latestNews[currentNewsIndex].timestamp) }}</div>
            <div class="news-title">
              <span v-if="latestNews[currentNewsIndex].importance === '3'" class="important-badge">重要</span>
              {{ latestNews[currentNewsIndex].title }}
            </div>
          </div>
        </transition>
      </div>
    </div>

    <div class="chart-container" ref="chartContainer">
      <div ref="chart" class="chart"></div>
    </div>

    <div class="sector-list" v-if="currentData.length > 0">
      <h3 class="sector-title">今日资金流入TOP10</h3>
      <div class="sector-grid">
        <div 
          v-for="sector in currentData.slice(0, 10)" 
          :key="sector.rank"
          class="sector-card"
          :class="{ 'top-3': sector.rank <= 3 }"
          @mouseenter="highlightSector(sector.name)"
          @mouseleave="unhighlightSector()"
        >
          <div class="rank">{{ sector.rank }}</div>
          <div class="name">{{ sector.name }}</div>
          <div class="flow">流入: {{ formatFlow(sector.flow) }}</div>
          <div class="change" :class="{ 'positive': sector.change > 0, 'negative': sector.change < 0 }">
            {{ sector.change > 0 ? '+' : '' }}{{ (sector.change * 100).toFixed(2) }}%
            <span class="trend-arrow">
              {{ sector.change > 0 ? '↑' : (sector.change < 0 ? '↓' : '→') }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="loading" v-if="loading && !chartInstance">
      <div class="spinner"></div>
      <p>加载数据中...</p>
    </div>

    <div class="error" v-if="error">
      <p>{{ error }}</p>
      <button @click="retry">重试</button>
    </div>
  </div>
</template>

<script src="./components/App/App.script.js"></script>
