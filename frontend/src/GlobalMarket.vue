<template>
  <div class="global-market-page">
    <header class="gm-header">
      <button @click="goBack" class="gm-back-button">← 返回</button>
      <h1>🌍 全球股市指数实时地图</h1>
      <div class="gm-header-right">
        <span class="gm-source-tag" v-if="data && data.source">
          数据源：{{ data.source === 'eastmoney' ? '东方财富' : '新浪财经' }}
        </span>
        <span class="gm-update" v-if="data && data.update_time">更新：{{ data.update_time }}</span>
        <button @click="fetchData(true)" class="gm-refresh-btn" :disabled="loading">
          {{ loading ? '刷新中...' : '🔄 刷新' }}
        </button>
      </div>
    </header>

    <div class="gm-body">
      <div class="gm-chart-wrapper">
        <div ref="chartEl" class="gm-chart"></div>
        <div class="gm-legend">
          <span class="legend-item"><i class="dot up"></i>上涨</span>
          <span class="legend-item"><i class="dot down"></i>下跌</span>
          <span class="legend-tip">滚轮缩放 · 拖动平移</span>
        </div>
      </div>

      <aside class="gm-rank">
        <div class="gm-rank-section">
          <h3 class="gm-rank-title up">📈 涨幅榜</h3>
          <div class="gm-rank-list">
            <div v-for="item in topGainers" :key="item.code" class="gm-rank-item">
              <span class="gm-rank-region">{{ item.region }}</span>
              <span class="gm-rank-name">{{ item.name }}</span>
              <span class="gm-rank-change up">{{ formatChange(item.change) }}</span>
            </div>
            <div v-if="topGainers.length === 0" class="gm-empty">暂无数据</div>
          </div>
        </div>
        <div class="gm-rank-section">
          <h3 class="gm-rank-title down">📉 跌幅榜</h3>
          <div class="gm-rank-list">
            <div v-for="item in topLosers" :key="item.code" class="gm-rank-item">
              <span class="gm-rank-region">{{ item.region }}</span>
              <span class="gm-rank-name">{{ item.name }}</span>
              <span class="gm-rank-change down">{{ formatChange(item.change) }}</span>
            </div>
            <div v-if="topLosers.length === 0" class="gm-empty">暂无数据</div>
          </div>
        </div>
      </aside>
    </div>

    <div class="gm-footer">数据来源：东方财富 / 新浪财经（双源容错）· 仅供投资参考，不构成建议</div>
    <SecurityAlert />
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getGlobalIndices } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

export default {
  name: 'GlobalMarket',
  components: { SecurityAlert },
  data() {
    return {
      loading: false,
      data: null,
      chart: null,
      timer: null
    }
  },
  computed: {
    indices() {
      return (this.data && this.data.indices) || []
    },
    topGainers() {
      return this.indices.slice(0, 8)
    },
    topLosers() {
      return this.indices.slice(-8).reverse()
    }
  },
  async mounted() {
    await this.loadMap()
    await this.fetchData(true)
    this.timer = setInterval(() => this.fetchData(false), 30000)
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
    async loadMap() {
      try {
        const res = await fetch('/world.json')
        const geo = await res.json()
        echarts.registerMap('world', geo)
      } catch (e) {
        console.error('世界地图加载失败', e)
      }
    },
    async fetchData(showLoading) {
      this.loading = showLoading
      try {
        const res = await getGlobalIndices()
        if (res.success) {
          this.data = res.data
          this.$nextTick(() => this.renderChart())
        }
      } catch (e) {
        console.error('获取全球指数失败', e)
      } finally {
        this.loading = false
      }
    },
    formatChange(change) {
      const pct = (change * 100).toFixed(2)
      return (change >= 0 ? '+' : '') + pct + '%'
    },
    handleResize() {
      if (this.chart) this.chart.resize()
    },
    renderChart() {
      const list = this.indices
      if (!list.length) return
      const el = this.$refs.chartEl
      if (!el) return
      if (!this.chart) {
        this.chart = echarts.init(el)
      }

      const scatterData = list.map(i => ({
        name: i.name,
        value: [i.lng, i.lat, +(i.change * 100).toFixed(2), i.price, i.region]
      }))

      const colorOf = v => v[2] >= 0 ? '#ff4d4f' : '#52c41a'
      const sizeOf = v => Math.min(Math.max(Math.abs(v[2]) * 3 + 8, 8), 38)

      this.chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
          trigger: 'item',
          backgroundColor: 'rgba(20,25,45,0.95)',
          borderColor: '#3a4a6b',
          borderWidth: 1,
          padding: [12, 16],
          textStyle: { color: '#e0e6f0', fontSize: 13 },
          formatter: p => {
            const v = p.value
            const chg = v[2]
            const c = chg >= 0 ? '#ff4d4f' : '#52c41a'
            return `<div style="min-width:170px">
              <div style="font-weight:bold;font-size:14px;border-bottom:1px solid #3a4a6b;padding-bottom:6px;margin-bottom:8px">${v[4]} · ${p.name}</div>
              <div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="color:#8ba4c7">最新价</span><span style="font-weight:500">${v[3]}</span></div>
              <div style="display:flex;justify-content:space-between"><span style="color:#8ba4c7">涨跌幅</span><span style="color:${c};font-weight:bold">${chg >= 0 ? '+' : ''}${chg}%</span></div>
            </div>`
          }
        },
        geo: {
          map: 'world',
          roam: true,
          zoom: 1.3,
          scaleLimit: { min: 0.8, max: 8 },
          itemStyle: { areaColor: '#0d1b2a', borderColor: '#1b3a5b' },
          emphasis: { itemStyle: { areaColor: '#1b3a5b' }, label: { show: false } },
          silent: false
        },
        series: [{
          type: 'effectScatter',
          coordinateSystem: 'geo',
          data: scatterData,
          symbolSize: v => sizeOf(v),
          showEffectOn: 'render',
          rippleEffect: { brushType: 'stroke', scale: 3, period: 4 },
          itemStyle: {
            color: p => colorOf(p.value),
            shadowBlur: 8,
            shadowColor: 'rgba(0,0,0,0.5)'
          },
          label: {
            show: true,
            position: 'right',
            color: '#e0e6f0',
            fontSize: 11,
            formatter: p => p.data.name,
            textShadowColor: '#000',
            textShadowBlur: 4
          },
          zlevel: 2
        }]
      }, true)
    }
  }
}
</script>

