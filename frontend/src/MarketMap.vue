<template>
  <div class="market-map-page">
    <header class="mm-header">
      <button @click="goBack" class="mm-back-button">← 返回</button>
      <h1>🗺️ A股大盘云图</h1>
      <div class="mm-header-right">
        <span class="mm-breadcrumb" v-if="currentSector">
          全市场 / <strong>{{ currentSectorName }}</strong>
          <button class="mm-back-sector" @click="backToSectors">返回全部</button>
        </span>
        <span class="mm-update" v-if="updateTime">更新：{{ updateTime }}</span>
        <button @click="fetchSectors(true)" class="mm-refresh-btn" :disabled="loading">
          {{ loading ? '刷新中...' : '🔄 刷新' }}
        </button>
      </div>
    </header>

    <div class="mm-chart-wrapper">
      <div ref="chartEl" class="mm-chart"></div>
      <div class="mm-legend">
        <span class="legend-grad up"></span>
        <span class="legend-label">涨</span>
        <span class="legend-zero"></span>
        <span class="legend-label">跌</span>
        <span class="legend-grad down"></span>
        <span class="legend-tip">面积=市值 · 颜色=涨跌幅 · 点击板块下钻个股 · 双击返回</span>
      </div>
      <div class="mm-loading" v-if="loading && !hasData">
        <div class="spinner"></div>
        <p>加载中...</p>
      </div>
    </div>

    <div class="mm-footer">数据来源：新浪财经 · 面积代表总市值，颜色代表涨跌幅 · 仅供投资参考</div>
    <SecurityAlert />
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getMarketMap, getMarketMapStocks } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

