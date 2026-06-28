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
      <div class="mm-loading" v-if="loading && !hasData">
        <div class="spinner"></div>
        <p>正在加载全市场数据，请稍候...</p>
      </div>
    </div>

    <div class="mm-footer">行业分类：东方财富(缓存) · 实时涨跌：新浪财经 · 面积=总市值，颜色=涨跌幅（红涨绿跌）· 点击行业放大下钻，底部面包屑逐级返回 · 仅供投资参考</div>
    <SecurityAlert />
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getMarketMap, refreshMarketMapCache } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

// dapanyuntu 配色色阶：涨跌幅(%) → [R,G,B]
// 跌：大幅=亮绿，小幅=深绿；涨：小幅=深红，大幅=亮红；0%=灰
const COLOR_STOPS = [
  [-10, [0, 214, 65]],   // ≤-4% 亮绿 #00d641
  [-3, [26, 164, 72]],   // -3% #1aa448
  [-2, [14, 111, 47]],   // -2% #0e6f2f
  [-1, [8, 84, 33]],     // -1% #085421
  [0, [66, 68, 83]],     // 0% #424453
  [1, [109, 20, 20]],    // +1% #6d1414
  [2, [150, 16, 16]],    // +2% #961010
  [3, [190, 8, 8]],      // +3% #be0808
  [10, [228, 20, 20]]    // ≥+4% 亮红 #e41414
]

function interpColor(change) {
  const c = Math.max(-10, Math.min(10, change))
  for (let i = 0; i < COLOR_STOPS.length - 1; i++) {
    const [p1, col1] = COLOR_STOPS[i]
    const [p2, col2] = COLOR_STOPS[i + 1]
    if (c >= p1 && c <= p2) {
      const t = p2 === p1 ? 0 : (c - p1) / (p2 - p1)
      const r = Math.round(col1[0] + (col2[0] - col1[0]) * t)
      const g = Math.round(col1[1] + (col2[1] - col1[1]) * t)
      const b = Math.round(col1[2] + (col2[2] - col1[2]) * t)
      return `rgb(${r},${g},${b})`
    }
  }
  return 'rgb(66,68,83)'
}

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
    // 统一配色（参考 dapanyuntu 精确色阶）
    colorOf(change) {
      return interpColor(change)
    },
    // 文字颜色：统一白色（股票字体要求为白色，不能是黑色）
    textColorOf() {
      return '#fff'
    },
    initChart() {
      const el = this.$refs.chartEl
      if (!el) return
      // 仅首次创建实例，后续刷新复用同一实例（避免销毁重建导致画面闪烁/缩放丢失）
      if (!this.chart) {
        this.chart = echarts.init(el)
      }
    },
    render() {
      this.initChart()
      if (!this.chart) return

      // 构建三级嵌套数据：申万一级 → 申万二级 → 个股
      // 每个节点附 itemStyle.color 和 label.color 实现统一红绿着色
      const buildNode = (n, isLeaf) => {
        const node = {
          name: n.name,
          change: n.change,
          itemStyle: { color: this.colorOf(n.change) },
          label: { color: this.textColorOf(n.change) }
        }
        if (isLeaf) {
          node.value = n.value
          node.code = n.code
        } else {
          node.children = n.children
        }
        return node
      }
      const data = this.tree.map(l1 => {
        const l1Node = buildNode(l1, false)
        l1Node.children = l1.children.map(l2 => {
          const l2Node = buildNode(l2, false)
          l2Node.children = l2.children.map(s => buildNode(s, true))
          return l2Node
        })
        return l1Node
      })

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
          name: 'A股',
          // 缩放交互：放弃滚轮缩放(roam)。ECharts treemap 的滚轮缩放在缩小到<1x时会触发
          // 已知 bug 导致整个云图空白，且 treemap 不能用 scaleLimit 可靠约束，屡修屡坏。
          // 改用官方稳定的「点击下钻」：点击一级行业/二级行业即放大该节点，
          // 底部面包屑(breadcrumb)逐级返回。这是 ECharts treemap 推荐的稳定交互。
          roam: false,
          nodeClick: 'zoomToNode',
          data,
          left: 4,
          right: 4,
          top: 4,
          bottom: 4,
          breadcrumb: {
            show: true,
            height: 22,
            bottom: 2,
            left: 'center',
            itemStyle: { color: 'rgba(26,35,53,0.92)', borderColor: '#3a4a6b', borderWidth: 1 },
            emphasis: { itemStyle: { color: '#2a3548' } }
          },
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
          // 三级 levels：一级(粗分组) → 二级(细分组) → 个股
          levels: [
            {
              itemStyle: { borderColor: '#050a14', borderWidth: 4, gapWidth: 4 },
              upperLabel: { height: 24, fontSize: 15 }
            },
            {
              itemStyle: { borderColor: '#050a14', borderWidth: 2, gapWidth: 2 },
              upperLabel: { height: 18, fontSize: 11 }
            },
            {
              itemStyle: { borderColor: '#050a14', borderWidth: 1, gapWidth: 1 }
            }
          ],
          // 个股标签：面积过小放不下的标签 ECharts 自动隐藏，缩放后变大自动显示
          label: {
            show: true,
            formatter: p => {
              if (p.data.children !== undefined) return ''
              const c = p.data.change || 0
              const sign = c >= 0 ? '+' : ''
              return `${p.name}\n${sign}${c}%`
            },
            fontSize: 11,
            fontWeight: 'bold',
            textBorderColor: 'rgba(0,0,0,0.7)',
            textBorderWidth: 1.5,
            textShadowColor: 'rgba(0,0,0,0.4)',
            textShadowBlur: 2
          }
        }]
      }, true)
    }
  }
}
</script>

