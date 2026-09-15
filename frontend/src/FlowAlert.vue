<template>
  <div class="fa-page">
    <header class="fa-header">
      <button @click="goBack" class="fa-back-button">← 返回</button>
      <h1>🚨 异动预警</h1>
      <div class="fa-main-tabs">
        <button :class="['fa-main-tab', {active: mainTab==='fund'}]" @click="switchMainTab('fund')">💰 资金异动</button>
        <button :class="['fa-main-tab', {active: mainTab==='pulse'}]" @click="switchMainTab('pulse')">📈 个股异动</button>
      </div>
      <div class="fa-header-right">
        <button v-if="mainTab==='fund'" @click="runDetect" class="fa-run-btn" :disabled="loading || needsAuth">
          <IconRefresh v-if="!loading" />
          {{ loading ? '检测中...' : '刷新全天结果' }}
        </button>
        <button @click="testNotification" class="fa-test-btn">🔔 测试通知</button>
      </div>
    </header>

    <div class="fa-snapshot" v-if="mainTab==='fund'">
      全天资金异动汇总：<strong>{{ snapshot.date || '--' }}</strong>
      <span>最新抓取 {{ snapshot.time || '--' }} · 覆盖当日全部 5 分钟时点（共 {{ findings.length }} 条），非单一时刻</span>
    </div>

    <div class="fa-controls" v-if="mainTab==='fund'">
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
      <!-- ==================== 个股异动（Stock Pulse，盘中每5分钟采样） ==================== -->
      <template v-if="mainTab==='pulse'">
        <!-- 板块聚集活动：多少板块在集体拉升/跳水及各自中位涨幅（不重复首页的涨跌家数） -->
        <div class="fa-pulse-activity" v-if="pulseSummary">
          <div class="fa-activity-head">
            <span class="fa-activity-title">🧲 板块聚集活动</span>
            <span class="fa-activity-time">{{ pulseSummary.date }} {{ pulseSummary.time }} 轮</span>
          </div>
          <div class="fa-activity-counts">
            <span class="act-pos">拉升板块 {{ pulseSummary.rising_count || 0 }}</span>
            <span class="act-neg">跳水板块 {{ pulseSummary.falling_count || 0 }}</span>
          </div>
          <!-- 全天累计：反复走强/反复走弱的板块（按触发轮数排序） -->
          <template v-if="(pulseSummary.day_strong || []).length || (pulseSummary.day_weak || []).length">
            <div class="fa-rank-line" v-if="pulseSummary.day_strong && pulseSummary.day_strong.length">
              <span class="fa-rank-tag rank-pos">全天领涨</span>
              <span v-for="s in pulseSummary.day_strong.slice(0, 4)" :key="'ds'+s.level+s.sector" class="fa-rank-item">
                {{ pulseSectorLabel(s) }}<em>拉升 {{ s.rounds }} 轮 · 峰值 {{ s.max_count }} 只 · 均值 {{ s.avg_median >= 0 ? '+' : '' }}{{ fmt(s.avg_median) }}%</em>
              </span>
            </div>
            <div class="fa-rank-line" v-if="pulseSummary.day_weak && pulseSummary.day_weak.length">
              <span class="fa-rank-tag rank-neg">全天领跌</span>
              <span v-for="s in pulseSummary.day_weak.slice(0, 4)" :key="'dw'+s.level+s.sector" class="fa-rank-item">
                {{ pulseSectorLabel(s) }}<em>跳水 {{ s.rounds }} 轮 · 峰值 {{ s.max_count }} 只 · 均值 {{ fmt(s.avg_median) }}%</em>
              </span>
            </div>
          </template>
          <div class="fa-rank-line" v-if="pulseSummary.sectors_rising && pulseSummary.sectors_rising.length">
            <span class="fa-rank-tag rank-pos">拉升</span>
            <span v-for="s in pulseSummary.sectors_rising" :key="'r'+s.level+s.sector" class="fa-rank-item">
              {{ pulseSectorLabel(s) }} <b class="pulse-pos">{{ s.median_pct >= 0 ? '+' : '' }}{{ fmt(s.median_pct) }}%</b>
              <em v-if="s.hits && s.hits.length">{{ s.hits[0].count }}/{{ s.total }} 只{{ s.hits[0].label }}</em>
            </span>
          </div>
          <div class="fa-rank-line" v-if="pulseSummary.sectors_falling && pulseSummary.sectors_falling.length">
            <span class="fa-rank-tag rank-neg">跳水</span>
            <span v-for="s in pulseSummary.sectors_falling" :key="'f'+s.level+s.sector" class="fa-rank-item">
              {{ pulseSectorLabel(s) }} <b class="pulse-neg">{{ fmt(s.median_pct) }}%</b>
              <em v-if="s.hits && s.hits.length">{{ s.hits[0].count }}/{{ s.total }} 只{{ s.hits[0].label }}</em>
            </span>
          </div>
          <div class="fa-activity-empty" v-if="!(pulseSummary.sectors_rising || []).length && !(pulseSummary.sectors_falling || []).length">
            最新一轮无板块聚集异动，市场相对平静
          </div>
        </div>
        <div v-else-if="!pulseLoading" class="fa-empty"><p>当日暂无采样数据（交易时段每 5 分钟自动采样）</p></div>

        <div class="fa-controls">
          <div class="fa-ctrl-group">
            <button @click="runPulseDetect" class="fa-run-btn" :disabled="pulseLoading || needsAuth">
              {{ pulseLoading ? '检测中...' : '刷新全天结果' }}
            </button>
          </div>
          <div class="fa-ctrl-group">
            <label>类型</label>
            <div class="fa-mode-toggle">
              <button :class="{active: pulseFilter==='all'}" @click="pulseFilter='all'">全部</button>
              <button :class="{active: pulseFilter==='sector'}" @click="pulseFilter='sector'">🧲 板块聚集</button>
              <button :class="{active: pulseFilter==='limit'}" @click="pulseFilter='limit'">🚨 涨停聚集</button>
            </div>
          </div>
        </div>

        <div class="fa-loading" v-if="pulseLoading"><div class="spinner"></div><p>正在扫描全天个股异动...</p></div>
        <div v-else-if="!shownPulseGroups.length" class="fa-empty">
          <p>{{ pulseFindings.length ? '该筛选下无命中' : '当日无异动命中，市场相对平静' }}</p>
        </div>
        <div v-else class="fa-timeline stagger-in">
          <template v-for="(g, gidx) in shownPulseGroups" :key="gidx">
            <!-- 板块聚集卡片：来源 analysis/stock_pulse.py -->
            <template v-for="(f, idx) in g.items" :key="gidx+'-'+idx">
              <!-- 涨跌停聚集卡片：同二级行业≥2只涨跌停 -->
              <div v-if="f.kind === 'pulse_limit_cluster'" class="fa-card fa-card-pulse"
                   :style="{ '--i': Math.min(gidx + idx, 15) }">
                <div class="fa-card-head">
                  <span class="fa-time">{{ f.date }} {{ f.time }}</span>
                  <span class="fa-sector">{{ f.sector }}</span>
                  <span class="fa-pulse-tag">🚨 {{ f.label }}聚集</span>
                </div>
                <div class="fa-hits">
                  <span :class="['fa-hit', f.type === 'limit_up_cluster' ? 'hit-pulse-pos' : 'hit-pulse-neg']">
                    {{ pulseHitIcon(f.type) }} {{ f.label }} {{ f.count }} 只
                  </span>
                </div>
                <div class="fa-pulse-leaders" v-if="f.members && f.members.length">
                  <span v-for="m in f.members" :key="m.code" class="fa-leader-item">
                    {{ m.name }} <b :class="m.pct >= 0 ? 'pulse-pos' : 'pulse-neg'">{{ m.pct >= 0 ? '+' : '' }}{{ fmt(m.pct) }}%</b>
                  </span>
                </div>
              </div>
              <!-- 板块聚集卡片（拉升/翻红/跳水） -->
              <div v-else class="fa-card fa-card-pulse"
                   :style="{ '--i': Math.min(gidx + idx, 15) }">
                <div class="fa-card-head">
                  <span class="fa-time">{{ f.date }} {{ f.time }}</span>
                  <span class="fa-sector">{{ pulseSectorLabel(f) }}</span>
                  <span class="fa-pulse-tag">🧲 板块聚集</span>
                </div>
                <div class="fa-card-meta">
                  <span class="fa-chg" :class="f.median_pct >= 0 ? 'pulse-pos' : 'pulse-neg'">中位涨幅 {{ f.median_pct >= 0 ? '+' : '' }}{{ fmt(f.median_pct) }}%</span>
                  <span class="fa-chg" :class="f.median_delta >= 0 ? 'pulse-pos' : 'pulse-neg'">较上轮 {{ f.median_delta >= 0 ? '+' : '' }}{{ fmt(f.median_delta) }}%</span>
                </div>
                <div class="fa-hits">
                  <span v-for="(h, i) in f.hits" :key="i" :class="['fa-hit', h.type === 'cluster_dump' ? 'hit-pulse-neg' : 'hit-pulse-pos']">
                    {{ pulseHitIcon(h.type) }} {{ h.label }} {{ h.count }}/{{ f.total }} 只
                  </span>
                </div>
                <div class="fa-pulse-leaders" v-if="f.leaders && f.leaders.length">
                  <span class="fa-leader-label">领涨</span>
                  <span v-for="ld in f.leaders" :key="ld.code" class="fa-leader-item">
                    {{ ld.name }} <b :class="ld.pct >= 0 ? 'pulse-pos' : 'pulse-neg'">{{ ld.pct >= 0 ? '+' : '' }}{{ fmt(ld.pct) }}%</b>
                  </span>
                </div>
              </div>
            </template>
          </template>
          <div class="fa-more" v-if="filteredPulseFindings.length > pulseShowLimit">
            <button @click="pulseShowLimit += 100">加载更多（剩余 {{ filteredPulseFindings.length - pulseShowLimit }}）</button>
          </div>
        </div>
      </template>

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
          <template v-for="(group, gidx) in groupedFindings" :key="gidx">
            <!-- 普通板块异动（无折叠） -->
            <div v-if="group.type === 'sector'" class="fa-card" v-for="(f, idx) in group.items" :key="gidx+'-'+idx"
                 :style="{ '--i': Math.min(gidx + idx, 15) }">
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
                <span v-for="(h, i) in f.hits" :key="i"
                      :class="['fa-hit', `hit-${h.type}`]"
                      :title="hitDetail(h)">
                  {{ hitIcon(h) }} {{ h.label }}
                  <span class="fa-hit-sub">{{ hitSub(h) }}</span>
                </span>
              </div>
            </div>
            <!-- TrendZen套利背离（同股折叠）：来源 monitors/trendzen_arb_monitor.py -->
            <div v-else-if="group.type === 'arb'" class="fa-card fa-card-stock" :style="{ '--i': Math.min(gidx, 15) }">
              <div class="fa-card-head" @click="toggleStockGroup(group.key)" style="cursor:pointer">
                <span class="fa-time">{{ group.latest.date }} {{ group.latest.time }}</span>
                <span class="fa-sector">{{ group.latest.name }} {{ group.latest.code }}</span>
                <span class="fa-stock-tag">🎯 套利背离</span>
                <span v-if="group.items.length > 1" class="fa-expand-hint">{{ expandedStocks[group.key] ? '收起' : `共${group.items.length}条 ▶` }}</span>
              </div>
              <div class="fa-card-meta">
                <span class="fa-chg" :class="group.latest.change_pct >= 0 ? 'pos' : 'neg'">
                  个股 {{ group.latest.change_pct >= 0 ? '+' : '' }}{{ fmt(group.latest.change_pct) }}%
                </span>
                <span class="fa-chg" :class="group.latest.bench_pct >= 0 ? 'pos' : 'neg'">
                  基准 {{ group.latest.bench_label }} {{ group.latest.bench_pct >= 0 ? '+' : '' }}{{ fmt(group.latest.bench_pct) }}%
                </span>
              </div>
              <div class="fa-hits">
                <span v-for="(h, i) in group.latest.hits" :key="i" :class="['fa-hit', 'hit-price']">
                  {{ hitIcon('arb') }} {{ h.label }}
                </span>
              </div>
              <div v-if="group.latest.reason" style="margin-top:6px;font-size:12px;line-height:1.5;opacity:.75">
                {{ group.latest.reason }}
              </div>
              <!-- 展开的历史告警 -->
              <div v-if="expandedStocks[group.key] && group.items.length > 1" class="fa-stock-history">
                <div v-for="(f, idx) in group.items.slice(1)" :key="idx" class="fa-stock-hist-item">
                  <span class="fa-time">{{ f.date }} {{ f.time }}</span>
                  <span class="fa-chg" :class="f.change_pct >= 0 ? 'pos' : 'neg'">
                    个股 {{ f.change_pct >= 0 ? '+' : '' }}{{ fmt(f.change_pct) }}%
                  </span>
                  <span class="fa-chg" :class="f.bench_pct >= 0 ? 'pos' : 'neg'">
                    基准 {{ f.bench_label }} {{ f.bench_pct >= 0 ? '+' : '' }}{{ fmt(f.bench_pct) }}%
                  </span>
                  <div v-if="f.reason" style="margin-top:4px;font-size:12px;line-height:1.5;opacity:.75">{{ f.reason }}</div>
                </div>
              </div>
            </div>
            <!-- 价格异动（同股折叠） -->
            <div v-else class="fa-card fa-card-stock" :style="{ '--i': Math.min(gidx, 15) }">
              <div class="fa-card-head" @click="toggleStockGroup(group.key)" style="cursor:pointer">
                <span class="fa-time">{{ group.latest.date }} {{ group.latest.time }}</span>
                <span class="fa-sector">{{ group.latest.name }} {{ group.latest.code }}</span>
                <span class="fa-stock-tag">📈 价格异动</span>
                <span v-if="group.items.length > 1" class="fa-expand-hint">{{ expandedStocks[group.key] ? '收起' : `共${group.items.length}条 ▶` }}</span>
              </div>
              <div class="fa-card-meta">
                <span class="fa-chg" :class="group.latest.change_pct >= 0 ? 'pos' : 'neg'">
                  {{ group.latest.change_pct >= 0 ? '+' : '' }}{{ fmt(group.latest.change_pct) }}%
                </span>
                <span class="fa-price">现价 {{ fmt(group.latest.price) }}</span>
              </div>
              <div class="fa-hits">
                <span v-for="(h, i) in group.latest.hits" :key="i"
                      :class="['fa-hit', 'hit-price']">
                  {{ hitIcon('price') }} {{ h.label }}
                </span>
              </div>
              <!-- 展开的历史异动 -->
              <div v-if="expandedStocks[group.key] && group.items.length > 1" class="fa-stock-history">
                <div v-for="(f, idx) in group.items.slice(1)" :key="idx" class="fa-stock-hist-item">
                  <span class="fa-time">{{ f.date }} {{ f.time }}</span>
                  <span class="fa-chg" :class="f.change_pct >= 0 ? 'pos' : 'neg'">
                    {{ f.change_pct >= 0 ? '+' : '' }}{{ fmt(f.change_pct) }}%
                  </span>
                  <span class="fa-price">现价 {{ fmt(f.price) }}</span>
                  <div class="fa-hits" style="margin-top:4px">
                    <span v-for="(h, i) in f.hits" :key="i" :class="['fa-hit', 'hit-price']">
                      {{ hitIcon('price') }} {{ h.label }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </template>
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
    </template>

    <div class="fa-footnote" v-if="mainTab==='fund'">
      异动判定：价量背离 / 巨量 z-score / 突变 / 连续同向 四维度。<br/>
      实时推送在交易时段每 5 分钟采集后自动触发（去重冷却 30 分钟）。可在「系统配置 → 异动检测」调整阈值。
    </div>
    <div class="fa-footnote" v-else>
      个股异动判定：板块聚集（同行业多只同时拉升/翻红/跳水）/ 涨停跌停（单纯个股拉升跳水不推）。盘中每 5 分钟采样一次，有异动才推送（同板块同类型冷却 40 分钟）。
    </div>

    <SecurityAlert />
  </div>
</template>

<script>
import { runAnomalyDetection, getAnomalyAlerts,
         getStockPulseSummary, runStockPulseDetection } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

const DIM_META = {
  divergence: { icon: '⚖️', label: '背离' },
  surge:      { icon: '💥', label: '巨量' },
  spike:      { icon: '⚡', label: '突变' },
  streak:     { icon: '🔁', label: '连续' },
  price:      { icon: '📈', label: '价格异动' },
  arb:        { icon: '🎯', label: '套利背离' }
}

// 个股异动（Stock Pulse）触发类型图标：红涨绿跌
const PULSE_ICONS = {
  cluster_surge: '🔴', cluster_turn_red: '🔴', cluster_dump: '🟢',
  limit_up: '🔴', limit_down: '🟢',
  limit_up_cluster: '🔴', limit_down_cluster: '🟢'
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
      showLimit: 100,
      expandedStocks: {},
      // 个股异动（Stock Pulse）
      mainTab: 'fund',
      pulseLoading: false,
      pulseFindings: [],
      pulseSummary: null,
      pulseFilter: 'all',
      pulseShowLimit: 100
    }
  },
  computed: {
    dims() { return Object.keys(DIM_META).map(k => ({ key: k, ...DIM_META[k] })) },
    sectorCount() { return new Set(this.findings.map(f => f.sector)).size },
    dimCount() {
      const c = {}
      this.findings.forEach(f => {
        if (f.kind === 'stock') { c.price = (c.price || 0) + 1; return }
        if (f.kind === 'arb') { c.arb = (c.arb || 0) + 1; return }
        f.hits.forEach(h => { c[h.type] = (c[h.type] || 0) + 1 })
      })
      return c
    },
    filteredFindings() {
      const list = this.filter === 'all' ? this.findings
        : this.filter === 'price'
          ? this.findings.filter(f => f.kind === 'stock')
          : this.filter === 'arb'
            ? this.findings.filter(f => f.kind === 'arb')
            : this.findings.filter(f => f.kind === 'sector' && f.hits.some(h => h.type === this.filter))
      return [...list].sort((a, b) => (a.time < b.time ? 1 : -1))
    },
    shownFindings() { return this.filteredFindings.slice(0, this.showLimit) },
    groupedFindings() {
      // 将 filteredFindings 分组：同一股票的价格异动/套利背离各自折叠
      const shown = this.shownFindings
      const groups = []
      const stockMap = new Map() // 分组key -> group index（价格异动与套利背离用不同前缀，避免同代码互相吞并）
      for (const f of shown) {
        if (f.kind === 'stock' || f.kind === 'arb') {
          const code = (f.kind === 'arb' ? 'arb:' : '') + (f.code || f.name)
          if (stockMap.has(code)) {
            const gidx = stockMap.get(code)
            groups[gidx].items.push(f)
          } else {
            stockMap.set(code, groups.length)
            groups.push({ type: f.kind, key: code, items: [f], latest: f })
          }
        } else {
          groups.push({ type: 'sector', items: [f] })
        }
      }
      // 每个stock/arb group按时间倒序，latest是最新的
      for (const g of groups) {
        if (g.type === 'stock' || g.type === 'arb') {
          g.items.sort((a, b) => (a.time < b.time ? 1 : -1))
          g.latest = g.items[0]
        }
      }
      return groups
    },
    // 个股异动（Stock Pulse）：按类型过滤
    filteredPulseFindings() {
      const f = this.pulseFilter
      let list = this.pulseFindings
      if (f === 'sector') list = list.filter(x => x.kind === 'pulse_sector')
      else if (f === 'limit') list = list.filter(x => x.kind === 'pulse_limit_cluster')
      return [...list].sort((a, b) => (a.time < b.time ? 1 : -1))
    },
    // 个股异动分组：每个 finding 一张卡（板块聚集 / 涨跌停聚集）
    shownPulseGroups() {
      const shown = this.filteredPulseFindings.slice(0, this.pulseShowLimit)
      return shown.map(f => ({ type: f.kind, key: `${f.kind}:${f.level}:${f.sector}:${f.time}`, items: [f] }))
    }
  },
  async mounted() {
    window.addEventListener('auth-required', this.onAuthRequired)
    window.addEventListener('auth-login-success', this.onAuthLogin)
    window.addEventListener('ws-stock-pulse', this.onPulsePush)
    this._autoTimer = setInterval(this.autoRefresh, 60000)  // 60s 自动刷新，免手动
    // 支持首页速览带 tab 参数直达：/flow-alert?tab=pulse → 个股异动
    if (this.$route.query.tab === 'pulse') this.switchMainTab('pulse')
    else await this.runDetect()
  },
  beforeUnmount() {
    window.removeEventListener('auth-required', this.onAuthRequired)
    window.removeEventListener('auth-login-success', this.onAuthLogin)
    window.removeEventListener('ws-stock-pulse', this.onPulsePush)
    if (this._autoTimer) clearInterval(this._autoTimer)
  },
  methods: {
    goBack() { this.$router.push('/') },
    promptLogin() { window.dispatchEvent(new CustomEvent('auth-request-login')) },
    onAuthRequired() { this.needsAuth = true; this.loading = false },
    onAuthLogin() { if (this.needsAuth) { this.needsAuth = false; this.runDetect() } },
    toggleStockGroup(key) {
      this.expandedStocks[key] = !this.expandedStocks[key]
      // 触发Vue响应式更新
      this.expandedStocks = { ...this.expandedStocks }
    },
    fmt(v) { return (v == null || isNaN(v)) ? '--' : Number(v).toFixed(2) },
    isReversal(h) { return !!(h && h.sub && String(h.sub).startsWith('reversal')) },
    hitIcon(t) {
      // 反转按方向上色：V底(流出减缓/转流入)=红，V顶(流入减缓/转流出)=绿；不再用闪电⚡
      if (t && typeof t === 'object') {
        if (this.isReversal(t)) return t.sub === 'reversal_up' ? '🔴' : '🟢'
        t = t.type
      }
      return (DIM_META[t] || {}).icon || '•'
    },
    hitDetail(h) {
      if (this.isReversal(h)) return h.detail || this.reversalDesc(h)
      if (h.type === 'surge') return h.sample_sufficient ? `z=${h.z}，历史上榜 ${h.count} 次` : `绝对量级判定（样本 ${h.count || 0} 次）`
      if (h.type === 'spike') return `Δ${h.delta} 亿（vs ${h.prev_time}）`
      if (h.type === 'streak') return `持续 ${h.streak} 段≈${h.minutes}分钟，累计增量 ${h.cum_delta} 亿`
      if (h.type === 'divergence') return `5分钟 价${h.d_change_pct >= 0 ? '+' : ''}${h.d_change_pct}% / 量${h.d_net_flow > 0 ? '+' : ''}${h.d_net_flow}亿`
      return ''
    },
    hitSub(h) {
      if (this.isReversal(h)) {
        // 优先使用后端提供的detail（新格式：距资金流出最低点上升xxx%）
        if (h.detail) {
          // detail格式: "距资金流出最低点上升xxx%（最低 x.xx亿 → 现 x.xx亿）"
          // 提取百分比部分显示
          const match = h.detail.match(/上升(\d+)%|下降(\d+)%/)
          if (match) {
            const pct = match[1] || match[2]
            const direction = match[1] ? '回升' : '回落'
            return `${direction}${pct}%`
          }
          return h.detail
        }
        // 兜底：旧格式
        const avg = Number(h.avg_delta), cur = Number(h.cur_delta), isUp = h.sub === 'reversal_up'
        const sameDir = isUp ? cur <= 0 : cur >= 0
        if (avg > 0 && sameDir) return `减缓${Math.round((avg - Math.abs(cur)) / avg * 100)}%`
        return isUp ? '转流入' : '转流出'
      }
      if (h.type === 'surge') return h.z != null ? `z=${h.z}` : `${h.net_flow}亿`
      if (h.type === 'spike') return `${h.delta > 0 ? '+' : ''}${h.delta}亿`
      if (h.type === 'streak') return `${h.minutes}分`
      if (h.type === 'divergence') return `5分钟 价${h.d_change_pct >= 0 ? '+' : ''}${h.d_change_pct}%/量${h.d_net_flow > 0 ? '+' : ''}${h.d_net_flow}亿`
      return ''
    },
    reversalDesc(h) {
      // 后端 detail 缺失时的兜底（旧数据）
      const avg = Number(h.avg_delta), cur = Number(h.cur_delta), isUp = h.sub === 'reversal_up'
      const tw = isUp ? '流出' : '流入'
      if (!(avg > 0)) return h.label || ''
      const sameDir = isUp ? cur <= 0 : cur >= 0
      if (sameDir) return `${tw}减缓${Math.round((avg - Math.abs(cur)) / avg * 100)}%：之前约${avg}亿/5min → 现在${Math.abs(cur)}亿/5min`
      const opp = isUp ? '流入' : '流出'
      return `${tw}转${opp}：之前约${avg}亿/5min${tw} → 现在${Math.abs(cur)}亿/5min${opp}`
    },
    switchView(v) {
      this.view = v
      if (v === 'pushed' && !this.pushed.length) this.loadPushed()
    },
    // ==================== 个股异动（Stock Pulse） ====================
    autoRefresh() {
      // 60s 静默自刷新（后端重放本地快照，开销小）；页面不可见/未登录时跳过
      if (this.needsAuth || document.hidden) return
      if (this.mainTab === 'fund') {
        if (this.loading) return
        if (this.view === 'pushed') { this.loadPushed(); return }
        this.runDetect(true)
      } else {
        if (this.pulseLoading) return
        this.runPulseDetect(true)
      }
    },
    switchMainTab(t) {
      this.mainTab = t
      if (t === 'pulse') {
        this.runPulseDetect()
      }
    },
    async loadPulseSummary() {
      try {
        const res = await getStockPulseSummary()
        if (res.success) this.pulseSummary = res.data
      } catch (e) { /* 401 已处理 */ }
    },
    async runPulseDetect(silent = false) {
      if (!silent) this.pulseLoading = true
      try {
        const res = await runStockPulseDetection()
        if (res.success) {
          this.pulseFindings = res.data || []
          if (res.summary) this.pulseSummary = res.summary
          else this.loadPulseSummary()
        }
      } catch (e) { /* 401 已处理 */ }
      finally { if (!silent) this.pulseLoading = false }
    },
    onPulsePush() {
      // WebSocket 收到新一轮推送：静默刷新温度与命中列表
      if (this.mainTab !== 'pulse') return
      this.loadPulseSummary()
      this.runPulseDetect(true)
    },
    pulseSectorLabel(f) {
      if (f.level === 'l2' && f.l1 && f.l1 !== f.sector) return `${f.l1}·${f.sector}`
      return f.sector
    },
    pulseHitIcon(type) { return PULSE_ICONS[type] || '•' },
    async onDateChange() {
      this.showLimit = 100
      if (this.view === 'detect') this.runDetect()
      else { this.pushed = []; this.loadPushed() }
    },
    async runDetect(silent = false) {
      // silent=true：自动刷新用，不清列表、不亮加载动画，静默替换数据
      if (!silent) { this.loading = true; this.findings = [] }
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
        // 同时测试飞书+微信推送
        const { default: apiService } = await import('./services/apiService')
        const res = await apiService.testPushNotification()
        const feishuOk = res.feishu === true
        const wechatOk = res.wechat === true

        // 桌面通知1: 模拟资金异动格式
        const n1 = new Notification('🔴 半导体回调吸筹 净流入+99.14亿', {
          body: '回调吸筹、突变｜+0.74% 龙头有研硅',
          icon: 'https://pic.0vk.top/%E8%82%A1%E7%A5%A8.png',
          tag: 'anomaly-test',
          requireInteraction: true
        })
        n1.onclick = () => { window.focus(); n1.close() }

        // 桌面通知2: 模拟价格异动格式
        setTimeout(() => {
          const n2 = new Notification('🟢 长电科技累计大跌 -5.31% -5.31%', {
            body: '现价97.25｜累计大跌 -5.31%',
            icon: 'https://pic.0vk.top/%E8%82%A1%E7%A5%A8.png',
            tag: 'price-test',
            requireInteraction: true
          })
          n2.onclick = () => { window.focus(); n2.close() }
        }, 800)

        // 播放声音
        const a = new Audio('/assets/sounds/important.mp3'); a.volume = 0.5
        a.play().catch(() => {})

        const channels = []
        if (feishuOk) channels.push('飞书✅')
        else channels.push('飞书❌')
        if (wechatOk) channels.push('微信✅')
        else channels.push('微信❌')
        alert(`推送测试结果：\n${channels.join('  ')}\n桌面通知✅\n\n请检查手机是否收到飞书/微信消息`)
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
.fa-header { display: flex; align-items: center; gap: 16px; margin-bottom: 16px; padding-right: 290px; /* 避让右上角固定北京时间+登录入口 */ }
.fa-back-button {
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b); color: #e0e6f0;
  border: 1px solid #4a5a7b; border-radius: 4px; padding: 8px 14px; cursor: pointer; font-size: 14px;
}
.fa-header h1 { font-size: 22px; font-weight: 600; margin: 0; }
/* 主 Tab 紧跟标题放在左侧；右侧按钮组 margin-left:auto 推到右边 */
.fa-header .fa-header-right { margin-left: auto; }
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
/* 价格异动(个股) */
.chip-price.active { background: #52c41a; border-color: #73d13d; }
.hit-price { background: rgba(82,196,26,.18); border-color: rgba(82,196,26,.5); }
.fa-card-stock { border-left-color: #52c41a; }
.fa-stock-tag { font-size: 11px; color: #52c41a; border: 1px solid #52c41a; border-radius: 10px; padding: 1px 8px; }
.fa-price { color: #c0cce0; }
.fa-expand-hint { font-size: 11px; color: #8ba4c7; border: 1px solid rgba(139,164,199,.3); border-radius: 10px; padding: 1px 8px; cursor: pointer; transition: all .2s; }
.fa-expand-hint:hover { color: #fff; border-color: #52c41a; }
.fa-stock-history { margin-top: 8px; padding-top: 8px; border-top: 1px dashed rgba(82,196,26,.3); }
.fa-stock-hist-item { padding: 6px 0; display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
.fa-stock-hist-item + .fa-stock-hist-item { border-top: 1px solid rgba(255,255,255,.04); }
.fa-more { text-align: center; margin-top: 10px; }
.fa-more button { background: #1a2236; color: #8ba4c7; border: 1px solid rgba(148,163,184,.25); border-radius: 4px; padding: 8px 20px; cursor: pointer; font-size: 13px; }
.fa-footnote { text-align: center; margin-top: 24px; font-size: 11px; color: #6a7a99; line-height: 1.8; }

/* ===== 个股异动（Stock Pulse）===== */
.fa-main-tabs { display: flex; gap: 4px; background: rgba(255,255,255,.06); border-radius: 6px; padding: 3px; }
.fa-main-tab { background: transparent; border: none; color: #8ba4c7; padding: 7px 16px; border-radius: 4px; cursor: pointer; font-size: 14px; transition: all .2s; }
.fa-main-tab.active { background: linear-gradient(135deg, #3a4a6b, #2a3a5b); color: #fff; }
.fa-card-pulse { border-left-color: #ff4d4f; }
.fa-pulse-tag { font-size: 11px; color: #ff7875; border: 1px solid #ff7875; border-radius: 10px; padding: 1px 8px; }
.hit-pulse-pos { background: rgba(255,77,79,.18); border-color: rgba(255,120,117,.5); }
.hit-pulse-neg { background: rgba(19,209,124,.16); border-color: rgba(19,209,124,.5); }
.pulse-pos { color: #ff4d4f; }
.pulse-neg { color: #13d17c; }
.fa-pulse-summary { margin-bottom: 14px; }
/* ===== 板块聚集活动卡片（替代原涨跌家数温度卡） ===== */
.fa-pulse-activity { background: rgba(26,35,53,.6); border: 1px solid rgba(58,74,107,.5); border-radius: 8px; padding: 10px 14px; font-size: 13px; margin-bottom: 14px; }
.fa-activity-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.fa-activity-title { font-weight: 600; color: #fff; }
.fa-activity-time { font-size: 11px; color: #6a7a99; }
.fa-activity-counts { display: flex; gap: 16px; font-size: 14px; font-weight: 700; margin-bottom: 6px; }
.act-pos { color: #ff7875; }
.act-neg { color: #13d17c; }
.fa-activity-empty { color: #6a7a99; font-size: 12px; padding: 2px 0; }
.fa-rank-item em { font-style: normal; color: #8ba4c7; font-size: 11px; margin-left: 2px; }
.fa-pulse-rank { background: rgba(26,35,53,.6); border: 1px solid rgba(58,74,107,.5); border-radius: 8px; padding: 10px 14px; font-size: 13px; }
.fa-rank-line { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 3px 0; }
.fa-rank-tag { font-size: 12px; border-radius: 10px; padding: 1px 10px; }
.rank-pos { color: #ff7875; border: 1px solid rgba(255,120,117,.5); background: rgba(255,77,79,.12); }
.rank-neg { color: #13d17c; border: 1px solid rgba(19,209,124,.5); background: rgba(19,209,124,.1); }
.fa-rank-item { opacity: .92; }
.fa-rank-item b { font-weight: 600; }
.fa-rank-time { font-size: 11px; color: #6a7a99; margin-top: 4px; }
.fa-pulse-leaders { margin-top: 8px; padding-top: 6px; border-top: 1px dashed rgba(255,120,117,.25); display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; color: #c0cce0; }
.fa-leader-label { color: #8ba4c7; }

/* ===== 移动端适配（原先完全没有 @media）===== */
@media (max-width: 768px) {
  .fa-page { padding: 12px; }
  /* 清除桌面端 .fa-header 的 padding-right:110px；标题与按钮组换行 */
  .fa-header { padding-right: 0; flex-wrap: wrap; gap: 10px; }
  .fa-header h1 { font-size: 18px; }
  .fa-header-right { width: 100%; display: flex; gap: 8px; }
  .fa-header-right .fa-run-btn,
  .fa-header-right .fa-test-btn { flex: 1; margin-left: 0; }
  /* 汇总说明文字另起一行，不再挤在日期后 */
  .fa-snapshot span { display: block; margin-left: 0; margin-top: 4px; }
  /* 6 个统计卡 3 列 × 2 行 */
  .fa-stats { gap: 8px; }
  .fa-stat { flex: 1 1 30%; min-width: 0; padding: 10px 6px; }
  .fa-stat-num { font-size: 20px; }
  /* 卡片头部允许换行，板块名超长省略 */
  .fa-card-head { flex-wrap: wrap; gap: 6px 10px; }
  .fa-sector { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .fa-card-meta { gap: 8px 16px; }
}
</style>
