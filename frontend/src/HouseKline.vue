<template>
  <div class="house-kline-page">
    <header class="kline-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>{{ currentTitle }}</h1>
      <div class="kline-actions">
        <select v-model="selectedId" @change="onDatasetChange" class="ds-select">
          <option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.title }}</option>
        </select>
        <button @click="openAddForm" class="action-btn">➕ 新增K线</button>
        <button v-if="currentDataset && !currentDataset.builtin" @click="onDelete" class="action-btn danger">🗑 删除</button>
      </div>
    </header>

    <div class="kline-controls">
      <div class="period-buttons">
        <button
          v-for="p in availablePeriods"
          :key="p.key"
          :class="['period-btn', { active: currentPeriod === p.key }]"
          @click="switchPeriod(p.key)"
        >{{ p.label }}</button>
      </div>
    </div>

    <div class="chart-container" ref="chartContainer">
      <div ref="mainChart" class="main-chart"></div>
      <div v-if="!loading && (!klineData || !klineData.points || !klineData.points.length)" class="empty-tip">
        该数据集暂无数据
      </div>
    </div>

    <div class="data-source">数据来源：{{ source }}</div>

    <div v-if="showAddForm" class="modal-mask" @click.self="closeAddForm">
      <div class="modal">
        <h2>新增K线</h2>
        <div class="form-grid">
          <div class="form-cell"><span class="form-label">标题</span>
            <input v-model="form.title" placeholder="如：奔驰二手车价格" class="inp" />
          </div>
          <div class="form-cell"><span class="form-label">单位</span>
            <input v-model="form.unit" placeholder="如：万 / 元（可空）" class="inp" />
          </div>
          <div class="form-cell"><span class="form-label">基础周期</span>
            <select v-model="form.basePeriod" class="inp">
              <option value="30min">30分钟（自动算日/月/季K）</option>
              <option value="daily">日K（自动算月/季K）</option>
              <option value="monthly">月K（自动算季K）</option>
            </select>
          </div>
          <div class="form-cell"><span class="form-label">起始日期</span>
            <input type="date" v-model="form.startDate" class="inp" />
          </div>
          <div class="form-cell"><span class="form-label">结束日期</span>
            <input type="date" v-model="form.endDate" class="inp" />
          </div>
        </div>
        <button @click="generateFrames" class="action-btn primary">生成输入框</button>

        <div v-if="form.frames.length" class="frames-wrap">
          <div class="frames-info">共 {{ form.frames.length }} 个时间框 · 每个填一个收盘价 · 空值会自动跳过</div>
          <div class="frame-list">
            <div v-for="(f, i) in form.frames" :key="i" class="frame-row">
              <span class="frame-date">{{ f.label }}</span>
              <input type="number" step="0.01" v-model.number="f.value" placeholder="收盘价" class="inp frame-inp" />
            </div>
          </div>
        </div>

        <div class="modal-actions">
          <button @click="closeAddForm" class="action-btn">取消</button>
          <button @click="saveNew" :disabled="saving" class="action-btn primary">{{ saving ? '保存中...' : '保存' }}</button>
        </div>
      </div>
    </div>

    <SecurityAlert />
  </div>
</template>

<script>
import * as echarts from 'echarts'
import { getHouseKline, getHouseDatasets, saveHouseDataset, deleteHouseDataset } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'

const PERIOD_LABELS = {
  '30min': '30分K',
  daily: '日K线',
  monthly: '月K线',
  quarterly: '季K线'
}
// 基础周期 → 该数据集可展示的全部周期（基础 + 自动聚合的更高周期）
const PERIODS_BY_BASE = {
  '30min': ['30min', 'daily', 'monthly', 'quarterly'],
  daily: ['daily', 'monthly', 'quarterly'],
  monthly: ['monthly', 'quarterly']
}
// 30 分钟交易时段
const HALF_HOUR_TIMES = ['09:30', '10:00', '10:30', '11:00', '13:00', '13:30', '14:00', '14:30']

