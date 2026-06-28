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
          <span class="legend-tip">颜色越深=涨跌幅越大 · 滚轮缩放 · 拖动平移</span>
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
            <div v-for="item in topLosers" :key="item.code" class="gm-rank-item clickable" @click="focusIndex(item)">
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

// 英文国家名 → 中文映射（覆盖世界地图主要国家）
const COUNTRY_ZH_MAP = {
  'China': '中国', 'Russia': '俄罗斯', 'Mongolia': '蒙古',
  'India': '印度', 'Japan': '日本', 'South Korea': '韩国', 'North Korea': '朝鲜',
  'Thailand': '泰国', 'Vietnam': '越南', 'Myanmar': '缅甸', 'Malaysia': '马来西亚',
  'Indonesia': '印度尼西亚', 'Philippines': '菲律宾', 'Pakistan': '巴基斯坦',
  'Kazakhstan': '哈萨克斯坦', 'Iran': '伊朗', 'Saudi Arabia': '沙特阿拉伯',
  'Iraq': '伊拉克', 'Turkey': '土耳其', 'United Arab Emirates': '阿联酋',
  'Afghanistan': '阿富汗', 'Israel': '以色列',
  'United States': '美国', 'Canada': '加拿大', 'Mexico': '墨西哥',
  'Brazil': '巴西', 'Argentina': '阿根廷', 'Chile': '智利', 'Colombia': '哥伦比亚',
  'Peru': '秘鲁', 'Venezuela': '委内瑞拉', 'Bolivia': '玻利维亚',
  'United Kingdom': '英国', 'France': '法国', 'Germany': '德国', 'Italy': '意大利',
  'Spain': '西班牙', 'Portugal': '葡萄牙', 'Netherlands': '荷兰', 'Belgium': '比利时',
  'Switzerland': '瑞士', 'Austria': '奥地利', 'Sweden': '瑞典', 'Norway': '挪威',
  'Finland': '芬兰', 'Denmark': '丹麦', 'Poland': '波兰', 'Greece': '希腊',
  'Ireland': '爱尔兰', 'Czech Republic': '捷克', 'Ukraine': '乌克兰', 'Romania': '罗马尼亚',
  'Hungary': '匈牙利', 'Croatia': '克罗地亚', 'Bulgaria': '保加利亚', 'Serbia': '塞尔维亚',
  'Egypt': '埃及', 'South Africa': '南非', 'Nigeria': '尼日利亚', 'Morocco': '摩洛哥',
  'Algeria': '阿尔及利亚', 'Kenya': '肯尼亚', 'Ethiopia': '埃塞俄比亚', 'Ghana': '加纳',
  'Australia': '澳大利亚', 'New Zealand': '新西兰', 'Papua New Guinea': '巴布亚新几内亚',
  'Somalia': '索马里', 'Sudan': '苏丹', 'Libya': '利比亚', 'Tanzania': '坦桑尼亚',
  'Angola': '安哥拉', 'Mali': '马里', 'Mozambique': '莫桑比克', 'Namibia': '纳米比亚',
  'Madagascar': '马达加斯加', 'Zimbabwe': '津巴布韦', 'Senegal': '塞内加尔', 'Cameroon': '喀麦隆',
  'Chad': '乍得', 'Tunisia': '突尼斯', 'Zambia': '赞比亚', 'Uganda': '乌干达',
  'Iceland': '冰岛', 'Belarus': '白俄罗斯', 'Latvia': '拉脱维亚', 'Lithuania': '立陶宛',
  'Estonia': '爱沙尼亚', 'Slovakia': '斯洛伐克', 'Moldova': '摩尔多瓦', 'Albania': '阿尔巴尼亚',
  'Macedonia': '马其顿', 'Slovenia': '斯洛文尼亚', 'Montenegro': '黑山',
  'Ecuador': '厄瓜多尔', 'Paraguay': '巴拉圭', 'Uruguay': '乌拉圭',
  'Guyana': '圭亚那', 'Suriname': '苏里南', 'Cuba': '古巴', 'Guatemala': '危地马拉',
  'Honduras': '洪都拉斯', 'Nicaragua': '尼加拉瓜', 'Panama': '巴拿马', 'Jamaica': '牙买加',
  'Korea': '韩国', 'Laos': '老挝', 'Cambodia': '柬埔寨', 'Bangladesh': '孟加拉国',
  'Nepal': '尼泊尔', 'Sri Lanka': '斯里兰卡', 'Yemen': '也门', 'Oman': '阿曼',
  'Jordan': '约旦', 'Lebanon': '黎巴嫩', 'Syria': '叙利亚', 'Georgia': '格鲁吉亚',
  'Armenia': '亚美尼亚', 'Azerbaijan': '阿塞拜疆', 'Turkmenistan': '土库曼斯坦',
  'Uzbekistan': '乌兹别克斯坦', 'Kyrgyzstan': '吉尔吉斯斯坦', 'Tajikistan': '塔吉克斯坦',
  'Dem. Rep. Congo': '刚果(金)', 'Dem. Rep. Korea': '朝鲜', 'Republic of Korea': '韩国',
  'Czechia': '捷克', 'Bosnia and Herz.': '波黑', 'Dominican Rep.': '多米尼加',
  'S. Sudan': '南苏丹', 'Central African Rep.': '中非', 'Eq. Guinea': '赤道几内亚',
  'W. Sahara': '西撒哈拉', 'Falkland Is.': '福克兰群岛', 'Greenland': '格陵兰',
  'Fr. S. Antarctic Lands': '法兰西南方领地', 'Antarctica': '南极洲',
  'Taiwan': '台湾', 'Hong Kong': '香港',
  'Solomon Is.': '所罗门群岛', 'New Caledonia': '新喀里多尼亚', 'Fiji': '斐济'
}

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

    // 点击榜单项：缩放到对应国家位置并高亮
    focusIndex(item) {
      if (!this.chart || !item) return
      const lng = item.lng
      const lat = item.lat
      // 缩放并居中到目标坐标
      this.chart.setOption({
        geo: {
          center: [lng, lat],
          zoom: 4
        }
      })
      // 高亮对应的散点并显示 tooltip
      const seriesData = this.chart.getOption().series[0].data
      const idx = seriesData.findIndex(d => d.code === item.code)
      if (idx >= 0) {
        this.chart.dispatchAction({ type: 'highlight', seriesIndex: 0, dataIndex: idx })
        this.chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: idx })
      }
    },

    async loadMap() {
      try {
        const res = await fetch('/world.json')
        const geo = await res.json()
        // 将国家英文名翻译为中文
        if (geo.features) {
          geo.features.forEach(f => {
            const enName = f.properties && f.properties.name
            const zhName = COUNTRY_ZH_MAP[enName]
            if (zhName) {
              f.properties.name = zhName
            }
          })
        }
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

      // 圆圈颜色：涨为红色系，跌为绿色系；涨跌幅越大颜色越深（透明度越高）
      const colorOf = v => {
        const pct = Math.abs(v[2])
        const opacity = Math.min(Math.max(pct / 4 * 0.6, 0.35), 0.95)
        return v[2] >= 0 ? `rgba(255, 77, 79, ${opacity})` : `rgba(82, 196, 26, ${opacity})`
      }
      // 边框颜色（更亮）
      const borderColorOf = v => v[2] >= 0 ? '#ff7875' : '#95de64'
      // 圆圈大小：按涨跌幅绝对值，最小18，最大42
      const sizeOf = v => Math.min(Math.max(Math.abs(v[2]) * 4 + 18, 18), 42)
      // 圆圈内文字颜色：随涨跌
      const textColorOf = v => v[2] >= 0 ? '#fff1f0' : '#f6ffed'

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
          // 深色科技感海洋 + 发光边界
          itemStyle: {
            areaColor: '#0a1628',
            borderColor: '#1e90ff',
            borderWidth: 0.6,
            shadowColor: 'rgba(30, 144, 255, 0.4)',
            shadowBlur: 8
          },
          emphasis: {
            itemStyle: { areaColor: '#1a3050', borderColor: '#00e0ff' },
            label: { show: true, color: '#8ba4c7', fontSize: 10 }
          },
          silent: false
        },
        series: [{
          type: 'scatter',
          coordinateSystem: 'geo',
          data: scatterData,
          symbolSize: v => sizeOf(v),
          itemStyle: {
            color: p => colorOf(p.value),
            borderColor: p => borderColorOf(p.value),
            borderWidth: 2,
            shadowBlur: 18,
            shadowColor: p => (p.value[2] >= 0 ? 'rgba(255,45,85,0.8)' : 'rgba(19,209,124,0.8)')
          },
          label: {
            show: true,
            // 圆圈内显示涨跌幅
            formatter: p => {
              const chg = p.value[2]
              return (chg >= 0 ? '+' : '') + chg + '%'
            },
            color: p => textColorOf(p.value),
            fontSize: 10,
            fontWeight: 'bold',
            position: 'inside'
          },
          // 高亮：圆圈放大、边框加粗、光晕增强
          emphasis: {
            scale: 1.6,
            itemStyle: {
              borderColor: '#ffd666',
              borderWidth: 3,
              shadowBlur: 24,
              shadowColor: '#ffd666'
            },
            label: { fontSize: 12 }
          },
          zlevel: 2
        }, {
          // 第二个系列：仅显示国名标签，放在圆圈下方
          type: 'scatter',
          coordinateSystem: 'geo',
          data: scatterData,
          symbolSize: 0,
          label: {
            show: true,
            formatter: p => p.data.name,
            color: '#e0e6f0',
            fontSize: 11,
            fontWeight: 500,
            position: 'bottom',
            distance: 8,
            textShadowColor: '#000',
            textShadowBlur: 4,
            backgroundColor: 'rgba(13, 27, 42, 0.7)',
            padding: [2, 6],
            borderRadius: 3
          },
          tooltip: { show: false },
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

.legend-item .dot.up { background: #ff2d55; box-shadow: 0 0 10px #ff2d55; }
.legend-item .dot.down { background: #13d17c; box-shadow: 0 0 10px #13d17c; }

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
