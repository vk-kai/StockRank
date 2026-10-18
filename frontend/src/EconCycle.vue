<template>
  <div class="ecy-page">
    <header class="ecy-header">
      <button class="ecy-back" @click="$router.push('/')">← 返回主页</button>
      <h1>🧭 经济周期 · 人生指示灯</h1>
      <button class="ecy-refresh" @click="loadAll" :disabled="loading">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </header>

    <section class="ecy-error" v-if="error">{{ error }}</section>

    <template v-if="overview">
      <!-- ===== 指示灯区 ===== -->
      <section class="ecy-lights">
        <div class="ecy-scope-card" v-for="sc in scopeCards" :key="sc.key"
             :style="{ borderColor: sc.color }">
          <div class="ecy-scope-name">{{ sc.title }}</div>
          <div class="ecy-scope-phase" :style="{ color: sc.color }">{{ sc.phaseCn }}</div>
          <div class="ecy-gauge">
            <div class="ecy-gauge-bar">
              <div class="ecy-gauge-fill" :style="{ width: sc.score + '%', background: sc.color }"></div>
            </div>
            <span class="ecy-gauge-num">{{ sc.score }}</span>
          </div>
          <div class="ecy-scope-month" v-if="sc.month">数据期间：{{ sc.month }}</div>
        </div>
      </section>

      <section class="ecy-decision">
        <div class="ecy-decision-card" :class="'light-' + overview.job_switch.light">
          <div class="ecy-decision-head">
            <span class="ecy-decision-icon">{{ lightIcon(overview.job_switch.light) }}</span>
            <span class="ecy-decision-title">换工作窗口</span>
            <span class="ecy-decision-state">{{ lightText(overview.job_switch.light) }}</span>
          </div>
          <ul class="ecy-decision-reasons">
            <li v-for="(r, i) in overview.job_switch.reasons" :key="i">{{ r }}</li>
          </ul>
        </div>
        <div class="ecy-decision-card" :class="'light-' + overview.startup.light">
          <div class="ecy-decision-head">
            <span class="ecy-decision-icon">{{ lightIcon(overview.startup.light) }}</span>
            <span class="ecy-decision-title">创业窗口</span>
            <span class="ecy-decision-state">{{ lightText(overview.startup.light) }}</span>
          </div>
          <ul class="ecy-decision-reasons">
            <li v-for="(r, i) in overview.startup.reasons" :key="i">{{ r }}</li>
          </ul>
        </div>
      </section>

      <!-- ===== 周期路径：走到哪了 + 各阶段对策 ===== -->
      <section class="ecy-path-section">
        <div class="ecy-section-head">
          <h2>完整周期路径 · 我们走到哪了</h2>
        </div>
        <div class="ecy-path-tip">经济像四季轮回，一个完整周期按下面顺序走。判断"走到哪"靠数据，不是靠感觉。</div>
        <div class="ecy-path-track">
          <div class="ecy-path-node" v-for="(p, idx) in phasePath" :key="p.phase"
               :class="{ current: currentPhase === p.phase, past: phasePast(p.phase) }"
               :style="{ '--pc': p.color }">
            <div class="ecy-path-idx">{{ idx + 1 }}</div>
            <div class="ecy-path-name">{{ p.name }}</div>
            <div class="ecy-path-current" v-if="currentPhase === p.phase">◀ 当前</div>
            <div class="ecy-path-block"><b>数据表现</b>{{ p.sign }}</div>
            <div class="ecy-path-block act"><b>该做什么</b>{{ p.action }}</div>
          </div>
        </div>
      </section>

      <!-- ===== 复苏传导链 ===== -->
      <section class="ecy-chain-section">
        <div class="ecy-section-head">
          <h2>复苏传导链 · 谁先好谁后好</h2>
        </div>
        <div class="ecy-chain-tip">复苏有固定顺序：订单 → 生产 → 价格 → 活钱 → 就业 → 消费。
          每一环比上一环晚 1~2 个季度，因为企业决策成本从低到高——接单最便宜，扩编招人最贵最不可逆。
          你觉得"工作难找"但新闻说经济回暖，就是因为走到中间环节了。</div>
        <div class="ecy-chain-track">
          <template v-for="(c, i) in chain" :key="c.key">
            <div class="ecy-chain-node" :class="'st-' + chainState(c.key).cls">
              <div class="ecy-chain-rank">{{ i + 1 }}</div>
              <div class="ecy-chain-name">{{ c.name }}</div>
              <div class="ecy-chain-status">{{ chainState(c.key).label }}</div>
              <div class="ecy-chain-val" v-if="chainState(c.key).value !== undefined">
                {{ chainState(c.key).value }}
              </div>
              <div class="ecy-chain-why">{{ c.why }}</div>
            </div>
            <div class="ecy-chain-arrow" v-if="i < chain.length - 1">→</div>
          </template>
        </div>
      </section>

      <!-- ===== 预判窗口 ===== -->
      <section class="ecy-forecast-section" v-if="forecast">
        <div class="ecy-section-head"><h2>时间预判 · 岗位什么时候回来</h2></div>
        <div class="ecy-forecast-main">
          <template v-if="forecast.ready">
            <div class="ecy-forecast-window">{{ forecast.window_text }}</div>
            <div class="ecy-forecast-basis">
              依据：新订单指数自 <b>{{ forecast.order_streak_start }}</b> 起连续
              <b>{{ forecast.order_streak_months }}</b> 个月 ≥50（最新 {{ forecast.order_latest_period }} = {{ forecast.order_latest }}）；
              历史规律是订单连续过线后 <b>6~12 个月</b>从业人员指数跟上。
            </div>
          </template>
          <template v-else>
            <div class="ecy-forecast-window dim">{{ forecast.window_text }}</div>
          </template>
          <div class="ecy-forecast-confirm">✅ 最终确认：以 <b>PMI从业人员指数 ≥50</b> 为准（每月 31 日统计局发布，系统自动更新）；
            ⚠️ 失效条件：期间新订单跌破 49，重新计时。</div>
          <div class="ecy-forecast-disclaimer">{{ forecast.disclaimer }}</div>
        </div>
      </section>

      <!-- ===== 周期规律图 ===== -->
      <section class="ecy-chart-section">
        <div class="ecy-section-head">
          <h2>周期规律（近 8 年 · 规则回放）</h2>
          <div class="ecy-scope-tabs">
            <button v-for="t in ['national', 'xian']" :key="t"
                    :class="['ecy-tab', { active: chartScope === t }]"
                    @click="chartScope = t; renderTrend()">{{ t === 'national' ? '全国' : '西安' }}</button>
          </div>
        </div>
        <div ref="trendChart" class="ecy-trend-chart"></div>
        <div class="ecy-chart-legend">
          <span v-for="(meta, ph) in phaseLabels" :key="ph" class="ecy-legend-item">
            <i :style="{ background: meta.color }"></i>{{ meta.cn }}
          </span>
        </div>
      </section>

      <!-- ===== 指标构成（带解读） ===== -->
      <section class="ecy-indicators" v-if="currentIndicators.length">
        <h2>关键指标构成（{{ chartScope === 'national' ? '全国' : '西安' }}）<span class="ecy-ind-hint">点击卡片看"怎么读 / 多少算好 / 为什么"</span></h2>
        <div class="ecy-ind-grid">
          <div class="ecy-ind-card" v-for="ind in currentIndicators" :key="ind.code"
               :class="{ open: expandedCode === ind.code }" @click="toggleGuide(ind.code)">
            <div class="ecy-ind-name">{{ ind.name }}<span class="ecy-ind-q">?</span></div>
            <div class="ecy-ind-value">{{ ind.value }}<span class="ecy-ind-state" :class="'st-' + ind.state">{{ stateText(ind.state) }}</span></div>
            <div class="ecy-ind-bar">
              <div class="ecy-ind-fill" :style="{ width: ind.score + '%' }"
                   :class="ind.score >= 55 ? 'hi' : (ind.score <= 45 ? 'lo' : '')"></div>
            </div>
            <div class="ecy-ind-meta">{{ layerText(ind.layer) }} · 贡献分 {{ ind.score }}</div>
            <div class="ecy-ind-guide" v-if="expandedCode === ind.code && guideOf(ind.code)">
              <div class="ecy-gd-row"><b>怎么读</b>{{ guideOf(ind.code).how }}</div>
              <div class="ecy-gd-row good"><b>好的标准</b>{{ guideOf(ind.code).good }}</div>
              <div class="ecy-gd-row bad"><b>差的信号</b>{{ guideOf(ind.code).bad }}</div>
              <div class="ecy-gd-row"><b>为什么重要</b>{{ guideOf(ind.code).why }}</div>
            </div>
          </div>
        </div>
      </section>

      <section class="ecy-note">
        结论基于公开官方数据与显式规则回放生成，非事后人工标注；分数与阶段阈值为 V1 版本，
        将随历史数据积累持续校准。不构成投资建议。
      </section>
    </template>
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getEconOverview, getEconPhases, getEconPlaybook } from './services/apiService'

