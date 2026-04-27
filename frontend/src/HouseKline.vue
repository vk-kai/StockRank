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
        >月K线</button>

        <button 
          :class="['period-btn', { active: currentPeriod === 'quarterly' }]"
          @click="switchPeriod('quarterly')"
        >季K线</button>
      </div>
    </div>

    <div class="chart-container">
      <div ref="mainChart" class="main-chart"></div>
    </div>
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getHouseKline } from './services/apiService'

export default {
  data() {
    return {
      currentPeriod: 'monthly',
      klineData: null,
      mainChart: null
    }
  },

  async mounted() {
    const res = await getHouseKline()
    if (res.success) {
      this.klineData = res.data
      this.$nextTick(() => {
        this.renderChart()
      })
    }

    window.addEventListener('resize', this.resize)
  },

  beforeUnmount() {
    window.removeEventListener('resize', this.resize)
    this.mainChart && this.mainChart.dispose()
  },

  methods: {
    goBack() {
      this.$router.push('/')
    },

    resize() {
      this.mainChart && this.mainChart.resize()
    },

    switchPeriod(p) {
      if (this.currentPeriod === p) return
      this.currentPeriod = p
      this.renderChart()
    },

    renderChart() {
      if (!this.klineData) return

      const chartDom = this.$refs.mainChart
      if (!this.mainChart) {
        this.mainChart = echarts.init(chartDom)
      }

      const data = this.currentPeriod === 'monthly'
        ? this.klineData.monthly
        : this.klineData.quarterly

      const dates = data.map(d =>
        this.currentPeriod === 'monthly'
          ? `${d.year}-${d.month}`
          : d.quarter
      )

      const ohlc = data.map(d => [d.open, d.close, d.low, d.high])

      const closes = data.map(d => d.close)
      const ma5 = this.calculateMA(closes, 5)
      const ma10 = this.calculateMA(closes, 10)

      const self = this

      const option = {
        animation: false,

        tooltip: {
          trigger: 'axis',
          axisPointer: { type: 'cross' },

          formatter(params) {
            const p = params.find(p => p.seriesType === 'candlestick')
            if (!p) return ''

            const i = p.dataIndex
            const item = data[i]

            const change = ((item.close - item.open) / item.open * 100).toFixed(2)
            const color = change >= 0 ? '#ff4d4f' : '#52c41a'

            const dateLabel = self.currentPeriod === 'monthly'
              ? `${item.year}年${item.month}月`
              : item.quarter

            return `
              <div>
                <b>${dateLabel}</b><br/>
                开盘：${item.open}<br/>
                收盘：${item.close}<br/>
                最高：${item.high}<br/>
                最低：${item.low}<br/>
                <span style="color:${color}">
                  涨跌：${change >= 0 ? '+' : ''}${change}%
                </span>
              </div>
            `
          }
        },

        legend: {
          data: ['K线', 'MA5', 'MA10']
        },

        xAxis: {
          type: 'category',
          data: dates
        },

        yAxis: {
          scale: true
        },

        series: [
          {
            name: 'K线',
            type: 'candlestick',
            data: ohlc,
            itemStyle: {
              color: '#ff4d4f',
              color0: '#52c41a'
            }
          },
          {
            name: 'MA5',
            type: 'line',
            data: ma5,
            smooth: true,
            showSymbol: false,
            connectNulls: true
          },
          {
            name: 'MA10',
            type: 'line',
            data: ma10,
            smooth: true,
            showSymbol: false,
            connectNulls: true
          }
        ]
      }

      this.mainChart.setOption(option, {
        notMerge: false,
        replaceMerge: ['series']
      })
    },

    calculateMA(data, period) {
      const result = []
      for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
          result.push(undefined) // ⚠️ 关键修复
        } else {
          let sum = 0
          for (let j = 0; j < period; j++) {
            sum += data[i - j]
          }
          result.push((sum / period).toFixed(2))
        }
      }
      return result
    }
  }
}
</script>

<style scoped>
.house-kline-page {
  padding: 20px;
  background: #0d1117;
}

.kline-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 20px;
}

.chart-container {
  height: 600px; /* ✅ 修复图变小 */
}

.main-chart {
  width: 100%;
  height: 100%;
}

.period-btn {
  margin: 5px;
}

.period-btn.active {
  background: #1890ff;
  color: #fff;
}
</style>