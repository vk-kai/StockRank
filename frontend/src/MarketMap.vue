<template>
  <div class="market-map-page">
    <header class="mm-header">
      <div class="mm-header-left">
        <button @click="goBack" class="mm-back-button">← 返回</button>
        <h1>🗺️ A股大盘云图</h1>
        <div class="mm-search-wrap">
          <input
            class="mm-search"
            v-model="searchQuery"
            @input="onSearchInput"
            @keyup.enter="onSearchInput"
            placeholder="🔍 搜索个股 / 行业，高亮定位"
          />
          <span class="mm-search-count" v-show="searchQuery">{{ matchCount ? matchCount + ' 项' : '无匹配' }}</span>
        </div>
      </div>
      <div class="mm-header-right">
        <span class="mm-stats" v-if="totalSectors">
          {{ totalSectors }} 一级行业 · {{ totalStocks }} 只个股
        </span>
        <span class="mm-update" v-if="cacheTime">行业库：{{ cacheTime }}</span>
        <button @click="refreshCache" class="mm-cache-btn" :disabled="cacheLoading">
          {{ cacheLoading ? '更新中...' : '🔄 行业库' }}
        </button>
        <button @click="fetchData(true)" class="mm-refresh-btn" :disabled="refreshing">
          <span class="mm-refresh-spin" :class="{ on: refreshing }">↻</span> 刷新行情
        </button>
      </div>
    </header>

    <div class="mm-chart-wrapper" ref="wrapperEl">
      <canvas
        ref="canvasEl"
        class="mm-canvas"
        @wheel.prevent="onWheel"
        @mousedown="onMouseDown"
        @mousemove="onMouseMove"
        @mouseup="onMouseUp"
        @mouseleave="onMouseLeave"
        @dblclick="onDblClick"
      ></canvas>
      <div
        ref="tooltipEl"
        class="mm-tooltip"
        v-show="tooltip.visible"
        :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
      >
        <div class="mm-tooltip-name">
          {{ tooltip.name }}
          <span class="mm-tooltip-code" v-if="tooltip.code">{{ tooltip.code }}</span>
        </div>
        <div class="mm-tooltip-row">
          <span class="mm-tooltip-label">涨跌幅</span>
          <span class="mm-tooltip-val" :class="tooltip.cls">{{ tooltip.change }}</span>
        </div>
        <div class="mm-tooltip-row">
          <span class="mm-tooltip-label">市值</span>
          <span class="mm-tooltip-val">{{ tooltip.marketCap }}</span>
        </div>
        <div class="mm-tooltip-row">
          <span class="mm-tooltip-label">市盈率</span>
          <span class="mm-tooltip-val">{{ tooltip.pe }}</span>
        </div>
      </div>
      <div class="mm-hint">滚轮缩放 · 拖动平移 · 双击个股看雪球</div>
      <div class="mm-changes-loading" v-show="changesLoading && hasData">
        <span class="mm-cl-dot"></span> 实时涨跌加载中…
      </div>
      <div class="mm-filter-badge" v-if="filterBadge" @click="clearFilter" title="点击清除筛选">
        <span>已筛选：{{ filterBadge.desc }}（{{ filterBadge.count }} 只）</span>
        <span class="mm-filter-clear">✕</span>
      </div>
    </div>

    <div class="mm-footer">
      <span class="mm-footer-text">行业分类：东方财富(缓存) · 实时涨跌：新浪财经 · 面积=总市值，颜色=涨跌幅（红涨绿跌）· 仅供投资参考</span>
      <div class="mm-legend">
        <button
          class="mm-limit-btn up"
          :class="{ active: activeLegend === 'limit_up' }"
          @click="toggleFilter('limit_up')"
          title="只看涨停，再点复原"
        >涨停</button>
        <button
          class="mm-limit-btn down"
          :class="{ active: activeLegend === 'limit_down' }"
          @click="toggleFilter('limit_down')"
          title="只看跌停，再点复原"
        >跌停</button>
        <div class="mm-legend-bar">
          <div
            v-for="(s, i) in legendSteps"
            :key="i"
            class="mm-legend-step"
            :class="{ active: activeLegend === s.value }"
            :style="{ background: s.color }"
            :title="s.title"
            @click="toggleFilter(s.value)"
          >{{ s.label }}</div>
        </div>
      </div>
    </div>
    <SecurityAlert />
  </div>
</template>

<script>
import { getMarketMap, getMarketMapStructure, refreshMarketMapCache } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

