<template>
  <div class="aic-page">
    <header class="aic-header">
      <button class="aic-back" @click="goBack">← 返回</button>
      <h1>🌐 AI产业链 · 外部环境温度计</h1>
      <div class="aic-header-right">
        <span class="aic-source" v-if="data && data.source">数据源：{{ sourceLabel }}</span>
        <span class="aic-update" v-if="data && data.update_time">更新：{{ data.update_time }}</span>
        <button class="aic-refresh" @click="fetchData(true)" :disabled="loading">
          {{ loading ? '刷新中...' : '🔄 刷新' }}
        </button>
      </div>
    </header>

    <!-- 综合环境温度计 -->
    <section class="aic-thermo" :class="overallClass" v-if="summary">
      <div class="aic-thermo-main">
        <span class="aic-thermo-dot"></span>
        <span class="aic-thermo-label">综合环境</span>
        <span class="aic-thermo-overall">{{ summary.overall }}</span>
      </div>
      <div class="aic-thermo-sub">
        <span class="aic-signal" :class="signalClass(summary.demand_signal)">需求链 {{ summary.demand_signal }}</span>
        <span class="aic-signal" :class="signalClass(summary.macro_signal)">宏观链 {{ summary.macro_signal }}</span>
        <span class="aic-counts">利好 {{ summary.bull_count }} · 利空 {{ summary.bear_count }}</span>
      </div>
    </section>

    <!-- 需求链 -->
    <section class="aic-chain">
      <h2 class="aic-chain-title">📈 AI / 半导体需求链 <small>（涨 = 利好，先进封装/AI 硬件需求强）</small></h2>
      <div class="aic-grid">
        <div class="aic-card" :class="impactClass(it)" v-for="it in demandList" :key="it.key">
          <div class="aic-card-top">
            <span class="aic-name">{{ it.name }}</span>
            <span class="aic-tag">{{ regionTag(it) }}</span>
          </div>
          <div class="aic-price">{{ formatPrice(it) }}</div>
          <div class="aic-change">{{ formatChange(it.change) }}</div>
          <div class="aic-impact">{{ it.impact }}</div>
          <div class="aic-meta">{{ it.source }}<span v-if="it.stale"> · 旧值</span></div>
        </div>
      </div>
    </section>

    <!-- 宏观链 -->
    <section class="aic-chain">
      <h2 class="aic-chain-title">💱 宏观 / 流动性链 <small>（涨 = 利空，折现率/美元走强压制 AI 估值）</small></h2>
      <div class="aic-grid aic-grid-macro">
        <div class="aic-card" :class="impactClass(it)" v-for="it in macroList" :key="it.key">
          <div class="aic-card-top">
            <span class="aic-name">{{ it.name }}</span>
            <span class="aic-tag">{{ regionTag(it) }}</span>
          </div>
          <div class="aic-price">{{ formatPrice(it) }}</div>
          <div class="aic-change">{{ formatChange(it.change) }}</div>
          <div class="aic-impact">{{ it.impact }}</div>
          <div class="aic-meta">{{ it.source }}<span v-if="it.stale"> · 旧值</span></div>
        </div>
      </div>
    </section>

    <div class="aic-empty" v-if="!loading && !indicators.length">暂无数据</div>
    <div class="aic-loading" v-if="loading && !data">
      <div class="aic-spinner"></div>加载中...
    </div>

    <footer class="aic-footer">
      数据来源：东方财富(韩股) · 新浪财经(美股/美元) · 美国财政部(美债)　颜色按"对 AI 链利好/利空"判定（红=利好/绿=利空）　仅供投资参考
    </footer>
    <SecurityAlert />
  </div>
</template>

<script>
import { getAiChain } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

const SOURCE_MAP = {
  sina: '新浪',
  eastmoney: '东方财富',
  treasury: '财政部',
  cache: '缓存'
}

