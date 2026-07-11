<template>
  <div class="fa-page">
    <header class="fa-header">
      <button @click="goBack" class="fa-back-button">← 返回</button>
      <h1>🚨 资金异动预警</h1>
      <div class="fa-header-right">
        <button @click="runDetect" class="fa-run-btn" :disabled="loading || needsAuth">
          {{ loading ? '检测中...' : '🔍 试跑检测' }}
        </button>
        <button @click="testNotification" class="fa-test-btn">🔔 测试通知</button>
      </div>
    </header>

    <div class="fa-snapshot">
      最近一次 5 分钟抓取：<strong>{{ snapshot.date && snapshot.time ? `${snapshot.date} ${snapshot.time}` : '暂无可用快照' }}</strong>
      <span>页面只显示这一时点的检测结果</span>
    </div>

    <div class="fa-controls">
      <div class="fa-ctrl-group" v-if="false">
        <label>日期</label>
        <select v-model="selectedDate" @change="onDateChange">
          <option v-for="d in dates" :key="d" :value="d">{{ d }}</option>
        </select>
      </div>
      <div class="fa-ctrl-group">
        <label>视图</label>
        <div class="fa-mode-toggle">
          <button :class="{active: view==='detect'}" @click="switchView('detect')">🔍 全天命中</button>
          <button :class="{active: view==='pushed'}" @click="switchView('pushed')">📱 已推送记录</button>
        </div>
      </div>
    </div>

    <div v-if="needsAuth" class="fa-auth-mask">
      <div class="fa-auth-content">
        <div class="fa-auth-icon">🔒</div>
        <div class="fa-auth-text">登录后查看异动预警</div>
        <button class="fa-auth-btn" @click="promptLogin">去登录</button>
      </div>
    </div>

    <template v-else>
      <!-- 全天命中视图 -->
      <div v-if="view==='detect'">
        <div class="fa-stats" v-if="findings.length">
          <div class="fa-stat"><div class="fa-stat-num">{{ findings.length }}</div><div class="fa-stat-lbl">命中条数</div></div>
          <div class="fa-stat"><div class="fa-stat-num">{{ sectorCount }}</div><div class="fa-stat-lbl">涉及板块</div></div>
          <div class="fa-stat"><div class="fa-stat-num">{{ dimCount.divergence || 0 }}</div><div class="fa-stat-lbl">价量背离</div></div>
          <div class="fa-stat"><div class="fa-stat-num">{{ dimCount.surge || 0 }}</div><div class="fa-stat-lbl">巨量异动</div></div>
          <div class="fa-stat"><div class="fa-stat-num">{{ dimCount.spike || 0 }}</div><div class="fa-stat-lbl">突变</div></div>
          <div class="fa-stat"><div class="fa-stat-num">{{ dimCount.streak || 0 }}</div><div class="fa-stat-lbl">连续同向</div></div>
        </div>

        <div class="fa-filter" v-if="findings.length">
          <button :class="['fa-chip', {active: filter==='all'}]" @click="filter='all'">全部</button>
          <button v-for="d in dims" :key="d.key" :class="['fa-chip', `chip-${d.key}`, {active: filter===d.key}]" @click="filter=d.key">
            {{ d.icon }} {{ d.label }} {{ dimCount[d.key] || 0 }}
          </button>
        </div>

        <div class="fa-loading" v-if="loading"><div class="spinner"></div><p>正在扫描全天资金异动...</p></div>

        <div v-else-if="!filteredFindings.length" class="fa-empty">
          <p>{{ findings.length ? '该筛选下无命中' : '当日无命中异动，市场相对平静' }}</p>
        </div>

        <div v-else class="fa-timeline stagger-in">
          <div class="fa-card" v-for="(f, idx) in shownFindings" :key="idx" :style="{ '--i': Math.min(idx, 15) }">
            <div class="fa-card-head">
              <span class="fa-time">{{ f.date }} {{ f.time }}</span>
              <span class="fa-sector">{{ f.sector }}</span>
              <span class="fa-rank" v-if="f.is_rank_top">★ 榜首</span>
              <span class="fa-rank-id" v-else>#{{ f.rank }}</span>
            </div>
            <div class="fa-card-meta">
              <span class="fa-net" :class="f.net_flow >= 0 ? 'pos' : 'neg'">
                净流入 {{ fmt(f.net_flow) }} 亿
              </span>
              <span class="fa-chg" :class="f.change_pct >= 0 ? 'pos' : 'neg'">
                {{ f.change_pct >= 0 ? '+' : '' }}{{ fmt(f.change_pct) }}%
              </span>
              <span class="fa-lead" v-if="f.lead_stock">龙头 {{ f.lead_stock }}<template v-if="f.lead_change != null"> {{ f.lead_change >= 0 ? '+' : '' }}{{ fmt(f.lead_change) }}%</template></span>
            </div>
            <div class="fa-hits">
              <span v-for="(h, i) in f.hits" :key="i" :class="['fa-hit', `hit-${h.type}`]" :title="hitDetail(h)">
                {{ hitIcon(h.type) }} {{ h.label }}
                <span class="fa-hit-sub">{{ hitSub(h) }}</span>
              </span>
            </div>
          </div>
          <div class="fa-more" v-if="filteredFindings.length > shownFindings.length">
            <button @click="showLimit += 100">加载更多（剩余 {{ filteredFindings.length - shownFindings.length }}）</button>
          </div>
        </div>
      </div>

      <!-- 已推送记录视图 -->
      <div v-else>
        <div class="fa-stats" v-if="pushed.length">
          <div class="fa-stat"><div class="fa-stat-num">{{ pushed.length }}</div><div class="fa-stat-lbl">已推送条数</div></div>
        </div>
        <div class="fa-loading" v-if="loadingPushed"><div class="spinner"></div><p>加载中...</p></div>
        <div v-else-if="!pushed.length" class="fa-empty"><p>暂无已推送记录（实时 hook 在交易时段触发，或试跑不推送）</p></div>
        <div v-else class="fa-timeline stagger-in">
          <div class="fa-card" v-for="(a, idx) in pushed" :key="idx">
            <div class="fa-card-head">
              <span class="fa-time">{{ a.date }} {{ a.time }}</span>
              <span class="fa-sector">{{ a.sector }}</span>
              <span class="fa-pushed-tag">{{ a.pushed ? '✓ 已送达' : '✗ 未送达' }}</span>
            </div>
            <div class="fa-card-meta">
              <span class="fa-net" :class="a.net_flow >= 0 ? 'pos' : 'neg'">净流入 {{ fmt(a.net_flow) }} 亿</span>
              <span class="fa-chg" :class="a.change_pct >= 0 ? 'pos' : 'neg'">{{ a.change_pct >= 0 ? '+' : '' }}{{ fmt(a.change_pct) }}%</span>
              <span class="fa-lead" v-if="a.lead_stock">龙头 {{ a.lead_stock }}</span>
            </div>
            <div class="fa-hits">
              <span v-for="(lb, i) in a.labels" :key="i" class="fa-hit">{{ lb }}</span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div class="fa-footnote">
      异动判定：价量背离 / 巨量 z-score / 突变 / 连续同向 四维度。<br/>
      实时推送在交易时段每 5 分钟采集后自动触发（去重冷却 30 分钟）。可在「系统配置 → 异动检测」调整阈值。
    </div>

    <SecurityAlert />
  </div>
