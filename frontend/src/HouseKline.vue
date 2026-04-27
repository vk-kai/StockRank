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

    <div class="chart-container" ref="chartContainer">
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
            setTimeout(() => {
              this.renderMainChart()
            }, 100)
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
      if (this.currentPeriod === period) return
      this.currentPeriod = period
      this.$nextTick(() => {
        this.renderMainChart()
      })
    },

    handleResize() {
      if (this.mainChart) {
        this.mainChart.resize()
      }
    },

    generateXAxisLabels(data) {
      const labels = []
      let lastYear = null
      
      for (let i = 0; i < data.length; i++) {
        const item = data[i]
        if (this.currentPeriod === 'monthly') {
          if (item.year !== lastYear) {
            labels.push(`${item.year}年\n${item.month}月`)
            lastYear = item.year
          } else {
            labels.push(`${item.month}月`)
          }
        } else {
          labels.push(item.quarter || `Q${item.month}`)
        }
      }
      return labels
    },

    renderMainChart() {
      if (!this.klineData) return

      const data = this.currentPeriod === 'monthly' 
        ? this.klineData.monthly 
        : this.klineData.quarterly

      if (!data || data.length === 0) return

      const chartDom = this.$refs.mainChart
      if (!chartDom) return

      if (this.mainChart) {
        this.mainChart.dispose()
      }
      this.mainChart = echarts.init(chartDom)

      const dates = this.generateXAxisLabels(data)
      const ohlc = data.map(item => [item.open, item.close, item.low, item.high])
      const ma5 = this.calculateMA(data.map(d => d.close), 5)
      const ma10 = this.calculateMA(data.map(d => d.close), 10)
      
      const macdData = data.map(item => item.macd || 0)
      const signalData = data.map(item => item.signal || 0)
      const histogramData = data.map(item => {
        const val = item.histogram || 0
        return {
          value: val,
          itemStyle: {
            color: val >= 0 ? '#ff4d4f' : '#52c41a'
          }
        }
      })

      const self = this
      const labelInterval = this.currentPeriod === 'monthly' ? 5 : 2

      const option = {
        animation: false,
        backgroundColor: 'transparent',
        axisPointer: {
          link: [{ xAxisIndex: 'all' }],
          label: {
            backgroundColor: '#777'
          }
        },
        tooltip: {
          trigger: 'item',
          backgroundColor: 'rgba(20, 25, 45, 0.95)',
          borderColor: '#3a4a6b',
          borderWidth: 1,
          padding: [12, 16],
          textStyle: {
            color: '#e0e6f0',
            fontSize: 13
          },
          confine: true,
          formatter: function(params) {
            if (!params) return ''
            
            const dataIndex = params.dataIndex
            const item = data[dataIndex]
            if (!item) return ''
            
            const change = ((item.close - item.open) / item.open * 100).toFixed(2)
            const changeColor = change >= 0 ? '#ff4d4f' : '#52c41a'
            const changePrefix = change >= 0 ? '+' : ''
            
            let dateLabel
            if (self.currentPeriod === 'monthly') {
              dateLabel = `${item.year}年${item.month}月`
            } else {
              dateLabel = item.quarter || `${item.year}年Q${item.month}`
            }
            
            const macdVal = item.macd || 0
            const signalVal = item.signal || 0
            const histogramVal = item.histogram || 0
            const macdColor = macdVal >= 0 ? '#ff4d4f' : '#52c41a'
            const signalColor = signalVal >= 0 ? '#faad14' : '#13c2c2'
            const histogramColor = histogramVal >= 0 ? '#ff4d4f' : '#52c41a'

            return `<div style="min-width: 200px;">
              <div style="font-weight: bold; margin-bottom: 10px; font-size: 14px; color: #fff; border-bottom: 1px solid #3a4a6b; padding-bottom: 8px;">
                📅 ${dateLabel}
              </div>
              <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span style="color: #8ba4c7;">开盘：</span>
                <span style="color: #faad14; font-weight: 500;">${item.open.toFixed(2)} 万/㎡</span>
              </div>
              <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span style="color: #8ba4c7;">收盘：</span>
                <span style="color: #1890ff; font-weight: 500;">${item.close.toFixed(2)} 万/㎡</span>
              </div>
              <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span style="color: #8ba4c7;">最高：</span>
                <span style="color: #ff4d4f; font-weight: 500;">${item.high.toFixed(2)} 万/㎡</span>
              </div>
              <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                <span style="color: #8ba4c7;">最低：</span>
                <span style="color: #52c41a; font-weight: 500;">${item.low.toFixed(2)} 万/㎡</span>
              </div>
              <div style="display: flex; justify-content: space-between; margin-top: 8px; padding-top: 8px; border-top: 1px dashed #3a4a6b;">
                <span style="color: #8ba4c7;">涨跌幅：</span>
                <span style="color: ${changeColor}; font-weight: bold; font-size: 14px;">${changePrefix}${change}%</span>
              </div>
              <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #3a4a6b;">
                <div style="color: #8ba4c7; font-weight: bold; margin-bottom: 6px;">📊 MACD指标</div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                  <span style="color: #8ba4c7;">MACD：</span>
                  <span style="color: ${macdColor};">${macdVal.toFixed(4)}</span>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                  <span style="color: #8ba4c7;">Signal：</span>
                  <span style="color: ${signalColor};">${signalVal.toFixed(4)}</span>
                </div>
                <div style="display: flex; justify-content: space-between;">
                  <span style="color: #8ba4c7;">Histogram：</span>
                  <span style="color: ${histogramColor};">${histogramVal.toFixed(4)}</span>
                </div>
              </div>
            </div>`
          }
        },
        grid: [
          {
            left: '3%',
            right: '3%',
            top: 30,
            height: '55%'
          },
          {
            left: '3%',
            right: '3%',
            top: '70%',
            height: '18%'
          }
        ],
        xAxis: [
          {
            type: 'category',
            data: dates,
            axisLine: {
              lineStyle: {
                color: '#3a4a6b',
                width: 1
              }
            },
            axisLabel: {
              show: false
            },
            axisTick: {
              show: false
            },
            splitLine: {
              show: false
            }
          },
          {
            type: 'category',
            gridIndex: 1,
            data: dates,
            axisLine: {
              lineStyle: {
                color: '#3a4a6b',
                width: 1
              }
            },
            axisLabel: {
              color: '#8ba4c7',
              fontSize: 11,
              interval: labelInterval
            },
            axisTick: {
              show: false
            },
            splitLine: {
              show: false
            }
          }
        ],
        yAxis: [
          {
            type: 'value',
            scale: true,
            min: function(value) {
              return Math.floor(value.min - 1)
            },
            max: function(value) {
              return Math.ceil(value.max + 1)
            },
            axisLine: {
              show: true,
              lineStyle: {
                color: '#3a4a6b'
              }
            },
            axisLabel: {
              color: '#8ba4c7',
              fontSize: 11,
              formatter: '{value}'
            },
            splitLine: {
              lineStyle: {
                color: '#1a2a3b',
                type: 'dashed'
              }
            }
          },
          {
            type: 'value',
            gridIndex: 1,
            scale: true,
            axisLine: {
              show: true,
              lineStyle: {
                color: '#3a4a6b'
              }
            },
            axisLabel: {
              color: '#8ba4c7',
              fontSize: 10,
              formatter: function(value) {
                return value.toFixed(2)
              }
            },
            splitLine: {
              lineStyle: {
                color: '#1a2a3b',
                type: 'dashed'
              }
            }
          }
        ],
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
            },
            barWidth: '60%'
          },
          {
            name: 'MA5',
            type: 'line',
            data: ma5,
            smooth: false,
            showSymbol: false,
            connectNulls: true,
            lineStyle: {
              color: '#faad14',
              width: 1.5,
              type: 'dashed'
            }
          },
          {
            name: 'MA10',
            type: 'line',
            data: ma10,
            smooth: false,
            showSymbol: false,
            connectNulls: true,
            lineStyle: {
              color: '#722ed1',
              width: 1.5,
              type: 'dotted'
            }
          },
          {
            name: 'MACD',
            type: 'line',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: macdData,
            showSymbol: false,
            lineStyle: {
              color: '#ff4d4f',
              width: 1.5
            }
          },
          {
            name: 'Signal',
            type: 'line',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: signalData,
            showSymbol: false,
            lineStyle: {
              color: '#faad14',
              width: 1.5
            }
          },
          {
            name: 'Histogram',
            type: 'bar',
            xAxisIndex: 1,
            yAxisIndex: 1,
            data: histogramData,
            barWidth: '40%'
          }
        ]
      }

      this.mainChart.setOption(option)
    },

    calculateMA(data, period) {
      const result = []
      for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
          result.push(null)
        } else {
          let sum = 0
          for (let j = 0; j < period; j++) {
            sum += data[i - j]
          }
          result.push(Number((sum / period).toFixed(2)))
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
  backdrop-filter: blur(10px);
}

