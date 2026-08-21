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
      testChart: null,
      toolChart: null,
      dailyChart: null
    }
  },
  async mounted() {
    this._onResize = () => {
      if (this.testChart) this.testChart.resize()
      if (this.toolChart) this.toolChart.resize()
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
    if (this.testChart) { this.testChart.dispose(); this.testChart = null }
    if (this.toolChart) { this.toolChart.dispose(); this.toolChart = null }
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
      this.loading = true // 重试时也回到加载态,避免闪出 overview 为空的主体
      try {
        const res = await getMpAdminOverview()
        if (res && res.success) {
          this.overview = res.data
        } else {
          this.error = (res && res.message) || '加载失败'
        }
      } catch (e) {
        const data = e && e.response && e.response.data
        this.error = (data && data.message) || '加载失败，请稍后重试'
      } finally {
        // 必须先解除加载态,图表容器(v-else分支)才会进DOM,再初始化echarts
        this.loading = false
        if (this.overview) this.$nextTick(() => this.renderCharts())
      }
    },
    renderCharts() {
      if (!this.overview) return
      this.renderBarChart('testChart', this.overview.test_counts, '#1890ff')
      this.renderBarChart('toolChart', this.overview.tool_counts, '#13c2c2')
      this.renderDailyChart()
    },
    _initChart(refName, key) {
      const dom = this.$refs[refName]
      if (!dom) return null
      if (this[key]) this[key].dispose()
      this[key] = echarts.init(dom)
      return this[key]
    },
    renderBarChart(refName, items, color) {
      if (!items || !items.length) return
      const chart = this._initChart(refName, refName)
      if (!chart) return
      chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'axis', axisPointer: { type: 'shadow' }, ...TOOLTIP,
          formatter: (params) => {
            const p = params[0]
            const item = items[p.dataIndex]
            return `${item.name}<br/><span style="color:#8ba4c7">${item.key}</span> ： ${p.value} 次`
          }
        },
        grid: { left: 10, right: 16, top: 16, bottom: 10, containLabel: true },
        xAxis: {
          type: 'category',
          data: items.map(x => x.name),
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
          itemStyle: { color, borderRadius: [3, 3, 0, 0] }
        }]
      })
    },
    renderDailyChart() {
      const chart = this._initChart('dailyChart', 'dailyChart')
      if (!chart) return
      const { days, tests, tools, scores, rooms } = this.overview.daily
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
          { name: '工具人次', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
            data: tools, itemStyle: { color: '#13c2c2' }, lineStyle: { width: 2 } },
          { name: '新增成绩', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
            data: scores, itemStyle: { color: '#faad14' }, lineStyle: { width: 2 } },
          { name: '新建房间', type: 'line', smooth: true, symbol: 'circle', symbolSize: 5,
            data: rooms, itemStyle: { color: '#b37feb' }, lineStyle: { width: 2 } }
        ]
      })
    }
  }
}
