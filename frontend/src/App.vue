<template>
  <div class="dashboard">
    <header class="header">
      <div class="header-title-row">
        <h1>A股板块资金流入统计</h1>
        <div class="title-actions">
          <button class="ai-analyze-button" @click="guardedAnalyzeDailyFlow" :disabled="aiAnalyzing">
            <span class="button-text">
              <template v-if="aiAnalyzing">
                <span class="step-text">{{ aiAnalysisStep }}</span>
                <span class="progress-text">{{ Math.round(aiAnalysisProgress) }}%</span>
              </template>
              <template v-else-if="aiAnalysisError">⚠️ 上次失败，点击重试</template>
              <template v-else>🤖 AI分析</template>
            </span>
            <div class="water-fill" v-if="aiAnalyzing" :style="{ width: aiAnalysisProgress + '%' }">
              <div class="wave"></div>
              <div class="wave wave2"></div>
            </div>
          </button>
          <button class="yuntu-button" @click="guardedGotoMarketMap"><IconTreemap />大盘云图</button>
          <button class="global-button" @click="guardedGotoGlobalMarket">🌍 全球股市地图</button>
          <button class="quant-button" @click="guardedOpenQuantSystem">📈 量化交易系统</button>
          <button class="flow-alert-button" :class="{ 'has-new': hasUnreadAnomaly }" @click="openFlowAlertModal">
            🚨 异动预警
            <span class="unread-dot" v-if="hasUnreadAnomaly" title="有新异动"></span>
          </button>
          <div class="more-menu-wrapper">
            <button class="more-button" @click="showMoreMenu = !showMoreMenu">☰ 更多</button>
            <div class="more-menu-overlay" v-if="showMoreMenu" @click="showMoreMenu = false"></div>
            <div class="more-dropdown" v-if="showMoreMenu">
              <div class="more-dropdown-item" @click="guardedGoToConfig(); showMoreMenu = false">AI配置</div>
              <div class="more-dropdown-item" @click="guardedGoToIndustryCycle(); showMoreMenu = false">行业见顶诊断</div>
              <div class="more-dropdown-item" @click="guardedGoToLogs(); showMoreMenu = false">日志</div>
              <div class="more-dropdown-item" @click="guardedGoToHouseKline(); showMoreMenu = false">房价K线</div>
              <div class="more-dropdown-item" v-if="isAdmin" @click="guardedGoToRedeemCode(); showMoreMenu = false">体验码</div>
              <div class="more-dropdown-item" v-if="isAdmin" @click="guardedGoToMpAdmin(); showMoreMenu = false">小程序数据后台</div>
            </div>
          </div>
        </div>
      </div>
      <div class="controls">
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

        <div
          class="ai-chain-strip"
          :class="aiChainOverallClass"
          @click="guardedGotoAiChain"
          title="AI产业链外部环境温度计"
        >
          <span class="ai-chain-dot"></span>
          <span class="ai-chain-label">AI环境</span>
          <span class="ai-chain-overall">{{ aiChainOverallText }}</span>
          <span class="ai-chain-sub">{{ aiChainSubText }}</span>
          <span class="ai-chain-arrow">›</span>
        </div>

        <button class="config-button" @click="guardedGoToConfig">
          AI配置
        </button>
        <button class="log-button" @click="guardedGoToLogs">
          日志
        </button>
        <button class="house-button" @click="guardedGoToHouseKline">
          房价K线
        </button>
      </div>
    </header>

    <div class="market-summary-panel">
      <div class="time-selector">
        <label>时间跨度：</label>
        <select v-model="selectedTimeRange" @change="fetchDataByTimeRange">
          <option :value="'today'">当天</option>
          <option :value="7">近7天</option>
          <option :value="15">近15天</option>
          <option :value="30">近30天</option>
        </select>
      </div>
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
        <span
          v-if="marginTotal && marginTotal.latest_total != null"
          class="market-margin-chip"
          @click="openMarginTotalModal"
          title="点击查看全市场融资余额趋势(口径:融资余额合计)"
        >
          融资{{ formatMarketAmount(marginTotal.latest_total, false) }}
          <span :class="getValueTrendClass(marginTotal.change_pct)">
            {{ marginTotal.change_pct >= 0 ? '↑' : '↓' }}{{ Math.abs(marginTotal.change_pct || 0).toFixed(2) }}%
          </span>
        </span>
      </div>

      <div class="market-turnover-row">
        <span class="market-turnover-label">今日实时成交额</span>
        <span class="market-turnover-value num-flash" :key="'t'+(marketSummary?.turnover?.turnover||0)">{{ formatMarketAmount(marketSummary?.turnover?.turnover, false) }}</span>
        <span class="market-turnover-spacer"></span>
        <span class="market-turnover-label">较上一日此时</span>
        <span class="market-turnover-value num-flash" :class="getValueTrendClass(marketSummary?.turnover?.turnover_change)" :key="'c'+(marketSummary?.turnover?.turnover_change||0)">
          {{ formatMarketAmount(marketSummary?.turnover?.turnover_change) }}
        </span>
      </div>
    </div>

    <div class="monitor-card-container" ref="monitorCard" @click="refreshHealth" v-if="!needsAuth">
      <div class="monitor-card-header">
        <span class="monitor-card-label">服务监控</span>
        <button class="health-check-btn" @click="refreshHealth" :disabled="healthChecking">
          {{ healthChecking ? '检测中...' : '检测' }}
        </button>
      </div>
      <div class="monitor-card-body">
        <div
          v-for="row in healthDisplayItems"
          :key="row.key"
          class="monitor-card-row"
          :class="getMonitorRowClass(row)"
        >
          <span class="monitor-dot"></span>
          <span class="monitor-name">{{ row.label }}</span>
          <span class="monitor-text">{{ getMonitorStatusText(row) }}</span>
          <span class="monitor-time" v-if="row.item.response_time && row.item.status === 'ok'">{{ row.item.response_time }}ms</span>
          <button class="monitor-retry-btn" v-if="row.kind === 'ths' && thsCrawlerFailed()" @click.stop="resetThsCrawler">
            重试
          </button>
          <button class="monitor-retry-btn" v-if="row.kind === 'push'" @click.stop="testPushService">
            测试
          </button>
        </div>
        <div v-if="healthDisplayItems.length === 0" class="monitor-card-row monitor-loading">
          <span class="monitor-dot"></span>
          <span class="monitor-text">检测中...</span>
        </div>
      </div>
    </div>

    <div class="news-ticker-container" v-if="!needsAuth && latestNews.length > 0">
      <div class="news-ticker-header">
        <span class="ticker-label clickable" @click="goToNews">最新新闻</span>
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
            <span v-if="currentNewsItem.importance === '3'" class="important-badge">重要</span>
            {{ currentNewsItem.title }}
          </div>
          <div class="news-time">{{ formatNewsTime(currentNewsItem.timestamp) }}</div>
        </div>
      </div>
    </div>

    <div class="chart-container" ref="chartContainer">
      <button
        class="chart-rotate-btn"
        v-if="!needsAuth"
        @click="toggleChartFullscreen"
        title="横屏全屏查看"
        aria-label="横屏全屏查看折线图"
      >
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 3v3a3 3 0 0 0 3 3h11"></path>
          <path d="M5 3a2 2 0 0 0-2 2v0a2 2 0 0 0 2 2"></path>
          <path d="M19 21v-3a3 3 0 0 0-3-3H5"></path>
          <path d="M19 21a2 2 0 0 0 2-2v0a2 2 0 0 0-2-2"></path>
        </svg>
      </button>
      <div class="chart-controls" v-if="!needsAuth">
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
      <div v-if="needsAuth" class="chart-auth-mask">
        <div class="chart-auth-content">
          <div class="chart-auth-icon">🔒</div>
          <div class="chart-auth-text">登录后查看资金流向图表</div>
          <button class="chart-auth-btn" @click="promptLogin">去登录</button>
        </div>
      </div>
    </div>

    <!-- 折线图横屏全屏（移动端点右上角旋转图标触发） -->
    <div v-if="chartFullscreen" class="chart-fullscreen-overlay" @click.self="toggleChartFullscreen">
      <button class="chart-fullscreen-close" @click="toggleChartFullscreen" aria-label="退出横屏">✕</button>
      <div class="chart-fullscreen-inner">
        <div ref="chartFullscreenEl" class="chart-fullscreen-canvas"></div>
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
            '--flow-border-alpha': sector.flow_border_alpha || 0.31,
            '--flow-strength': sector.flow_strength || 0.5
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

    <!-- 多日模式(7/15/30天): 累计净流入TOP5 + 净流出TOP5,卡片结构与当天模式同款(红/绿着色) -->
    <div class="sector-list" ref="sectorList" v-if="selectedTimeRange !== 'today' && accumulatedTop10Sectors.length > 0">
      <h3 class="sector-title">{{ accumulatedTitle }}</h3>
      <div class="sector-grid">
        <div
          v-for="sector in accumulatedTop10Sectors"
          :key="`${sector.flow_direction}-${sector.rank}-${sector.name}`"
          class="sector-card"
          :class="{
            'top-3': sector.rank <= 3,
            'net-in-card': (sector.flow_direction || sector.flow_group) !== 'out' && (sector.flow_direction || sector.flow_group) !== 'net_out',
            'net-out-card': (sector.flow_direction || sector.flow_group) === 'out' || (sector.flow_direction || sector.flow_group) === 'net_out'
          }"
          :style="{
            '--flow-alpha': sector.flow_alpha || 0.22,
            '--flow-deep-alpha': sector.flow_deep_alpha || 0.25,
            '--flow-border-alpha': sector.flow_border_alpha || 0.31,
            '--flow-strength': sector.flow_strength || 0.5
          }"
          @mouseenter="highlightSector(sector.name)"
          @mouseleave="unhighlightSector()"
        >
          <div class="rank">{{ sector.rank }}</div>
          <div class="name">{{ sector.name }}</div>
          <div class="flow" :class="{ 'net-negative': (sector.total_net_flow ?? sector.net_flow ?? 0) < 0 }">
            累计净流入: {{ formatFlow(sector.total_net_flow ?? sector.net_flow) }}
          </div>
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

    <!-- 两融融资余额折线图弹窗 -->
    <div class="modal-overlay" v-if="marginTotalModalOpen" @click="closeMarginTotalModal">
      <div class="modal-container" @click.stop>
        <div class="modal-header">
          <h3>全市场融资余额趋势</h3>
          <button class="close-btn" @click="closeMarginTotalModal">×</button>
        </div>
        <div class="modal-body">
          <div v-if="marginTotal && marginTotal.latest_date" class="margin-total-meta">
            <span>数据截止 {{ formatMarginDate(marginTotal.latest_date) }}</span>
            <span v-if="marginTotal.updated_at" class="margin-total-meta-sub">更新于 {{ marginTotal.updated_at }}</span>
          </div>
          <div ref="marginTotalChartEl" style="width:100%;height:360px;"></div>
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
          <div v-if="aiAnalysisResult" class="ai-analysis-content" v-html="renderedAIAnalysis"></div>
          <div v-else-if="aiAnalysisError" class="ai-analysis-error">
            {{ aiAnalysisError }}
          </div>
        </div>
        <div class="modal-footer">
          <span v-if="aiAnalysisDate" class="analysis-date">分析日期: {{ aiAnalysisDate }}</span>
          <button class="reanalyze-btn" @click="reanalyzeDailyFlow" :disabled="aiAnalyzing">
            {{ aiAnalyzing ? '分析中...' : '重新分析' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 资金异动速览弹窗（首页一键瞄一眼，深入看跳 /flow-alert） -->
    <div class="modal-overlay" v-if="showFlowAlertModal" @click="closeFlowAlertModal">
      <div class="flow-alert-modal" @click.stop>
        <div class="modal-header">
          <h3>🚨 资金异动速览</h3>
          <button class="close-btn" @click="closeFlowAlertModal">×</button>
        </div>
        <div class="modal-body">
          <div class="fa-quick-stats" v-if="flowAlertSummary.total">
            <div class="fa-quick-stat">
              <span class="num">{{ flowAlertSummary.total }}</span>
              <span class="lbl">今日推送</span>
            </div>
            <div class="fa-quick-stat">
              <span class="num">{{ flowAlertSummary.sectors }}</span>
              <span class="lbl">涉及板块</span>
            </div>
            <div class="fa-quick-stat">
              <span class="num">{{ flowAlertSummary.latest }}</span>
              <span class="lbl">最新时点</span>
            </div>
          </div>
          <div class="fa-quick-loading" v-if="flowAlertLoading">
            <div class="spinner"></div>
            <p>加载中...</p>
          </div>
          <div v-else-if="!flowAlertList.length" class="fa-quick-empty">
            <p>今日暂无已推送异动</p>
            <p class="fa-quick-empty-sub">交易时段每 5 分钟采集后自动触发</p>
          </div>
          <div v-else class="fa-quick-list">
            <div class="fa-quick-card" v-for="(a, idx) in flowAlertList" :key="idx">
              <div class="fa-quick-head">
                <span class="fa-quick-time">{{ a.date }} {{ a.time }}</span>
                <span class="fa-quick-sector">{{ a.sector }}</span>
                <span class="fa-quick-push" :class="a.pushed ? 'ok' : 'fail'">{{ a.pushed ? '✓' : '✗' }}</span>
              </div>
              <div class="fa-quick-meta">
                <span class="fa-quick-net" :class="a.net_flow >= 0 ? 'pos' : 'neg'">净流入 {{ faNet(a.net_flow) }}亿</span>
                <span class="fa-quick-chg" :class="a.change_pct >= 0 ? 'pos' : 'neg'">{{ faPct(a.change_pct) }}%</span>
                <span class="fa-quick-labels" v-if="a.labels && a.labels.length">{{ a.labels.join('、') }}</span>
                <span class="fa-quick-lead" v-if="a.lead_stock">龙头 {{ a.lead_stock }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="reanalyze-btn" @click="refreshFlowAlertModal" :disabled="flowAlertLoading">
            <IconRefresh v-if="!flowAlertLoading" />
            {{ flowAlertLoading ? '刷新中...' : '刷新' }}
          </button>
          <button class="fa-quick-viewall" @click="gotoFlowAlertPage">查看全天全部 →</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script src="./components/App/App.script.js"></script>