export default {
  name: 'AiChain',
  components: { SecurityAlert },
  data() {
    return { loading: false, data: null, timer: null }
  },
  computed: {
    indicators() { return this.data?.indicators || [] },
    demandList() { return this.indicators.filter(i => i.chain === 'demand') },
    macroList() { return this.indicators.filter(i => i.chain === 'macro') },
    summary() { return this.data?.summary || null },
    overallClass() { return this.signalClass(this.summary?.overall) },
    sourceLabel() {
      const s = this.data?.source
      if (!s) return ''
      return s.split('+').map(x => SOURCE_MAP[x] || x).join('+')
    }
  },
  mounted() {
    this.fetchData(true)
    this.timer = setInterval(() => this.fetchData(false), 30000)
  },
  beforeUnmount() {
    clearInterval(this.timer)
  },
  methods: {
    goBack() { this.$router.push('/') },
    async fetchData(showLoading) {
      this.loading = showLoading
      try {
        const res = await getAiChain()
        if (res.success) this.data = res.data
      } catch (e) {
        console.error('AI链指标获取失败:', e)
      } finally {
        this.loading = false
      }
    },
    impactClass(it) {
      if (it.impact === '利好') return 'bull'
      if (it.impact === '利空') return 'bear'
      return 'neutral'
    },
    signalClass(s) {
      if (s === '偏多') return 'bull'
      if (s === '偏空') return 'bear'
      return 'neutral'
    },
    formatChange(c) {
      if (c === null || c === undefined || Number.isNaN(Number(c))) return '--'
      const pct = Number(c) * 100
      return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%'
    },
    formatPrice(it) {
      const p = it.price
      if (p === null || p === undefined) return '--'
      if (it.key === 'us10y') return Number(p).toFixed(2) + '%'
      if (it.region === '美股' || it.key === 'dxy') {
        return Number(p).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      }
      return Number(p).toLocaleString('en-US', { maximumFractionDigits: 2 })
    },
    regionTag(it) {
      if (it.region === '美股') return '隔夜'
      if (it.key === 'us10y') return '日线 ' + (it.date || '')
      return it.region
    }
  }
}
</script>

<style scoped>
.aic-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0e17 0%, #1a1f35 50%, #0d1321 100%);
  color: #e0e6f0;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.aic-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 15px 20px;
  background: rgba(26, 35, 53, 0.8);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  backdrop-filter: blur(10px);
  margin-bottom: 18px;
  gap: 12px;
}
.aic-header h1 {
  font-size: 1.3rem;
  color: #fff;
  margin: 0;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}
.aic-header-right { display: flex; align-items: center; gap: 14px; }
.aic-source {
  padding: 5px 12px;
  background: rgba(24, 144, 255, 0.15);
  border: 1px solid rgba(24, 144, 255, 0.4);
  border-radius: 6px;
  font-size: 12px;
  color: #69c0ff;
}
.aic-update { font-size: 12px; color: #8ba4c7; }
.aic-back, .aic-refresh {
  border: 1px solid #4a5a7b;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  color: #e0e6f0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s ease;
}
.aic-back { padding: 10px 20px; }
.aic-refresh { padding: 8px 16px; }
.aic-back:hover, .aic-refresh:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}
.aic-refresh:disabled { opacity: 0.6; cursor: not-allowed; }

