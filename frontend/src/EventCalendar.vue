<template>
  <div class="evc-wrap">
    <div class="evc-toolbar">
      <button
        v-for="lv in [1, 2, 3]"
        :key="lv"
        class="evc-filter-btn"
        :class="{ active: minImp === lv }"
        :style="minImp === lv ? { borderColor: impColor(lv), color: impColor(lv) } : {}"
        @click="minImp = lv"
      >
        {{ lv === 1 ? '全部' : lv === 2 ? '★2以上' : '★3 重大' }}
      </button>
      <span class="evc-meta">
        未来{{ days }}天 · 北京时间<template v-if="items"> · {{ items.length }}条(★3有{{ highCount }})</template>
      </span>
      <button class="evc-refresh" @click="load" :disabled="loading">
        {{ loading ? '刷新中…' : '刷新' }}
      </button>
    </div>

    <div v-if="error" class="evc-error">{{ error }}</div>

    <div class="evc-list">
      <div v-if="loading && !items" class="evc-empty">加载中…(首次约5秒)</div>
      <div v-else-if="items && filtered.length === 0" class="evc-empty">该重要度范围内暂无事件</div>
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
            <span class="evc-stars" :style="{ color: impColor(it.importance) }">{{ starRow(it.importance) }}</span>
            <span class="evc-time">{{ it.time.slice(11) }}</span>
            <span class="evc-region" :title="it.region">{{ regionFlag(it.region) }} {{ it.region }}</span>
            <span class="evc-name">{{ it.event }}</span>
            <span class="evc-vals">
              预期 <b>{{ it.forecast || '--' }}</b>
              · 前值 <b>{{ it.previous || '--' }}</b>
              <template v-if="it.actual != null"> · 公布 <b class="evc-actual">{{ it.actual }}</b></template>
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="evc-footer">源: 百度股市通 + ForexFactory · 缓存30分钟</div>
  </div>
</template>

<script>
import { getEventCalendar } from './services/apiService'

const REGION_FLAG = {
  美国: '🇺🇸', 中国: '🇨🇳', 欧元区: '🇪🇺', 英国: '🇬🇧', 日本: '🇯🇵',
  澳大利亚: '🇦🇺', 加拿大: '🇨🇦', 瑞士: '🇨🇭', 新西兰: '🇳🇿', 国际: '🌍',
  韩国: '🇰🇷', 香港: '🇭🇰', 德国: '🇩🇪', 法国: '🇫🇷'
}

const IMP_COLOR = { 3: '#ff4d4f', 2: '#f0b90b', 1: '#8ba4c7' }

export default {
  name: 'EventCalendar',
  data() {
    return { items: null, loading: false, error: null, minImp: 2, days: 7 }
  },
  computed: {
    todayStr() {
      const d = new Date()
      const p = (n) => String(n).padStart(2, '0')
      return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
    },
    filtered() {
      return (this.items || []).filter((it) => (it.importance || 1) >= this.minImp)
    },
    grouped() {
      const map = new Map()
      for (const it of this.filtered) {
        const d = String(it.time || '').slice(0, 10)
        if (!map.has(d)) map.set(d, [])
        map.get(d).push(it)
      }
      return Array.from(map.entries()).map(([date, list]) => ({ date, list }))
    },
    highCount() {
      return (this.items || []).filter((it) => it.importance === 3).length
    }
  },
  mounted() {
    this.load()
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
    impColor(imp) {
      return IMP_COLOR[imp] || IMP_COLOR[1]
    },
    starRow(imp) {
      return '★'.repeat(imp) + '☆'.repeat(3 - imp)
    },
    regionFlag(region) {
      return REGION_FLAG[region] || '🏳️'
    },
    dayLabel(dateStr) {
      const dt = new Date(`${dateStr}T00:00:00`)
      const week = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][dt.getDay()]
      const prefix = dateStr === this.todayStr ? '今天 ' : ''
      return `${prefix}${dateStr.slice(5)} ${week}`
    }
  }
}
</script>

<style scoped>
.evc-wrap {
  background: rgba(26, 35, 53, 0.6);
  border: 1px solid rgba(58, 74, 107, 0.5);
  border-radius: 12px;
  padding: 14px 16px;
}
.evc-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.evc-filter-btn {
  padding: 3px 10px;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid rgba(58, 74, 107, 0.8);
  background: transparent;
  color: #8ba4c7;
  cursor: pointer;
  font-weight: 400;
}
.evc-filter-btn.active {
  background: rgba(240, 185, 11, 0.08);
  font-weight: 700;
}
.evc-meta {
  font-size: 11px;
  color: #8ba4c7;
  margin-left: auto;
}
.evc-refresh {
  padding: 3px 10px;
  font-size: 12px;
  border-radius: 6px;
  border: 1px solid #4a5a7b;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  color: #e0e6f0;
  cursor: pointer;
}
.evc-refresh:disabled { opacity: 0.6; cursor: not-allowed; }
.evc-error {
  color: #ff4d4f;
  font-size: 12px;
  margin-bottom: 8px;
}
.evc-list {
  display: grid;
  gap: 10px;
  max-height: 62vh;
  overflow-y: auto;
}
.evc-empty {
  color: #8ba4c7;
  font-size: 13px;
  padding: 20px;
  text-align: center;
}
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
  border: 1px solid rgba(58, 74, 107, 0.4);
  border-left: 3px solid #8ba4c7;
}
.evc-item.major {
  border-color: rgba(255, 77, 79, 0.25);
  border-left-color: #ff4d4f;
  background: rgba(255, 77, 79, 0.06);
}
.evc-stars {
  font-weight: 700;
  letter-spacing: 1px;
  min-width: 44px;
}
.evc-time {
  color: #8ba4c7;
  font-variant-numeric: tabular-nums;
}
.evc-region { color: #cbd5e1; }
.evc-name {
  flex: 1;
  min-width: 180px;
  color: #e0e6f0;
}
.evc-item.major .evc-name { font-weight: 700; }
.evc-vals {
  color: #8ba4c7;
  font-size: 11px;
}
.evc-vals b {
  color: #e0e6f0;
  font-weight: 600;
}
.evc-vals b.evc-actual {
  color: #69c0ff;
  font-weight: 700;
}
.evc-footer {
  text-align: right;
  font-size: 11px;
  color: #6b7d99;
  margin-top: 8px;
}
@media (max-width: 640px) {
  .evc-name { min-width: 100%; }
}
</style>
