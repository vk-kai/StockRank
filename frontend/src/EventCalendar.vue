<template>
  <div class="evc-wrap">
    <!-- ① 未来72小时核心事件(自动挑★3,带倒计时,一眼看到最重要的事) -->
    <section class="evc-section">
      <div class="evc-sec-head">
        <span class="evc-sec-title">🔥 未来72小时核心事件</span>
        <button class="evc-refresh" @click="load" :disabled="loading">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
      <div v-if="loading && !items" class="evc-empty">加载中…(首次约5秒)</div>
      <div v-else-if="error" class="evc-error">{{ error }}</div>
      <div v-else-if="coreEvents.length === 0" class="evc-empty">未来72小时暂无重大事件(🔴级)</div>
      <div v-else class="evc-core-list">
        <div v-for="ev in coreEvents" :key="'core-' + ev.time + ev.event" class="evc-core-card">
          <div class="evc-core-left">
            <span class="evc-core-time">{{ ev.time.slice(11) }}</span>
            <span class="evc-core-date">{{ shortDayLabel(ev.time) }}</span>
            <span class="evc-core-countdown">⏱ {{ countdown(ev.time) }}</span>
          </div>
          <div class="evc-core-main">
            <div class="evc-core-title-row">
              <span class="evc-region">{{ regionFlag(ev.region) }} {{ ev.region }}</span>
              <span class="evc-core-name">{{ deco(ev.event).zh }}</span>
              <span class="evc-badge lv3">🔴 极高</span>
            </div>
            <div v-if="deco(ev.event).orig" class="evc-core-orig">{{ deco(ev.event).orig }}</div>
            <div class="evc-vals">
              预期 <b>{{ ev.forecast || '--' }}</b> · 前值 <b>{{ ev.previous || '--' }}</b>
              <template v-if="ev.actual != null"> · 公布 <b class="evc-actual">{{ ev.actual }}</b></template>
            </div>
            <div v-if="deco(ev.event).assets.length" class="evc-core-assets">
              <span class="evc-assets-label">🎯 重点影响</span>
              <span v-for="a in deco(ev.event).assets" :key="a" class="evc-asset-tag">{{ a }}</span>
            </div>
            <div v-if="deco(ev.event).note" class="evc-core-note">💡 {{ deco(ev.event).note }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- ② 未来7天事件(默认只看高影响,一键展开全部) -->
    <section class="evc-section">
      <div class="evc-sec-head">
        <span class="evc-sec-title">📅 未来{{ days }}天事件</span>
        <button class="evc-toggle" @click="showAll = !showAll">
          {{ showAll ? '只看重要(🟠高以上)' : `显示全部 ${items ? items.length : ''} 条` }}
        </button>
      </div>
      <div class="evc-list">
        <div v-if="!loading && items && filtered.length === 0" class="evc-empty">该范围内暂无事件</div>
        <div v-for="group in grouped" :key="group.date" class="evc-day">
          <div class="evc-day-head" :class="{ today: group.date === todayStr }">
            {{ dayLabel(group.date) }}
            <span v-if="group.date === todayStr" class="evc-day-today-badge">今日</span>
          </div>
          <div class="evc-day-body">
            <div
              v-for="it in group.list"
              :key="it.time + it.event + it.source"
              class="evc-item"
              :class="{ major: it.importance === 3 }"
            >
              <span class="evc-badge" :class="'lv' + it.importance">{{ levelText(it.importance) }}</span>
              <span class="evc-time">{{ it.time.slice(11) }}</span>
              <span class="evc-region">{{ regionFlag(it.region) }} {{ it.region }}</span>
              <span class="evc-name">
                {{ deco(it.event).zh }}
                <span v-if="deco(it.event).cat" class="evc-cat">{{ deco(it.event).cat }}</span>
              </span>
              <span class="evc-vals">
                预期 <b>{{ it.forecast || '--' }}</b> · 前值 <b>{{ it.previous || '--' }}</b>
                <template v-if="it.actual != null"> · 公布 <b class="evc-actual">{{ it.actual }}</b></template>
              </span>
            </div>
          </div>
        </div>
      </div>
      <div class="evc-footer">源: 百度股市通 + ForexFactory · 缓存30分钟 · 等级: 🔴极高 / 🟠高 / ⚪低</div>
    </section>
  </div>
</template>

<script>
import { getEventCalendar } from './services/apiService'

const REGION_FLAG = {
  美国: '🇺🇸', 中国: '🇨🇳', 欧元区: '🇪🇺', 英国: '🇬🇧', 日本: '🇯🇵',
  澳大利亚: '🇦🇺', 加拿大: '🇨🇦', 瑞士: '🇨🇭', 新西兰: '🇳🇿', 国际: '🌍',
  韩国: '🇰🇷', 香港: '🇭🇰', 德国: '🇩🇪', 法国: '🇫🇷'
}

// 静态规则表: 按事件名关键词归类 → 中文标题(仅翻译英文事件)/类别/影响资产/一句话解读。
// 数据源只有事件名+预期/前值,影响方向等需要实时推演的不做,避免编数据。
const EVENT_RULES = [
  { re: /fomc|federal funds|fed interest|利率决议|议息/i, zh: '美联储利率决议', cat: '美联储', assets: ['纳指', 'AI', '半导体', '美元', '黄金'], note: '决定是否降息及未来政策方向,是全球流动性的定价锚' },
  { re: /press conference|新闻发布会|powell|鲍威尔/i, zh: '美联储主席新闻发布会', cat: '美联储', assets: ['纳指', 'AI', '半导体', '美元'], note: '释放降息路径指引,波动往往比决议本身更大' },
  { re: /\bcpi\b|consumer price|通胀/i, zh: 'CPI通胀数据', cat: '通胀', assets: ['纳指', '美元', '黄金'], note: '通胀超预期会浇灭降息预期,压制科技股估值' },
  { re: /\bpce\b|personal consumption expenditures/i, zh: 'PCE物价数据', cat: '通胀', assets: ['纳指', '美元'], note: '美联储最看重的通胀指标' },
  { re: /non-?farm|payroll|就业|失业|jobless|claim/i, zh: '就业数据', cat: '就业', assets: ['纳指', '美元'], note: '就业强弱直接左右降息节奏的预期' },
  { re: /retail|零售/i, zh: '零售销售', cat: '消费', assets: ['美元', '纳指'], note: '美国消费韧性的晴雨表' },
  { re: /\bgdp\b|国内生产总值/i, zh: 'GDP经济数据', cat: '增长', assets: ['美元', '纳指'], note: '衡量经济增速与衰退担忧' },
  { re: /\bpmi\b|采购经理/i, zh: 'PMI景气数据', cat: '景气', assets: ['纳指', '美元', '原油'], note: '制造业/服务业景气前瞻,影响衰退与复苏叙事' },
  { re: /crude|原油|eia|opec|石油/i, zh: '原油库存/OPEC', cat: '能源', assets: ['原油', '通胀预期'], note: '油价传导通胀预期与风险偏好' },
  { re: /treasury|国债|债券|10-?year/i, zh: '美债/债市', cat: '利率', assets: ['纳指', '美元'], note: '美债收益率是全球资产定价之锚' },
  { re: /lpr|mlf|社融|信贷|中国|china/i, zh: '中国政策/数据', cat: '中国', assets: ['A股', '港股', '人民币'], note: '国内政策与流动性信号' },
  { re: /housing|新屋|成屋|home sales|房地产/i, zh: '房地产数据', cat: '地产', assets: ['美元', '纳指'], note: '地产是利率敏感型经济的温度计' },
]

const _decoCache = new Map()

function hasCJK(s) {
  return /[\u4e00-\u9fff]/.test(s || '')
}

function decorateEvent(name) {
  const n = String(name || '')
  if (_decoCache.has(n)) return _decoCache.get(n)
  let out = { zh: n, orig: '', cat: '', assets: [], note: '' }
  for (const r of EVENT_RULES) {
    if (r.re.test(n)) {
      // 百度源事件名本身是中文 → 保留原名只补类别/资产/解读;ForexFactory英文 → 翻译成中文
      out = hasCJK(n)
        ? { zh: n, orig: '', cat: r.cat, assets: r.assets, note: r.note }
        : { zh: r.zh, orig: n, cat: r.cat, assets: r.assets, note: r.note }
      break
    }
  }
  _decoCache.set(n, out)
  return out
}

export default {
  name: 'EventCalendar',
  data() {
    return { items: null, loading: false, error: null, showAll: false, days: 7 }
  },
  computed: {
    todayStr() {
      const d = new Date()
      const p = (n) => String(n).padStart(2, '0')
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
    },
    // 未发生的事件(后端按北京时间升序,直接字符串比较)
    upcoming() {
      const nowKey = this._nowKey()
      return (this.items || []).filter((it) => String(it.time || '') >= nowKey)
    },
    // 未来72小时内的★3重大事件,按时间升序取前3
    coreEvents() {
      const horizon = Date.now() + 72 * 3600 * 1000
      return this.upcoming
        .filter((it) => it.importance === 3)
        .filter((it) => {
          const t = new Date(String(it.time).replace(' ', 'T')).getTime()
          return !Number.isNaN(t) && t <= horizon
        })
        .slice(0, 3)
    },
    filtered() {
      const items = this.showAll ? (this.items || []) : (this.items || []).filter((it) => (it.importance || 1) >= 2)
      return items
    },
    grouped() {
      const map = new Map()
      for (const it of this.filtered) {
        const d = String(it.time || '').slice(0, 10)
        if (!map.has(d)) map.set(d, [])
        map.get(d).push(it)
      }
      return Array.from(map.entries()).map(([date, list]) => ({ date, list }))
    }
  },
  mounted() {
    this.load()
  },
  beforeUnmount() {
    _decoCache.clear()
  },
  methods: {
    async load() {
      this.loading = true
      this.error = null
      try {
        const res = await getEventCalendar(this.days, 1)
        if (res.success) this.items = res.data || []
        else this.error = res.error || res.message || '获取事件日历失败'
      } catch (e) {
        const body = e?.response?.data
        this.error = body?.error || body?.message || e?.message || '网络错误'
      } finally {
        this.loading = false
      }
    },
    deco(name) {
      return decorateEvent(name)
    },
    _nowKey() {
      const pad = (n) => String(n).padStart(2, '0')
      const now = new Date()
      return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`
    },
    levelText(imp) {
      return imp === 3 ? '🔴 极高' : imp === 2 ? '🟠 高' : '⚪ 低'
    },
    regionFlag(region) {
      return REGION_FLAG[region] || '🏳️'
    },
    _dayDiff(dateStr) {
      const pad = (n) => String(n).padStart(2, '0')
      const dayKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
      const dt = new Date(`${dateStr}T00:00:00`)
      const today = new Date()
      return Math.round((dt.getTime() - new Date(dayKey(today)).getTime()) / 86400000)
    },
    shortDayLabel(timeStr) {
      const diff = this._dayDiff(String(timeStr).slice(0, 10))
      if (diff <= 0) return '今天'
      if (diff === 1) return '明天'
      if (diff === 2) return '后天'
      return String(timeStr).slice(5, 10)
    },
    dayLabel(dateStr) {
      const dt = new Date(`${dateStr}T00:00:00`)
      const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][dt.getDay()]
      const diff = this._dayDiff(dateStr)
      const prefix = diff <= 0 ? '今天 ' : diff === 1 ? '明天 ' : diff === 2 ? '后天 ' : ''
      return `${prefix}${dateStr.slice(5)} ${week}`
    },
    countdown(timeStr) {
      const diff = new Date(String(timeStr).replace(' ', 'T')).getTime() - Date.now()
      if (Number.isNaN(diff) || diff <= 0) return '已公布'
      const h = Math.floor(diff / 3600000)
      const m = Math.round((diff % 3600000) / 60000)
      if (h >= 48) return `还有 ${Math.floor(h / 24)}天${h % 24}小时`
      if (h >= 1) return `还有 ${h}小时${m}分`
      return m > 0 ? `还有 ${m}分钟` : '即将公布'
    }
  }
}
</script>

<style scoped>
.evc-wrap {
  display: grid;
  gap: 14px;
}
.evc-section {
  background: rgba(26, 35, 53, 0.6);
  border: 1px solid rgba(58, 74, 107, 0.5);
  border-radius: 12px;
  padding: 14px 16px;
}
.evc-sec-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.evc-sec-title {
  font-size: 14px;
  font-weight: 700;
  color: #e0e6f0;
}
.evc-refresh {
  margin-left: auto;
  padding: 3px 10px;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid #4a5a7b;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  color: #e0e6f0;
  cursor: pointer;
}
.evc-refresh:disabled { opacity: 0.6; cursor: not-allowed; }
.evc-toggle {
  margin-left: auto;
  padding: 3px 10px;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid rgba(24, 144, 255, 0.4);
  background: rgba(24, 144, 255, 0.12);
  color: #69c0ff;
  cursor: pointer;
}
.evc-empty {
  color: #8ba4c7;
  font-size: 13px;
  padding: 18px;
  text-align: center;
}
.evc-error {
  color: #ff4d4f;
  font-size: 12px;
  padding: 8px 0;
}

/* ── 影响等级色块(代替星星) ── */
.evc-badge {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
  white-space: nowrap;
}
.evc-badge.lv3 { color: #ff7875; background: rgba(255, 77, 79, 0.16); border: 1px solid rgba(255, 77, 79, 0.4); }
.evc-badge.lv2 { color: #f0b90b; background: rgba(240, 185, 11, 0.12); border: 1px solid rgba(240, 185, 11, 0.35); }
.evc-badge.lv1 { color: #8ba4c7; background: rgba(139, 164, 199, 0.12); border: 1px solid rgba(139, 164, 199, 0.3); }

/* ── ① 核心事件大卡片 ── */
.evc-core-list { display: grid; gap: 10px; }
.evc-core-card {
  display: flex;
  gap: 14px;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(255, 77, 79, 0.06);
  border: 1px solid rgba(255, 77, 79, 0.35);
  border-left: 4px solid #ff4d4f;
}
.evc-core-left {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
  min-width: 92px;
  padding-right: 12px;
  border-right: 1px dashed rgba(255, 77, 79, 0.3);
}
.evc-core-time {
  font-size: 1.35rem;
  font-weight: 800;
  color: #fff;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}
.evc-core-date { font-size: 11px; color: #ff7875; font-weight: 700; }
.evc-core-countdown { font-size: 11px; color: #f0b90b; font-weight: 700; white-space: nowrap; }
.evc-core-main { flex: 1; display: grid; gap: 5px; min-width: 0; }
.evc-core-title-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.evc-core-name { font-size: 15px; font-weight: 800; color: #fff; }
.evc-core-orig { font-size: 11px; color: #6b7d99; }
.evc-core-assets { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.evc-assets-label { font-size: 11px; color: #8ba4c7; }
.evc-asset-tag {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 4px;
  color: #69c0ff;
  background: rgba(24, 144, 255, 0.12);
  border: 1px solid rgba(24, 144, 255, 0.3);
}
.evc-core-note { font-size: 12px; color: #cbd5e1; line-height: 1.5; }

/* ── ② 7天列表 ── */
.evc-list { display: grid; gap: 10px; }
.evc-day {
  background: rgba(16, 24, 39, 0.5);
  border: 1px solid rgba(58, 74, 107, 0.4);
  border-radius: 10px;
  padding: 10px;
}
.evc-day-head {
  font-size: 12px;
  font-weight: 700;
  color: #e0e6f0;
  margin-bottom: 6px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.evc-day-head.today { color: #69c0ff; }
.evc-day-today-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  background: rgba(24, 144, 255, 0.15);
  color: #69c0ff;
}
.evc-day-body { display: grid; gap: 4px; }
.evc-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
  padding: 5px 8px;
  border-radius: 6px;
  border: 1px solid transparent;
}
.evc-item.major {
  border-color: rgba(255, 77, 79, 0.25);
  background: rgba(255, 77, 79, 0.05);
}
.evc-time { color: #8ba4c7; font-variant-numeric: tabular-nums; }
.evc-region { color: #cbd5e1; }
.evc-name {
  flex: 1;
  min-width: 160px;
  color: #e0e6f0;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.evc-item.major .evc-name { font-weight: 700; }
.evc-cat {
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 4px;
  color: #8ba4c7;
  background: rgba(58, 74, 107, 0.5);
}
.evc-vals { color: #8ba4c7; font-size: 11px; }
.evc-vals b { color: #e0e6f0; font-weight: 600; }
.evc-vals b.evc-actual { color: #69c0ff; font-weight: 700; }
.evc-footer {
  text-align: right;
  font-size: 11px;
  color: #6b7d99;
  margin-top: 8px;
}
@media (max-width: 640px) {
  .evc-core-card { flex-direction: column; }
  .evc-core-left {
    flex-direction: row;
    border-right: none;
    border-bottom: 1px dashed rgba(255, 77, 79, 0.3);
    padding: 0 0 8px 0;
  }
  .evc-name { min-width: 100%; }
}
</style>