export default {
  name: 'MarketMap',
  components: { SecurityAlert },
  data() {
    return {
      loading: false,
      sectors: [],
      currentSector: null,
      currentSectorName: '',
      stocks: [],
      updateTime: '',
      chart: null,
      timer: null
    }
  },
  computed: {
    hasData() {
      return (this.currentSector && this.stocks.length > 0) || this.sectors.length > 0
    }
  },
  async mounted() {
    await this.fetchSectors(true)
    this.timer = setInterval(() => this.autoRefresh(), 30000)
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    clearInterval(this.timer)
    window.removeEventListener('resize', this.handleResize)
    if (this.chart) {
      this.chart.dispose()
      this.chart = null
    }
  },
  methods: {
    goBack() {
      this.$router.push('/')
    },
    async fetchSectors(showLoading) {
      this.loading = showLoading
      try {
        const res = await getMarketMap()
        if (res.success) {
          this.sectors = res.data.sectors
          this.updateTime = res.data.update_time
          this.currentSector = null
          this.currentSectorName = ''
          this.stocks = []
          this.$nextTick(() => this.renderSectors())
        }
      } catch (e) {
        console.error('获取板块失败', e)
      } finally {
        this.loading = false
      }
    },
    async fetchStocks(sector, showLoading) {
      this.loading = showLoading
      try {
        const res = await getMarketMapStocks(sector.code)
        if (res.success) {
          this.currentSector = sector
          this.currentSectorName = sector.name
          this.stocks = res.data.stocks
          this.updateTime = res.data.update_time
          this.$nextTick(() => this.renderStocks())
        }
      } catch (e) {
        console.error('获取个股失败', e)
      } finally {
        this.loading = false
      }
    },
    backToSectors() {
      this.fetchSectors(false)
    },
    async autoRefresh() {
      // 仅在板块层级自动刷新，避免打断下钻浏览
      if (this.currentSector) return
      try {
        const res = await getMarketMap()
        if (res.success) {
          this.sectors = res.data.sectors
          this.updateTime = res.data.update_time
          this.renderSectors()
        }
      } catch (e) {
        // 静默失败
      }
    },
    handleResize() {
      if (this.chart) this.chart.resize()
    },
    // 涨跌幅(%) → 颜色：红涨绿跌，幅度越大越深
    colorOf(change) {
      const c = Math.abs(change)
      // 钳制在 0~6% 范围，避免极端值
      const ratio = Math.min(c / 6, 1)
      // 透明度 0.25~0.95
      const opacity = 0.25 + ratio * 0.7
      return change >= 0
        ? `rgba(240, 65, 55, ${opacity})`
        : `rgba(40, 175, 99, ${opacity})`
    },
    textColorOf(change) {
      return Math.abs(change) > 2 ? '#fff' : '#f0f3fa'
    },
    initChart() {
      const el = this.$refs.chartEl
      if (!el) return
      if (this.chart) {
        this.chart.dispose()
      }
      this.chart = echarts.init(el)
    },
    renderSectors() {
      this.initChart()
      if (!this.chart) return
      const data = this.sectors.map(s => ({
        name: s.name,
        value: s.value,
        sectorCode: s.code,
        change: s.change,
        leader: s.leader,
        leaderChange: s.leader_change
      }))
      this.chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
          backgroundColor: 'rgba(20,25,45,0.95)',
          borderColor: '#3a4a6b',
          borderWidth: 1,
          padding: [12, 16],
          textStyle: { color: '#e0e6f0', fontSize: 13 },
          formatter: p => {
            const d = p.data
            const c = d.change
            const cc = c >= 0 ? '#ff4d4f' : '#52c41a'
            const cap = (d.value / 1e8).toFixed(1)
            const leaderStr = d.leader ? `<br/><span style="color:#8ba4c7">领涨：${d.leader} <span style="color:${d.leaderChange >= 0 ? '#ff4d4f' : '#52c41a'}">${d.leaderChange >= 0 ? '+' : ''}${d.leaderChange}%</span></span>` : ''
            return `<div style="min-width:150px">
              <div style="font-weight:bold;font-size:15px;margin-bottom:6px">${d.name}</div>
              <div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="color:#8ba4c7">总市值</span><span>${cap} 亿</span></div>
              <div style="display:flex;justify-content:space-between"><span style="color:#8ba4c7">涨跌幅</span><span style="color:${cc};font-weight:bold;font-size:15px">${c >= 0 ? '+' : ''}${c}%</span></div>
              ${leaderStr}
              <div style="color:#5a6b8c;margin-top:6px;font-size:11px">点击查看个股</div>
            </div>`
          }
        },
        series: [{
          type: 'treemap',
          roam: false,
          nodeClick: false,
          data,
          breadcrumb: { show: false },
          left: 8,
          right: 8,
          top: 8,
          bottom: 8,
          label: {
            show: true,
            formatter: p => {
              const c = p.data.change
              const sign = c >= 0 ? '+' : ''
              return `{n|${p.name}}\n{c|${sign}${c}%}`
            },
            rich: {
              n: { color: '#fff', fontSize: 14, fontWeight: 'bold', lineHeight: 22, textShadowColor: 'rgba(0,0,0,0.4)', textShadowBlur: 3 },
              c: { color: '#fff', fontSize: 13, lineHeight: 18, textShadowColor: 'rgba(0,0,0,0.4)', textShadowBlur: 3 }
            }
          },
          upperLabel: { show: false },
          itemStyle: {
            borderColor: '#0a0e17',
            borderWidth: 2,
            gapWidth: 2
          },
          levels: [{
            itemStyle: {
              borderColor: '#0a0e17',
              borderWidth: 2,
              gapWidth: 2
            }
          }],
          visualDimension: null
        }]
      }, true)
      // 点击下钻到个股
      this.chart.off('click')
      this.chart.on('click', params => {
        if (params.data && params.data.sectorCode) {
          this.fetchStocks({ code: params.data.sectorCode, name: params.data.name }, true)
        }
      })
      // 双击返回
      this.chart.getZr().off('dblclick')
      this.chart.getZr().on('dblclick', () => {
        if (this.currentSector) this.backToSectors()
      })
    },
    renderStocks() {
      this.initChart()
      if (!this.chart) return
      const self = this
      const data = this.stocks.map(s => ({
        name: s.name,
        value: s.value,
        code: s.code,
        change: s.change,
        price: s.price
      }))
      this.chart.setOption({
        backgroundColor: 'transparent',
        title: {
          text: `${this.currentSectorName} · 个股云图`,
          left: 16,
          top: 8,
          textStyle: { color: '#8ba4c7', fontSize: 14, fontWeight: 'normal' }
        },
        tooltip: {
          backgroundColor: 'rgba(20,25,45,0.95)',
          borderColor: '#3a4a6b',
          borderWidth: 1,
          padding: [12, 16],
          textStyle: { color: '#e0e6f0', fontSize: 13 },
          formatter: p => {
            const d = p.data
            const c = d.change
            const cc = c >= 0 ? '#ff4d4f' : '#52c41a'
            return `<div style="min-width:150px">
              <div style="font-weight:bold;font-size:15px;margin-bottom:6px">${d.name} <span style="color:#8ba4c7;font-weight:normal">${d.code}</span></div>
              <div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="color:#8ba4c7">现价</span><span>${d.price}</span></div>
              <div style="display:flex;justify-content:space-between"><span style="color:#8ba4c7">涨跌幅</span><span style="color:${cc};font-weight:bold;font-size:15px">${c >= 0 ? '+' : ''}${c}%</span></div>
            </div>`
          }
        },
        series: [{
          type: 'treemap',
          roam: false,
          nodeClick: false,
          data: data.map(d => ({
            ...d,
            itemStyle: { color: self.colorOf(d.change) }
          })),
          breadcrumb: { show: false },
          left: 8,
          right: 8,
          top: 50,
          bottom: 8,
          label: {
            show: true,
            formatter: p => {
              const c = p.data.change
              const sign = c >= 0 ? '+' : ''
              // 大块显示名称+涨跌，小块只显示涨跌
              if (p.data.value < this.maxStockValue() * 0.04) {
                return `{c|${sign}${c}%}`
              }
              return `{n|${p.name}}\n{c|${sign}${c}%}`
            },
            rich: {
              n: { color: '#fff', fontSize: 12, fontWeight: 'bold', lineHeight: 20, textShadowColor: 'rgba(0,0,0,0.4)', textShadowBlur: 3 },
              c: { color: '#fff', fontSize: 11, lineHeight: 16, textShadowColor: 'rgba(0,0,0,0.4)', textShadowBlur: 3 }
            }
          },
          upperLabel: { show: false },
          itemStyle: {
            borderColor: '#0a0e17',
            borderWidth: 2,
            gapWidth: 2
          }
        }]
      }, true)
      this.chart.off('click')
      // 双击返回全部板块
      this.chart.getZr().off('dblclick')
      this.chart.getZr().on('dblclick', () => {
        this.backToSectors()
      })
    },
    maxStockValue() {
      return this.stocks.length ? this.stocks[0].value : 1
    }
  }
}
</script>