.kline-header h1 {
  font-size: 1.5rem;
  color: #fff;
  margin: 0;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

.back-button {
  padding: 10px 20px;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  border: 1px solid #4a5a7b;
  border-radius: 8px;
  color: #e0e6f0;
  cursor: pointer;
  transition: all 0.3s ease;
  font-size: 14px;
}

.back-button:hover {
  background: linear-gradient(135deg, #4a5a7b, #3a4a6b);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
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
  font-size: 14px;
  font-weight: 500;
}

.period-btn:hover {
  background: rgba(58, 74, 107, 0.5);
  color: #fff;
}

.period-btn.active {
  background: linear-gradient(135deg, #1890ff, #096dd9);
  color: #fff;
  font-weight: bold;
  box-shadow: 0 4px 12px rgba(24, 144, 255, 0.3);
}

.chart-container {
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.main-chart {
  width: 100%;
  height: 600px;
}

.data-source {
  text-align: center;
  padding: 15px;
  color: #8ba4c7;
  font-size: 0.9rem;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 8px;
  border: 1px solid rgba(58, 74, 107, 0.3);
}

@media (max-width: 768px) {
  .house-kline-page {
    padding: 10px;
  }
  
  .kline-header {
    flex-direction: column;
    gap: 10px;
    text-align: center;
  }
  
  .kline-header h1 {
    font-size: 1.2rem;
  }
  
  .header-spacer {
    display: none;
  }
  
  .period-btn {
    padding: 8px 20px;
    font-size: 13px;
  }
  
  .main-chart {
    height: 500px;
  }
}
</style>
