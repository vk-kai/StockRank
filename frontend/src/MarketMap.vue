<template>
  <div class="market-map-page">
    <header class="mm-header">
      <button @click="goBack" class="mm-back-button">← 返回</button>
      <h1>🗺️ A股大盘云图</h1>
      <div class="mm-header-right">
        <span class="mm-stats" v-if="totalSectors">
          {{ totalSectors }} 一级行业 · {{ totalStocks }} 只个股
        </span>
        <span class="mm-update" v-if="cacheTime">行业库：{{ cacheTime }}</span>
        <button @click="refreshCache" class="mm-cache-btn" :disabled="cacheLoading">
          {{ cacheLoading ? '更新中...' : '🔄 行业库' }}
        </button>
        <button @click="fetchData(true)" class="mm-refresh-btn" :disabled="loading">
          {{ loading ? '加载中...' : '⚡ 刷新行情' }}
        </button>
      </div>
    </header>

    <div class="mm-chart-wrapper">
      <div ref="chartEl" class="mm-chart"></div>
      <div class="mm-legend">
        <span class="legend-block up-deep"></span>
        <span class="legend-block up-light"></span>
        <span class="legend-zero">0</span>
        <span class="legend-block down-light"></span>
        <span class="legend-block down-deep"></span>
        <span class="legend-tip">面积=流通市值 · 颜色=涨跌幅 · 悬停查看详情</span>
      </div>
      <div class="mm-loading" v-if="loading && !hasData">
        <div class="spinner"></div>
        <p>正在加载全市场数据，请稍候...</p>
      </div>
    </div>

    <div class="mm-footer">行业分类：东方财富(缓存) · 实时涨跌：新浪财经 · 面积=总市值，颜色=涨跌幅 · 仅供投资参考</div>
    <SecurityAlert />
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getMarketMap, refreshMarketMapCache } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

export default {
  name: 'MarketMap',
  components: { SecurityAlert },
  data() {
    return {
      loading: false,
      cacheLoading: false,
      refreshing: false,
      tree: [],
      totalSectors: 0,
      totalStocks: 0,
      updateTime: '',
      cacheTime: '',
      chart: null,
      timer: null
    }
  },
  computed: {
    hasData() {
      return this.tree.length > 0
    }
  },
  async mounted() {
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
    async fetchData(showLoading) {
      // 防重入：上一次请求未返回时跳过（避免5秒高频下请求堆积）
      if (this.refreshing) return
      this.refreshing = true
      this.loading = showLoading
      try {
        const res = await getMarketMap()
        if (res.success) {
          this.tree = res.data.tree
          this.totalSectors = res.data.total_sectors
          this.totalStocks = res.data.total_stocks
          this.updateTime = res.data.update_time
          this.cacheTime = res.data.cache_time || ''
          this.$nextTick(() => this.render())
        }
      } catch (e) {
        console.error('获取大盘云图失败', e)
      } finally {
        this.loading = false
        this.refreshing = false
      }
    },
    async refreshCache() {
      this.cacheLoading = true
      try {
        const res = await refreshMarketMapCache()
        if (res.success) {
          await this.fetchData(true)
        }
      } catch (e) {
        console.error('刷新行业库失败', e)
      } finally {
        this.cacheLoading = false
      }
    },
    handleResize() {
      if (this.chart) this.chart.resize()
    },
    // 统一配色：涨=红色系，跌=绿色系；幅度越大越深
    // baseOpacity 传入则固定透明度（用于行业条带）
    colorOf(change, baseOpacity = 0) {
      const pct = Math.abs(change)
      const opacity = baseOpacity > 0
        ? baseOpacity
        : Math.min(0.5 + pct * 0.08, 0.95)
      return change >= 0
        ? `rgba(228, 48, 56, ${opacity})`
        : `rgba(28, 168, 86, ${opacity})`
    },
    initChart() {
      const el = this.$refs.chartEl
      if (!el) return
      if (this.chart) this.chart.dispose()
      this.chart = echarts.init(el)
    },
    render() {
      this.initChart()
      if (!this.chart) return

      // 构建三级嵌套数据：申万一级 → 申万二级 → 个股
      // 每个叶子(个股)和分组都附 itemStyle.color 实现统一红绿着色
      const data = this.tree.map(l1 => ({
        name: l1.name,
        change: l1.change,
        itemStyle: { color: this.colorOf(l1.change, 0.5) },
        children: l1.children.map(l2 => ({
          name: l2.name,
          change: l2.change,
          itemStyle: { color: this.colorOf(l2.change, 0.6) },
          children: l2.children.map(s => ({
            name: s.name,
            value: s.value,
            change: s.change,
            code: s.code,
            itemStyle: { color: this.colorOf(s.change) }
          }))
        }))
      }))

      // 最大个股市值（用于决定小块是否显示文字）
      let maxValue = 1
      this.tree.forEach(l1 => l1.children.forEach(l2 => {
        if (l2.children[0] && l2.children[0].value > maxValue) maxValue = l2.children[0].value
      }))

      this.chart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
          backgroundColor: 'rgba(20,25,45,0.96)',
          borderColor: '#3a4a6b',
          borderWidth: 1,
          padding: [12, 16],
          textStyle: { color: '#e0e6f0', fontSize: 13 },
          formatter: p => {
            const d = p.data
            const c = d.change || 0
            const cc = c >= 0 ? '#ff4d4f' : '#52c41a'
            // 个股层（叶子，value 是原始数值）
            if (d.children === undefined) {
              return `<div style="min-width:160px">
                <div style="font-weight:bold;font-size:15px;margin-bottom:6px">${d.name} <span style="color:#8ba4c7;font-weight:normal;font-size:12px">${d.code}</span></div>
                <div style="display:flex;justify-content:space-between"><span style="color:#8ba4c7">涨跌幅</span><span style="color:${cc};font-weight:bold;font-size:16px">${c >= 0 ? '+' : ''}${c}%</span></div>
              </div>`
            }
            // 一级或二级分组
            return `<div style="min-width:140px">
              <div style="font-weight:bold;font-size:15px;margin-bottom:6px">${d.name}</div>
              <div style="display:flex;justify-content:space-between"><span style="color:#8ba4c7">区间涨跌</span><span style="color:${cc};font-weight:bold">${c >= 0 ? '+' : ''}${c}%</span></div>
            </div>`
          }
        },
        series: [{
          type: 'treemap',
          roam: false,
          nodeClick: false,
          data,
          left: 8,
          right: 8,
          top: 8,
          bottom: 8,
          // 分组标题（显示在矩形顶部条带）
          upperLabel: {
            show: true,
            height: 22,
            color: '#fff',
            fontSize: 13,
            fontWeight: 'bold',
            textShadowColor: 'rgba(0,0,0,0.6)',
            textShadowBlur: 4,
            formatter: p => {
              const c = p.data.change || 0
              const sign = c >= 0 ? '+' : ''
              return `${p.name}  ${sign}${c}%`
            }
          },
          breadcrumb: { show: false },
          // 三级 levels：一级(粗分组) → 二级(细分组) → 个股
          levels: [
            {
              // 申万一级：最粗边框 + 大间隙
              itemStyle: { borderColor: '#050a14', borderWidth: 4, gapWidth: 4 },
              upperLabel: { height: 24, fontSize: 15 }
            },
            {
              // 申万二级：中等边框
              itemStyle: { borderColor: '#050a14', borderWidth: 2, gapWidth: 2 },
              upperLabel: { height: 18, fontSize: 11 }
            },
            {
              // 个股：细边框
              itemStyle: { borderColor: '#050a14', borderWidth: 1, gapWidth: 1 }
            }
          ],
          label: {
            show: true,
            formatter: p => {
              if (p.data.children !== undefined) return ''  // 分组不显示内部label
              const c = p.data.change || 0
              const sign = c >= 0 ? '+' : ''
              // 小块只显示涨跌幅，不显示名称
              if (p.data.value < maxValue * 0.02) return `{c|${sign}${c}%}`
              if (p.data.value < maxValue * 0.08) return `{c|${sign}${c}%}`
              return `{n|${p.name}}\n{c|${sign}${c}%}`
            },
            rich: {
              n: { color: '#fff', fontSize: 11, fontWeight: 'bold', lineHeight: 18, textShadowColor: 'rgba(0,0,0,0.6)', textShadowBlur: 3 },
              c: { color: '#fff', fontSize: 10, lineHeight: 14, textShadowColor: 'rgba(0,0,0,0.6)', textShadowBlur: 3 }
            }
          }
        }]
      }, true)
    }
  }
}
</script>

