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
      <!-- ===== 第一屏:一句话结论总览 ===== -->
      <section class="ecy-hero" :style="{ '--pc': heroColor }">
        <div class="ecy-hero-top">
          <div class="ecy-hero-tabs">
            <button :class="['ecy-tab', { active: chartScope === 'national' }]" @click="chartScope = 'national'">🇨🇳 全国</button>
            <button :class="['ecy-tab', { active: chartScope === 'xian' }]" @click="chartScope = 'xian'">🏛 西安</button>
          </div>
          <div class="ecy-hero-right">
            <span class="ecy-hero-month" v-if="heroItem">数据期间 {{ heroItem.month }}</span>
            <button class="ecy-ai-btn" @click="showAiModal = true">📋 复制给AI分析</button>
          </div>
        </div>
        <template v-if="heroConclusion">
          <div class="ecy-hero-main">
            <div class="ecy-hero-score">
              <span class="ecy-hero-num">{{ heroConclusion.score }}</span>
              <span class="ecy-hero-denom">/100</span>
            </div>
            <div class="ecy-hero-text">
              <div class="ecy-hero-headline">{{ heroConclusion.headline }}</div>
              <div class="ecy-hero-sub">
                <span class="ecy-hero-phase" :style="{ color: heroColor }">{{ heroConclusion.phase_cn }}</span>
                · 景气水平{{ heroConclusion.level_text }}（分数=近期历史分位，非PMI荣枯线）
              </div>
            </div>
          </div>
          <div class="ecy-hero-grid">
            <div class="ecy-hero-cell">
              <b>变化趋势</b>
              <span :class="'tr-' + heroConclusion.trend.cls">{{ heroConclusion.trend.text }}</span>
            </div>
            <div class="ecy-hero-cell">
              <b>最大压力</b>
              <span class="tr-down">{{ heroConclusion.pressure.text }}</span>
              <i>{{ heroConclusion.pressure.name }} {{ heroConclusion.pressure.value }}</i>
            </div>
            <div class="ecy-hero-cell">
              <b>复苏信号</b>
              <span :class="'sg-' + heroConclusion.signal.cls">{{ heroConclusion.signal.text }}</span>
            </div>
            <div class="ecy-hero-cell lights">
              <b>决策灯</b>
              <span>{{ lightIcon(overview.job_switch.light) }}换工作·{{ lightText(overview.job_switch.light) }}</span>
              <span>{{ lightIcon(overview.startup.light) }}创业·{{ lightText(overview.startup.light) }}</span>
            </div>
          </div>
        </template>
        <div v-else class="ecy-hero-empty">暂无数据：请在服务器上执行一次数据采集（管理员登录后 POST /api/econ/collect）</div>
      </section>

      <section class="ecy-decision">
        <div class="ecy-decision-card" :class="'light-' + overview.job_switch.light">
          <div class="ecy-decision-head">
            <span class="ecy-decision-icon">{{ lightIcon(overview.job_switch.light) }}</span>
            <span class="ecy-decision-title">换工作窗口</span>
            <span class="ecy-decision-state">{{ lightText(overview.job_switch.light) }} · {{ overview.job_switch.score }}分</span>
          </div>
          <ul class="ecy-decision-reasons">
            <li v-for="(r, i) in overview.job_switch.reasons" :key="i">{{ r }}</li>
          </ul>
        </div>
        <div class="ecy-decision-card" :class="'light-' + overview.startup.light">
          <div class="ecy-decision-head">
            <span class="ecy-decision-icon">{{ lightIcon(overview.startup.light) }}</span>
            <span class="ecy-decision-title">创业环境灯</span>
            <span class="ecy-decision-state">{{ lightText(overview.startup.light) }} · {{ overview.startup.score }}分</span>
          </div>
          <ul class="ecy-decision-reasons">
            <li v-for="(r, i) in overview.startup.reasons" :key="i">{{ r }}</li>
          </ul>
          <div class="ecy-decision-note">⚠ 这只评"宏观环境"合不合适。一个具体项目值不值得做，取决于客户痛点、付费验证和获客成本——宏观看天，验证看人。点右上「复制给AI分析」可带数据去讨论具体项目。</div>
        </div>
      </section>

      <!-- ===== 复苏进度条:五阶段窄带 + 六环传导 ===== -->
      <section class="ecy-prog-section">
        <div class="ecy-section-head">
          <h2>经济复苏进度 · 走到哪了</h2>
        </div>
        <div class="ecy-prog-band">
          <div class="ecy-prog-seg" v-for="(p, idx) in phasePath" :key="p.phase"
               :class="{ current: currentPhase === p.phase, past: phasePast(p.phase) }"
               :style="{ '--pc': p.color }" @click="openPhase = openPhase === p.phase ? '' : p.phase">
            <span class="ecy-prog-step">{{ idx + 1 }}·{{ p.name }}</span>
            <span class="ecy-prog-cur" v-if="currentPhase === p.phase">◀ 当前</span>
          </div>
        </div>
        <div class="ecy-prog-detail" v-if="openPhase">
          <b :style="{ color: openPhaseMeta.color }">{{ openPhaseMeta.name }}</b>
          <p><b>数据表现</b>{{ openPhaseMeta.sign }}</p>
          <p class="act"><b>该做什么</b>{{ openPhaseMeta.action }}</p>
        </div>
        <div class="ecy-prog-chain">
          <template v-for="(c, i) in chain" :key="c.key">
            <div class="ecy-chain-node" :class="['st-' + chainState(c.key).cls, { dim: !chainState(c.key).lit }]" @click="openChain = openChain === c.key ? '' : c.key">
              <div class="ecy-chain-rank">{{ i + 1 }}</div>
              <div class="ecy-chain-name">{{ c.name }}</div>
              <div class="ecy-chain-status">{{ chainState(c.key).label }}</div>
              <div class="ecy-chain-val" v-if="chainState(c.key).value !== undefined">{{ chainState(c.key).value }}</div>
              <div class="ecy-chain-why" v-if="openChain === c.key">{{ c.why }}</div>
            </div>
            <div class="ecy-chain-arrow" v-if="i < chain.length - 1">→</div>
          </template>
        </div>
        <div class="ecy-chain-tip">企业决策成本从低到高：接单最便宜、扩编最贵，所以复苏总是"订单先来、岗位最后到"——你觉得工作难找但新闻说回暖，就是卡在中间环节。</div>
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
          <h2>历史趋势（规则回放）<span class="ecy-chart-note">色带=当时所处阶段 · 虚线=50分位中线(非PMI荣枯线)</span></h2>
          <div>
            <button v-for="y in [3, 5, 8]" :key="y" :class="['ecy-tab', { active: chartYears === y }]"
                    @click="chartYears = y; renderTrend()">{{ y }}年</button>
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

      <!-- ===== 改善/恶化榜 ===== -->
      <section class="ecy-move-section" v-if="currentIndicators.length">
        <div class="ecy-section-head"><h2>正在改善 vs 仍在恶化（{{ chartScope === 'national' ? '全国' : '西安' }}）</h2></div>
        <div class="ecy-move-grid">
          <div class="ecy-move-col good">
            <b>↑ 正在改善 ({{ improvingList.length }})</b>
            <div class="ecy-move-item" v-for="ind in improvingList" :key="ind.code" @click="toggleGuide(ind.code)">
              <span class="mi-name">{{ ind.name }}</span>
              <span class="mi-val">{{ ind.value }} <i :class="'st-' + ind.state">{{ stateText(ind.state) }}</i></span>
            </div>
            <div class="ecy-move-empty" v-if="!improvingList.length">暂无明显改善项</div>
          </div>
          <div class="ecy-move-col bad">
            <b>↓ 仍在恶化 ({{ worseningList.length }})</b>
            <div class="ecy-move-item" v-for="ind in worseningList" :key="ind.code" @click="toggleGuide(ind.code)">
              <span class="mi-name">{{ ind.name }}</span>
              <span class="mi-val">{{ ind.value }} <i :class="'st-' + ind.state">{{ stateText(ind.state) }}</i></span>
            </div>
            <div class="ecy-move-empty" v-if="!worseningList.length">没有恶化项</div>
          </div>
        </div>
        <div class="ecy-move-guide" v-if="expandedCode && guideOf(expandedCode)">
          <b>{{ guideOf(expandedCode).name }}</b>
          <div class="ecy-gd-row"><b>怎么读</b>{{ guideOf(expandedCode).how }}</div>
          <div class="ecy-gd-row good"><b>好的标准</b>{{ guideOf(expandedCode).good }}</div>
          <div class="ecy-gd-row bad"><b>差的信号</b>{{ guideOf(expandedCode).bad }}</div>
          <div class="ecy-gd-row"><b>为什么重要</b>{{ guideOf(expandedCode).why }}</div>
        </div>
      </section>

      <!-- ===== 全部指标明细(默认折叠) ===== -->
      <section class="ecy-indicators" v-if="currentIndicators.length">
        <h2 class="ecy-fold" @click="showDetail = !showDetail">
          {{ showDetail ? '▾' : '▸' }} 全部指标明细（{{ currentIndicators.length }}项 · 贡献分与解读）
        </h2>
        <div class="ecy-ind-grid" v-if="showDetail">
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

      <!-- ===== AI分析弹窗 ===== -->
      <div class="ecy-modal-overlay" v-if="showAiModal" @click.self="showAiModal = false">
        <div class="ecy-modal">
          <div class="ecy-modal-head">
            <b>📋 复制给AI分析（含提示词+全部关键数据）</b>
            <button class="ecy-modal-close" @click="showAiModal = false">✕</button>
          </div>
          <div class="ecy-modal-tip">下面的内容已经打包好"你是谁、想要什么、全部数据、数据口径说明"。整体复制发给任意 AI（豆包/DeepSeek/ChatGPT）即可，它会按你要的方式分析。</div>
          <pre class="ecy-modal-pre">{{ aiReport }}</pre>
          <div class="ecy-modal-foot">
            <button class="ecy-copy-btn" @click="copyAiReport">{{ copied ? '✓ 已复制' : '一键复制全文' }}</button>
          </div>
        </div>
      </div>
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
      chartYears: 5,
      trendChart: null,
      phaseLabels: PHASE_LABELS,
      playbook: null,
      expandedCode: '',
      showDetail: false,
      openPhase: '',
      openChain: '',
      showAiModal: false,
      copied: false
    }
  },
  computed: {
    phasePath() { return (this.playbook && this.playbook.phase_path) || [] },
    chain() { return (this.playbook && this.playbook.chain) || [] },
    forecast() { return this.playbook && this.playbook.forecast },
    heroItem() {
      const o = this.overview || {}
      return this.chartScope === 'xian' ? o.xian : o.national
    },
    currentPhase() { return this.heroItem && this.heroItem.phase },
    heroColor() { return (PHASE_LABELS[this.currentPhase] || PHASE_LABELS.bottoming).color },
    heroConclusion() {
      // 优先用后端 conclusion;西安没有 conclusion 字段时前端按 national 结构降级取 indicators 生成不了则 null
      const item = this.heroItem
      if (!item) return null
      if (item.conclusion) return item.conclusion
      if (item.indicators && item.indicators.length) {
        // 降级:本地粗略生成(headline 按 phase,压力取最低分)
        const heads = {
          downturn: '经济仍在下行通道,先保住现金流',
          bottoming: '经济仍处低位,复苏尚未确认',
          early_recovery: '订单已回暖,岗位还没跟上——卡在复苏初期',
          expansion: '经济确认上行,就业正在改善',
          overheating: '经济偏热,扩张的同时注意风险'
        }
        const worst = item.indicators.reduce((a, b) => (a.score <= b.score ? a : b))
        return {
          headline: heads[item.phase] || '数据不足',
          phase_cn: item.phase_cn, score: item.score,
          level_text: item.score >= 65 ? '高位' : (item.score >= 50 ? '中位偏上' : (item.score >= 40 ? '中位偏下' : '低位')),
          month: item.month,
          trend: { text: '详见改善/恶化榜', cls: 'flat' },
          pressure: { name: worst.name, value: worst.value, text: worst.name + '仍偏弱' },
          signal: { cls: 'off', text: '详见复苏进度条' }
        }
      }
      return null
    },
    openPhaseMeta() {
      return this.phasePath.find(p => p.phase === this.openPhase) || {}
    },
    improvingList() { return this.currentIndicators.filter(i => i.state === 'rising') },
    worseningList() { return this.currentIndicators.filter(i => i.state === 'falling') },
    aiReport() {
      if (!this.overview) return ''
      const o = this.overview
      const L = []
      const fmt = it => it ? (it.value !== undefined && it.value !== null ? it.value : '—') : '—'
      L.push('请扮演一位既懂宏观经济又接地气的职业顾问。我在西安工作，正在纠结两个决定：')
      L.push('1) 现在换工作时机好不好（担心岗位越来越少）；2) 有没有适合轻量创业的窗口。')
      L.push('我不懂经济指标，请全程用大白话，少用术语，直接给结论和理由。')
      L.push('')
      L.push('请按以下顺序回答：')
      L.push('一、用3句话概括当前经济到底怎么样（发生了什么、在变好还是变坏、我最该关心什么）')
      L.push('二、逐条评估"换工作"和"创业"现在该不该动，明确说"能动/再等等/别动"，并给出你认为的关键理由')
      L.push('三、检查下面这套系统的判定有没有问题（数据口径、规则缺陷、可能的误判），你觉得哪里不可信就直说')
      L.push('四、给我未来6个月的行动清单：盯哪些数据、出现什么数值就该做什么动作')
      L.push('')
      L.push('===== 系统判定（供你核对，不要盲从） =====')
      for (const [key, label] of [['national', '全国'], ['xian', '西安']]) {
        const it = o[key]
        if (!it) continue
        const c = it.conclusion
        L.push('【' + label + '】' + it.phase_cn + ' ' + it.score + '/100（' + (c && c.month ? c.month : it.month) + '）')
        if (c) {
          L.push('  一句话：' + c.headline)
          L.push('  趋势：' + c.trend.text + ' | 最大压力：' + c.pressure.text + '（' + c.pressure.name + '=' + fmt(c.pressure) + '）| 复苏信号：' + c.signal.text)
        }
      }
      const jb = o.job_switch, st = o.startup
      if (jb) L.push('【换工作灯】' + jb.light + ' ' + jb.score + '分 | 依据：' + (jb.reasons || []).join('；'))
      if (st) L.push('【创业灯】' + st.light + ' ' + st.score + '分 | 依据：' + (st.reasons || []).join('；'))
      const fc = this.forecast
      if (fc) {
        L.push('【岗位回暖窗口预判】' + (fc.ready ? fc.window_text : '尚未形成可靠信号——' + (fc.window_text || '新订单需连续2个月≥50才开始计时')))
        L.push('  订单状态：' + (fc.order_latest_period || '') + ' 新订单=' + fc.order_latest + (fc.order_streak_start ? ('，自' + fc.order_streak_start + '起累计站稳' + fc.order_streak_months + '个月') : '，未形成连续站稳'))
        if (fc.confirm) L.push('  确认条件：' + fc.confirm)
        if (fc.disclaimer) L.push('  ' + fc.disclaimer)
      }
      L.push('')
      L.push('===== 指标明细（全国） =====')
      const nat = o.national
      if (nat && nat.indicators) {
        nat.indicators.forEach(i => {
          L.push('- ' + i.name + '：' + fmt(i) + '（' + (i.period || '') + '）趋势' + (i.state === 'rising' ? '↑好转' : i.state === 'falling' ? '↓恶化' : '→走平') + '，贡献分' + i.score + '/100，属' + (i.layer === 'leading' ? '先行指标(预告变化)' : i.layer === 'coincident' ? '同步指标(反映现在)' : '滞后指标(确认结果)'))
        })
      }
      const xa = o.xian
      if (xa && xa.indicators && xa.indicators.length) {
        L.push('')
        L.push('===== 西安指标（累计同比口径） =====')
        xa.indicators.forEach(i => {
          L.push('- ' + i.name + '：' + fmt(i) + '（' + (i.period || '') + '）趋势' + (i.state === 'rising' ? '↑' : i.state === 'falling' ? '↓' : '→') + '，贡献分' + i.score)
        })
      }
      const bands = (this.bands.national || []).slice(-24)
      if (bands.length) {
        L.push('')
        L.push('===== 全国近' + bands.length + '个月分数与阶段 =====')
        L.push(bands.map(b => b.month.slice(2) + ':' + b.score + '(' + (this.phaseLabels[b.phase] || {}).cn + ')').join(' '))
      }
      L.push('')
      L.push('===== 数据口径说明（分析前必读） =====')
      L.push('1. 分数0-100是"近60期历史分位"，不是PMI的50荣枯线；50中线=中位水平')
      L.push('2. 西安单月值由"1-N月累计同比"差分还原，只看方向别抠绝对值；西安数据2022年起')
      L.push('3. 阶段判定是显式规则（阈值+动量），V1版回测命中率：信号后3月分数上行占比约40%，6月约45%——所以它只是概率参考')
      L.push('4. 全部数据来自国家统计局/央行/交通部/西安统计局官网及权威接口，均带发布日期，无AI生成数据')
      L.push('5. PMI从业人员指数<50代表被调查企业中减员多于增员——这是岗位供给的直接读数')
      return L.join('\n')
    },
    currentIndicators() {
      const item = this.heroItem
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
    // 传导链每环状态:从全国 indicators 取趋势态;lit=该环已确认好转
    chainState(code) {
      const o = this.overview || {}
      const nat = o.national
      const ind = nat && (nat.indicators || []).find(i => i.code === code)
      if (!ind) return { cls: 'nodata', label: '暂无数据', lit: false }
      const v = ind.value !== undefined ? ind.value : ''
      if (ind.state === 'rising') return { cls: 'up', label: '↑ 好转中', value: v, lit: true }
      if (ind.state === 'falling') return { cls: 'down', label: '↓ 还没好', value: v, lit: false }
      return { cls: 'flat', label: '→ 平稳待启动', value: v, lit: false }
    },
    guideOf(code) {
      return this.playbook && this.playbook.guide && this.playbook.guide[code]
    },
    toggleGuide(code) {
      this.expandedCode = this.expandedCode === code ? '' : code
    },
    async copyAiReport() {
      const text = this.aiReport
      try {
        await navigator.clipboard.writeText(text)
      } catch (e) {
        // 兼容非安全上下文/旧内核:降级 execCommand
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        document.execCommand('copy')
        document.body.removeChild(ta)
      }
      this.copied = true
      setTimeout(() => { this.copied = false }, 2000)
    },
    renderTrend() {
      const dom = this.$refs.trendChart
      if (!dom) return
      if (!this.trendChart) this.trendChart = echarts.init(dom)
      // 默认只显示 chartYears 年,避免长历史稀释当前状态
      const all = this.bands[this.chartScope] || []
      const months = this.chartYears * 12
      const bands = all.length > months ? all.slice(-months) : all
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
      const last = bands[bands.length - 1]
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
            data: [{ yAxis: 50, label: { formatter: '50 分位中线', color: '#889' } }] },
          markPoint: {
            symbol: 'circle', symbolSize: 9, itemStyle: { color: '#ffd98a', borderColor: '#fff', borderWidth: 1 },
            label: { show: true, formatter: '当前 ' + last.score, color: '#ffd98a', position: 'top', fontSize: 11 },
            data: [{ coord: [last.month, last.score] }]
          }
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

/* ===== AI分析弹窗 ===== */
.ecy-hero-right { display: flex; align-items: center; gap: 10px; }
.ecy-ai-btn { background: linear-gradient(135deg, #2b5fad, #3d8f5f); color: #fff; border: none; border-radius: 8px; padding: 7px 14px; font-size: 13px; font-weight: 700; cursor: pointer; transition: filter .15s; }
.ecy-ai-btn:hover { filter: brightness(1.15); }
.ecy-modal-overlay { position: fixed; inset: 0; background: rgba(6, 10, 18, .78); backdrop-filter: blur(3px); z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 20px; }
.ecy-modal { background: #1a2130; border: 1px solid #2f3a52; border-radius: 14px; width: min(860px, 100%); max-height: 88vh; display: flex; flex-direction: column; padding: 18px 20px; }
.ecy-modal-head { display: flex; justify-content: space-between; align-items: center; font-size: 15px; color: #e8eefb; }
.ecy-modal-close { background: none; border: none; color: #8896ad; font-size: 18px; cursor: pointer; padding: 4px 8px; }
.ecy-modal-close:hover { color: #fff; }
.ecy-modal-tip { font-size: 12px; color: #8394ad; line-height: 1.6; margin: 8px 0 10px; background: #161d2b; border: 1px dashed #2a3244; border-radius: 8px; padding: 8px 12px; }
.ecy-modal-pre { flex: 1; overflow: auto; background: #121826; border: 1px solid #252e42; border-radius: 10px; padding: 14px 16px; font-size: 12.5px; line-height: 1.75; color: #c3cde0; white-space: pre-wrap; word-break: break-word; margin: 0 0 12px; font-family: Consolas, 'Microsoft YaHei', monospace; }
.ecy-modal-foot { display: flex; justify-content: flex-end; }
.ecy-copy-btn { background: linear-gradient(135deg, #3d8f5f, #4da3ff); color: #fff; border: none; border-radius: 8px; padding: 10px 26px; font-size: 14px; font-weight: 700; cursor: pointer; }
.ecy-copy-btn:hover { filter: brightness(1.12); }
@media (max-width: 640px) { .ecy-modal { padding: 14px; max-height: 92vh; } .ecy-hero-right { flex-direction: column; align-items: flex-end; gap: 6px; } }

.ecy-decision-note { font-size: 11.5px; color: #8a7a4e; background: #1d1e28; border: 1px dashed #4a4636; border-radius: 8px; padding: 7px 10px; margin-top: 10px; line-height: 1.7; }
.ecy-decision-card .ecy-decision-note { flex: 0 0 auto; }

/* ===== 第一屏总览卡 ===== */
.ecy-hero { background: linear-gradient(135deg, #1b2436, #18202f); border: 1px solid #2a3244; border-left: 4px solid var(--pc); border-radius: 14px; padding: 18px 22px; margin-bottom: 14px; }
.ecy-hero-top { display: flex; justify-content: space-between; align-items: center; }
.ecy-hero-month { font-size: 12px; color: #67788f; }
.ecy-hero-main { display: flex; align-items: center; gap: 22px; margin: 14px 0 16px; }
.ecy-hero-num { font-size: 54px; font-weight: 800; color: var(--pc); line-height: 1; }
.ecy-hero-denom { font-size: 15px; color: #67788f; }
.ecy-hero-headline { font-size: 24px; font-weight: 700; line-height: 1.35; }
.ecy-hero-sub { font-size: 13px; color: #8394ad; margin-top: 6px; }
.ecy-hero-phase { font-weight: 700; }
.ecy-hero-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.ecy-hero-cell { background: #161d2b; border: 1px solid #252e42; border-radius: 10px; padding: 10px 12px; font-size: 13px; line-height: 1.6; }
.ecy-hero-cell b { display: block; font-size: 11px; color: #67788f; margin-bottom: 4px; }
.ecy-hero-cell i { display: block; font-style: normal; font-size: 11px; color: #67788f; margin-top: 2px; }
.ecy-hero-cell.lights span { display: block; }
.tr-up { color: #7fb069; font-weight: 700; } .tr-down { color: #e05252; font-weight: 700; } .tr-flat { color: #d9a441; font-weight: 700; }
.sg-on { color: #7fb069; font-weight: 700; } .sg-weak { color: #d9a441; font-weight: 700; } .sg-off { color: #8896ad; font-weight: 700; }
.ecy-hero-empty { color: #8896ad; padding: 24px 0; text-align: center; }
.ecy-chart-note { font-size: 11px; color: #67788f; font-weight: 400; margin-left: 10px; }

/* ===== 复苏进度条 ===== */
.ecy-prog-section { background: #1a2130; border: 1px solid #2a3244; border-radius: 12px; padding: 16px 18px; margin-bottom: 16px; }
.ecy-prog-band { display: flex; gap: 4px; margin: 10px 0 8px; }
.ecy-prog-seg { flex: 1; padding: 9px 12px; background: #161d2b; border: 1px solid #252e42; border-top: 3px solid var(--pc); border-radius: 8px; cursor: pointer; opacity: .6; }
.ecy-prog-seg.past { opacity: .9; }
.ecy-prog-seg.current { opacity: 1; border-color: var(--pc); box-shadow: 0 0 12px -4px var(--pc); background: #1b2436; }
.ecy-prog-step { font-size: 13px; font-weight: 700; color: var(--pc); }
.ecy-prog-cur { font-size: 11px; color: #ffd98a; margin-left: 8px; font-weight: 700; }
.ecy-prog-detail { background: #161d2b; border: 1px dashed #2a3244; border-radius: 8px; padding: 10px 14px; margin-bottom: 10px; font-size: 13px; color: #b9c4d8; line-height: 1.7; }
.ecy-prog-detail p { margin: 4px 0; }
.ecy-prog-detail p b, .ecy-prog-detail b { font-size: 12px; color: #67788f; margin-right: 8px; }
.ecy-prog-detail p.act { color: #d9c9a8; }
.ecy-prog-chain { display: flex; align-items: stretch; gap: 4px; }
.ecy-prog-chain .ecy-chain-node { cursor: pointer; }
.ecy-prog-chain .ecy-chain-node.dim { opacity: .55; }

/* ===== 改善/恶化榜 ===== */
.ecy-move-section { background: #1a2130; border: 1px solid #2a3244; border-radius: 12px; padding: 16px 18px; margin-bottom: 16px; }
.ecy-move-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 10px; }
.ecy-move-col { background: #161d2b; border: 1px solid #252e42; border-radius: 10px; padding: 12px 14px; }
.ecy-move-col > b { font-size: 13px; display: block; margin-bottom: 8px; }
.ecy-move-col.good > b { color: #7fb069; } .ecy-move-col.bad > b { color: #e05252; }
.ecy-move-item { display: flex; justify-content: space-between; align-items: center; padding: 7px 0; border-bottom: 1px dashed #202939; cursor: pointer; font-size: 13px; }
.ecy-move-item:last-of-type { border-bottom: none; }
.ecy-move-item:hover .mi-name { color: #4da3ff; }
.mi-name { color: #c3cde0; }
.mi-val { color: #e8eefb; font-weight: 700; }
.mi-val i { font-style: normal; font-size: 11px; margin-left: 4px; font-weight: 400; }
.ecy-move-empty { font-size: 12px; color: #67788f; padding: 8px 0; }
.ecy-move-guide { background: #1b2436; border: 1px dashed #2b5fad; border-radius: 8px; padding: 10px 14px; margin-top: 10px; font-size: 12px; }
.ecy-move-guide > b { color: #cdd7ea; font-size: 13px; display: block; margin-bottom: 4px; }
.ecy-fold { cursor: pointer; user-select: none; }
.ecy-fold:hover { color: #4da3ff; }
.ecy-ind-hint { display: none; }

@media (max-width: 900px) {
  .ecy-hero-grid { grid-template-columns: 1fr 1fr; }
  .ecy-hero-main { flex-direction: column; gap: 8px; }
  .ecy-move-grid { grid-template-columns: 1fr; }
  .ecy-prog-band { flex-direction: column; }
  .ecy-prog-chain { flex-direction: column; }
  .ecy-chain-arrow { transform: rotate(90deg); align-self: flex-start; padding-left: 12px; }
}

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