<style scoped>
.market-map-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0e17 0%, #1a1f35 50%, #0d1321 100%);
  color: #e0e6f0;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.mm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 20px;
  background: rgba(26, 35, 53, 0.8);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  backdrop-filter: blur(10px);
  margin-bottom: 16px;
}

.mm-header h1 {
  font-size: 1.4rem;
  color: #fff;
  margin: 0;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

.mm-header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.mm-breadcrumb {
  font-size: 13px;
  color: #8ba4c7;
  display: flex;
  align-items: center;
  gap: 6px;
}

.mm-breadcrumb strong {
  color: #e0e6f0;
}

.mm-back-sector {
  background: rgba(58, 74, 107, 0.5);
  border: 1px solid #4a5a7b;
  border-radius: 4px;
  color: #e0e6f0;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
  margin-left: 4px;
  transition: all 0.2s ease;
}

.mm-back-sector:hover {
  background: rgba(58, 74, 107, 0.8);
}

.mm-update {
  font-size: 12px;
  color: #8ba4c7;
}

.mm-back-button {
  padding: 10px 20px;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  border: 1px solid #4a5a7b;
  border-radius: 8px;
  color: #e0e6f0;
  cursor: pointer;
  transition: all 0.3s ease;
  font-size: 14px;
}

.mm-back-button:hover {
  background: linear-gradient(135deg, #4a5a7b, #3a4a6b);
  transform: translateY(-2px);
}

.mm-refresh-btn {
  padding: 8px 16px;
  background: linear-gradient(135deg, #1890ff, #096dd9);
  border: 1px solid #40a9ff;
  border-radius: 6px;
  color: #fff;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.3s ease;
}

.mm-refresh-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #40a9ff, #1890ff);
  transform: translateY(-2px);
}

.mm-refresh-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.mm-chart-wrapper {
  flex: 1;
  position: relative;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  padding: 16px;
  min-height: 600px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.mm-chart {
  width: 100%;
  height: 100%;
  min-height: 580px;
}

.mm-legend {
  position: absolute;
  bottom: 18px;
  left: 24px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #8ba4c7;
  pointer-events: none;
  z-index: 5;
}

.legend-grad {
  width: 60px;
  height: 10px;
  border-radius: 3px;
  display: inline-block;
}

.legend-grad.up {
  background: linear-gradient(90deg, rgba(240,65,55,0.25), rgba(240,65,55,0.95));
}

.legend-grad.down {
  background: linear-gradient(90deg, rgba(40,175,99,0.95), rgba(40,175,99,0.25));
}

.legend-zero {
  width: 4px;
  height: 14px;
  background: #8ba4c7;
  border-radius: 2px;
  display: inline-block;
}

.legend-label {
  font-size: 11px;
}

.legend-tip {
  margin-left: 12px;
  color: #5a6b8c;
}

.mm-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(10, 14, 23, 0.6);
  color: #8ba4c7;
  z-index: 10;
}

.spinner {
  width: 36px;
  height: 36px;
  border: 3px solid rgba(58, 74, 107, 0.4);
  border-top-color: #1890ff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 12px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.mm-footer {
  text-align: center;
  padding: 14px;
  color: #8ba4c7;
  font-size: 0.85rem;
  margin-top: 16px;
}

@media (max-width: 768px) {
  .market-map-page { padding: 10px; }
  .mm-header {
    flex-direction: column;
    gap: 10px;
    text-align: center;
  }
  .mm-header h1 { font-size: 1.1rem; }
  .mm-chart-wrapper { min-height: 460px; }
  .mm-chart { min-height: 440px; }
  .legend-tip { display: none; }
}
</style>
