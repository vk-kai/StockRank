import * as echarts from 'echarts'
import { getAuthSession, getMpAdminOverview } from '../../services/apiService'

// 图表公共暗色样式(与 HouseKline/首页一致)
const AXIS_LINE = '#3a4a6b'
const AXIS_LABEL = '#8ba4c7'
const SPLIT_LINE = { lineStyle: { color: '#1a2a3b', type: 'dashed' } }
const TOOLTIP = {
  backgroundColor: 'rgba(20, 25, 45, 0.95)',
  borderColor: '#3a4a6b',
  textStyle: { color: '#e0e6f0', fontSize: 13 }
}

export default {
  name: 'MpAdmin',
  data() {
    return {
      loading: true,
      isAdmin: false,
      error: null,
      overview: null,
      statChart: null,
      dailyChart: null
    }
  },
  async mounted() {
    this._onResize = () => {
      if (this.statChart) this.statChart.resize()
      if (this.dailyChart) this.dailyChart.resize()
    }
    window.addEventListener('resize', this._onResize)
    try {
      const session = await getAuthSession()
      this.isAdmin = !!(session && session.is_admin)
      if (this.isAdmin) {
        await this.fetchOverview()
      }
    } catch (e) {
      this.isAdmin = false
      this.error = '加载失败：' + (e && e.message ? e.message : '网络异常')
    } finally {
      this.loading = false
    }
  },
  beforeUnmount() {
    window.removeEventListener('resize', this._onResize)
    if (this.statChart) { this.statChart.dispose(); this.statChart = null }
    if (this.dailyChart) { this.dailyChart.dispose(); this.dailyChart = null }
  },
  methods: {
    goBack() {
      if (this.$router) this.$router.push('/')
    },
    goManage() {
      this.$router.push('/mp-admin/manage')
    },
    async fetchOverview() {
      this.error = null
      try {
        const res = await getMpAdminOverview()
        if (res && res.success) {
          this.overview = res.data
          this.$nextTick(() => this.renderCharts())
        } else {
          this.error = (res && res.message) || '加载失败'
        }
      } catch (e) {
        const data = e && e.response && e.response.data
        this.error = (data && data.message) || '加载失败，请稍后重试'
      }
    },
    renderCharts() {
      if (!this.overview) return
      this.renderStatChart()
      this.renderDailyChart()
    },
    _initChart(refName, key) {
      const dom = this.$refs[refName]
      if (!dom) return null
      if (this[key]) this[key].dispose()
      this[key] = echarts.init(dom)
      return this[key]
    },
    renderStatChart() {
      const chart = this._initChart('statChart', 'statChart')
      if (!chart) return
      const items = this.overview.stat_counts
      chart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, ...TOOLTIP },
        grid: { left: 10, right: 16, top: 16, bottom: 10, containLabel: true },
        xAxis: {
          type: 'category',
          data: items.map(x => x.key),
          axisLine: { lineStyle: { color: AXIS_LINE } },
          axisLabel: { color: AXIS_LABEL, fontSize: 11, interval: 0, rotate: items.length > 6 ? 32 : 0 },
          axisTick: { show: false }
        },
        yAxis: {
          type: 'value',
          minInterval: 1,
          axisLabel: { color: AXIS_LABEL, fontSize: 11 },
          splitLine: SPLIT_LINE
        },
        series: [{
          type: 'bar',
          data: items.map(x => x.count),
          barMaxWidth: 34,
          itemStyle: { color: '#1890ff', borderRadius: [3, 3, 0, 0] }
        }]
      })
    },
    renderDailyChart() {
      const chart = this._initChart('dailyChart', 'dailyChart')
      if (!chart) return
      const { days, tests, scores, rooms } = this.overview.daily
      const shortDays = days.map(d => d.slice(5)) // MM-DD
      chart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', ...TOOLTIP },
        legend: {
          top: 0, right: 8, itemWidth: 14, itemHeight: 8,
          textStyle: { color: AXIS_LABEL, fontSize: 11 }
        },
        grid: { left: 10, right: 16, top: 30, bottom: 10, containLabel: true },
        xAxis: {
          type: 'category',
          data: shortDays,
          axisLine: { lineStyle: { color: AXIS_LINE } },
          axisLabel: { color: AXIS_LABEL, fontSize: 11 },
          axisTick: { show: false }
        },
        yAxis: {
          type: 'value',
          minInterval: 1,
          axisLabel: { color: AXIS_LABEL, fontSize: 11 },
          splitLine: SPLIT_LINE
        },
        series: [
          { name: '测试人次', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
            data: tests, itemStyle: { color: '#1890ff' }, lineStyle: { width: 2 } },
          { name: '新增成绩', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
            data: scores, itemStyle: { color: '#faad14' }, lineStyle: { width: 2 } },
          { name: '新建房间', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
            data: rooms, itemStyle: { color: '#13c2c2' }, lineStyle: { width: 2 } }
        ]
      })
    }
  }
}