export default {
  name: 'HouseKline',
  components: { SecurityAlert },
  data() {
    return {
      loading: false,
      datasets: [],
      selectedId: 'house',
      klineData: null,
      currentPeriod: 'monthly',
      unit: '万',
      source: '国家统计局',
      mainChart: null,
      showAddForm: false,
      saving: false,
      form: {
        title: '',
        unit: '万',
        basePeriod: 'daily',
        startDate: '',
        endDate: '',
        frames: []
      }
    }
  },
  computed: {
    currentDataset() {
      return this.datasets.find(d => d.id === this.selectedId) || null
    },
    currentTitle() {
      return this.currentDataset ? this.currentDataset.title : '📈 K线分析'
    },
    availablePeriods() {
      const base = (this.currentDataset && this.currentDataset.basePeriod) || 'monthly'
      return (PERIODS_BY_BASE[base] || ['monthly', 'quarterly']).map(k => ({ key: k, label: PERIOD_LABELS[k] || k }))
    }
  },
  mounted() {
    this.fetchDatasets().then(() => this.fetchKline())
    window.addEventListener('resize', this.handleResize)
  },
  beforeUnmount() {
    window.removeEventListener('resize', this.handleResize)
    if (this.mainChart) {
      this.mainChart.dispose()
      this.mainChart = null
    }
  },
  methods: {
    goBack() {
      this.$router.push('/')
    },

    async fetchDatasets(selectId) {
      try {
        const res = await getHouseDatasets()
        if (res.success) {
          this.datasets = res.data
          if (selectId) {
            this.selectedId = selectId
          } else if (!this.datasets.find(d => d.id === this.selectedId)) {
            this.selectedId = 'house'
          }
        }
      } catch (e) {
        console.error('获取数据集列表失败', e)
      }
    },

    onDatasetChange() {
      // 切换数据集后，周期重置为该数据集的基础周期
      this.currentPeriod = (this.currentDataset && this.currentDataset.basePeriod) || 'monthly'
      this.fetchKline()
    },

    switchPeriod(period) {
      if (this.currentPeriod === period) return
      this.currentPeriod = period
      this.fetchKline()
    },

    async fetchKline() {
      this.loading = true
      try {
        const res = await getHouseKline(this.selectedId, this.currentPeriod)
        if (res.success) {
          this.klineData = res.data
          this.unit = res.data.unit || ''
          this.source = res.data.source || ''
          this.$nextTick(() => setTimeout(() => this.renderMainChart(), 50))
        }
      } catch (e) {
        console.error('获取K线失败', e)
      } finally {
        this.loading = false
      }
    },

    handleResize() {
      if (this.mainChart) this.mainChart.resize()
    },

    // ---------- 新增表单 ----------
    openAddForm() {
      this.form = { title: '', unit: '万', basePeriod: 'daily', startDate: '', endDate: '', frames: [] }
      this.showAddForm = true
    },
    closeAddForm() {
      this.showAddForm = false
    },
    fmtDate(d) {
      const y = d.getFullYear()
      const m = String(d.getMonth() + 1).padStart(2, '0')
      const da = String(d.getDate()).padStart(2, '0')
      return `${y}-${m}-${da}`
    },
    generateFrames() {
      const { basePeriod, startDate, endDate } = this.form
      if (!startDate || !endDate) { alert('请先选择起始和结束日期'); return }
      const s = new Date(startDate + 'T00:00:00')
      const e = new Date(endDate + 'T00:00:00')
      if (isNaN(s.getTime()) || isNaN(e.getTime())) { alert('日期格式有误'); return }
      if (s > e) { alert('起始日期不能晚于结束日期'); return }

      const frames = []
      if (basePeriod === 'monthly') {
        let y = s.getFullYear(), m = s.getMonth()
        const ey = e.getFullYear(), em = e.getMonth()
        while (y < ey || (y === ey && m <= em)) {
          const mm = String(m + 1).padStart(2, '0')
          frames.push({ date: `${y}-${mm}-01`, label: `${y}-${mm}`, value: null })
          m++; if (m > 11) { m = 0; y++ }
        }
      } else {
        const cur = new Date(s)
        while (cur <= e) {
          const dow = cur.getDay()
          if (dow !== 0 && dow !== 6) {
            const d = this.fmtDate(cur)
            if (basePeriod === 'daily') {
              frames.push({ date: d, label: d, value: null })
            } else {
              // 30min
              const mm = String(cur.getMonth() + 1).padStart(2, '0')
              const dd = String(cur.getDate()).padStart(2, '0')
              for (const t of HALF_HOUR_TIMES) {
                frames.push({ date: `${d} ${t}`, label: `${mm}-${dd} ${t}`, value: null })
              }
            }
          }
          cur.setDate(cur.getDate() + 1)
        }
      }
      this.form.frames = frames
    },
    async saveNew() {
      const title = (this.form.title || '').trim()
      if (!title) { alert('请填写标题'); return }
      const points = this.form.frames
        .filter(f => f.value !== null && f.value !== '' && f.value !== undefined && !isNaN(Number(f.value)))
        .map(f => ({ date: f.date, value: Number(f.value) }))
      if (!points.length) { alert('请至少填入一个数据点'); return }

      this.saving = true
      const basePeriod = this.form.basePeriod
      try {
        const res = await saveHouseDataset({
          title,
          unit: (this.form.unit || '').trim(),
          basePeriod,
          points
        })
        if (res.success) {
          this.showAddForm = false
          await this.fetchDatasets(res.id)
          this.currentPeriod = basePeriod
          await this.fetchKline()
        } else {
          alert(res.error || '保存失败')
        }
      } catch (e) {
        alert('保存失败: ' + (e.message || e))
      } finally {
        this.saving = false
      }
    },
    async onDelete() {
      if (!this.currentDataset || this.currentDataset.builtin) return
      if (!confirm(`确定删除「${this.currentDataset.title}」？此操作不可恢复。`)) return
      try {
        const res = await deleteHouseDataset(this.selectedId)
        if (res.success) {
          this.selectedId = 'house'
          await this.fetchDatasets()
          this.currentPeriod = 'monthly'
          await this.fetchKline()
        } else {
          alert(res.error || '删除失败')
        }
      } catch (e) {
        alert('删除失败: ' + (e.message || e))
      }
    },

    // ---------- 图表 ----------
    calculateMA(data, period) {
      const result = []
      for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
          result.push(null)
        } else {
          let sum = 0
          for (let j = 0; j < period; j++) sum += data[i - j]
          result.push(Number((sum / period).toFixed(2)))
        }
      }
      return result
    },
    detectKeyPoints(data) {
      const points = []
      if (!data.length) return points
      let maxHigh = -Infinity, maxHighIndex = -1
      data.forEach((item, index) => {
        if (item.high > maxHigh) { maxHigh = item.high; maxHighIndex = index }
      })
      if (maxHighIndex >= 0) {
        points.push({ name: '最高点', coord: [maxHighIndex, maxHigh], itemStyle: { color: '#ff4d4f' }, label: { formatter: '最高点' } })
      }
      const lookback = 10
      for (let i = lookback; i < data.length - lookback; i++) {
        const current = data[i]
        const prev = [], next = []
        for (let j = 1; j <= lookback; j++) { prev.push(data[i - j]); next.push(data[i + j]) }
        const isLow = current.low <= Math.min(...prev.map(p => p.low)) && current.low <= Math.min(...next.map(p => p.low))
        if (isLow && i !== maxHighIndex) {
          points.push({ name: '阶段低点', coord: [i, current.low], itemStyle: { color: '#52c41a' }, label: { formatter: '阶段低点' } })
        }
      }
      return points.filter((p, i, arr) => i === arr.findIndex(q => q.coord[0] === p.coord[0]))
    },
    renderMainChart() {
      const data = this.klineData && this.klineData.points ? this.klineData.points : []
      const chartDom = this.$refs.mainChart
      if (!chartDom) return
      if (this.mainChart) this.mainChart.dispose()
      this.mainChart = echarts.init(chartDom)

      if (!data.length) {
        this.mainChart.setOption({ backgroundColor: 'transparent' })
        return
      }

      const unit = this.unit ? ' ' + this.unit : ''
      const dates = data.map(p => p.label)
      const ohlc = data.map(p => [p.open, p.close, p.low, p.high])
      const closes = data.map(p => p.close)
      const ma5 = this.calculateMA(closes, 5)
      const ma10 = this.calculateMA(closes, 10)
      const macdData = data.map(p => p.macd || 0)
      const signalData = data.map(p => p.signal || 0)
      const histogramData = data.map(p => {
        const v = p.histogram || 0
        return { value: v, itemStyle: { color: v >= 0 ? '#ff4d4f' : '#52c41a' } }
      })
      const markPoints = this.detectKeyPoints(data)
      const labelInterval = Math.max(1, Math.floor(data.length / 12))
      const self = this

      const option = {
        animation: false,
        backgroundColor: 'transparent',
        axisPointer: { link: [{ xAxisIndex: 'all' }], label: { backgroundColor: '#777' } },
        tooltip: {
          trigger: 'item',
          backgroundColor: 'rgba(20, 25, 45, 0.95)',
          borderColor: '#3a4a6b',
          borderWidth: 1,
          padding: [12, 16],
          textStyle: { color: '#e0e6f0', fontSize: 13 },
          confine: true,
          formatter(params) {
            if (!params) return ''
            const item = data[params.dataIndex]
            if (!item) return ''
            const seriesName = params.seriesName
            const dateLabel = item.label
            if (seriesName === 'K线' || seriesName === 'MA5' || seriesName === 'MA10') {
              const change = item.open ? ((item.close - item.open) / item.open * 100).toFixed(2) : '0.00'
              const changeColor = change >= 0 ? '#ff4d4f' : '#52c41a'
              const sign = change >= 0 ? '+' : ''
              return `<div style="min-width:200px;">
                <div style="font-weight:bold;margin-bottom:10px;font-size:14px;color:#fff;border-bottom:1px solid #3a4a6b;padding-bottom:8px;">📅 ${dateLabel}</div>
                <div style="display:flex;justify-content:space-between;margin-bottom:6px;"><span style="color:#8ba4c7;">开盘</span><span style="color:#faad14;font-weight:500;">${item.open.toFixed(2)}${unit}</span></div>
                <div style="display:flex;justify-content:space-between;margin-bottom:6px;"><span style="color:#8ba4c7;">收盘</span><span style="color:#1890ff;font-weight:500;">${item.close.toFixed(2)}${unit}</span></div>
                <div style="display:flex;justify-content:space-between;margin-bottom:6px;"><span style="color:#8ba4c7;">最高</span><span style="color:#ff4d4f;font-weight:500;">${item.high.toFixed(2)}${unit}</span></div>
                <div style="display:flex;justify-content:space-between;margin-bottom:6px;"><span style="color:#8ba4c7;">最低</span><span style="color:#52c41a;font-weight:500;">${item.low.toFixed(2)}${unit}</span></div>
                <div style="display:flex;justify-content:space-between;margin-top:8px;padding-top:8px;border-top:1px dashed #3a4a6b;"><span style="color:#8ba4c7;">涨跌幅</span><span style="color:${changeColor};font-weight:bold;font-size:14px;">${sign}${change}%</span></div>
              </div>`
            }
            const macdVal = item.macd || 0
            const signalVal = item.signal || 0
            const histVal = item.histogram || 0
            return `<div style="min-width:180px;">
              <div style="font-weight:bold;margin-bottom:10px;font-size:14px;color:#fff;border-bottom:1px solid #3a4a6b;padding-bottom:8px;">📅 ${dateLabel}</div>
              <div style="color:#8ba4c7;font-weight:bold;margin-bottom:6px;">📊 MACD指标</div>
              <div style="display:flex;justify-content:space-between;margin-bottom:4px;"><span style="color:#8ba4c7;">MACD</span><span style="color:${macdVal >= 0 ? '#ff4d4f' : '#52c41a'};">${macdVal.toFixed(4)}</span></div>
              <div style="display:flex;justify-content:space-between;margin-bottom:4px;"><span style="color:#8ba4c7;">Signal</span><span style="color:${signalVal >= 0 ? '#faad14' : '#13c2c2'};">${signalVal.toFixed(4)}</span></div>
              <div style="display:flex;justify-content:space-between;"><span style="color:#8ba4c7;">Histogram</span><span style="color:${histVal >= 0 ? '#ff4d4f' : '#52c41a'};">${histVal.toFixed(4)}</span></div>
            </div>`
          }
        },
        grid: [
          { left: '3%', right: '3%', top: 30, height: '55%' },
          { left: '3%', right: '3%', top: '70%', height: '18%' }
        ],
        xAxis: [
          {
            type: 'category', data: dates,
            axisLine: { lineStyle: { color: '#3a4a6b', width: 1 } },
            axisLabel: { color: '#8ba4c7', fontSize: 11, interval: labelInterval },
            axisTick: { show: false }, splitLine: { show: false }
          },
          {
            type: 'category', gridIndex: 1, data: dates,
            axisLine: { lineStyle: { color: '#3a4a6b', width: 1 } },
            axisLabel: { show: false }, axisTick: { show: false }, splitLine: { show: false }
          }
        ],
        yAxis: [
          {
            type: 'value', scale: true,
            min: v => Math.floor(v.min - 1), max: v => Math.ceil(v.max + 1),
            axisLine: { show: true, lineStyle: { color: '#3a4a6b' } },
            axisLabel: { color: '#8ba4c7', fontSize: 11 },
            splitLine: { lineStyle: { color: '#1a2a3b', type: 'dashed' } }
          },
          {
            type: 'value', gridIndex: 1, scale: true,
            axisLine: { show: true, lineStyle: { color: '#3a4a6b' } },
            axisLabel: { color: '#8ba4c7', fontSize: 10, formatter: v => v.toFixed(2) },
            splitLine: { lineStyle: { color: '#1a2a3b', type: 'dashed' } }
          }
        ],
        series: [
          {
            name: 'K线', type: 'candlestick', data: ohlc,
            itemStyle: { color: '#ff4d4f', color0: '#52c41a', borderColor: '#ff4d4f', borderColor0: '#52c41a' },
            barWidth: '60%',
            markPoint: {
              symbol: 'pin', symbolSize: 50,
              itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.5)' },
              label: { show: true, color: '#fff', fontSize: 10, fontWeight: 'bold', formatter: p => p.name },
              data: markPoints
            }
          },
          { name: 'MA5', type: 'line', data: ma5, smooth: false, showSymbol: false, connectNulls: true, lineStyle: { color: '#faad14', width: 1.5, type: 'dashed' } },
          { name: 'MA10', type: 'line', data: ma10, smooth: false, showSymbol: false, connectNulls: true, lineStyle: { color: '#722ed1', width: 1.5, type: 'dotted' } },
          { name: 'MACD', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: macdData, showSymbol: false, lineStyle: { color: '#ff4d4f', width: 1.5 } },
          { name: 'Signal', type: 'line', xAxisIndex: 1, yAxisIndex: 1, data: signalData, showSymbol: false, lineStyle: { color: '#faad14', width: 1.5 } },
          { name: 'Histogram', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: histogramData, barWidth: '40%' }
        ]
      }
      try {
        this.mainChart.setOption(option)
      } catch (e) {
        console.error('K线图表渲染失败:', e)
      }
    }
  }
}
</script>