<style scoped>
.market-map-page {
  height: 100vh;
  background:
    radial-gradient(ellipse at 20% 20%, rgba(228, 48, 56, 0.06) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(28, 168, 86, 0.05) 0%, transparent 50%),
    linear-gradient(135deg, #050a14 0%, #0a1628 40%, #08101e 100%);
  color: #e0e6f0;
  padding: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.mm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 14px;
  background: rgba(26, 35, 53, 0.8);
  border-radius: 8px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  backdrop-filter: blur(10px);
  margin-bottom: 8px;
  flex-shrink: 0;
}

.mm-header h1 {
  font-size: 1.05rem;
  color: #fff;
  margin: 0;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
  white-space: nowrap;
}

.mm-header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mm-stats {
  font-size: 12px;
  color: #8ba4c7;
  white-space: nowrap;
}

.mm-update {
  font-size: 11px;
  color: #8ba4c7;
  white-space: nowrap;
}

.mm-back-button {
  padding: 6px 14px;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  border: 1px solid #4a5a7b;
  border-radius: 6px;
  color: #e0e6f0;
  cursor: pointer;
  transition: all 0.3s ease;
  font-size: 13px;
  white-space: nowrap;
}

.mm-back-button:hover {
  background: linear-gradient(135deg, #4a5a7b, #3a4a6b);
  transform: translateY(-1px);
}

.mm-refresh-btn {
  padding: 6px 12px;
  background: linear-gradient(135deg, #1890ff, #096dd9);
  border: 1px solid #40a9ff;
  border-radius: 6px;
  color: #fff;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.3s ease;
  white-space: nowrap;
}

.mm-cache-btn {
  padding: 6px 10px;
  background: rgba(58, 74, 107, 0.6);
  border: 1px solid #4a5a7b;
  border-radius: 6px;
  color: #8ba4c7;
  cursor: pointer;
  font-size: 11px;
  transition: all 0.3s ease;
  white-space: nowrap;
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
  transform: translateY(-1px);
}

.mm-refresh-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.mm-chart-wrapper {
  flex: 1;
  position: relative;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 8px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  padding: 4px;
  min-height: 300px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}

.mm-chart {
  width: 100%;
  height: 100%;
  min-height: 280px;
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
  border-radius: 8px;
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
  padding: 5px 8px;
  color: #8ba4c7;
  font-size: 0.72rem;
  margin-top: 6px;
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .market-map-page { padding: 6px; }
  .mm-header {
    flex-direction: column;
    gap: 6px;
    text-align: center;
  }
  .mm-header h1 { font-size: 1rem; }
  .mm-chart-wrapper { min-height: 240px; }
  .mm-chart { min-height: 220px; }
}
</style>