/* 综合环境温度计 */
.aic-thermo {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 18px 24px;
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  background: rgba(26, 35, 53, 0.6);
  margin-bottom: 18px;
  border-left: 5px solid #8ba4c7;
}
.aic-thermo.bull { border-left-color: #ff4d4f; background: rgba(239, 83, 80, 0.08); }
.aic-thermo.bear { border-left-color: #52c41a; background: rgba(82, 196, 26, 0.08); }
.aic-thermo-main { display: flex; align-items: center; gap: 12px; }
.aic-thermo-dot { width: 14px; height: 14px; border-radius: 50%; background: #8ba4c7; }
.aic-thermo.bull .aic-thermo-dot { background: #ff4d4f; box-shadow: 0 0 12px #ff4d4f; }
.aic-thermo.bear .aic-thermo-dot { background: #52c41a; box-shadow: 0 0 12px #52c41a; }
.aic-thermo-label { font-size: 14px; color: #8ba4c7; }
.aic-thermo-overall { font-size: 1.6rem; font-weight: 800; color: #fff; }
.aic-thermo.bull .aic-thermo-overall { color: #ff7875; }
.aic-thermo.bear .aic-thermo-overall { color: #73d13d; }
.aic-thermo-sub { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.aic-signal {
  padding: 5px 12px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 700;
  background: rgba(58, 74, 107, 0.4);
  color: #cbd5e1;
}
.aic-signal.bull { color: #ff7875; background: rgba(239, 83, 80, 0.15); }
.aic-signal.bear { color: #73d13d; background: rgba(82, 196, 26, 0.15); }
.aic-counts { font-size: 12px; color: #8ba4c7; }

/* 链区 */
.aic-chain { margin-bottom: 18px; }
.aic-chain-title {
  font-size: 1.05rem;
  color: #e0e6f0;
  margin: 0 0 12px 2px;
}
.aic-chain-title small { font-size: 12px; color: #8ba4c7; font-weight: 400; }

.aic-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 14px;
}
.aic-grid-macro { grid-template-columns: repeat(2, 1fr); max-width: 50%; }

/* 卡片 */
.aic-card {
  position: relative;
  background: rgba(26, 35, 53, 0.6);
  border: 1px solid rgba(58, 74, 107, 0.5);
  border-radius: 12px;
  padding: 16px 14px;
  border-top: 3px solid #8ba4c7;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.aic-card:hover { transform: translateY(-3px); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25); }
.aic-card.bull { border-top-color: #ff4d4f; }
.aic-card.bear { border-top-color: #52c41a; }
.aic-card.neutral { border-top-color: #8ba4c7; }
.aic-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.aic-name { font-size: 14px; font-weight: 700; color: #e0e6f0; }
.aic-tag {
  font-size: 11px;
  color: #8ba4c7;
  background: rgba(58, 74, 107, 0.4);
  padding: 2px 7px;
  border-radius: 4px;
}
.aic-price {
  font-size: 1.5rem;
  font-weight: 800;
  color: #fff;
  line-height: 1.1;
  margin-bottom: 4px;
}
.aic-change { font-size: 1.05rem; font-weight: 700; margin-bottom: 8px; }
.aic-card.bull .aic-change { color: #ff4d4f; }
.aic-card.bear .aic-change { color: #52c41a; }
.aic-card.neutral .aic-change { color: #cbd5e1; }
.aic-impact {
  display: inline-block;
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 4px;
  margin-bottom: 8px;
}
.aic-card.bull .aic-impact { color: #ff4d4f; background: rgba(239, 83, 80, 0.15); }
.aic-card.bear .aic-impact { color: #73d13d; background: rgba(82, 196, 26, 0.15); }
.aic-card.neutral .aic-impact { color: #cbd5e1; background: rgba(139, 164, 199, 0.15); }
.aic-meta { font-size: 11px; color: #6b7d99; }

.aic-empty, .aic-loading {
  text-align: center;
  color: #8ba4c7;
  padding: 40px;
  font-size: 15px;
}
.aic-spinner {
  display: inline-block;
  width: 22px;
  height: 22px;
  border: 3px solid rgba(58, 74, 107, 0.4);
  border-top-color: #69c0ff;
  border-radius: 50%;
  animation: aic-spin 0.8s linear infinite;
  vertical-align: middle;
  margin-right: 8px;
}
@keyframes aic-spin { to { transform: rotate(360deg); } }

.aic-footer {
  text-align: center;
  padding: 14px;
  color: #8ba4c7;
  font-size: 0.8rem;
  margin-top: 16px;
  line-height: 1.7;
}

@media (max-width: 1024px) {
  .aic-grid { grid-template-columns: repeat(3, 1fr); }
  .aic-grid-macro { max-width: 100%; }
}
@media (max-width: 640px) {
  .aic-grid { grid-template-columns: repeat(2, 1fr); }
  .aic-grid-macro { grid-template-columns: repeat(2, 1fr); }
  .aic-header { flex-direction: column; text-align: center; }
  .aic-header h1 { font-size: 1.05rem; }
}
</style>
