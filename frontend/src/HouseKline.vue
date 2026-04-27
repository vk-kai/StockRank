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

    <div class="chart-container" v-if="!loading && !error">
      <div ref="mainChart" class="main-chart"></div>
      <div ref="macdChart" class="macd-chart"></div>
    </div>

    <div class="data-source">
      数据来源：国家统计局
    </div>

    <div class="info-section">
      <div class="info-card">
        <h3>📊 图表说明</h3>
        <ul>
          <li><strong>基准价格</strong>：2018年12月 = 100.00万元</li>
          <li><strong>红色K线</strong>：价格上涨</li>
          <li><strong>绿色K线</strong>：价格下跌</li>
          <li><strong>橙色虚线</strong>：5周期均线</li>
          <li><strong>紫色点线</strong>：12周期均线</li>
        </ul>
      </div>
      <div class="info-card">
        <h3>📈 MACD指标</h3>
        <ul>
          <li><strong>蓝色线</strong>：MACD线 (DIF)</li>
          <li><strong>橙色线</strong>：信号线 (DEA)</li>
          <li><strong>红色柱</strong>：多头动能</li>
          <li><strong>绿色柱</strong>：空头动能</li>
        </ul>
      </div>
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
      mainChart: null,
      macdChart: null
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
    }
    if (this.macdChart) {
      this.macdChart.dispose()
    }
  },
  methods: {
    goBack() {
      this.$router.push('/')
    },

    async fetchKlineData() {
      this.loading = true
      this.error = null
      try {
        const response = await getHouseKline()
        if (response.success) {
          this.klineData = response.data
          this.$nextTick(() => {
            this.renderCharts()
          })
        } else {
          this.error = '获取数据失败'
        }
      } catch (err) {
        this.error = '获取数据失败: ' + err.message
      } finally {
        this.loading = false
      }
    },

    switchPeriod(period) {
      this.currentPeriod = period
      this.renderCharts()
    },

    handleResize() {
      if (this.mainChart) {
        this.mainChart.resize()
      }
      if (this.macdChart) {
        this.macdChart.resize()
      }
    },

    renderCharts() {
      this.renderMainChart()
      this.renderMacdChart()
    },

    renderMainChart() {
      if (!this.klineData) return

      const data = this.currentPeriod === 'monthly' 
        ? this.klineData.monthly 
        : this.klineData.quarterly

      if (this.mainChart) {
        this.mainChart.dispose()
      }
      this.mainChart = echarts.init(this.$refs.mainChart)

      const dates = data.map(item => {
        if (this.currentPeriod === 'monthly') {
          return `${item.year}年${item.month}月`
        }
        return item.quarter
      })

      const ohlc = data.map(item => [item.open, item.close, item.low, item.high])
      const ma5 = this.calculateMA(data.map(d => d.close), 5)
      const ma12 = this.calculateMA(data.map(d => d.close), 12)

      const option = {
        animation: false,
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross'
          },
          backgroundColor: 'rgba(20, 25, 45, 0.95)',
          borderColor: '#3a4a6b',
          textStyle: {
            color: '#fff'
          },
          formatter: function(params) {
            const dataIndex = params[0].dataIndex
            const item = data[dataIndex]
            const change = ((item.close - item.open) / item.open * 100).toFixed(2)
            const changeColor = change >= 0 ? '#ff4d4f' : '#52c41a'
            
            let html = `<div style="padding: 8px;">
              <div style="font-weight: bold; margin-bottom: 8px;">${dates[dataIndex]}</div>
              <div>开盘: ${item.open.toFixed(2)}万元</div>
              <div>收盘: ${item.close.toFixed(2)}万元</div>
              <div>最高: ${item.high.toFixed(2)}万元</div>
              <div>最低: ${item.low.toFixed(2)}万元</div>
              <div style="color: ${changeColor};">涨跌: ${change >= 0 ? '+' : ''}${change}%</div>`
            
            if (item.huanbi !== undefined) {
              html += `<div>环比: ${item.huanbi.toFixed(2)}</div>`
              html += `<div>同比: ${item.tongbi.toFixed(2)}</div>`
            }
            
            html += '</div>'
            return html
          }
        },
        legend: {
          data: ['K线', 'MA5', 'MA12'],
          textStyle: {
            color: '#8ba4c7'
          },
          top: 10
        },
        grid: {
          left: '10%',
          right: '10%',
          top: 60,
          bottom: 40
        },
        xAxis: {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: '#3a4a6b' } },
          axisLabel: {
            color: '#8ba4c7',
            rotate: 45,
            fontSize: 10
          },
          splitLine: { show: false }
        },
        yAxis: {
          type: 'value',
          scale: true,
          axisLine: { lineStyle: { color: '#3a4a6b' } },
          axisLabel: {
            color: '#8ba4c7',
            formatter: '{value}万'
          },
          splitLine: {
            lineStyle: {
              color: '#2a3a5b'
            }
          }
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
            lineStyle: {
              color: '#faad14',
              width: 1,
              type: 'dashed'
            },
            symbol: 'none'
          },
          {
            name: 'MA12',
            type: 'line',
            data: ma12,
            smooth: true,
            lineStyle: {
              color: '#722ed1',
              width: 2,
              type: 'dotted'
            },
            symbol: 'none'
          }
        ]
      }

      this.mainChart.setOption(option)
    },

    renderMacdChart() {
      if (!this.klineData) return

      const data = this.currentPeriod === 'monthly' 
        ? this.klineData.monthly 
        : this.klineData.quarterly

      if (this.macdChart) {
        this.macdChart.dispose()
      }
      this.macdChart = echarts.init(this.$refs.macdChart)

      const dates = data.map(item => {
        if (this.currentPeriod === 'monthly') {
          return `${item.year}年${item.month}月`
        }
        return item.quarter
      })

      const macd = data.map(item => item.macd)
      const signal = data.map(item => item.signal)
      const histogram = data.map(item => item.histogram)

      const option = {
        animation: false,
        tooltip: {
          trigger: 'axis',
          backgroundColor: 'rgba(20, 25, 45, 0.95)',
          borderColor: '#3a4a6b',
          textStyle: {
            color: '#fff'
          },
          formatter: function(params) {
            const dataIndex = params[0].dataIndex
            const item = data[dataIndex]
            let html = `<div style="padding: 8px;">
              <div style="font-weight: bold; margin-bottom: 8px;">${dates[dataIndex]}</div>
              <div style="color: #1890ff;">MACD: ${item.macd.toFixed(4)}</div>
              <div style="color: #fa8c16;">Signal: ${item.signal.toFixed(4)}</div>
              <div style="color: ${item.histogram >= 0 ? '#ff4d4f' : '#52c41a'};">Histogram: ${item.histogram.toFixed(4)}</div>
            </div>`
            return html
          }
        },
        legend: {
          data: ['MACD', 'Signal', 'Histogram'],
          textStyle: {
            color: '#8ba4c7'
          },
          top: 10
        },
        grid: {
          left: '10%',
          right: '10%',
          top: 60,
          bottom: 40
        },
        xAxis: {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: '#3a4a6b' } },
          axisLabel: {
            color: '#8ba4c7',
            rotate: 45,
            fontSize: 10
          },
          splitLine: { show: false }
        },
        yAxis: {
          type: 'value',
          axisLine: { lineStyle: { color: '#3a4a6b' } },
          axisLabel: {
            color: '#8ba4c7',
            formatter: '{value}'
          },
          splitLine: {
            lineStyle: {
              color: '#2a3a5b'
            }
          }
        },
        series: [
          {
            name: 'MACD',
            type: 'line',
            data: macd,
            lineStyle: {
              color: '#1890ff',
              width: 1.5
            },
            symbol: 'none'
          },
          {
            name: 'Signal',
            type: 'line',
            data: signal,
            lineStyle: {
              color: '#fa8c16',
              width: 1.5
            },
            symbol: 'none'
          },
          {
            name: 'Histogram',
            type: 'bar',
            data: histogram,
            itemStyle: {
              color: function(params) {
                return params.value >= 0 ? 'rgba(255, 77, 79, 0.6)' : 'rgba(82, 196, 26, 0.6)'
              }
            }
          }
        ],
        markLine: {
          silent: true,
          data: [
            {
              yAxis: 0,
              lineStyle: {
                color: '#666',
                type: 'dashed'
              }
            }
          ]
        }
      }

      this.macdChart.setOption(option)
    },

    calculateMA(data, period) {
      const result = []
      for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
          result.push('-')
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
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0e17 0%, #1a1f35 50%, #0d1321 100%);
  color: #e0e6f0;
  padding: 20px;
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

.main-chart {
  width: 100%;
  height: 400px;
}

.macd-chart {
  width: 100%;
  height: 200px;
  margin-top: 20px;
}

.data-source {
  text-align: center;
  padding: 15px;
  color: #8ba4c7;
  font-size: 0.9rem;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 8px;
  margin-bottom: 20px;
}

.info-section {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 20px;
}

.info-card {
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  padding: 20px;
}

.info-card h3 {
  color: #fff;
  margin-bottom: 15px;
  font-size: 1.1rem;
}

.info-card ul {
  list-style: none;
  padding: 0;
  margin: 0;
}

.info-card li {
  padding: 8px 0;
  color: #8ba4c7;
  border-bottom: 1px solid rgba(58, 74, 107, 0.3);
}

.info-card li:last-child {
  border-bottom: none;
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