// 配色色阶：涨跌幅(%) → [R,G,B]。跌=绿、涨=红、0%=灰。
// 颜色按参考云图逐块读真实涨跌幅锚点后插值得到（红：+0.33/+1.51/+2.88%、绿：-0.87/-2.04/-3.97%），
// 渐变在 0% 附近较陡，超过 ±4% 饱和到两端满色（亮绿/亮红）；interpColor 把 change 钳制在 ±4。
const COLOR_STOPS = [
  [-4, [59, 204, 95]],
  [-3, [56, 170, 87]],
  [-2, [53, 136, 80]],
  [-1, [58, 101, 79]],
  [0, [76, 68, 84]],
  [1, [122, 68, 81]],
  [2, [165, 64, 75]],
  [3, [202, 58, 69]],
  [4, [243, 47, 61]]
]

function interpColor(change) {
  const c = Math.max(-4, Math.min(4, change)) // 超过 ±4% 饱和到两端满色
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

// 筛选灰显色（未命中个股）与整板块变暗面纱（某行业一只都没命中时叠加）
const DIM_COLOR = '#1b2330'
const VEIL_COLOR = 'rgba(8,14,24,0.78)'

// 按股票代码前缀判断涨跌停限幅(%)：主板 10 / 创业板·科创板 20 / 北交所 30
function limitThreshold(code) {
  const m = String(code || '').match(/(\d{6})/)
  const d = m ? m[1] : ''
  if (!d) return 10
  if (d.startsWith('688') || d.startsWith('300') || d.startsWith('301')) return 20
  if (d[0] === '8' || d[0] === '4') return 30
  return 10
}

// 个股是否命中当前筛选。active 取值：null(无) / 数值 -4..4(色块区间) / 'limit_up' / 'limit_down'
// 区间为半开 (L-1, L]，两极延伸：-4 → change≤-4；+4 → change>3
function inFilter(change, code, active) {
  if (active == null) return true
  if (typeof change !== 'number' || isNaN(change)) return false
  if (active === 'limit_up') return change >= limitThreshold(code) - 0.1
  if (active === 'limit_down') return change <= -(limitThreshold(code) - 0.1)
  const L = active
  if (L <= -4) return change <= -4
  if (L >= 4) return change > 3
  return change > (L - 1) && change <= L
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const fmtPct = c => (c >= 0 ? '+' : '') + c + '%'
// 市值格式化：元 → 万亿/亿/万
const fmtCap = v => {
  if (!v || v <= 0) return '-'
  const yi = v / 1e8
  if (yi >= 10000) return (yi / 10000).toFixed(2) + '万亿'
  if (yi >= 100) return yi.toFixed(0) + '亿'
  if (yi >= 1) return yi.toFixed(1) + '亿'
  return (v / 1e4).toFixed(0) + '万'
}
// 市盈率格式化：负值=亏损，无数据=-
const fmtPE = pe => {
  if (pe == null || pe === '' || isNaN(pe)) return '-'
  if (pe < 0) return '亏损'
  return Number(pe).toFixed(1)
}

// 股票代码 → 雪球个股页：https://xueqiu.com/S/SH601288 （交易所前缀大写 + 6 位代码）
function xueqiuUrl(code) {
  if (!code) return ''
  const c = String(code).trim()
  let m = c.match(/^(sh|sz|bj)(\d{6})$/i)
  if (m) return `https://xueqiu.com/S/${m[1].toUpperCase()}${m[2]}`
  m = c.match(/(\d{6})/)
  if (m) {
    const d = m[1]
    const prefix = d[0] === '6' ? 'SH' : (d[0] === '8' || d[0] === '4') ? 'BJ' : 'SZ'
    return `https://xueqiu.com/S/${prefix}${d}`
  }
  return `https://xueqiu.com/S/${c.toUpperCase()}`
}

// Squarified Treemap（Bruls 等人算法）：把 items 按 value 比例铺满 rect，
// 尽量让每个矩形接近正方形。直接给每个 item 写入 x/y/w/h（布局坐标）。
function squarify(items, x, y, w, h) {
  if (!items.length || w <= 0 || h <= 0) return
  const positives = items.filter(it => it.value > 0)
  if (!positives.length) return
  const total = positives.reduce((s, it) => s + it.value, 0)
  if (total <= 0) return
  const scale = (w * h) / total
  let curX = x, curY = y, curW = w, curH = h
  // 不在此处重排：尊重调用方传入的顺序（buildLayout 已按市值降序排好 L1/L2/个股）
  let queue = positives.map(it => ({ a: it.value * scale, ref: it }))

  const worst = (arr, len) => {
    let sum = 0, mx = -Infinity, mn = Infinity
    for (const a of arr) { sum += a; if (a > mx) mx = a; if (a < mn) mn = a }
    if (mn <= 0) return Infinity
    const l2 = len * len
    return Math.max((l2 * mx) / (sum * sum), (sum * sum) / (l2 * mn))
  }

  while (queue.length && curW > 0 && curH > 0) {
    const short = Math.min(curW, curH)
    let row = [queue[0]]
    let rowWorst = worst(row.map(t => t.a), short)
    let i = 1
    while (i < queue.length) {
      const tw = worst(row.concat(queue[i]).map(t => t.a), short)
      if (tw <= rowWorst) { row = row.concat(queue[i]); rowWorst = tw; i++ }
      else break
    }
    const rowSum = row.reduce((s, t) => s + t.a, 0)
    if (curW >= curH) {
      const stripW = rowSum / curH
      let oy = curY
      for (const t of row) {
        const ih = t.a / stripW
        t.ref.x = curX; t.ref.y = oy; t.ref.w = stripW; t.ref.h = ih
        oy += ih
      }
      curX += stripW; curW -= stripW
    } else {
      const stripH = rowSum / curW
      let ox = curX
      for (const t of row) {
        const iw = t.a / stripH
        t.ref.x = ox; t.ref.y = curY; t.ref.w = iw; t.ref.h = stripH
        ox += iw
      }
      curY += stripH; curH -= stripH
    }
    queue = queue.slice(i)
  }
}

export default {
  name: 'MarketMap',
  components: { SecurityAlert },
  data() {
    return {
      cacheLoading: false,
      refreshing: false,
      changesLoading: false,
      tree: [],
      totalSectors: 0,
      totalStocks: 0,
      cacheTime: '',
      tooltip: { visible: false, name: '', code: '', change: '', cls: '', marketCap: '', pe: '', x: 0, y: 0 },
      searchQuery: '',
      matchCount: 0,
      activeLegend: null  // null=无筛选 | 数值-4..4(色块) | 'limit_up' | 'limit_down'
    }
  },
  computed: {
    hasData() {
      return this.tree.length > 0
    },
    // 图例：与 COLOR_STOPS 一一对应，每块标注涨跌幅阈值（左=跌/绿 → 中=0/灰 → 右=涨/红）
    legendSteps() {
      const labels = ['-4%', '-3%', '-2%', '-1%', '0%', '1%', '2%', '3%', '4%']
      const titles = ['跌幅 ≤ -4%', '-4% ~ -3%', '-3% ~ -2%', '-2% ~ -1%', '-1% ~ 0%', '0% ~ 1%', '1% ~ 2%', '2% ~ 3%', '涨幅 > 3%']
      return COLOR_STOPS.map(([v, rgb], i) => ({
        value: v,
        label: labels[i],
        title: '点击只看 ' + titles[i] + '，再点复原',
        color: `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`
      }))
    },
    // 当前筛选状态条：activeLegend 非空时返回 {desc, count}，供顶部徽标展示
    filterBadge() {
      const a = this.activeLegend
      if (a == null) return null
      let count = 0
      for (const s of this.tree) {
        for (const l2 of (s.children || [])) {
          for (const st of (l2.children || [])) {
            if (inFilter(st.change, st.code, a)) count++
          }
        }
      }
      let desc
      if (a === 'limit_up') desc = '涨停'
      else if (a === 'limit_down') desc = '跌停'
      else if (a <= -4) desc = '跌幅 ≤ -4%'
      else if (a >= 4) desc = '涨幅 > 3%'
      else desc = `${a - 1}% ~ ${a}%`
      return { desc, count }
    }
  },
  async mounted() {
    // 非响应式实例属性（频繁变化的缩放/布局，不放 data 避免响应式开销）
    this.view = { k: 1, tx: 0, ty: 0 }
    this.layout = null
    this.cssW = 0
    this.cssH = 0
    this.dpr = window.devicePixelRatio || 1
    this.dragging = false
    this.lastX = 0
    this.lastY = 0
    this._raf = 0
    this._hlUntil = 0      // 搜索高亮截止时间戳(ms)
    this._hlTimer = null   // 高亮5秒后自动清除的定时器
    this._matches = null   // { stocks:Set(code), l1s:Set(name), l2s:Set(name) }

    this.syncSize()
    this.ro = new ResizeObserver(() => this.onResize())
    if (this.$refs.wrapperEl) this.ro.observe(this.$refs.wrapperEl)

    await this.fetchData(true)
    this.timer = setInterval(() => this.fetchData(false), 30000)
  },
  beforeUnmount() {
    clearInterval(this.timer)
    if (this._raf) cancelAnimationFrame(this._raf)
    if (this._hlTimer) clearTimeout(this._hlTimer)
    if (this.ro) this.ro.disconnect()
  },
  methods: {
    goBack() {
      this.$router.push('/')
    },

    // 图例筛选：点击同一项复原，点击不同项切换；同一时刻仅一个生效
    toggleFilter(v) {
      this.activeLegend = (this.activeLegend === v) ? null : v
      this.render()
    },
    clearFilter() {
      if (this.activeLegend == null) return
      this.activeLegend = null
      this.render()
    },

    // 搜索：模糊匹配个股(名称/代码)与行业(一/二级)，命中项在云图上高亮5秒(醒目黄框)
    onSearchInput() {
      if (!this.layout) { this.matchCount = 0; return }
      const m = this.computeMatches(this.searchQuery)
      this._matches = m
      this.matchCount = m ? (m.stocks.size + m.l1s.size + m.l2s.size) : 0
      if (m) {
        this._hlUntil = Date.now() + 5000
        this.view = { k: 1, tx: 0, ty: 0 }   // 复位到全图，确保高亮落在视野内
        if (this._hlTimer) clearTimeout(this._hlTimer)
        this._hlTimer = setTimeout(() => { this._hlUntil = 0; this.render() }, 5000)
      } else {
        this._hlUntil = 0
        if (this._hlTimer) clearTimeout(this._hlTimer)
      }
      this.render()
    },
    computeMatches(q) {
      const ql = (q || '').trim().toLowerCase()
      if (!ql) return null
      const stocks = new Set(), l1s = new Set(), l2s = new Set()
      for (const s of this.layout) {
        if (s.name.toLowerCase().includes(ql)) l1s.add(s.name)
        for (const l2 of s.children) {
          if (l2.name.toLowerCase().includes(ql)) l2s.add(l2.name)
          for (const st of l2.children) {
            if (st.name.toLowerCase().includes(ql) || (st.code || '').toLowerCase().includes(ql)) stocks.add(st.code)
          }
        }
      }
      if (!stocks.size && !l1s.size && !l2s.size) return null
      return { stocks, l1s, l2s }
    },
    async fetchData(showLoading) {
      if (this.refreshing) return
      this.refreshing = true
      try {
        // 首屏两阶段：先读行业+市值缓存秒开灰色(0%)云图，再请求实时涨跌幅二次上色
        if (showLoading && !this.hasData) {
          try {
            const skel = await getMarketMapStructure()
            if (skel.success) {
              this.applyData(skel.data)
              this.changesLoading = true // 灰图已出，实时涨跌幅加载中
            }
          } catch (e) { /* 骨架失败则忽略，继续走全量 */ }
        }
        const res = await getMarketMap()
        if (res.success) this.applyData(res.data)
      } catch (e) {
        console.error('获取大盘云图失败', e)
      } finally {
        this.changesLoading = false
        this.refreshing = false
      }
    },
    applyData(data) {
      this.tree = data.tree
      this.totalSectors = data.total_sectors
      this.totalStocks = data.total_stocks
      this.cacheTime = data.cache_time || ''
      this.$nextTick(() => { this.buildLayout(); this.render() })
    },
    async refreshCache() {
      this.cacheLoading = true
      try {
        const res = await refreshMarketMapCache()
        if (res.success) await this.fetchData(true)
      } catch (e) {
        console.error('刷新行业库失败', e)
      } finally {
        this.cacheLoading = false
      }
    },

    onResize() {
      this.syncSize()
      this.buildLayout()
      this.view = { k: 1, tx: 0, ty: 0 } // 容器尺寸变化后重置缩放
      this.render()
    },
    syncSize() {
      const wrap = this.$refs.wrapperEl
      const canvas = this.$refs.canvasEl
      if (!wrap || !canvas) return
      // 用容器内容区尺寸算布局，并显式设置 canvas 显示尺寸，
      // 保证 布局坐标 == 屏幕可用面积，treemap 正好铺满、不会溢出屏幕
      const pad = 4
      const w = Math.max(0, wrap.clientWidth - pad * 2)
      const h = Math.max(0, wrap.clientHeight - pad * 2)
      this.cssW = w
      this.cssH = h
      this.dpr = window.devicePixelRatio || 1
      canvas.style.width = w + 'px'
      canvas.style.height = h + 'px'
      canvas.width = Math.round(w * this.dpr)
      canvas.height = Math.round(h * this.dpr)
    },

    // 三级嵌套布局：申万一级 → 申万二级 → 个股，每级顶部留一条标题条
    buildLayout() {
      if (!this.tree.length || this.cssW <= 0) { this.layout = null; return }
      const sectors = this.tree.map(l1 => ({
        name: l1.name, change: l1.change, value: l1.value || 0,
        headerH: 0,
        children: (l1.children || []).map(l2 => ({
          name: l2.name, change: l2.change, value: l2.value || 0,
          headerH: 0,
          children: (l2.children || []).map(s => ({
            name: s.name, code: s.code, change: s.change, value: s.value || 0, pe: s.pe,
            color: interpColor(s.change)
          }))
        }))
      }))
      sectors.sort((a, b) => b.value - a.value)
      for (const s of sectors) {
        s.children.sort((a, b) => b.value - a.value)
        for (const l2 of s.children) l2.children.sort((a, b) => b.value - a.value)
      }

      // 顶部留 6px 边距，避免最上面一级行业的标题被画布上沿截断
      squarify(sectors, 0, 6, this.cssW, this.cssH - 6)
      for (const s of sectors) {
        s.headerH = s.h > 26 ? Math.min(18, s.h * 0.35) : 0
        squarify(s.children, s.x, s.y + s.headerH, s.w, s.h - s.headerH)
        for (const l2 of s.children) {
          l2.headerH = l2.h > 22 ? Math.min(13, l2.h * 0.3) : 0
          squarify(l2.children, l2.x, l2.y + l2.headerH, l2.w, l2.h - l2.headerH)
        }
      }
      this.layout = sectors
    },

    render() {
      const canvas = this.$refs.canvasEl
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      const dpr = this.dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.fillStyle = '#0a1220'
      ctx.fillRect(0, 0, this.cssW, this.cssH)
      if (!this.layout) return

      const active = this.activeLegend
      const { k, tx, ty } = this.view
      const cw = this.cssW, ch = this.cssH
      ctx.lineWidth = 1
      ctx.strokeStyle = '#070b13'

      for (const s of this.layout) {
        // 一级 sector 视口剔除：整个板块在视口外则跳过其全部子级
        const sx = s.x * k + tx, sy = s.y * k + ty, sw = s.w * k, sh = s.h * k
        if (sx >= cw || sx + sw <= 0 || sy >= ch || sy + sh <= 0) continue
        let sectorHasMatch = false  // 本板块是否有命中个股（无则整块变暗）
        for (const l2 of s.children) {
          const lx = l2.x * k + tx, ly = l2.y * k + ty, lw = l2.w * k, lh = l2.h * k
          if (lx >= cw || lx + lw <= 0 || ly >= ch || ly + lh <= 0) continue
          // 个股
          for (const st of l2.children) {
            const x = st.x * k + tx, y = st.y * k + ty, w = st.w * k, h = st.h * k
            if (w < 0.5 || h < 0.5) continue
            if (x >= cw || x + w <= 0 || y >= ch || y + h <= 0) continue
            const matched = (active == null) || inFilter(st.change, st.code, active)
            if (matched) sectorHasMatch = true
            ctx.fillStyle = matched ? st.color : DIM_COLOR
            ctx.fillRect(x, y, w, h)
            // 个股间隙：描边贴边(内缩0)，相邻个股共用1条1px细缝（原内缩0.5时各画各的、拼成2px）。
            // 行业L1(2.5px)/二级L2(1.5px)板块边框在下方单独描边，缝隙不受影响。
            if (w >= 2.5 && h >= 2.5) ctx.strokeRect(x, y, w, h)
            // 未命中(灰显)的个股不画文字标签，突出命中的
            if (matched) {
              if (w >= 50 && h >= 26) this.drawStockLabel(ctx, st.name, st.change, x, y, w, h, true)
              else if (w >= 32 && h >= 12) this.drawStockLabel(ctx, st.name, st.change, x, y, w, h, false)
            }
          }
          // 二级标题条
          if (l2.headerH > 0) {
            const hh = l2.headerH * k
            ctx.fillStyle = '#171f2e'
            ctx.fillRect(lx, ly, lw, hh)
            this.drawHeaderText(ctx, `${l2.name}  ${fmtPct(l2.change)}`, lx + 5, ly, lw, hh, clamp(hh * 0.6, 9, 13))
          }
          ctx.lineWidth = 1.5
          ctx.strokeStyle = '#05080f'
          ctx.strokeRect(lx + 0.75, ly + 0.75, lw - 1.5, lh - 1.5)
          ctx.lineWidth = 1
          ctx.strokeStyle = '#070b13'
        }
        // 一级标题条 + 边框
        if (s.headerH > 0) {
          const hh = s.headerH * k
          ctx.fillStyle = '#10151f'
          ctx.fillRect(sx, sy, sw, hh)
          this.drawHeaderText(ctx, `${s.name}    ${fmtPct(s.change)}`, sx + 8, sy, sw, hh, clamp(hh * 0.72, 11, 17))
        }
        ctx.lineWidth = 2.5
        ctx.strokeStyle = '#3a4a6b'
        ctx.strokeRect(sx + 1.25, sy + 1.25, sw - 2.5, sh - 2.5)
        ctx.lineWidth = 1
        ctx.strokeStyle = '#070b13'
        // 该板块一只都没命中：叠加暗色面纱，整块（含标题条/二级/边框）统一变暗
        if (active != null && !sectorHasMatch) {
          ctx.fillStyle = VEIL_COLOR
          ctx.fillRect(sx, sy, sw, sh)
        }
      }

      // 搜索高亮：在所有元素之上叠加醒目黄色边框（5秒内有效）
      if (this._matches && Date.now() < (this._hlUntil || 0)) {
        const { stocks, l1s, l2s } = this._matches
        ctx.save()
        ctx.strokeStyle = '#FFE100'
        ctx.lineWidth = 4
        for (const s of this.layout) {              // 一级行业（最显眼）
          if (l1s.has(s.name)) {
            const SX = s.x * k + tx, SY = s.y * k + ty, SW = s.w * k, SH = s.h * k
            ctx.strokeRect(SX + 2, SY + 2, Math.max(1, SW - 4), Math.max(1, SH - 4))
          }
        }
        ctx.lineWidth = 3
        for (const s of this.layout) for (const l2 of s.children) {   // 二级行业
          if (l2s.has(l2.name)) {
            const LX = l2.x * k + tx, LY = l2.y * k + ty, LW = l2.w * k, LH = l2.h * k
            ctx.strokeRect(LX + 1.5, LY + 1.5, Math.max(1, LW - 3), Math.max(1, LH - 3))
          }
        }
        ctx.lineWidth = 2.5
        for (const s of this.layout) for (const l2 of s.children) for (const st of l2.children) {  // 个股
          if (stocks.has(st.code)) {
            const X = st.x * k + tx, Y = st.y * k + ty, W = st.w * k, H = st.h * k
            if (W >= 1 && H >= 1) ctx.strokeRect(X + 1, Y + 1, Math.max(1, W - 2), Math.max(1, H - 2))
          }
        }
        ctx.restore()
      }
    },

    // 个股标签（分级）：面积够大→名称+涨跌幅；中等→仅名称；太小→不显示（调用方按阈值过滤）
    drawStockLabel(ctx, name, change, x, y, w, h, withPct) {
      const cx = x + w / 2
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillStyle = '#fff'
      const font = s => `bold ${s}px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
      if (withPct) {
        const nameSize = clamp(Math.min(w, h) * 0.19, 10, 15)
        const pctSize = nameSize * 0.8
        const cy = y + h / 2
        ctx.font = font(nameSize)
        ctx.fillText(name, cx, cy - nameSize * 0.55)
        ctx.font = font(pctSize)
        ctx.fillText(fmtPct(change), cx, cy + pctSize * 0.6)
      } else {
        // 仅名称：按宽高自适应字号，保证名称能放进格子
        const n = Math.max(name.length, 2)
        const size = Math.round(clamp(Math.min((w / n) * 0.95, h * 0.6), 8, 14))
        ctx.font = font(size)
        ctx.fillText(name, cx, y + h / 2)
      }
    },
    drawHeaderText(ctx, text, x, y, w, hh, size) {
      if (w < 30) return
      ctx.textAlign = 'left'
      ctx.textBaseline = 'middle'
      ctx.fillStyle = '#fff'
      ctx.font = `bold ${size}px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
      ctx.fillText(text, x, y + hh / 2)
    },

    scheduleRender() {
      if (this._raf) return
      this._raf = requestAnimationFrame(() => { this._raf = 0; this.render() })
    },

    // 限制平移范围：缩放 k>=1 时地图始终覆盖整个视口，绝不出现虚无空白；
    // k=1（最小）时 tx/ty 锁死为 0，即初始全图、不能拖。
    clampView() {
      const k = this.view.k
      this.view.tx = clamp(this.view.tx, this.cssW * (1 - k), 0)
      this.view.ty = clamp(this.view.ty, this.cssH * (1 - k), 0)
    },

    // 滚轮缩放（以鼠标位置为中心），限定 1~12 倍，永远不会触发空白 bug
    onWheel(e) {
      const r = this.$refs.canvasEl.getBoundingClientRect()
      const mx = e.clientX - r.left, my = e.clientY - r.top
      const f = Math.exp(-e.deltaY * 0.0015)
      const nk = clamp(this.view.k * f, 1, 12)
      if (nk === this.view.k) return
      const Lx = (mx - this.view.tx) / this.view.k
      const Ly = (my - this.view.ty) / this.view.k
      this.view.k = nk
      this.view.tx = mx - Lx * nk
      this.view.ty = my - Ly * nk
      this.clampView()
      this.scheduleRender()
    },
    onMouseDown(e) {
      this.dragging = true
      const r = this.$refs.canvasEl.getBoundingClientRect()
      this.lastX = e.clientX - r.left
      this.lastY = e.clientY - r.top
      this.$refs.canvasEl.style.cursor = 'grabbing'
    },
    onMouseMove(e) {
      const r = this.$refs.canvasEl.getBoundingClientRect()
      const mx = e.clientX - r.left, my = e.clientY - r.top
      if (this.dragging) {
        this.view.tx += mx - this.lastX
        this.view.ty += my - this.lastY
        this.lastX = mx
        this.lastY = my
        this.clampView()
        this.scheduleRender()
        return
      }
      this.updateHover(mx, my)
    },
    onMouseUp() {
      this.dragging = false
      this.$refs.canvasEl.style.cursor = 'grab'
    },
    onMouseLeave() {
      this.dragging = false
      this.tooltip.visible = false
      if (this.$refs.canvasEl) this.$refs.canvasEl.style.cursor = 'grab'
    },
    resetZoom() {
      this.view = { k: 1, tx: 0, ty: 0 }
      this.render()
    },
    // 双击：落在个股上 → 新标签页打开雪球；落在行业/空白 → 复位缩放
    onDblClick(e) {
      if (!this.layout) return
      const r = this.$refs.canvasEl.getBoundingClientRect()
      const mx = e.clientX - r.left, my = e.clientY - r.top
      const Lx = (mx - this.view.tx) / this.view.k
      const Ly = (my - this.view.ty) / this.view.k
      const hit = this.hitTest(Lx, Ly)
      if (hit && hit.node && hit.node.code) {
        const url = xueqiuUrl(hit.node.code)
        if (url) window.open(url, '_blank')
        return
      }
      this.resetZoom()
    },

    updateHover(mx, my) {
      if (!this.layout) return
      const Lx = (mx - this.view.tx) / this.view.k
      const Ly = (my - this.view.ty) / this.view.k
      const hit = this.hitTest(Lx, Ly)
      if (hit) {
        const n = hit.node
        this.tooltip = {
          visible: true,
          name: n.name,
          code: n.code || '',
          change: fmtPct(n.change),
          cls: n.change >= 0 ? 'up' : 'down',
          marketCap: fmtCap(n.value),
          pe: fmtPE(n.pe),
          x: mx + 14,
          y: my + 14
        }
        this.$refs.canvasEl.style.cursor = 'pointer'
      } else {
        this.tooltip.visible = false
        this.$refs.canvasEl.style.cursor = 'grab'
      }
    },
    hitTest(Lx, Ly) {
      for (const s of this.layout) {
        if (Lx < s.x || Lx > s.x + s.w || Ly < s.y || Ly > s.y + s.h) continue
        if (s.headerH > 0 && Ly < s.y + s.headerH) return { node: s }
        for (const l2 of s.children) {
          if (Lx < l2.x || Lx > l2.x + l2.w || Ly < l2.y || Ly > l2.y + l2.h) continue
          if (l2.headerH > 0 && Ly < l2.y + l2.headerH) return { node: l2 }
          // 个股层：精确命中优先；落在子像素缝隙时吸附到中心最近的个股，
          // 避免悬停缝隙时错误地回退到二级行业、显示成"别的股票"
          let hit = null, near = null, nearD = Infinity
          for (const st of l2.children) {
            if (st.w == null || st.h == null) continue
            if (!hit && Lx >= st.x && Lx <= st.x + st.w && Ly >= st.y && Ly <= st.y + st.h) hit = st
            const dx = Lx - (st.x + st.w / 2), dy = Ly - (st.y + st.h / 2)
            const d = dx * dx + dy * dy
            if (d < nearD) { nearD = d; near = st }
          }
          if (hit) return { node: hit }
          if (near) return { node: near }
          return { node: l2 }
        }
        return { node: s }
      }
      return null
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
.mm-header h1 { font-size: 1.05rem; color: #fff; margin: 0; text-shadow: 0 2px 4px rgba(0,0,0,0.3); white-space: nowrap; }
.mm-header-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
.mm-search-wrap { position: relative; display: flex; align-items: center; }
.mm-search {
  width: 200px;
  padding: 6px 44px 6px 10px;
  background: rgba(13, 19, 32, 0.8);
  border: 1px solid #3a4a6b;
  border-radius: 6px;
  color: #e0e6f0;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.mm-search:focus { border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.15); }
.mm-search::placeholder { color: #5a6b8c; }
.mm-search-count { position: absolute; right: 8px; font-size: 11px; color: #8ba4c7; pointer-events: none; white-space: nowrap; }
.mm-header-right { display: flex; align-items: center; gap: 10px; }
.mm-stats { font-size: 12px; color: #8ba4c7; white-space: nowrap; }
.mm-update { font-size: 11px; color: #8ba4c7; white-space: nowrap; }
.mm-back-button { padding: 6px 14px; background: linear-gradient(135deg, #3a4a6b, #2a3a5b); border: 1px solid #4a5a7b; border-radius: 6px; color: #e0e6f0; cursor: pointer; transition: all 0.3s ease; font-size: 13px; white-space: nowrap; }
.mm-back-button:hover { background: linear-gradient(135deg, #4a5a7b, #3a4a6b); transform: translateY(-1px); }
.mm-refresh-btn { padding: 6px 12px; background: linear-gradient(135deg, #1890ff, #096dd9); border: 1px solid #40a9ff; border-radius: 6px; color: #fff; cursor: pointer; font-size: 12px; transition: all 0.3s ease; white-space: nowrap; }
.mm-cache-btn { padding: 6px 10px; background: rgba(58, 74, 107, 0.6); border: 1px solid #4a5a7b; border-radius: 6px; color: #8ba4c7; cursor: pointer; font-size: 11px; transition: all 0.3s ease; white-space: nowrap; }
.mm-cache-btn:hover:not(:disabled) { background: rgba(58, 74, 107, 0.9); color: #e0e6f0; }
.mm-cache-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.mm-refresh-btn:hover:not(:disabled) { background: linear-gradient(135deg, #40a9ff, #1890ff); transform: translateY(-1px); }
.mm-refresh-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.mm-refresh-spin { display: inline-block; margin-right: 3px; font-size: 13px; line-height: 1; }
.mm-refresh-spin.on { animation: mm-btn-spin 0.8s linear infinite; }
@keyframes mm-btn-spin { to { transform: rotate(360deg); } }

.mm-chart-wrapper {
  flex: 1;
  position: relative;
  background: rgba(10, 18, 32, 0.6);
  border-radius: 8px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  min-height: 300px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}
.mm-canvas {
  position: absolute;
  top: 4px; left: 4px; right: 4px; bottom: 4px;
  display: block;
  cursor: grab;
}

.mm-tooltip {
  position: absolute;
  pointer-events: none;
  z-index: 20;
  min-width: 150px;
  background: rgba(20, 25, 45, 0.96);
  border: 1px solid #3a4a6b;
  border-radius: 6px;
  padding: 8px 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
.mm-tooltip-name { font-size: 14px; font-weight: bold; color: #fff; margin-bottom: 5px; }
.mm-tooltip-code { font-weight: normal; font-size: 12px; color: #8ba4c7; margin-left: 6px; }
.mm-tooltip-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.mm-tooltip-label { font-size: 12px; color: #8ba4c7; }
.mm-tooltip-val { font-size: 15px; font-weight: bold; }
.mm-tooltip-val.up { color: #ff4d4f; }
.mm-tooltip-val.down { color: #52c41a; }

.mm-hint {
  position: absolute;
  top: 8px; right: 12px;
  z-index: 15;
  font-size: 11px;
  color: #5a6b8c;
  background: rgba(13, 19, 32, 0.6);
  padding: 3px 8px;
  border-radius: 4px;
  pointer-events: none;
}

.mm-changes-loading {
  position: absolute;
  top: 8px; left: 12px;
  z-index: 15;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #b0c4e0;
  background: rgba(13, 19, 32, 0.72);
  border: 1px solid rgba(58, 74, 107, 0.5);
  padding: 3px 10px;
  border-radius: 10px;
  pointer-events: none;
}
.mm-cl-dot { width: 6px; height: 6px; border-radius: 50%; background: #1890ff; animation: mm-cl-pulse 1s ease-in-out infinite; }
@keyframes mm-cl-pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }

.mm-legend {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}
.mm-legend-bar {
  display: flex;
  gap: 1px;
  width: 252px;
  height: 18px;
  border-radius: 2px;
  overflow: visible; /* 让激活/悬停色块能上抬放大，不被裁切 */
}
.mm-legend-step {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  font-weight: bold;
  color: #fff;
  height: 100%;
  white-space: nowrap;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.mm-legend-step:hover { transform: translateY(-2px) scaleY(1.2); z-index: 1; }
.mm-legend-step.active {
  transform: translateY(-3px) scaleY(1.35);
  box-shadow: 0 0 0 2px #fff, 0 0 10px rgba(255, 255, 255, 0.7);
  z-index: 2;
}

/* 涨停/跌停按钮：红涨绿跌，与图例配色一致 */
.mm-limit-btn {
  height: 20px;
  padding: 0 10px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 4px;
  font-size: 11px;
  font-weight: bold;
  color: #fff;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.mm-limit-btn.up { background: linear-gradient(135deg, #f32f3d, #c91a26); }
.mm-limit-btn.down { background: linear-gradient(135deg, #3bcc5f, #1ea645); }
.mm-limit-btn:hover { transform: translateY(-1px); }
.mm-limit-btn.active {
  transform: translateY(-2px);
  box-shadow: 0 0 0 2px #fff, 0 0 10px rgba(255, 255, 255, 0.7);
}

/* 筛选状态条：画布顶部居中，点击清除 */
.mm-filter-badge {
  position: absolute;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 15;
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(13, 19, 32, 0.88);
  border: 1px solid #3a4a6b;
  border-radius: 12px;
  padding: 4px 12px;
  font-size: 12px;
  color: #e0e6f0;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.mm-filter-badge:hover { border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.18); }
.mm-filter-clear { color: #8ba4c7; font-weight: bold; }

.mm-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 5px 8px; color: #8ba4c7; font-size: 0.72rem; margin-top: 6px; flex-shrink: 0; }
.mm-footer-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 768px) {
  .market-map-page { padding: 6px; }
  .mm-header { flex-direction: column; gap: 6px; text-align: center; }
  .mm-header h1 { font-size: 1rem; }
  .mm-chart-wrapper { min-height: 240px; }
}
</style>