</template>

<script>
import { runAnomalyDetection, getAnomalyAlerts } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

const DIM_META = {
  divergence: { icon: '⚖️', label: '背离' },
  surge:      { icon: '💥', label: '巨量' },
  spike:      { icon: '⚡', label: '突变' },
  streak:     { icon: '🔁', label: '连续' }
}

export default {
  name: 'FlowAlert',
  components: { SecurityAlert },
  data() {
    return {
      loading: false,
      loadingPushed: false,
      needsAuth: false,
      snapshot: { date: '', time: '' },
      view: 'detect',
      findings: [],
      pushed: [],
      filter: 'all',
      showLimit: 100
    }
  },
  computed: {
    dims() { return Object.keys(DIM_META).map(k => ({ key: k, ...DIM_META[k] })) },
    sectorCount() { return new Set(this.findings.map(f => f.sector)).size },
    dimCount() {
      const c = {}
      this.findings.forEach(f => f.hits.forEach(h => { c[h.type] = (c[h.type] || 0) + 1 }))
      return c
    },
    filteredFindings() {
      const list = this.filter === 'all' ? this.findings
        : this.findings.filter(f => f.hits.some(h => h.type === this.filter))
      return [...list].sort((a, b) => (a.time < b.time ? 1 : -1))
    },
    shownFindings() { return this.filteredFindings.slice(0, this.showLimit) }
  },
  async mounted() {
    window.addEventListener('auth-required', this.onAuthRequired)
    window.addEventListener('auth-login-success', this.onAuthLogin)
    await this.runDetect()
  },
  beforeUnmount() {
    window.removeEventListener('auth-required', this.onAuthRequired)
    window.removeEventListener('auth-login-success', this.onAuthLogin)
  },
  methods: {
    goBack() { this.$router.push('/') },
    promptLogin() { window.dispatchEvent(new CustomEvent('auth-request-login')) },
    onAuthRequired() { this.needsAuth = true; this.loading = false },
    onAuthLogin() { if (this.needsAuth) { this.needsAuth = false; this.runDetect() } },
    fmt(v) { return (v == null || isNaN(v)) ? '--' : Number(v).toFixed(2) },
    hitIcon(t) { return (DIM_META[t] || {}).icon || '•' },
    hitDetail(h) {
      if (h.type === 'surge') return h.sample_sufficient ? `z=${h.z}，历史上榜 ${h.count} 次` : `绝对量级判定（样本 ${h.count || 0} 次）`
      if (h.type === 'spike') return `Δ${h.delta} 亿（vs ${h.prev_time}）`
      if (h.type === 'streak') return `持续 ${h.streak} 段≈${h.minutes}分钟，累计增量 ${h.cum_delta} 亿`
      if (h.type === 'divergence') return `5分钟 价${h.d_change_pct >= 0 ? '+' : ''}${h.d_change_pct}% / 量${h.d_net_flow > 0 ? '+' : ''}${h.d_net_flow}亿`
      return ''
    },
    hitSub(h) {
      if (h.type === 'surge') return h.z != null ? `z=${h.z}` : `${h.net_flow}亿`
      if (h.type === 'spike') return `${h.delta > 0 ? '+' : ''}${h.delta}亿`
      if (h.type === 'streak') return `${h.minutes}分`
      if (h.type === 'divergence') return `5分钟 价${h.d_change_pct >= 0 ? '+' : ''}${h.d_change_pct}%/量${h.d_net_flow > 0 ? '+' : ''}${h.d_net_flow}亿`
      return ''
    },
    switchView(v) {
      this.view = v
      if (v === 'pushed' && !this.pushed.length) this.loadPushed()
    },
    async onDateChange() {
      this.showLimit = 100
      if (this.view === 'detect') this.runDetect()
      else { this.pushed = []; this.loadPushed() }
    },
    async runDetect() {
      this.loading = true
      this.findings = []
      try {
        const res = await runAnomalyDetection()
        if (res.success) {
          this.findings = res.data || []
          this.snapshot = res.snapshot || { date: '', time: '' }
        }
      } catch (e) { /* 401 已处理 */ }
      finally { this.loading = false }
    },
    async testNotification() {
      if (!('Notification' in window)) { alert('当前浏览器不支持桌面通知'); return }
      if (Notification.permission === 'default') {
        const p = await Notification.requestPermission()
        if (p !== 'granted') { alert('已拒绝通知权限，无法测试'); return }
      }
      if (Notification.permission !== 'granted') { alert('请先允许浏览器通知权限'); return }
      try {
        const n = new Notification('🚨 资金异动 · 半导体（测试）', {
          body: '回调吸筹｜突变｜净流入+99.14亿 +0.74% 龙头有研硅',
          icon: 'https://pic.0vk.top/%E8%82%A1%E7%A5%A8.png',
          tag: 'anomaly-test',
          requireInteraction: true
        })
        n.onclick = () => { window.focus(); n.close() }
        const tryPlay = (paths) => {
          if (!paths.length) return
          const a = new Audio(paths[0]); a.volume = 0.5
          a.play().catch(() => tryPlay(paths.slice(1)))
        }
        tryPlay(['/assets/sounds/important.mp3', '/sounds/important.mp3'])
      } catch (e) { alert('通知发送失败: ' + e) }
    },
    async loadPushed() {
      if (!this.selectedDate) return
      this.loadingPushed = true
      try {
        const res = await getAnomalyAlerts(this.selectedDate)
        if (res.success) this.pushed = res.data || []
      } catch (e) { /* ignore */ }
      finally { this.loadingPushed = false }
    }
  }
}
</script>