<style scoped>
.house-kline-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0e17 0%, #1a1f35 50%, #0d1321 100%);
  color: #e0e6f0;
  padding: 20px;
}

.kline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 20px;
  padding: 15px 20px;
  background: rgba(26, 35, 53, 0.8);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  backdrop-filter: blur(10px);
}
.kline-header h1 { font-size: 1.4rem; color: #fff; margin: 0; text-shadow: 0 2px 4px rgba(0,0,0,0.3); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.kline-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.ds-select { padding: 8px 10px; background: rgba(13,19,32,0.8); color: #e0e6f0; border: 1px solid #3a4a6b; border-radius: 8px; font-size: 13px; max-width: 220px; }
.ds-select option { background: #0d1321; color: #e0e6f0; }

.action-btn { padding: 8px 14px; background: linear-gradient(135deg, #3a4a6b, #2a3a5b); border: 1px solid #4a5a7b; border-radius: 8px; color: #e0e6f0; cursor: pointer; font-size: 13px; transition: all 0.3s ease; white-space: nowrap; }
.action-btn:hover { transform: translateY(-1px); }
.action-btn.primary { background: linear-gradient(135deg, #1890ff, #096dd9); border-color: #40a9ff; color: #fff; }
.action-btn.danger { background: linear-gradient(135deg, #ff4d4f, #cf1322); border-color: #ff7875; color: #fff; }
.action-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.back-button { padding: 10px 20px; background: linear-gradient(135deg, #3a4a6b, #2a3a5b); border: 1px solid #4a5a7b; border-radius: 8px; color: #e0e6f0; cursor: pointer; transition: all 0.3s ease; font-size: 14px; white-space: nowrap; }
.back-button:hover { background: linear-gradient(135deg, #4a5a7b, #3a4a6b); transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }

.kline-controls { display: flex; justify-content: center; margin-bottom: 20px; }
.period-buttons { display: flex; gap: 10px; padding: 5px; background: rgba(26,35,53,0.8); border-radius: 10px; border: 1px solid rgba(58,74,107,0.5); }
.period-btn { padding: 10px 30px; background: transparent; border: none; border-radius: 8px; color: #8ba4c7; cursor: pointer; transition: all 0.3s ease; font-size: 14px; font-weight: 500; }
.period-btn:hover { background: rgba(58,74,107,0.5); color: #fff; }
.period-btn.active { background: linear-gradient(135deg, #1890ff, #096dd9); color: #fff; font-weight: bold; box-shadow: 0 4px 12px rgba(24,144,255,0.3); }

.chart-container { position: relative; background: rgba(26,35,53,0.6); border-radius: 12px; border: 1px solid rgba(58,74,107,0.5); padding: 20px; margin-bottom: 20px; box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
.main-chart { width: 100%; height: 600px; }
.empty-tip { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #8ba4c7; font-size: 16px; }

.data-source { text-align: center; padding: 15px; color: #8ba4c7; font-size: 0.9rem; background: rgba(26,35,53,0.6); border-radius: 8px; border: 1px solid rgba(58,74,107,0.3); }

/* 弹窗 + 表单 */
.modal-mask { position: fixed; inset: 0; background: rgba(5,10,20,0.7); display: flex; align-items: flex-start; justify-content: center; z-index: 2000; padding: 40px 16px; overflow-y: auto; }
.modal { width: 100%; max-width: 720px; background: linear-gradient(135deg, #0d1321, #131a2e); border: 1px solid #3a4a6b; border-radius: 12px; padding: 24px; box-shadow: 0 12px 40px rgba(0,0,0,0.5); }
.modal h2 { margin: 0 0 16px; color: #fff; font-size: 1.2rem; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.form-cell { display: flex; flex-direction: column; gap: 5px; color: #8ba4c7; font-size: 13px; }
.inp { padding: 8px 10px; background: rgba(13,19,32,0.9); color: #e0e6f0; border: 1px solid #3a4a6b; border-radius: 6px; font-size: 13px; }
/* 日期框：深色主题下原生日期控件必须声明 color-scheme:dark 才能正常渲染/交互；
   并反相日历图标，否则图标在深色背景上几乎不可见，看着像“点不动” */
.inp[type="date"] { color-scheme: dark; }
.inp[type="date"]::-webkit-calendar-picker-indicator { filter: invert(0.8); cursor: pointer; }
.frames-wrap { margin-top: 14px; }
.frames-info { color: #8ba4c7; font-size: 12px; margin-bottom: 8px; }
.frame-list { max-height: 360px; overflow-y: auto; display: grid; grid-template-columns: 1fr 1fr; gap: 6px 12px; padding: 6px; background: rgba(13,19,32,0.4); border-radius: 8px; }
.frame-row { display: flex; align-items: center; gap: 8px; }
.frame-date { flex: 0 0 120px; color: #8ba4c7; font-size: 12px; font-family: monospace; }
.frame-inp { flex: 1; min-width: 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }

@media (max-width: 768px) {
  .house-kline-page { padding: 10px; }
  .kline-header { flex-wrap: wrap; }
  .kline-header h1 { font-size: 1.1rem; }
  .form-grid { grid-template-columns: 1fr; }
  .frame-list { grid-template-columns: 1fr; }
  .main-chart { height: 500px; }
}
</style>