const PHASE_LABELS = {
  downturn: { cn: '持续恶化', color: '#e05252' },
  bottoming: { cn: '低位企稳', color: '#d9a441' },
  early_recovery: { cn: '复苏初期', color: '#7fb069' },
  expansion: { cn: '上行', color: '#3d8f5f' },
  overheating: { cn: '过热', color: '#c2703d' }
}

export default {
  name: 'EconCycle',
  data() {
    return {
      loading: false,
      error: '',
      overview: null,
      bands: { national: [], xian: [] },
      chartScope: 'national',
      trendChart: null,
      phaseLabels: PHASE_LABELS,
      playbook: null,
      expandedCode: ''
    }
  },
  computed: {
    phasePath() { return (this.playbook && this.playbook.phase_path) || [] },
    chain() { return (this.playbook && this.playbook.chain) || [] },
    forecast() { return this.playbook && this.playbook.forecast },
    currentPhase() {
      const o = this.overview || {}
      const item = this.chartScope === 'xian' ? o.xian : o.national
      return item && item.phase
    },
    scopeCards() {
      const o = this.overview || {}
      const mk = (key, title, item) => {
        const phase = item ? item.phase : 'bottoming'
        const meta = PHASE_LABELS[phase] || PHASE_LABELS.bottoming
        return {
          key, title,
          phaseCn: item ? item.phase_cn : '数据不足',
          score: item ? item.score : 0,
          month: item ? item.month : '',
          color: meta.color
        }
      }
      return [
        mk('national', '🇨🇳 全国景气', o.national),
        mk('xian', '🏛 西安景气', o.xian)
      ]
    },
    currentIndicators() {
      const o = this.overview || {}
      const item = this.chartScope === 'xian' ? o.xian : o.national
      return (item && item.indicators) || []
    }
  },
  async mounted() {
    await this.loadAll()
  },
  beforeUnmount() {
    if (this.trendChart) {
      this.trendChart.dispose()
      this.trendChart = null
    }
  },
  methods: {
    async loadAll() {
      this.loading = true
      this.error = ''
      try {
        const [ov, nat, xa, pb] = await Promise.all([
          getEconOverview(),
          getEconPhases('national'),
          getEconPhases('xian'),
          getEconPlaybook().catch(() => null)
        ])
        this.overview = ov.data
        this.bands.national = nat.bands || []
        this.bands.xian = xa.bands || []
        this.playbook = pb && pb.data
        this.$nextTick(() => this.renderTrend())
      } catch (e) {
        this.error = '数据加载失败：' + (e.response?.data?.error || e.message)
      } finally {
        this.loading = false
      }
    },
    // 周期路径:当前阶段之前的都算"已走完"(按 PHASE_PATH 顺序)
    phasePast(phase) {
      const order = this.phasePath.map(p => p.phase)
      const cur = order.indexOf(this.currentPhase)
      const me = order.indexOf(phase)
      return cur >= 0 && me >= 0 && me < cur
    },
    // 传导链每环状态:从全国 indicators 取趋势态
    chainState(code) {
      const o = this.overview || {}
      const nat = o.national
      const ind = nat && (nat.indicators || []).find(i => i.code === code)
      if (!ind) return { cls: 'nodata', label: '暂无数据' }
      const v = ind.value !== undefined ? ind.value : ''
      if (ind.state === 'rising') return { cls: 'up', label: '↑ 好转中', value: v }
      if (ind.state === 'falling') return { cls: 'down', label: '↓ 还没好', value: v }
      return { cls: 'flat', label: '→ 平稳待启动', value: v }
    },
    guideOf(code) {
      return this.playbook && this.playbook.guide && this.playbook.guide[code]
    },
    toggleGuide(code) {
      this.expandedCode = this.expandedCode === code ? '' : code
    },
    renderTrend() {
      const dom = this.$refs.trendChart
      if (!dom) return
      if (!this.trendChart) this.trendChart = echarts.init(dom)
      const bands = this.bands[this.chartScope] || []
      if (!bands.length) {
        this.trendChart.clear()
        this.trendChart.setOption({ title: { text: '暂无回放数据', left: 'center', top: 'middle', textStyle: { color: '#889' } } })
        return
      }
      // 连续同阶段合并为 markArea 区间
      const areas = []
      let start = null, prev = null
      bands.forEach(b => {
        if (b.phase !== prev) {
          if (prev) areas.push([{ xAxis: start }, { xAxis: prev, itemStyle: { color: (PHASE_LABELS[prev] || {}).color + '22' } }])
          start = b.month
          prev = b.phase
        }
      })
      if (prev) areas.push([{ xAxis: start }, { xAxis: bands[bands.length - 1].month, itemStyle: { color: (PHASE_LABELS[prev] || {}).color + '22' } }])
      const scoreData = bands.map(b => [b.month, b.score])
      const chart = this.trendChart
      chart.clear()
      chart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis' },
        grid: { left: 50, right: 20, top: 30, bottom: 60 },
        xAxis: { type: 'category', data: bands.map(b => b.month), axisLabel: { color: '#9ab', rotate: 45, interval: 5 } },
        yAxis: { type: 'value', min: 0, max: 100, splitLine: { lineStyle: { color: '#2a3244' } }, axisLabel: { color: '#9ab' } },
        series: [{
          name: '景气温度计',
          type: 'line',
          data: scoreData,
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#4da3ff', width: 2 },
          markArea: { silent: true, data: areas },
          markLine: { silent: true, symbol: 'none', lineStyle: { color: '#667', type: 'dashed' },
            data: [{ yAxis: 50, label: { formatter: '50 中线', color: '#889' } }] }
        }]
      })
      setTimeout(() => chart.resize(), 50)
    },
    lightIcon(l) { return l === 'green' ? '🟢' : (l === 'yellow' ? '🟡' : '🔴') },
    lightText(l) { return l === 'green' ? '窗口开启' : (l === 'yellow' ? '观望准备' : '不是时机') },
    stateText(s) { return s === 'rising' ? '↑改善' : (s === 'falling' ? '↓走弱' : '→平稳') },
    layerText(l) { return l === 'leading' ? '领先' : (l === 'lagging' ? '滞后' : '同步') }
  }
}
</script>