<style scoped>
.fa-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0e17 0%, #1a1f35 50%, #0d1321 100%);
  color: #e0e6f0; padding: 20px;
}
.fa-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; padding-right: 110px; }
.fa-back-button {
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b); color: #e0e6f0;
  border: 1px solid #4a5a7b; border-radius: 4px; padding: 8px 14px; cursor: pointer; font-size: 14px;
}
.fa-header h1 { font-size: 22px; font-weight: 600; margin: 0; flex: 1; }
.fa-snapshot {
  margin: 0 0 16px; padding: 10px 14px; border-radius: 8px;
  background: rgba(26,35,53,.6); border: 1px solid rgba(58,74,107,.5);
  color: #8ba4c7; font-size: 13px;
}
.fa-snapshot strong { margin-left: 6px; color: #fff; font-family: monospace; }
.fa-snapshot span { margin-left: 14px; font-size: 12px; color: #6a7a99; }
.fa-run-btn {
  background: linear-gradient(135deg, #ff4d4f, #cf1322); color: #fff;
  border: 1px solid #ff7875; border-radius: 4px; padding: 8px 18px; cursor: pointer; font-size: 13px;
  box-shadow: 0 4px 12px rgba(255,77,79,.3);
}
.fa-run-btn:disabled { opacity: .6; cursor: not-allowed; }
.fa-test-btn {
  background: linear-gradient(135deg, #fa8c16, #d4670c); color: #fff;
  border: 1px solid #ffa940; border-radius: 4px; padding: 8px 16px; cursor: pointer; font-size: 13px;
  box-shadow: 0 4px 12px rgba(250,140,22,.3); margin-left: 8px;
}

.fa-controls {
  display: none;
  background: rgba(26,35,53,.6); border: 1px solid rgba(58,74,107,.5);
  border-radius: 8px; padding: 14px 18px; margin-bottom: 16px;
}
.fa-ctrl-group { display: flex; flex-direction: column; gap: 6px; }
.fa-ctrl-group label { font-size: 12px; color: #8ba4c7; }
.fa-ctrl-group select {
  background: #111827; color: #e0e6f0; border: 1px solid rgba(148,163,184,.3);
  border-radius: 4px; padding: 6px 10px; font-size: 13px; min-width: 130px;
}
.fa-mode-toggle { display: flex; }
.fa-mode-toggle button {
  background: #1a2236; color: #8ba4c7; border: 1px solid rgba(148,163,184,.25);
  padding: 6px 12px; font-size: 12px; cursor: pointer;
}
.fa-mode-toggle button:first-child { border-radius: 4px 0 0 4px; }
.fa-mode-toggle button:last-child { border-radius: 0 4px 4px 0; border-left: none; }
.fa-mode-toggle button.active { background: linear-gradient(135deg, #ff4d4f, #cf1322); color: #fff; border-color: #ff7875; }

.fa-auth-mask, .fa-loading, .fa-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 60px 0; color: #8ba4c7;
}
.fa-auth-content { text-align: center; }
.fa-auth-icon { font-size: 48px; margin-bottom: 12px; }
.fa-auth-btn { margin-top: 14px; background: linear-gradient(135deg, #1890ff, #096dd9); color: #fff; border: none; border-radius: 4px; padding: 8px 22px; cursor: pointer; }
.spinner { width: 36px; height: 36px; border: 3px solid rgba(58,74,107,.3); border-top-color: #ff4d4f; border-radius: 50%; animation: spin 1s linear infinite; margin-bottom: 12px; }
@keyframes spin { to { transform: rotate(360deg); } }

.fa-stats { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.fa-stat {
  flex: 1; min-width: 110px; background: rgba(26,35,53,.6); border: 1px solid rgba(58,74,107,.5);
  border-radius: 8px; padding: 12px; text-align: center;
}
.fa-stat-num { font-size: 24px; font-weight: 600; color: #fff; }
.fa-stat-lbl { font-size: 11px; color: #8ba4c7; margin-top: 4px; }

.fa-filter { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.fa-chip {
  background: #1a2236; color: #8ba4c7; border: 1px solid rgba(148,163,184,.25);
  border-radius: 16px; padding: 5px 14px; font-size: 12px; cursor: pointer; transition: all .2s;
}
.fa-chip.active { color: #fff; border-color: #40a9ff; }
.chip-divergence.active { background: #722ed1; border-color: #9254de; }
.chip-surge.active { background: #ff4d4f; border-color: #ff7875; }
.chip-spike.active { background: #fa8c16; border-color: #ffa940; }
.chip-streak.active { background: #06b6d4; border-color: #22d3ee; }

.fa-timeline { display: flex; flex-direction: column; gap: 10px; }
.fa-card {
  background: rgba(26,35,53,.6); border: 1px solid rgba(58,74,107,.5);
  border-radius: 8px; padding: 12px 16px; border-left: 3px solid #3a4a6b;
}
.fa-card-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.fa-time { font-size: 12px; color: #8ba4c7; font-family: monospace; }
.fa-sector { font-size: 16px; font-weight: 600; color: #fff; flex: 1; }
.fa-rank { font-size: 11px; color: #faad14; border: 1px solid #faad14; border-radius: 10px; padding: 1px 8px; }
.fa-rank-id { font-size: 11px; color: #8ba4c7; }
.fa-pushed-tag { font-size: 11px; padding: 2px 8px; border-radius: 10px; background: rgba(82,196,26,.15); color: #52c41a; border: 1px solid rgba(82,196,26,.4); }
.fa-card-meta { display: flex; gap: 18px; font-size: 13px; margin-bottom: 8px; flex-wrap: wrap; }
.fa-net.pos, .fa-chg.pos { color: #ff4d4f; }
.fa-net.neg, .fa-chg.neg { color: #13d17c; }
.fa-lead { color: #c0cce0; }
.fa-hits { display: flex; gap: 8px; flex-wrap: wrap; }
.fa-hit {
  font-size: 12px; padding: 4px 10px; border-radius: 12px;
  background: rgba(255,255,255,.06); border: 1px solid rgba(148,163,184,.2); color: #e0e6f0;
}
.fa-hit-sub { color: #8ba4c7; margin-left: 4px; font-size: 11px; }
.hit-divergence { background: rgba(114,46,209,.18); border-color: rgba(146,84,222,.5); }
.hit-surge { background: rgba(255,77,79,.18); border-color: rgba(255,120,117,.5); }
.hit-spike { background: rgba(250,140,22,.18); border-color: rgba(255,169,64,.5); }
.hit-streak { background: rgba(6,182,212,.18); border-color: rgba(34,211,238,.5); }
.fa-more { text-align: center; margin-top: 10px; }
.fa-more button { background: #1a2236; color: #8ba4c7; border: 1px solid rgba(148,163,184,.25); border-radius: 4px; padding: 8px 20px; cursor: pointer; font-size: 13px; }
.fa-footnote { text-align: center; margin-top: 24px; font-size: 11px; color: #6a7a99; line-height: 1.8; }
</style>
