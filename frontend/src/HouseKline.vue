<template>
  <div class="house-kline-page">
    <header class="kline-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>🏠 西安二手房价格K线分析</h1>
      <div class="header-spacer"></div>
    </header>

    <div class="kline-controls">
      <div class="period-buttons">
        <button 
          :class="['period-btn', { active: currentPeriod === 'monthly' }]"
          @click="switchPeriod('monthly')"
        >
          月K线
        </button>
        <button 
          :class="['period-btn', { active: currentPeriod === 'quarterly' }]"
          @click="switchPeriod('quarterly')"
        >
          季K线
        </button>
      </div>
    </div>

    <div class="loading" v-if="loading">
      <div class="spinner"></div>
      <p>加载数据中...</p>
    </div>

    <div class="error" v-if="error">
      <p>{{ error }}</p>
      <button @click="fetchKlineData">重试</button>
    </div>

    <div class="chart-container" v-show="!loading && !error">
      <div ref="mainChart" class="main-chart"></div>
    </div>

    <div class="data-source">
      数据来源：国家统计局
    </div>
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getHouseKline } from './services/apiService'

export default {
  name: 'HouseKline',

  data() {
    return {
      loading: false,
      error: null,
      klineData: null,
      currentPeriod: 'monthly',
      mainChart: null
    }
  },

  mounted() {
    this.fetchKlineData()
    window.addEventListener('resize', this.handleResize)
  },

  beforeUnmount() {
    window.removeEventListener('resize', this.handleResize)
    if (this.mainChart) {
      this.mainChart.dispose()
      this.mainChart = null
    }
  },

  methods: {
    async fetchKlineData() {
      this.loading = true
      this.error = null

      try {
        const res = await getHouseKline()
        if (res.success) {
          this.klineData = res.data

          // ✅ 延迟确保DOM有高度
          this.$nextTick(() => {
            setTimeout(() => {
              this.renderMainChart()
            }, 200)
          })
        } else {
          this.error = '获取数据失败'
        }
      } catch (e) {
        this.error = e.message
      } finally {
        this.loading = false
      }
    },

    switchPeriod(period) {
      if (this.currentPeriod === period) return
      this.currentPeriod = period
      this.renderMainChart()
    },

    handleResize() {
      if (this.mainChart) {
        this.mainChart.resize()
      }
    },

    renderMainChart() {
      if (!this.klineData) return

      const chartDom = this.$refs.mainChart
      if (!chartDom || chartDom.clientHeight === 0) {
        setTimeout(() => this.renderMainChart(), 200)
        return
      }

      const raw = this.currentPeriod === 'monthly'
        ? this.klineData.monthly
        : this.klineData.quarterly

      if (!raw || raw.length === 0) return

      // ✅ 核心：强制数据清洗（防崩）
      const data = raw.map(item => {
        const open = Number(item.open)
        const close = Number(item.close)
        const low = Number(item.low)
        const high = Number(item.high)

        if (
          isNaN(open) ||
          isNaN(close) ||
          isNaN(low) ||
          isNaN(high)
        ) return null

        return { ...item, open, close, low, high }
      }).filter(Boolean)

      if (data.length === 0) {
        console.error('K线数据全部无效')
        return
      }

      const dates = data.map(item =>
        this.currentPeriod === 'monthly'
          ? `${item.year}-${item.month}`
          : item.quarter
      )

      const ohlc = data.map(i => [i.open, i.close, i.low, i.high])
      const closeList = data.map(i => i.close)

      const ma5 = this.calculateMA(closeList, 5)
      const ma10 = this.calculateMA(closeList, 10)

      // ✅ 初始化一次
      if (!this.mainChart) {
        this.mainChart = echarts.init(chartDom)
      }

      const option = {
        animation: false,

        grid: {
          left: '3%',
          right: '3%',
          top: 50,
          bottom: 30
        },

        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },

          formatter: (params) => {
            const candle = params.find(p => p.seriesType === 'candlestick')
            if (!candle) return ''

            const i = candle.dataIndex
            const item = data[i]
            if (!item) return ''

            const change = ((item.close - item.open) / item.open * 100).toFixed(2)
            const color = change >= 0 ? '#ff4d4f' : '#52c41a'

            return `
              <div>
                <b>${dates[i]}</b><br/>
                开盘：${item.open}<br/>
                收盘：${item.close}<br/>
                最高：${item.high}<br/>
                最低：${item.low}<br/>
                涨跌：<span style="color:${color}">
                  ${change}%
                </span>
              </div>
            `
          }
        },

        legend: {
          data: ['K线', 'MA5', 'MA10'],
          textStyle: { color: '#aaa' }
        },

        xAxis: {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: '#666' } }
        },

        yAxis: {
          scale: true,
          axisLine: { lineStyle: { color: '#666' } }
        },

        series: [
          {
            name: 'K线',
            type: 'candlestick',
            data: ohlc,
            itemStyle: {
              color: '#ff4d4f',
              color0: '#52c41a',
              borderColor: '#ff4d4f',
              borderColor0: '#52c41a'
            }
          },
          {
            name: 'MA5',
            type: 'line',
            data: ma5,
            smooth: true,
            showSymbol: false
          },
          {
            name: 'MA10',
            type: 'line',
            data: ma10,
            smooth: true,
            showSymbol: false
          }
        ]
      }

      this.mainChart.setOption(option, true)
    },

    calculateMA(data, period) {
      return data.map((_, i) => {
        if (i < period - 1) return null
        let sum = 0
        for (let j = 0; j < period; j++) {
          sum += data[i - j]
        }
        return +(sum / period).toFixed(2)
      })
    }
  }
}
</script>

