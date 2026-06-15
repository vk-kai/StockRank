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
        <div class="title-actions">
          <button class="config-button" @click="goToConfig">AI配置</button>
          <button class="log-button" @click="goToLogs">日志</button>
          <button class="house-button" @click="goToHouseKline">房价K线</button>
          <button class="quant-button" @click="openQuantSystem">📈 量化交易系统</button>
          <button class="ai-analyze-button" @click="analyzeDailyFlow" :disabled="aiAnalyzing">
            {{ aiAnalyzing ? '分析中...' : '🤖 AI分析' }}
          </button>
        </div>
      </div>
      <div class="controls">
        <div class="time-selector">
          <label>时间跨度：</label>
          <select v-model="selectedTimeRange" @change="fetchDataByTimeRange">
            <option :value="'today'">当天</option>
            <option :value="7">近7天</option>
            <option :value="15">近15天</option>
            <option :value="30">近30天</option>
          </select>
        </div>
        <div class="last-update" v-if="lastUpdate">
          最后更新：{{ lastUpdate }}
        </div>
        <div class="countdown">
          下次刷新：{{ countdownMinutes }}:{{ countdownSeconds }}
        </div>

        <div class="market-index-strip">
          <span
            v-for="indexItem in marketIndexCards"
            :key="indexItem.code"
            class="market-index-chip"
          >
            {{ indexItem.name }} {{ formatMarketNumber(indexItem.price) }}
            <span :class="getValueTrendClass(indexItem.change)">
              {{ formatMarketPercent(indexItem.change) }}
            </span>
          </span>
        </div>

        <button class="config-button" @click="goToConfig">
          AI配置
        </button>
        <button class="log-button" @click="goToLogs">
          日志
        </button>
        <button class="house-button" @click="goToHouseKline">
          房价K线
        </button>
      </div>
    </header>

    <div class="market-summary-panel">
      <div class="market-breadth-row">
        <span class="market-down">跌{{ formatMarketNumber(marketSummary?.breadth?.down_count) }}</span>
        <span class="market-up">涨{{ formatMarketNumber(marketSummary?.breadth?.up_count) }}</span>
      </div>
      <div class="market-breadth-bar" aria-label="上涨下跌比例">
        <div class="market-breadth-fill market-breadth-fill-down" :style="{ width: getBreadthPercent('down') }"></div>
        <div class="market-breadth-divider"></div>
        <div class="market-breadth-fill market-breadth-fill-up" :style="{ width: getBreadthPercent('up') }"></div>
      </div>
      <div class="market-limit-row">
        <span class="market-down">跌停{{ formatMarketNumber(marketSummary?.breadth?.limit_down_count) }}</span>
        <span class="market-up">涨停{{ formatMarketNumber(marketSummary?.breadth?.limit_up_count) }}</span>
      </div>

      <div class="market-turnover-row">
        <span class="market-turnover-label">今日实时成交额</span>
        <span class="market-turnover-value">{{ formatMarketAmount(marketSummary?.turnover?.turnover, false) }}</span>
        <span class="market-turnover-spacer"></span>
        <span class="market-turnover-label">较上一日此时</span>
        <span class="market-turnover-value" :class="getValueTrendClass(marketSummary?.turnover?.turnover_change)">
          {{ formatMarketAmount(marketSummary?.turnover?.turnover_change) }}
        </span>
      </div>
    </div>

    <div class="monitor-card-container" ref="monitorCard" @click="refreshHealth">
      <div class="monitor-card-header">
        <span class="monitor-card-label">服务监控</span>
        <button class="health-check-btn" @click="refreshHealth" :disabled="healthChecking">
          {{ healthChecking ? '检测中...' : '检测' }}
        </button>
      </div>
      <div class="monitor-card-body">
        <div 
          v-for="(item, key) in healthDisplayItems" 
          :key="key" 
          class="monitor-card-row"
          :class="getMonitorRowClass(key, item)"
        >
          <span class="monitor-dot"></span>
          <span class="monitor-name">{{ getHealthLabel(key) }}</span>
          <span class="monitor-text">{{ getMonitorStatusText(key, item) }}</span>
          <span class="monitor-time" v-if="item.response_time && item.status === 'ok'">{{ item.response_time }}ms</span>
            <button class="monitor-retry-btn" v-if="getCrawlerStatus(key) === 'failed'" @click.stop="resetCrawlerStatus(getCrawlerKey(key))">
            重试
          </button>
        </div>
        <div v-if="Object.keys(healthDisplayItems).length === 0" class="monitor-card-row monitor-loading">
          <span class="monitor-dot"></span>
          <span class="monitor-text">检测中...</span>
        </div>
      </div>
    </div>

    <div class="news-ticker-container" v-if="latestNews.length > 0">
      <div class="news-ticker-header">
        <span class="ticker-label clickable" @click="goToNews">最新新闻</span>
        <div class="header-controls">
          <label class="notification-toggle">
            <input type="checkbox" :checked="enableNotification" @change="toggleNotification">
            <span class="toggle-slider"></span>
            <span class="toggle-label">{{ enableNotification ? '已开启' : '已关闭' }}</span>
          </label>
          <select v-model="soundMode" @change="saveSoundMode(soundMode)" class="sound-mode-selector">
            <option value="none">静音</option>
            <option value="important">仅重要</option>
            <option value="all">全部提醒</option>
          </select>
        </div>
      </div>
      <div class="news-ticker-content">
        <div 
          v-if="currentNewsItem"
          class="ticker-item"
          :class="{ 'important': currentNewsItem.importance === '3' }"
          @click="openNews(currentNewsItem.url)"
        >
          <div class="news-title">
            <span class="news-index">{{ currentNewsIndex + 1 }}:</span>
            <span v-if="currentNewsItem.importance === '3'" class="important-badge">閲嶈</span>
            {{ currentNewsItem.title }}
          </div>
          <div class="news-time">{{ formatNewsTime(currentNewsItem.timestamp) }}</div>
        </div>
      </div>
    </div>

    <div class="chart-container" ref="chartContainer">
      <div class="chart-controls">
        <div v-if="selectedTimeRange === 'today'" class="replay-date-selector">
          <label>回放日期：</label>
          <input 
            type="date" 
            v-model="replayDate" 
            :min="minReplayDate"
            :max="todayDate"
            @change="onReplayDateChange"
          />
        </div>
      </div>
      <div ref="chart" class="chart"></div>
      <div v-if="showChartLoading" class="chart-loading-mask">
        <div class="chart-loading-content">
          <div class="chart-loading-spinner"></div>
          <div class="chart-loading-text">正在检测服务并加载图表...</div>
        </div>
      </div>
    </div>

    <div class="sector-list" ref="sectorList" v-if="selectedTimeRange === 'today' && replayTop10Sectors.length > 0">
      <h3 class="sector-title">{{ replayTop10Title }}</h3>
      <div class="sector-grid">
        <div 
          v-for="sector in replayTop10Sectors" 
          :key="`${sector.flow_direction || sector.flow_group || 'flow'}-${sector.rank}-${sector.name}`"
          class="sector-card clickable"
          :class="{
            'top-3': sector.rank <= 3,
            'net-in-card': (sector.flow_direction || sector.flow_group) !== 'out' && (sector.flow_direction || sector.flow_group) !== 'net_out',
            'net-out-card': (sector.flow_direction || sector.flow_group) === 'out' || (sector.flow_direction || sector.flow_group) === 'net_out'
          }"
          :style="{
            '--flow-alpha': sector.flow_alpha || 0.22,
            '--flow-deep-alpha': sector.flow_deep_alpha || 0.25,
            '--flow-border-alpha': sector.flow_border_alpha || 0.31
          }"
          @mouseenter="highlightSector(sector.name)"
          @mouseleave="unhighlightSector()"
          @click="openStockModal(sector)"
        >
          <div class="rank">{{ sector.rank }}</div>
          <div class="name">{{ sector.name }}</div>
          <div class="net-flow" :class="{ 'net-negative': sector.net_flow < 0 }">
            净流入: {{ formatNetFlow(sector.net_flow) }}
          </div>
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

    <div class="sector-list" ref="sectorList" v-if="selectedTimeRange !== 'today' && accumulatedData.length > 0">
      <h3 class="sector-title">{{ selectedTimeRange }}日累计资金流入TOP10</h3>
      <div class="sector-grid">
        <div 
          v-for="sector in accumulatedData" 
          :key="sector.rank"
          class="sector-card"
          :class="{ 'top-3': sector.rank <= 3 }"
          @mouseenter="highlightSector(sector.name)"
          @mouseleave="unhighlightSector()"
        >
          <div class="rank">{{ sector.rank }}</div>
          <div class="name">{{ sector.name }}</div>
          <div class="flow">累计流入: {{ formatFlow(sector.total_flow) }}</div>
          <div class="change" :class="{ 'positive': sector.accumulated_change_percent > 0, 'negative': sector.accumulated_change_percent < 0 }">
            {{ sector.accumulated_change_percent > 0 ? '+' : '' }}{{ (sector.accumulated_change_percent * 100).toFixed(2) }}%
            <span class="trend-arrow">
              {{ sector.accumulated_change_percent > 0 ? '↑' : (sector.accumulated_change_percent < 0 ? '↓' : '→') }}
            </span>
          </div>
            <div class="appearances">上榜: {{ sector.appearances }}次</div>
        </div>
      </div>
    </div>

    <div class="loading" v-if="loading">
      <div class="spinner"></div>
      <p>加载数据中...</p>
    </div>

    <div class="error" v-if="error">
      <p>{{ error }}</p>
      <button @click="retry">重试</button>
    </div>

    <footer class="cdn-footer">
      <a
        class="footer-record-link"
        href="http://beian.miit.gov.cn/"
        target="_blank"
        rel="noopener noreferrer"
      >
        陕ICP备2022001273号
      </a>
      <span class="footer-divider">|</span>
      <span class="cdn-service-text">
        <span>本网站由</span>
        <a
          class="cdn-provider-link"
          href="https://www.upyun.com/?utm_source=lianmeng&utm_medium=referral"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="又拍云"
        >
          <img src="/upyun-logo.png" alt="又拍云" class="cdn-provider-logo" />
        </a>
        <span>提供CDN加速服务</span>
      </span>
    </footer>
    
    <SecurityAlert />

    <!-- 个股详情弹窗 -->
    <div class="modal-overlay" v-if="showStockModal" @click="closeStockModal">
      <div class="modal-container" @click.stop>
        <div class="modal-header">
          <h3>{{ selectedSector?.name }} - 个股详情</h3>
          <button class="close-btn" @click="closeStockModal">×</button>
        </div>
        
        <div class="modal-controls">
          <div class="sort-controls">
            <span class="sort-hint">点击表头即可排序</span>
          </div>
        </div>

        <div class="modal-body">
          <div class="stocks-table">
            <div class="table-header">
              <div class="col">序号</div>
              <div class="col">代码</div>
              <div class="col">名称</div>
              <div class="col clickable" @click="toggleSort('change')">
                涨跌幅
                <span v-if="stockSortField === 'change'" class="sort-icon">{{ stockSortOrder === 'desc' ? '↓' : '↑' }}</span>
              </div>
              <div class="col clickable" @click="toggleSort('price')">
                股价
                <span v-if="stockSortField === 'price'" class="sort-icon">{{ stockSortOrder === 'desc' ? '↓' : '↑' }}</span>
              </div>
              <div class="col clickable" @click="toggleSort('turnover')">
                换手率
                <span v-if="stockSortField === 'turnover'" class="sort-icon">{{ stockSortOrder === 'desc' ? '↓' : '↑' }}</span>
              </div>
              <div class="col">成交量</div>
            </div>
            <div 
              v-for="(stock, index) in sectorStocks" 
              :key="stock.code || index"
              class="table-row"
            >
              <div class="col">{{ index + 1 }}</div>
              <div class="col">{{ stock.code }}</div>
              <div class="col clickable" @click="openXueqiuStock(stock.code)">{{ stock.name }}</div>
              <div class="col" :class="stock.change >= 0 ? 'positive' : 'negative'">
                {{ stock.change >= 0 ? '+' : '' }}{{ (stock.change * 100).toFixed(2) }}%
              </div>
              <div class="col">{{ stock.price }}</div>
              <div class="col">{{ stock.turnover }}</div>
              <div class="col">{{ stock.volume }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- AI分析结果弹窗 -->
    <div class="modal-overlay" v-if="showAIAnalysisModal" @click="closeAIAnalysisModal">
      <div class="ai-analysis-modal" @click.stop>
        <div class="modal-header">
          <h3>🤖 AI全天走势分析</h3>
          <button class="close-btn" @click="closeAIAnalysisModal">×</button>
        </div>
        <div class="modal-body">
          <div v-if="aiAnalysisResult" class="ai-analysis-content">
            {{ aiAnalysisResult }}
          </div>
          <div v-else-if="aiAnalysisError" class="ai-analysis-error">
            {{ aiAnalysisError }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script src="./components/App/App.script.js"></script>