<style scoped>
.global-market-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0e17 0%, #1a1f35 50%, #0d1321 100%);
  color: #e0e6f0;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.gm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 20px;
  background: rgba(26, 35, 53, 0.8);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  backdrop-filter: blur(10px);
  margin-bottom: 20px;
}

.gm-header h1 {
  font-size: 1.4rem;
  color: #fff;
  margin: 0;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

.gm-header-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.gm-source-tag {
  padding: 5px 12px;
  background: rgba(24, 144, 255, 0.15);
  border: 1px solid rgba(24, 144, 255, 0.4);
  border-radius: 6px;
  font-size: 12px;
  color: #69c0ff;
}

.gm-update {
  font-size: 12px;
  color: #8ba4c7;
}

.gm-back-button {
  padding: 10px 20px;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  border: 1px solid #4a5a7b;
  border-radius: 8px;
  color: #e0e6f0;
  cursor: pointer;
  transition: all 0.3s ease;
  font-size: 14px;
}

.gm-back-button:hover {
  background: linear-gradient(135deg, #4a5a7b, #3a4a6b);
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.gm-refresh-btn {
  padding: 8px 16px;
  background: linear-gradient(135deg, #1890ff, #096dd9);
  border: 1px solid #40a9ff;
  border-radius: 6px;
  color: #fff;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.3s ease;
}

.gm-refresh-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, #40a9ff, #1890ff);
  transform: translateY(-2px);
}

.gm-refresh-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.gm-body {
  display: flex;
  gap: 20px;
  flex: 1;
  min-height: 0;
}

.gm-chart-wrapper {
  flex: 1;
  position: relative;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  padding: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.gm-chart {
  width: 100%;
  height: 100%;
  min-height: 600px;
}

.gm-legend {
  position: absolute;
  bottom: 20px;
  left: 24px;
  display: flex;
  align-items: center;
  gap: 18px;
  font-size: 12px;
  color: #8ba4c7;
  pointer-events: none;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 5px;
}

.legend-item .dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}

.legend-item .dot.up { background: #ff4d4f; box-shadow: 0 0 8px #ff4d4f; }
.legend-item .dot.down { background: #52c41a; box-shadow: 0 0 8px #52c41a; }

.gm-rank {
  width: 280px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.gm-rank-section {
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  padding: 16px;
}

.gm-rank-title {
  font-size: 15px;
  margin: 0 0 12px 0;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(58, 74, 107, 0.5);
}

.gm-rank-title.up { color: #ff7875; }
.gm-rank-title.down { color: #73d13d; }

.gm-rank-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 320px;
  overflow-y: auto;
}

.gm-rank-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 8px;
  border-radius: 6px;
  transition: background 0.2s ease;
  font-size: 13px;
}

.gm-rank-item:hover {
  background: rgba(58, 74, 107, 0.4);
}

.gm-rank-region {
  color: #8ba4c7;
  font-size: 12px;
  min-width: 48px;
}

.gm-rank-name {
  flex: 1;
  color: #e0e6f0;
  margin: 0 8px;
}

.gm-rank-change {
  font-weight: 600;
  font-size: 13px;
}

.gm-rank-change.up { color: #ff4d4f; }
.gm-rank-change.down { color: #52c41a; }

.gm-empty {
  text-align: center;
  color: #8ba4c7;
  padding: 20px;
  font-size: 13px;
}

.gm-footer {
  text-align: center;
  padding: 14px;
  color: #8ba4c7;
  font-size: 0.85rem;
  margin-top: 16px;
}

.gm-rank-list::-webkit-scrollbar {
  width: 5px;
}
.gm-rank-list::-webkit-scrollbar-thumb {
  background: rgba(58, 74, 107, 0.6);
  border-radius: 3px;
}

@media (max-width: 1024px) {
  .gm-body {
    flex-direction: column;
  }
  .gm-rank {
    width: 100%;
    flex-direction: row;
  }
  .gm-rank-section {
    flex: 1;
  }
}

@media (max-width: 768px) {
  .global-market-page {
    padding: 10px;
  }
  .gm-header {
    flex-direction: column;
    gap: 10px;
    text-align: center;
  }
  .gm-header h1 {
    font-size: 1.1rem;
  }
  .gm-rank {
    flex-direction: column;
  }
  .gm-chart {
    min-height: 420px;
  }
}
</style>
