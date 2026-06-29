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
      </div>
      <div class="mm-hint">滚轮缩放 · 拖动平移 · 双击个股看雪球</div>
      <div class="mm-loading" v-if="loading && !hasData">
        <div class="spinner"></div>
        <p>正在加载全市场数据，请稍候...</p>
      </div>
    </div>

    <div class="mm-footer">
      <span class="mm-footer-text">行业分类：东方财富(缓存) · 实时涨跌：新浪财经 · 面积=总市值，颜色=涨跌幅（红涨绿跌）· 仅供投资参考</span>
      <div class="mm-legend">
        <div class="mm-legend-bar">
          <div v-for="(s, i) in legendSteps" :key="i" class="mm-legend-step" :style="{ background: s.color }">{{ s.label }}</div>
        </div>
      </div>
    </div>
    <SecurityAlert />
  </div>
</template>

<script>
import { getMarketMap, refreshMarketMapCache } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

// 配色色阶：涨跌幅(%) → [R,G,B]。跌=绿、涨=红、0%=灰。
// RGB 取自参考截图的真实像素采样（亮绿 rgb(56,204,92)、亮红 rgb(240,44,60)、灰 rgb(76,68,84)），
// 红绿两端在 ±3% 处即接近饱和，与截图"大涨大跌铺满亮色"的观感一致。
const COLOR_STOPS = [
  [-10, [34, 214, 74]],
  [-3, [56, 204, 92]],
  [-2, [52, 128, 80]],
  [-1, [61, 88, 81]],
  [0, [76, 68, 84]],
  [1, [98, 68, 82]],
  [2, [132, 66, 78]],
  [3, [188, 60, 68]],
  [10, [240, 44, 60]]
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

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const fmtPct = c => (c >= 0 ? '+' : '') + c + '%'

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
  // 不在此处重排：尊重调用方传入的顺序（buildLayout 已按需排序——L1 银行置顶，L2/个股按市值降序）
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
      loading: false,
      cacheLoading: false,
      refreshing: false,
      tree: [],
      totalSectors: 0,
      totalStocks: 0,
      cacheTime: '',
      tooltip: { visible: false, name: '', code: '', change: '', cls: '', x: 0, y: 0 }
    }
  },
  computed: {
    hasData() {
      return this.tree.length > 0
    },
    // 图例：与 COLOR_STOPS 一一对应，每块标注涨跌幅阈值（左=跌/绿 → 中=0/灰 → 右=涨/红）
    legendSteps() {
      const labels = ['-4%', '-3%', '-2%', '-1%', '0%', '1%', '2%', '3%', '4%']
      return COLOR_STOPS.map(([, rgb], i) => ({ label: labels[i], color: `rgb(${rgb[0]},${rgb[1]},${rgb[2]})` }))
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

    this.syncSize()
    this.ro = new ResizeObserver(() => this.onResize())
    if (this.$refs.wrapperEl) this.ro.observe(this.$refs.wrapperEl)

    await this.fetchData(true)
    this.timer = setInterval(() => this.fetchData(false), 30000)
  },
  beforeUnmount() {
    clearInterval(this.timer)
    if (this._raf) cancelAnimationFrame(this._raf)
    if (this.ro) this.ro.disconnect()
  },
  methods: {
    goBack() {
      this.$router.push('/')
    },
    async fetchData(showLoading) {
      if (this.refreshing) return
      this.refreshing = true
      this.loading = showLoading
      try {
        const res = await getMarketMap()
        if (res.success) {
          this.tree = res.data.tree
          this.totalSectors = res.data.total_sectors
          this.totalStocks = res.data.total_stocks
          this.cacheTime = res.data.cache_time || ''
          this.$nextTick(() => { this.buildLayout(); this.render() })
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
            name: s.name, code: s.code, change: s.change, value: s.value || 0,
            color: interpColor(s.change)
          }))
        }))
      }))
      sectors.sort((a, b) => b.value - a.value)
      // 银行强制置顶（放在左上角，参考 dapanyuntu），其余仍按市值降序
      const bankIdx = sectors.findIndex(s => s.name === '银行')
      if (bankIdx > 0) sectors.unshift(sectors.splice(bankIdx, 1)[0])
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

      const { k, tx, ty } = this.view
      const cw = this.cssW, ch = this.cssH
      ctx.lineWidth = 1
      ctx.strokeStyle = '#070b13'

      for (const s of this.layout) {
        // 一级 sector 视口剔除：整个板块在视口外则跳过其全部子级
        const sx = s.x * k + tx, sy = s.y * k + ty, sw = s.w * k, sh = s.h * k
        if (sx >= cw || sx + sw <= 0 || sy >= ch || sy + sh <= 0) continue
        for (const l2 of s.children) {
          const lx = l2.x * k + tx, ly = l2.y * k + ty, lw = l2.w * k, lh = l2.h * k
          if (lx >= cw || lx + lw <= 0 || ly >= ch || ly + lh <= 0) continue
          // 个股
          for (const st of l2.children) {
            const x = st.x * k + tx, y = st.y * k + ty, w = st.w * k, h = st.h * k
            if (w < 0.5 || h < 0.5) continue
            if (x >= cw || x + w <= 0 || y >= ch || y + h <= 0) continue
            ctx.fillStyle = st.color
            ctx.fillRect(x, y, w, h)
            if (w >= 2.5 && h >= 2.5) ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1)
            if (w >= 50 && h >= 26) this.drawStockLabel(ctx, st.name, st.change, x, y, w, h, true)
            else if (w >= 32 && h >= 12) this.drawStockLabel(ctx, st.name, st.change, x, y, w, h, false)
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

.mm-legend {
  flex-shrink: 0;
  pointer-events: none;
}
.mm-legend-bar {
  display: flex;
  gap: 1px;
  width: 252px;
  height: 18px;
  border-radius: 2px;
  overflow: hidden;
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
.spinner { width: 40px; height: 40px; border: 3px solid rgba(58, 74, 107, 0.3); border-top-color: #1890ff; border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 14px; }
@keyframes spin { to { transform: rotate(360deg); } }

.mm-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 5px 8px; color: #8ba4c7; font-size: 0.72rem; margin-top: 6px; flex-shrink: 0; }
.mm-footer-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

@media (max-width: 768px) {
  .market-map-page { padding: 6px; }
  .mm-header { flex-direction: column; gap: 6px; text-align: center; }
  .mm-header h1 { font-size: 1rem; }
  .mm-chart-wrapper { min-height: 240px; }
}
</style>