<style scoped>
.house-kline-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0e17 0%, #1a1f35 50%, #0d1321 100%);
  color: #e0e6f0;
  padding: 20px;
}
.main-chart {
  width: 100%;
  height: 500px;
  min-height: 500px; /* ⭐关键 */
}
.kline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
  padding: 15px 20px;
  background: rgba(26, 35, 53, 0.8);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
}

.kline-header h1 {
  font-size: 1.5rem;
  color: #fff;
  margin: 0;
}

.back-button {
  padding: 10px 20px;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  border: 1px solid #4a5a7b;
  border-radius: 8px;
  color: #e0e6f0;
  cursor: pointer;
  transition: all 0.3s ease;
}

.back-button:hover {
  background: linear-gradient(135deg, #4a5a7b, #3a4a6b);
  transform: translateY(-2px);
}

.header-spacer {
  width: 100px;
}

.kline-controls {
  display: flex;
  justify-content: center;
  margin-bottom: 20px;
}

.period-buttons {
  display: flex;
  gap: 10px;
  padding: 5px;
  background: rgba(26, 35, 53, 0.8);
  border-radius: 10px;
  border: 1px solid rgba(58, 74, 107, 0.5);
}

.period-btn {
  padding: 10px 30px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #8ba4c7;
  cursor: pointer;
  transition: all 0.3s ease;
  font-size: 1rem;
}

.period-btn:hover {
  background: rgba(58, 74, 107, 0.5);
  color: #fff;
}

.period-btn.active {
  background: linear-gradient(135deg, #1890ff, #096dd9);
  color: #fff;
  font-weight: bold;
}

.chart-container {
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  padding: 20px;
  margin-bottom: 20px;
}

.data-source {
  text-align: center;
  padding: 15px;
  color: #8ba4c7;
  font-size: 0.9rem;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 8px;
}

.loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
}

.spinner {
  width: 50px;
  height: 50px;
  border: 4px solid rgba(24, 144, 255, 0.3);
  border-top-color: #1890ff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

.error {
  text-align: center;
  padding: 40px;
  color: #ff4d4f;
}

.error button {
  margin-top: 15px;
  padding: 10px 30px;
  background: linear-gradient(135deg, #ff4d4f, #cf1322);
  border: none;
  border-radius: 8px;
  color: #fff;
  cursor: pointer;
  transition: all 0.3s ease;
}

.error button:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(255, 77, 79, 0.4);
}
</style>
