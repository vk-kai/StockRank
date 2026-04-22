<template>
  <div class="dashboard">
    <header class="header">
      <div class="header-title-row">
        <h1>A股板块资金流入统计</h1>
        <a href="https://github.com/vk-kai/StockRank" target="_blank" class="github-link">
          <svg class="github-icon" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
          </svg>
          <span>GitHub</span>
        </a>
      </div>
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
          🤖 AI配置
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

    <div class="market-overview" v-if="marketData">
      <div class="market-section">
        <div class="market-title">📊 大盘指数</div>
        <div class="index-cards">
          <div 
            v-for="(index, code) in marketData.indices" 
            :key="code" 
            class="index-card"
            :class="{ 'up': index.change > 0, 'down': index.change < 0 }"
          >
            <div class="index-name">{{ index.name }}</div>
            <div class="index-price">{{ index.price.toFixed(2) }}</div>
            <div class="index-change">
              <span class="change-percent">{{ index.change > 0 ? '+' : '' }}{{ (index.change * 100).toFixed(2) }}%</span>
              <span class="change-amount">{{ index.change_amount > 0 ? '+' : '' }}{{ index.change_amount.toFixed(2) }}</span>
            </div>
          </div>
        </div>
      </div>
      
      <div class="market-section">
        <div class="market-title">📈 涨跌统计</div>
        <div class="stats-cards">
          <div class="stat-card up">
            <div class="stat-value">{{ marketData.stats.up_count }}</div>
            <div class="stat-label">上涨</div>
          </div>
          <div class="stat-card down">
            <div class="stat-value">{{ marketData.stats.down_count }}</div>
            <div class="stat-label">下跌</div>
          </div>
          <div class="stat-card flat">
            <div class="stat-value">{{ marketData.stats.flat_count }}</div>
            <div class="stat-label">平盘</div>
          </div>
          <div class="stat-card limit-up">
            <div class="stat-value">{{ marketData.stats.limit_up_count }}</div>
            <div class="stat-label">涨停</div>
          </div>
          <div class="stat-card limit-down">
            <div class="stat-value">{{ marketData.stats.limit_down_count }}</div>
            <div class="stat-label">跌停</div>
          </div>
        </div>
      </div>
      
      <div class="market-section">
        <div class="market-title">💰 成交量</div>
        <div class="volume-info">
          <div class="volume-value">{{ formatVolume(marketData.stats.total_volume) }}</div>
          <div class="volume-label">今日总成交额</div>
        </div>
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
