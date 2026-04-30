<template>
  <div class="daily-report-page">
    <header class="report-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>📊 每日汇总报表</h1>
      <div class="header-spacer"></div>
    </header>

    <div class="ai-analysis-section" v-if="aiAnalysis">
      <h2>🤖 AI 分析</h2>
      <div class="ai-content">
        {{ aiAnalysis }}
      </div>
    </div>

    <div class="report-controls">
      <div class="date-selector">
        <label>选择日期：</label>
        <input type="date" v-model="selectedDate" @change="fetchReport" />
      </div>
      <div class="last-update" v-if="lastUpdate">
        更新时间: {{ lastUpdate }}
      </div>
    </div>

    <div class="loading" v-if="loading">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <div class="error" v-if="error">
      <p>{{ error }}</p>
      <button @click="fetchReport">重试</button>
    </div>

    <div class="report-content" v-if="!loading && !error && reportData">
      <div class="comparison-section">
        <h2>📈 TOP5 板块对比</h2>
        <div class="comparison-table">
          <div class="table-header">
            <div class="col rank">排名</div>
            <div class="col name">板块</div>
            <div class="col today-flow">今日流入</div>
            <div class="col today-change">今日涨跌</div>
            <div class="col yesterday-flow">昨日流入</div>
            <div class="col yesterday-change">昨日涨跌</div>
            <div class="col strength">强度</div>
          </div>
          <div 
            class="table-row" 
            v-for="item in reportData.comparison.top5" 
            :key="item.rank"
            :class="{ 'top-3': item.rank <= 3 }"
          >
            <div class="col rank">{{ item.rank }}</div>
            <div class="col name">{{ item.name }}</div>
            <div class="col today-flow">
              <span class="flow-value">{{ formatFlow(item.today_flow) }}</span>
            </div>
            <div class="col today-change" :class="getChangeClass(item.today_change)">
              {{ formatChange(item.today_change) }}
            </div>
            <div class="col yesterday-flow">
              {{ item.yesterday_flow ? formatFlow(item.yesterday_flow) : '-' }}
            </div>
            <div class="col yesterday-change" :class="getChangeClass(item.yesterday_change)">
              {{ item.yesterday_change !== null ? formatChange(item.yesterday_change) : '-' }}
            </div>
            <div class="col strength">
              <span :class="getStrengthClass(item.strength)">
                {{ getStrengthIcon(item.strength) }} {{ item.strength }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div class="all-sectors-section">
        <h2>📋 全部板块数据（点击查看个股详情）</h2>
        <div class="sectors-grid">
          <div 
            class="sector-card clickable" 
            v-for="(sector, index) in reportData.today" 
            :key="index"
            :class="{ 'top-3': index < 3 }"
            @click="openStockModal(sector)"
          >
            <div class="sector-rank">{{ index + 1 }}</div>
            <div class="sector-name">{{ sector.name }}</div>
            <div class="sector-flow">
              流入: <span class="flow-value">{{ formatFlow(sector.flow) }}</span>
            </div>
            <div class="sector-change" :class="getChangeClass(sector.change)">
              {{ formatChange(sector.change) }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="no-data" v-if="!loading && !error && !reportData">
      <p>暂无数据</p>
    </div>

    <!-- 个股详情弹窗 -->
    <div class="modal-overlay" v-if="showStockModal" @click="closeStockModal">
      <div class="modal-container" @click.stop>
        <div class="modal-header">
          <h3>📊 {{ selectedSector?.name }} - 个股详情</h3>
          <button class="close-btn" @click="closeStockModal">×</button>
        </div>
        
        <div class="modal-controls">
          <div class="sort-controls">
            <label>排序方式：</label>
            <select v-model="stockSortField" @change="sortStocks">
              <option value="change">涨跌幅</option>
              <option value="flow">资金流入</option>
              <option value="price">股价</option>
              <option value="turnover">换手率</option>
            </select>
            <button class="sort-order-btn" @click="toggleSortOrder">
              {{ stockSortOrder === 'desc' ? '↓ 降序' : '↑ 升序' }}
            </button>
          </div>
        </div>

        <div class="modal-body">
          <div class="loading" v-if="loadingStocks">
            <div class="spinner"></div>
            <p>加载个股数据...</p>
          </div>

          <div class="error" v-if="stocksError">
            <p>{{ stocksError }}</p>
          </div>

          <div class="stocks-table" v-if="!loadingStocks && !stocksError && sectorStocks.length > 0">
            <div class="table-header">
              <div class="col rank">序号</div>
              <div class="col code">代码</div>
              <div class="col name">名称</div>
              <div class="col price">现价</div>
              <div class="col change">涨跌幅</div>
              <div class="col change-value">涨跌额</div>
              <div class="col turnover">换手率</div>
              <div class="col volume">成交额</div>
              <div class="col market-cap">流通市值</div>
            </div>
            <div 
              class="table-row" 
              v-for="stock in sectorStocks" 
              :key="stock.code"
            >
              <div class="col rank">{{ stock.rank }}</div>
              <div class="col code">{{ stock.code }}</div>
              <div class="col name">{{ stock.name }}</div>
              <div class="col price" :class="getChangeClass(stock.change)">
                {{ stock.price.toFixed(2) }}
              </div>
              <div class="col change" :class="getChangeClass(stock.change)">
                {{ formatChange(stock.change) }}
              </div>
              <div class="col change-value" :class="getChangeClass(stock.change)">
                {{ stock.change_value.toFixed(2) }}
              </div>
              <div class="col turnover">{{ stock.turnover.toFixed(2) }}%</div>
              <div class="col volume">{{ stock.volume }}</div>
              <div class="col market-cap">{{ stock.market_cap }}</div>
            </div>
          </div>

          <div class="no-data" v-if="!loadingStocks && !stocksError && sectorStocks.length === 0">
            <p>暂无个股数据</p>
          </div>
        </div>
      </div>
    </div>

    <SecurityAlert />
  </div>
</template>

<script src="./components/DailyReport/DailyReport.script.js"></script>
<style scoped src="./components/DailyReport/DailyReport.style.css"></style>