<style scoped>
.ecy-page { min-height: 100vh; background: #131824; color: #dfe6f3; padding: 18px 20px 40px; font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif; }
.ecy-header { display: flex; align-items: center; gap: 14px; margin-bottom: 18px; }
.ecy-header h1 { font-size: 20px; margin: 0; flex: 1; }
.ecy-back, .ecy-refresh { background: #1d2536; color: #9ab; border: 1px solid #2a3244; border-radius: 8px; padding: 8px 14px; cursor: pointer; font-size: 13px; }
.ecy-back:hover, .ecy-refresh:hover { color: #fff; border-color: #4da3ff; }
.ecy-error { background: #3a1f24; border: 1px solid #e05252; color: #ffb4b4; border-radius: 10px; padding: 12px 16px; margin-bottom: 14px; }

.ecy-lights { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px; margin-bottom: 14px; }
.ecy-scope-card { background: #1a2130; border: 1px solid #2a3244; border-left-width: 4px; border-radius: 12px; padding: 16px 18px; }
.ecy-scope-name { font-size: 13px; color: #9ab; }
.ecy-scope-phase { font-size: 26px; font-weight: 700; margin: 6px 0 10px; }
.ecy-gauge { display: flex; align-items: center; gap: 10px; }
.ecy-gauge-bar { flex: 1; height: 8px; background: #232c3f; border-radius: 4px; overflow: hidden; }
.ecy-gauge-fill { height: 100%; border-radius: 4px; transition: width .6s; }
.ecy-gauge-num { font-size: 18px; font-weight: 700; width: 40px; text-align: right; }
.ecy-scope-month { font-size: 12px; color: #67788f; margin-top: 8px; }

.ecy-decision { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; margin-bottom: 22px; }
.ecy-decision-card { background: #1a2130; border: 1px solid #2a3244; border-radius: 12px; padding: 14px 18px; }
.ecy-decision-card.light-green { border-left: 4px solid #3d8f5f; }
.ecy-decision-card.light-yellow { border-left: 4px solid #d9a441; }
.ecy-decision-card.light-red { border-left: 4px solid #e05252; }
.ecy-decision-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.ecy-decision-title { font-size: 16px; font-weight: 700; }
.ecy-decision-state { font-size: 13px; color: #9ab; margin-left: auto; }
.ecy-decision-reasons { margin: 0; padding-left: 18px; }
.ecy-decision-reasons li { font-size: 13px; color: #b9c4d8; line-height: 1.8; }

.ecy-chart-section, .ecy-indicators { background: #1a2130; border: 1px solid #2a3244; border-radius: 12px; padding: 16px 18px; margin-bottom: 16px; }
.ecy-section-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.ecy-section-head h2, .ecy-indicators h2 { font-size: 15px; margin: 0; color: #cdd7ea; }
.ecy-tab { background: #232c3f; color: #9ab; border: none; border-radius: 6px; padding: 5px 14px; cursor: pointer; margin-left: 6px; }
.ecy-tab.active { background: #2b5fad; color: #fff; }
.ecy-trend-chart { width: 100%; height: 340px; }
.ecy-chart-legend { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 6px; }
.ecy-legend-item { font-size: 12px; color: #9ab; display: flex; align-items: center; gap: 5px; }
.ecy-legend-item i { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }

.ecy-ind-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; margin-top: 12px; }
.ecy-ind-card { background: #161d2b; border: 1px solid #252e42; border-radius: 10px; padding: 12px 14px; }
.ecy-ind-name { font-size: 13px; color: #9ab; }
.ecy-ind-value { font-size: 20px; font-weight: 700; margin: 4px 0; }
.ecy-ind-state { font-size: 12px; margin-left: 8px; font-weight: 400; }
.st-rising { color: #7fb069; } .st-falling { color: #e05252; } .st-flat { color: #8896ad; }
.ecy-ind-bar { height: 5px; background: #232c3f; border-radius: 3px; overflow: hidden; }
.ecy-ind-fill { height: 100%; background: #8896ad; border-radius: 3px; }
.ecy-ind-fill.hi { background: #3d8f5f; } .ecy-ind-fill.lo { background: #e05252; }
.ecy-ind-meta { font-size: 11px; color: #67788f; margin-top: 6px; }

.ecy-note { font-size: 12px; color: #67788f; line-height: 1.7; }

/* ===== 周期路径 ===== */
.ecy-path-section { background: #1a2130; border: 1px solid #2a3244; border-radius: 12px; padding: 16px 18px; margin-bottom: 16px; }
.ecy-path-tip { font-size: 12px; color: #8394ad; margin: 8px 0 12px; line-height: 1.7; }
.ecy-path-track { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; }
.ecy-path-node { background: #161d2b; border: 1px solid #252e42; border-top: 3px solid var(--pc); border-radius: 10px; padding: 10px 10px 12px; position: relative; opacity: .82; }
.ecy-path-node.current { border-color: var(--pc); box-shadow: 0 0 14px -4px var(--pc); opacity: 1; background: #1b2436; }
.ecy-path-node.past { opacity: 1; }
.ecy-path-idx { position: absolute; top: 8px; right: 10px; font-size: 22px; font-weight: 800; color: var(--pc); opacity: .35; }
.ecy-path-name { font-size: 15px; font-weight: 700; color: var(--pc); margin-bottom: 8px; }
.ecy-path-current { font-size: 11px; color: #ffd98a; font-weight: 700; margin: -4px 0 6px; }
.ecy-path-block { font-size: 12px; color: #b9c4d8; line-height: 1.65; margin-bottom: 6px; }
.ecy-path-block b { display: block; font-size: 11px; color: #67788f; margin-bottom: 2px; }
.ecy-path-block.act { color: #d9c9a8; }

/* ===== 传导链 ===== */
.ecy-chain-section { background: #1a2130; border: 1px solid #2a3244; border-radius: 12px; padding: 16px 18px; margin-bottom: 16px; }
.ecy-chain-tip { font-size: 12px; color: #8394ad; margin: 8px 0 12px; line-height: 1.8; }
.ecy-chain-track { display: flex; align-items: stretch; gap: 4px; }
.ecy-chain-node { flex: 1; background: #161d2b; border: 1px solid #252e42; border-radius: 10px; padding: 10px 10px 12px; min-width: 0; }
.ecy-chain-node.st-up { border-color: #3d8f5f; }
.ecy-chain-node.st-down { border-color: #7a3b3b; }
.ecy-chain-rank { font-size: 11px; color: #67788f; }
.ecy-chain-name { font-size: 15px; font-weight: 700; margin: 2px 0 4px; }
.ecy-chain-status { font-size: 12px; font-weight: 700; }
.st-up .ecy-chain-status { color: #7fb069; }
.st-down .ecy-chain-status { color: #e05252; }
.st-flat .ecy-chain-status { color: #d9a441; }
.st-nodata .ecy-chain-status { color: #67788f; }
.ecy-chain-val { font-size: 12px; color: #9ab; margin-top: 2px; }
.ecy-chain-why { font-size: 11px; color: #8394ad; line-height: 1.6; margin-top: 6px; }
.ecy-chain-arrow { align-self: center; color: #4a5670; font-size: 16px; flex-shrink: 0; }

/* ===== 预判 ===== */
.ecy-forecast-section { background: linear-gradient(135deg, #1b2436, #1a2130); border: 1px solid #2b5fad; border-radius: 12px; padding: 16px 18px; margin-bottom: 16px; }
.ecy-forecast-window { font-size: 30px; font-weight: 800; color: #4da3ff; letter-spacing: 1px; }
.ecy-forecast-window.dim { font-size: 18px; color: #8394ad; font-weight: 500; }
.ecy-forecast-basis { font-size: 13px; color: #b9c4d8; line-height: 1.8; margin-top: 8px; }
.ecy-forecast-basis b { color: #ffd98a; }
.ecy-forecast-confirm { font-size: 12px; color: #9ab; margin-top: 8px; line-height: 1.8; }
.ecy-forecast-disclaimer { font-size: 11px; color: #67788f; margin-top: 6px; }

/* ===== 指标解读展开 ===== */
.ecy-ind-hint { font-size: 11px; color: #67788f; font-weight: 400; margin-left: 10px; }
.ecy-ind-card { cursor: pointer; transition: border-color .2s; }
.ecy-ind-card.open, .ecy-ind-card:hover { border-color: #4da3ff; }
.ecy-ind-q { float: right; width: 16px; height: 16px; border-radius: 50%; background: #2a3244; color: #9ab; font-size: 11px; text-align: center; line-height: 16px; }
.ecy-ind-guide { margin-top: 10px; border-top: 1px dashed #2a3244; padding-top: 8px; }
.ecy-gd-row { font-size: 12px; color: #b9c4d8; line-height: 1.7; margin-bottom: 6px; }
.ecy-gd-row b { display: inline-block; color: #67788f; font-size: 11px; margin-right: 6px; }
.ecy-gd-row.good b { color: #7fb069; } .ecy-gd-row.bad b { color: #e05252; }

@media (max-width: 900px) {
  .ecy-path-track { grid-template-columns: 1fr; }
  .ecy-chain-track { flex-direction: column; }
  .ecy-chain-arrow { transform: rotate(90deg); align-self: flex-start; padding-left: 12px; }
}
@media (max-width: 640px) {
  .ecy-page { padding: 12px 12px 30px; }
  .ecy-trend-chart { height: 260px; }
}
</style>