<style scoped>
.market-map-page {
  min-height: 100vh;
  background:
    radial-gradient(ellipse at 20% 20%, rgba(228, 48, 56, 0.06) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(28, 168, 86, 0.05) 0%, transparent 50%),
    linear-gradient(135deg, #050a14 0%, #0a1628 40%, #08101e 100%);
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

.mm-stats {
  font-size: 13px;
  color: #8ba4c7;
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

.mm-cache-btn {
  padding: 8px 14px;
  background: rgba(58, 74, 107, 0.6);
  border: 1px solid #4a5a7b;
  border-radius: 6px;
  color: #8ba4c7;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.3s ease;
}

.mm-cache-btn:hover:not(:disabled) {
  background: rgba(58, 74, 107, 0.9);
  color: #e0e6f0;
}

.mm-cache-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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
  min-height: 620px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.mm-chart {
  width: 100%;
  height: 100%;
  min-height: 600px;
}

.mm-legend {
  position: absolute;
  bottom: 18px;
  left: 24px;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: #8ba4c7;
  pointer-events: none;
  z-index: 5;
}

.legend-block {
  width: 26px;
  height: 12px;
  border-radius: 2px;
  display: inline-block;
}

.legend-block.up-deep { background: rgba(228, 48, 56, 0.95); }
.legend-block.up-light { background: rgba(228, 48, 56, 0.5); }
.legend-block.down-light { background: rgba(28, 168, 86, 0.5); }
.legend-block.down-deep { background: rgba(28, 168, 86, 0.95); }

.legend-zero {
  width: 20px;
  text-align: center;
  font-size: 11px;
  color: #8ba4c7;
}

.legend-tip {
  margin-left: 12px;
  color: #5a6b8c;
  font-size: 11px;
}

.mm-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(5, 10, 20, 0.7);
  color: #8ba4c7;
  z-index: 10;
  border-radius: 12px;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(58, 74, 107, 0.3);
  border-top-color: #1890ff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 14px;
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
  .mm-chart-wrapper { min-height: 480px; }
  .mm-chart { min-height: 460px; }
  .legend-tip { display: none; }
}
</style>
