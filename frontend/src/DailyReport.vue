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
        <h2>📋 全部板块数据</h2>
        <div class="sectors-grid">
          <div 
            class="sector-card" 
            v-for="(sector, index) in reportData.today" 
            :key="index"
            :class="{ 'top-3': index < 3 }"
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
  </div>
</template>

<script src="./components/DailyReport/DailyReport.script.js"></script>
<style scoped src="./components/DailyReport/DailyReport.style.css"></style>
