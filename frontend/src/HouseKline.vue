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
    goBack() {
      this.$router.push('/')
    },

    async fetchKlineData() {
      console.log('[HouseKline] fetchKlineData 开始')
      this.loading = true
      this.error = null
      try {
        const response = await getHouseKline()
        console.log('[HouseKline] API响应:', response)
        if (response.success) {
          this.klineData = response.data
          console.log('[HouseKline] klineData:', this.klineData)
          console.log('[HouseKline] monthly数据条数:', this.klineData?.monthly?.length)
          console.log('[HouseKline] quarterly数据条数:', this.klineData?.quarterly?.length)
          if (this.klineData?.monthly?.length > 0) {
            console.log('[HouseKline] monthly第一条数据:', this.klineData.monthly[0])
          }
          this.$nextTick(() => {
            setTimeout(() => {
              console.log('[HouseKline] 延迟后准备渲染图表')
              this.renderMainChart()
            }, 100)
          })
        } else {
          this.error = '获取数据失败'
          console.log('[HouseKline] response.success 为 false')
        }
      } catch (err) {
        console.error('[HouseKline] fetchKlineData 错误:', err)
        this.error = '获取数据失败: ' + err.message
      } finally {
        this.loading = false
      }
    },

    switchPeriod(period) {
      if (this.currentPeriod === period) return
      this.currentPeriod = period
      this.$nextTick(() => {
        if (this.mainChart) {
          this.renderMainChart()
        }
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
          labels.push(item.quarter)
        }
      }
      return labels
    },

    renderMainChart() {
      console.log('[HouseKline] renderMainChart 开始')
      console.log('[HouseKline] klineData:', this.klineData)
      console.log('[HouseKline] currentPeriod:', this.currentPeriod)
      
      if (!this.klineData) {
        console.log('[HouseKline] klineData 为空，退出渲染')
        return
      }

      const data = this.currentPeriod === 'monthly' 
        ? this.klineData.monthly 
        : this.klineData.quarterly

      console.log('[HouseKline] 选中数据:', data)
      console.log('[HouseKline] 数据长度:', data?.length)

      if (!data || data.length === 0) {
        console.log('[HouseKline] 数据为空或长度为0，退出渲染')
        return
      }

      const chartDom = this.$refs.mainChart
      console.log('[HouseKline] chartDom:', chartDom)
      if (!chartDom) {
        console.log('[HouseKline] chartDom 为空，退出渲染')
        return
      }

      if (!this.mainChart) {
        console.log('[HouseKline] 初始化新的echarts实例')
        this.mainChart = echarts.init(chartDom)
      } else {
        console.log('[HouseKline] 使用已有的echarts实例，先clear')
        this.mainChart.clear()
      }

      const dates = this.generateXAxisLabels(data)
      const ohlc = data.map(item => [item.open, item.close, item.low, item.high])
      const ma5 = this.calculateMA(data.map(d => d.close), 5)
      const ma10 = this.calculateMA(data.map(d => d.close), 10)

      console.log('[HouseKline] dates长度:', dates.length)
      console.log('[HouseKline] dates前5个:', dates.slice(0, 5))
      console.log('[HouseKline] ohlc长度:', ohlc.length)
      console.log('[HouseKline] ohlc前5个:', ohlc.slice(0, 5))
      console.log('[HouseKline] ma5前10个:', ma5.slice(0, 10))
      console.log('[HouseKline] ma10前10个:', ma10.slice(0, 10))

      const self = this
      const totalPoints = data.length
      const labelInterval = this.currentPeriod === 'monthly' ? 5 : 2

      const option = {
        animation: false,
        tooltip: {
          trigger: 'axis',
          axisPointer: {
            type: 'cross',
            crossStyle: {
              color: '#3a4a6b'
            },
            snap: true
          },
          backgroundColor: 'rgba(20, 25, 45, 0.95)',
          borderColor: '#3a4a6b',
          textStyle: {
            color: '#fff'
          },
          confine: true,
          enterable: true,
          formatter: function(params) {
            console.log('[HouseKline] tooltip formatter 被调用')
            console.log('[HouseKline] params:', params)
            try {
              if (!params || params.length === 0) {
                console.log('[HouseKline] params为空或长度为0')
                return ''
              }
              
              let itemIndex = -1
              for (let i = 0; i < params.length; i++) {
                console.log(`[HouseKline] params[${i}]:`, params[i])
                if (params[i].dataIndex !== undefined && params[i].dataIndex !== null) {
                  itemIndex = params[i].dataIndex
                  console.log(`[HouseKline] 找到 dataIndex: ${itemIndex}`)
                  break
                }
                if (params[i].dataIndexInAxis !== undefined && params[i].dataIndexInAxis !== null) {
                  itemIndex = params[i].dataIndexInAxis
                  console.log(`[HouseKline] 找到 dataIndexInAxis: ${itemIndex}`)
                  break
                }
              }
              
              if (itemIndex === -1) {
                console.log('[HouseKline] 未找到有效的itemIndex')
                return ''
              }
              
              const item = data[itemIndex]
              console.log('[HouseKline] data[itemIndex]:', item)
              if (!item) {
                console.log('[HouseKline] item为空')
                return ''
              }
              
              const change = ((item.close - item.open) / item.open * 100).toFixed(2)
              const changeColor = change >= 0 ? '#ff4d4f' : '#52c41a'
              
              let dateLabel
              if (self.currentPeriod === 'monthly') {
                dateLabel = `${item.year}年${item.month}月`
              } else {
                dateLabel = item.quarter
              }
              
              let highLow = ''
              if (item.high !== undefined && item.low !== undefined) {
                highLow = `<div style="margin-bottom: 5px;">最高: <span style="color: #ff4d4f;">${item.high.toFixed(2)}万元</span></div>
                <div style="margin-bottom: 5px;">最低: <span style="color: #52c41a;">${item.low.toFixed(2)}万元</span></div>`
              }

              return `<div style="padding: 10px;">
                <div style="font-weight: bold; margin-bottom: 10px; font-size: 14px;">${dateLabel}</div>
                <div style="margin-bottom: 5px;">开盘: <span style="color: #faad14;">${item.open.toFixed(2)}万元</span></div>
                <div style="margin-bottom: 5px;">收盘: <span style="color: #1890ff;">${item.close.toFixed(2)}万元</span></div>
                ${highLow}
                <div style="margin-bottom: 5px;">涨跌: <span style="color: ${changeColor}; font-weight: bold;">${change >= 0 ? '+' : ''}${change}%</span></div>
              </div>`
            } catch (e) {
              console.error('tooltip error:', e, params)
              return ''
            }
          }
        },
        legend: {
          data: ['K线', 'MA5', 'MA10'],
          textStyle: {
            color: '#8ba4c7'
          },
          top: 10
        },
        grid: {
          left: '8%',
          right: '8%',
          top: 60,
          bottom: 60
        },
        xAxis: {
          type: 'category',
          data: dates,
          axisLine: { lineStyle: { color: '#3a4a6b' } },
          axisLabel: {
            color: '#8ba4c7',
            fontSize: 11,
            interval: labelInterval,
            rotate: 0
          },
          splitLine: { show: false },
          axisTick: {
            alignWithLabel: true
          },
          axisPointer: {
            show: true,
            type: 'shadow',
            label: {
              show: true,
              color: '#8ba4c7'
            }
          }
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
          },
          axisPointer: {
            show: true,
            label: {
              show: true,
              color: '#8ba4c7'
            }
          }
        },
        series: [
          {
            name: 'K线',
            type: 'candlestick',
            data: ohlc,
            xAxisIndex: 0,
            yAxisIndex: 0,
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
            xAxisIndex: 0,
            yAxisIndex: 0,
            smooth: false,
            connectNulls: true,
            lineStyle: {
              color: '#faad14',
              width: 1,
              type: 'dashed'
            },
            symbol: 'none'
          },
          {
            name: 'MA10',
            type: 'line',
            data: ma10,
            xAxisIndex: 0,
            yAxisIndex: 0,
            smooth: false,
            connectNulls: true,
            lineStyle: {
              color: '#722ed1',
              width: 2,
              type: 'dotted'
            },
            symbol: 'none'
          }
        ]
      }

      console.log('[HouseKline] 准备调用 setOption')
      console.log('[HouseKline] option:', option)
      
      try {
        this.mainChart.setOption(option)
        console.log('[HouseKline] setOption 调用成功')
      } catch (e) {
        console.error('[HouseKline] setOption 调用失败:', e)
      }
      
      this.mainChart.on('legendselectchanged', function(params) {
        console.log('[HouseKline] legendselectchanged 事件触发')
        console.log('[HouseKline] legend params:', params)
      })
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
  height: 500px;
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
