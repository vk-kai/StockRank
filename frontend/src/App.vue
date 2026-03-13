<template>
  <div class="dashboard">
    <header class="header">
      <h1>A股板块资金流入统计</h1>
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
      </div>
    </header>

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

<script>
import * as echarts from 'echarts'
import { formatFlow } from './utils/formatters'
import { getCurrentFlow, getHistoryData, getMinuteData } from './services/apiService'
import { generateChartOption, generateSeries } from './services/chartService'
import './styles/App.css'

export default {
  name: 'App',
  data() {
    return {
      selectedTimeRange: 'today',
      currentData: [],
      historyData: {},
      minuteData: {},
      chartInstance: null,
      loading: false,
      error: null,
      lastUpdate: null,
      colors: [
        '#5470c6', '#91cc75', '#fac858', '#ee6666', '#73c0de',
        '#3ba272', '#fc8452', '#9a60b4', '#ea7ccc', '#ff5722',
        '#00bcd4', '#8bc34a', '#ffc107', '#9c27b0', '#3f51b5'
      ],
      countdown: 300, // 5分钟，单位秒
      countdownInterval: null
    }
  },
  computed: {
    countdownMinutes() {
      return Math.floor(this.countdown / 60).toString().padStart(2, '0')
    },
    countdownSeconds() {
      return (this.countdown % 60).toString().padStart(2, '0')
    }
  },
  mounted() {
    this.initChart()
    this.fetchDataByTimeRange()
    this.startCountdown()
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.handleResize)
    if (this.chartInstance) {
      this.chartInstance.dispose()
      this.chartInstance = null
    }
    if (this.countdownInterval) {
      clearInterval(this.countdownInterval)
    }
  },
  methods: {
    initChart() {
      // 确保 DOM 已渲染完成
      this.$nextTick(() => {
        this.chartInstance = echarts.init(this.$refs.chart)
      })
    },

    handleResize() {
      if (this.chartInstance) {
        this.chartInstance.resize()
      }
    },

    highlightSector(sectorName) {
      if (!this.chartInstance) return
            
      // 使用 ECharts 的 dispatchAction 来高亮系列
      this.chartInstance.dispatchAction({
        type: 'highlight',
        seriesName: sectorName
      })
      
      // 淡化其他系列
      const option = this.chartInstance.getOption()
      if (option.series) {
        option.series.forEach((series) => {
          if (series.name !== sectorName) {
            // 淡化其他系列
            this.chartInstance.dispatchAction({
              type: 'downplay',
              seriesName: series.name
            })
          }
        })
      }
    },

    unhighlightSector() {
      if (!this.chartInstance) return
      
      
      // 取消所有高亮
      this.chartInstance.dispatchAction({
        type: 'downplay'
      })
    },

    async fetchCurrentData() {
      try {
        this.loading = true
        this.error = null
        const response = await getCurrentFlow()
        if (response.success) {
          this.currentData = response.data
          const timestamp = new Date(response.timestamp)
          this.lastUpdate = timestamp.toLocaleString('zh-CN')
          
          if (this.selectedTimeRange === 'today') {
            await this.fetchMinuteData()
          } else {
            this.updateChart()
          }
        }
      } catch (err) {
        console.error('获取当前数据失败:', err)
        this.error = '获取当前数据失败: ' + err.message
      } finally {
        this.loading = false
      }
    },

    async fetchHistoryData(days) {
      this.loading = true
      this.error = null
      try {
        const response = await getHistoryData(days)
        if (response.success) {
          this.historyData = response.data
          
          // 使用最新的历史数据作为 currentData 显示在下方榜单
          const dates = Object.keys(this.historyData).sort()
          if (dates.length > 0) {
            const latestDate = dates[dates.length - 1]
            this.currentData = this.historyData[latestDate] || []
          }
          
          this.updateChart()
        }
      } catch (err) {
        this.error = '获取历史数据失败: ' + err.message
      } finally {
        this.loading = false
      }
    },

    async fetchMinuteData() {
      this.loading = true
      this.error = null
      try {
        const response = await getMinuteData(24)
        if (response.success) {
          this.minuteData = response.data
          this.updateChart()
        }
      } catch (err) {
        this.error = '获取分钟数据失败: ' + err.message
      } finally {
        this.loading = false
      }
    },

    async fetchDataByTimeRange() {
      if (this.selectedTimeRange === 'today') {
        await this.fetchCurrentData()
        await this.fetchMinuteData()
      } else {
        await this.fetchCurrentData()
        await this.fetchHistoryData(this.selectedTimeRange)
      }
    },

    async fetchData() {
      await this.fetchCurrentData()
      if (this.selectedTimeRange === 'today') {
        await this.fetchMinuteData()
      } else {
        await this.fetchHistoryData(this.selectedTimeRange)
      }
    },

    retry() {
      this.error = null
      this.fetchDataByTimeRange()
    },

    startCountdown() {
      this.countdownInterval = setInterval(() => {
        if (this.countdown > 0) {
          this.countdown--
        } else {
          this.fetchData()
          this.countdown = 300 // 重置为5分钟
        }
      }, 1000) // 每秒更新一次
    },

    updateChart() {
      if (!this.chartInstance) {
        console.log('图表实例不存在，重新初始化')
        this.initChart()
        return
      }

      const oldOption = this.chartInstance.getOption()
      const oldSelected = oldOption?.legend?.[0]?.selected || {}

      let timeData, allData

      if (this.selectedTimeRange === 'today') {
        timeData = Object.keys(this.minuteData).sort()
        allData = this.minuteData
      } else {
        timeData = Object.keys(this.historyData).sort()
        // 将 historyData 转换为统一格式 {date: {data: [板块列表]}}
        allData = {}
        timeData.forEach(date => {
          const sectorList = this.historyData[date]
          if (Array.isArray(sectorList)) {
            allData[date] = { data: sectorList }
          } else {
            allData[date] = sectorList
          }
        })
      }

      let option
      if (timeData.length === 0) {
        console.log('没有数据，显示空图表')
        // 显示空图表配置
        option = {
          tooltip: {
            trigger: 'item',
            backgroundColor: 'rgba(20,25,45,0.95)',
            borderColor: '#3a4a6b',
            borderWidth: 1
          },
          legend: {
            data: [],
            textStyle: {
              color: '#8ba4c7'
            }
          },
          grid: {
            left: '3%',
            right: '4%',
            bottom: '15%',
            top: '15%',
            containLabel: true
          },
          xAxis: {
            type: 'category',
            boundaryGap: false,
            data: ['暂无数据'],
            axisLabel: {
              color: '#8ba4c7'
            }
          },
          yAxis: {
            type: 'value',
            name: '资金流入',
            axisLabel: {
              color: '#8ba4c7',
              formatter: (value) => {
                if (value >= 100000000) {
                  return (value / 100000000).toFixed(1) + '亿'
                }
                if (value >= 10000) {
                  return (value / 10000).toFixed(1) + '万'
                }
                return value
              }
            }
          },
          series: []
        }
      } else {
        const topSectors = this.getTopSectors(timeData, allData)
        const series = generateSeries(topSectors, timeData, allData, this.colors)
        option = generateChartOption(timeData, series, topSectors, oldSelected, this.colors)
      }

      this.chartInstance.setOption(option)
    },
    getTopSectors(timeData, allData) {
      const sectorFlows = {}
      
      timeData.forEach(timeKey => {
        const data = allData[timeKey]?.data || []
        data.forEach(item => {
          if (!sectorFlows[item.name]) {
            sectorFlows[item.name] = []
          }
          sectorFlows[item.name].push(item.flow)
        })
      })

      const avgFlows = Object.entries(sectorFlows).map(([name, flows]) => {
        const validFlows = flows.filter(f => f !== null)
        if (validFlows.length === 0) return { name, avgFlow: 0 }
        const avg = validFlows.reduce((a, b) => a + b, 0) / validFlows.length
        return { name, avgFlow: avg }
      })

      avgFlows.sort((a, b) => b.avgFlow - a.avgFlow)
      
      return avgFlows.slice(0, 15).map(s => s.name)
    },

    formatFlow(value) {
      return formatFlow(value)
    }
  }
}
</script>