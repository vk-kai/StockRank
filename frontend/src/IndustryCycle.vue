<template>
  <div class="icy-page">
    <header class="icy-header">
      <div class="icy-header-left">
        <button class="icy-back" @click="goBack">← 返回主页</button>
        <button class="icy-back icy-back-map" @click="goBackToMap" v-if="fromMap">← 大盘云图</button>
        <h1>🔬 行业见顶周期诊断</h1>
      </div>
      <!-- 已分析行业下拉框 -->
      <div class="icy-history" v-if="analyzedIndustries.length > 0">
        <span class="icy-history-label">已诊断：</span>
        <select class="icy-history-select" @change="onHistorySelect($event.target.value)" :value="currentIndustry">
          <option value="">选择行业...</option>
          <option v-for="name in analyzedIndustries" :key="name" :value="name">{{ name }}</option>
        </select>
      </div>
    </header>

    <!-- 输入区 -->
    <section class="icy-input-section">
      <div class="icy-input-row">
        <input
          class="icy-input"
          v-model="industryName"
          placeholder="输入行业名称，如：AI、新能源、医药、白酒、半导体..."
          @keyup.enter="startAnalysis"
          :disabled="analyzing"
        />
        <button class="icy-start-btn" @click="startAnalysis" :disabled="analyzing || !industryName.trim()">
          <template v-if="analyzing">
            <span class="icy-spinner"></span>
            {{ analysisStep }}
          </template>
          <template v-else>开始诊断</template>
        </button>
      </div>
      <div class="icy-input-hint">
        基于六大见顶信号（渗透率/产能/利润率/政策/全民讨论/龙头走弱），AI将对行业进行周期诊断并与历史经典周期对标
      </div>
    </section>

    <!-- 分析中进度条 -->
    <section class="icy-progress-section" v-if="analyzing">
      <div class="icy-progress-bar">
        <div class="icy-progress-fill" :style="{ width: progress + '%' }"></div>
      </div>
      <div class="icy-progress-text">
        <span>{{ analysisStep }}</span>
        <span class="icy-progress-pct">{{ progress }}%</span>
      </div>
    </section>

    <!-- 分析失败 -->
    <section class="icy-error-section" v-if="error && !analyzing">
      <div class="icy-error-card">
        <div class="icy-error-icon">⚠️</div>
        <div class="icy-error-msg">{{ error }}</div>
        <button class="icy-retry-btn" @click="startAnalysis">重新分析</button>
      </div>
    </section>

    <!-- 结果展示 -->
    <section class="icy-result" v-if="result && !analyzing">

      <!-- 总体判断 -->
      <div class="icy-verdict" :class="verdictClass">
        <div class="icy-verdict-main">
          <span class="icy-verdict-industry">{{ result.industry }}</span>
          <span class="icy-verdict-text">{{ result.overall_verdict }}</span>
        </div>
        <div class="icy-verdict-score">
          <span class="icy-score-label">见顶风险指数</span>
          <span class="icy-score-value" :class="scoreClass">{{ result.overall_score }}</span>
          <span class="icy-score-max">/100</span>
        </div>
        <div class="icy-verdict-time" v-if="result.analyze_time">分析时间：{{ result.analyze_time }}</div>
      </div>

      <!-- 六大信号诊断 -->
      <div class="icy-signals">
        <h2 class="icy-section-title">📊 六大见顶信号诊断</h2>
        <div class="icy-signals-grid">
          <div
            class="icy-signal-card"
            :class="getSignalClass(signal)"
            v-for="(signal, idx) in result.signals"
            :key="idx"
          >
            <div class="icy-signal-header">
              <span class="icy-signal-name">{{ signal.name }}</span>
              <span class="icy-signal-status" :class="getStatusClass(signal)">{{ signal.status }}</span>
            </div>
            <div class="icy-signal-score-bar">
              <div class="icy-signal-score-fill" :style="{ width: signal.score + '%' }" :class="getScoreBarClass(signal.score)"></div>
            </div>
            <div class="icy-signal-score-num">风险值 {{ signal.score }}<span class="icy-score-max">/100</span></div>
            <div class="icy-signal-detail">{{ signal.detail }}</div>
          </div>
        </div>
      </div>

      <!-- 周期对标 -->
      <div class="icy-comparison" v-if="result.cycle_comparison">
        <h2 class="icy-section-title">📅 周期对标（与{{ result.cycle_comparison.reference_industry }}对比）</h2>
        <div class="icy-comparison-info">
          <span class="icy-comparison-current">当前阶段：<strong>{{ result.cycle_comparison.current_phase }}</strong></span>
          <span class="icy-comparison-equiv">相当于{{ result.cycle_comparison.reference_industry }}：<strong>{{ result.cycle_comparison.equivalent_year }}年</strong></span>
        </div>
        <div class="icy-comparison-table-wrap">
          <table class="icy-comparison-table">
            <thead>
              <tr>
                <th class="icy-th-phase">周期阶段</th>
                <th class="icy-th-ref">{{ result.cycle_comparison.reference_industry }}</th>
                <th class="icy-th-target">{{ result.industry }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(phase, idx) in result.cycle_comparison.phases" :key="idx" :class="getPhaseRowClass(phase)">
                <td class="icy-td-phase">
                  <span class="icy-phase-dot" :class="'phase-' + idx"></span>
                  {{ phase.phase }}
                </td>
                <td class="icy-td-ref">{{ phase.new_energy }}</td>
                <td class="icy-td-target">{{ phase.target_industry }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 警示信号 -->
      <div class="icy-warnings" v-if="result.warnings && result.warnings.length">
        <h2 class="icy-section-title">🚨 需警惕的见顶信号</h2>
        <div class="icy-warning-list">
          <div class="icy-warning-item" v-for="(w, idx) in result.warnings" :key="idx">
            {{ w }}
          </div>
        </div>
      </div>

      <!-- 综合结论 -->
      <div class="icy-summary" v-if="result.summary">
        <h2 class="icy-section-title">📝 综合结论</h2>
        <div class="icy-summary-text">{{ result.summary }}</div>
      </div>

      <!-- AI原始返回（解析失败时） -->
      <div class="icy-raw" v-if="result.parse_error && result.raw_content">
        <h2 class="icy-section-title">AI原始返回</h2>
        <div class="icy-raw-content">{{ result.raw_content }}</div>
      </div>
    </section>

    <!-- 无结果提示 -->
    <section class="icy-empty" v-if="!result && !analyzing && !error">
      <div class="icy-empty-icon">🔬</div>
      <div class="icy-empty-text">输入行业名称，开始见顶周期诊断</div>
      <div class="icy-empty-sub">分析需要1-3分钟，支持异步查询</div>
    </section>

    <footer class="icy-footer">
      本工具基于AI分析，仅供投资参考，不构成投资建议。评分越高代表见顶风险越大。
    </footer>
  </div>
</template>

<script>
import { startIndustryCycle, getIndustryCycleStatus, getIndustryCycleResult, getIndustryCycleAllScores, getIndustryCycleSingleScore } from './services/apiService'

export default {
  name: 'IndustryCycle',
  data() {
    return {
      industryName: '',
      analyzing: false,
      progress: 0,
      analysisStep: '',
      error: '',
      result: null,
      pollTimer: null,
      // 已分析行业列表
      analyzedIndustries: [],
      currentIndustry: '',
      // 来源标记
      fromMap: false
    }
  },
  computed: {
    verdictClass() {
      if (!this.result) return ''
      const s = this.result.overall_score || 0
      if (s < 30) return 'verdict-safe'
      if (s < 50) return 'verdict-caution'
      if (s < 70) return 'verdict-warning'
      return 'verdict-danger'
    },
    scoreClass() {
      if (!this.result) return ''
      const s = this.result.overall_score || 0
      if (s < 30) return 'score-safe'
      if (s < 50) return 'score-caution'
      if (s < 70) return 'score-warning'
      return 'score-danger'
    }
  },
  mounted() {
    // 检查是否从大盘云图跳转过来
    const query = this.$route?.query || {}
    this.fromMap = query.from === 'market-map'
    const queryIndustry = (query.industry || '').trim()

    // 加载已分析行业列表
    this.loadAnalyzedIndustries()

    if (queryIndustry) {
      // 从大盘云图跳转，先检查是否已有诊断结果
      this.industryName = queryIndustry
      this.currentIndustry = queryIndustry
      this.loadAndShowIndustry(queryIndustry)
    } else {
      // 尝试加载上次结果
      this.loadLastResult()
    }
  },
  beforeUnmount() {
    this.stopPolling()
  },
  methods: {
    goBack() {
      this.$router.push('/')
    },
    goBackToMap() {
      this.$router.push('/market-map')
    },
    async loadAnalyzedIndustries() {
      try {
        const res = await getIndustryCycleAllScores()
        if (res && res.success && res.industries) {
          this.analyzedIndustries = res.industries
        }
      } catch (e) {
        // 忽略
      }
    },
    async loadAndShowIndustry(industryName) {
      // 先尝试从批量诊断结果中获取
      try {
        const res = await getIndustryCycleSingleScore(industryName)
        if (res && res.success && res.data) {
          this.result = res.data
          this.currentIndustry = industryName
          return
        }
      } catch (e) {
        // 忽略
      }
      // 没有结果，自动启动诊断
      this.startAnalysis()
    },
    onHistorySelect(name) {
      if (!name) return
      this.industryName = name
      this.currentIndustry = name
      this.loadAndShowIndustry(name)
    },
    async loadLastResult() {
      try {
        const res = await getIndustryCycleResult()
        if (res.success && res.data) {
          // 如果没有解析错误，或有原始内容，都显示
          if (!res.data.parse_error || res.data.raw_content) {
            this.result = res.data
            if (res.data.industry) {
              this.industryName = res.data.industry
            }
          }
        }
      } catch (e) {
        // 忽略
      }
    },
    async startAnalysis() {
      const name = this.industryName.trim()
      if (!name || this.analyzing) return

      this.error = ''
      this.result = null
      this.progress = 0
      this.analysisStep = '正在启动分析...'
      this.analyzing = true
      this.currentIndustry = name

      try {
        const res = await startIndustryCycle(name)
        if (res.success) {
          // 开始轮询状态
          this.startPolling()
        } else {
          this.error = res.message || '启动分析失败'
          this.analyzing = false
        }
      } catch (e) {
        this.error = e.response?.data?.message || '启动分析失败'
        this.analyzing = false
      }
    },
    startPolling() {
      this.stopPolling()
      this.pollTimer = setInterval(() => this.pollStatus(), 3000)
      // 立即查一次
      this.pollStatus()
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer)
        this.pollTimer = null
      }
    },
    async pollStatus() {
      try {
        const res = await getIndustryCycleStatus()
        if (res.status === 'running') {
          this.progress = res.progress || 0
          this.analysisStep = res.step || '分析中...'
        } else if (res.status === 'completed') {
          this.analyzing = false
          this.progress = 100
          this.analysisStep = '分析完成'
          this.stopPolling()

          if (res.result) {
            this.result = res.result
          } else {
            // 加载完整结果
            const resultRes = await getIndustryCycleResult()
            if (resultRes.success && resultRes.data) {
              this.result = resultRes.data
            }
          }
          // 刷新已分析行业列表
          this.loadAnalyzedIndustries()
        } else if (res.status === 'failed') {
          this.analyzing = false
          this.error = res.error || '分析失败'
          this.stopPolling()
        }
      } catch (e) {
        console.error('轮询状态失败:', e)
      }
    },
    getSignalClass(signal) {
      const s = signal.score || 0
      if (s < 30) return 'signal-safe'
      if (s < 50) return 'signal-caution'
      if (s < 70) return 'signal-warning'
      return 'signal-danger'
    },
    getStatusClass(signal) {
      const s = signal.score || 0
      if (s < 30) return 'status-safe'
      if (s < 50) return 'status-caution'
      if (s < 70) return 'status-warning'
      return 'status-danger'
    },
    getScoreBarClass(score) {
      if (score < 30) return 'bar-safe'
      if (score < 50) return 'bar-caution'
      if (score < 70) return 'bar-warning'
      return 'bar-danger'
    },
    getPhaseRowClass(phase) {
      const t = phase.target_industry || ''
      if (t.includes('？') || t.includes('?')) return 'phase-future'
      return ''
    }
  }
}
</script>

<style scoped>
.icy-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0a0e17 0%, #1a1f35 50%, #0d1321 100%);
  color: #e0e6f0;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.icy-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 20px;
  background: rgba(26, 35, 53, 0.8);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  backdrop-filter: blur(10px);
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.icy-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.icy-header h1 {
  font-size: 1.3rem;
  color: #fff;
  margin: 0;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}
.icy-back-map {
  background: linear-gradient(135deg, #d4380d, #ad2102) !important;
  border-color: #ff7a45 !important;
}
.icy-back {
  border: 1px solid #4a5a7b;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  color: #e0e6f0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 14px;
  padding: 10px 20px;
  transition: all 0.3s ease;
}
.icy-back:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

/* 输入区 */
.icy-input-section {
  padding: 20px 24px;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  margin-bottom: 18px;
}
.icy-input-row {
  display: flex;
  gap: 12px;
}
.icy-input {
  flex: 1;
  padding: 12px 16px;
  background: rgba(10, 14, 23, 0.6);
  border: 1px solid rgba(58, 74, 107, 0.6);
  border-radius: 8px;
  color: #e0e6f0;
  font-size: 15px;
  outline: none;
  transition: border-color 0.3s;
}
.icy-input:focus {
  border-color: #69c0ff;
}
.icy-input::placeholder {
  color: #5a6a8a;
}
.icy-input:disabled {
  opacity: 0.6;
}
.icy-start-btn {
  padding: 12px 24px;
  background: linear-gradient(135deg, #1890ff, #096dd9);
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.3s;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 6px;
}
.icy-start-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(24, 144, 255, 0.4);
}
.icy-start-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.icy-input-hint {
  margin-top: 10px;
  font-size: 12px;
  color: #8ba4c7;
  line-height: 1.5;
}

/* 进度条 */
.icy-progress-section {
  margin-bottom: 18px;
}
.icy-progress-bar {
  height: 6px;
  background: rgba(58, 74, 107, 0.4);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}
.icy-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #1890ff, #69c0ff);
  border-radius: 3px;
  transition: width 0.5s ease;
}
.icy-progress-text {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #8ba4c7;
}
.icy-progress-pct {
  color: #69c0ff;
  font-weight: 700;
}

/* 错误 */
.icy-error-section {
  margin-bottom: 18px;
}
.icy-error-card {
  padding: 24px;
  background: rgba(239, 83, 80, 0.1);
  border: 1px solid rgba(239, 83, 80, 0.4);
  border-radius: 12px;
  text-align: center;
}
.icy-error-icon {
  font-size: 2rem;
  margin-bottom: 8px;
}
.icy-error-msg {
  color: #ff7875;
  margin-bottom: 12px;
}
.icy-retry-btn {
  padding: 8px 20px;
  background: linear-gradient(135deg, #3a4a6b, #2a3a5b);
  border: 1px solid #4a5a7b;
  border-radius: 8px;
  color: #e0e6f0;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}
.icy-retry-btn:hover {
  transform: translateY(-1px);
}

/* 结果区 */
.icy-result {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.icy-section-title {
  font-size: 1.05rem;
  color: #e0e6f0;
  margin: 0 0 12px 2px;
}

/* 总体判断 */
.icy-verdict {
  padding: 20px 24px;
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  background: rgba(26, 35, 53, 0.6);
  border-left: 5px solid #8ba4c7;
}
.icy-verdict.verdict-safe { border-left-color: #52c41a; background: rgba(82, 196, 26, 0.08); }
.icy-verdict.verdict-caution { border-left-color: #faad14; background: rgba(250, 173, 20, 0.08); }
.icy-verdict.verdict-warning { border-left-color: #fa8c16; background: rgba(250, 140, 22, 0.08); }
.icy-verdict.verdict-danger { border-left-color: #ff4d4f; background: rgba(255, 77, 79, 0.08); }

.icy-verdict-main {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin-bottom: 12px;
}
.icy-verdict-industry {
  font-size: 1.3rem;
  font-weight: 800;
  color: #fff;
}
.icy-verdict-text {
  font-size: 1.1rem;
  font-weight: 600;
  color: #e0e6f0;
}
.icy-verdict-score {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 8px;
}
.icy-score-label {
  font-size: 13px;
  color: #8ba4c7;
}
.icy-score-value {
  font-size: 2.2rem;
  font-weight: 900;
  line-height: 1;
}
.icy-score-value.score-safe { color: #73d13d; }
.icy-score-value.score-caution { color: #ffc53d; }
.icy-score-value.score-warning { color: #fa8c16; }
.icy-score-value.score-danger { color: #ff7875; }
.icy-score-max { font-size: 14px; color: #6b7d99; }
.icy-verdict-time {
  font-size: 12px;
  color: #6b7d99;
}

/* 信号卡片 */
.icy-signals-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 14px;
}
.icy-signal-card {
  background: rgba(26, 35, 53, 0.6);
  border: 1px solid rgba(58, 74, 107, 0.5);
  border-radius: 12px;
  padding: 16px;
  border-top: 3px solid #8ba4c7;
  transition: transform 0.2s, box-shadow 0.2s;
}
.icy-signal-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.25);
}
.icy-signal-card.signal-safe { border-top-color: #52c41a; }
.icy-signal-card.signal-caution { border-top-color: #faad14; }
.icy-signal-card.signal-warning { border-top-color: #fa8c16; }
.icy-signal-card.signal-danger { border-top-color: #ff4d4f; }

.icy-signal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.icy-signal-name {
  font-size: 15px;
  font-weight: 700;
  color: #e0e6f0;
}
.icy-signal-status {
  font-size: 12px;
  font-weight: 700;
  padding: 3px 10px;
  border-radius: 4px;
  background: rgba(58, 74, 107, 0.4);
  color: #cbd5e1;
}
.icy-signal-status.status-safe { color: #73d13d; background: rgba(82, 196, 26, 0.15); }
.icy-signal-status.status-caution { color: #ffc53d; background: rgba(250, 173, 20, 0.15); }
.icy-signal-status.status-warning { color: #fa8c16; background: rgba(250, 140, 22, 0.15); }
.icy-signal-status.status-danger { color: #ff7875; background: rgba(255, 77, 79, 0.15); }

.icy-signal-score-bar {
  height: 6px;
  background: rgba(58, 74, 107, 0.3);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 6px;
}
.icy-signal-score-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.6s ease;
}
.icy-signal-score-fill.bar-safe { background: linear-gradient(90deg, #52c41a, #73d13d); }
.icy-signal-score-fill.bar-caution { background: linear-gradient(90deg, #faad14, #ffc53d); }
.icy-signal-score-fill.bar-warning { background: linear-gradient(90deg, #fa8c16, #faad14); }
.icy-signal-score-fill.bar-danger { background: linear-gradient(90deg, #ff4d4f, #ff7875); }

.icy-signal-score-num {
  font-size: 13px;
  color: #8ba4c7;
  margin-bottom: 8px;
}
.icy-signal-detail {
  font-size: 13px;
  color: #a0b0c7;
  line-height: 1.6;
}

/* 周期对标 */
.icy-comparison {
  padding: 20px 24px;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
}
.icy-comparison-info {
  display: flex;
  gap: 24px;
  margin-bottom: 16px;
  font-size: 14px;
  color: #a0b0c7;
}
.icy-comparison-info strong {
  color: #69c0ff;
}
.icy-comparison-table-wrap {
  overflow-x: auto;
}
.icy-comparison-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}
.icy-comparison-table th {
  padding: 10px 14px;
  text-align: center;
  background: rgba(24, 144, 255, 0.1);
  border-bottom: 2px solid rgba(24, 144, 255, 0.3);
  color: #69c0ff;
  font-weight: 700;
}
.icy-comparison-table td {
  padding: 12px 14px;
  text-align: center;
  border-bottom: 1px solid rgba(58, 74, 107, 0.3);
  color: #e0e6f0;
}
.icy-comparison-table tr.phase-future td {
  color: #6b7d99;
  font-style: italic;
}
.icy-td-phase {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: center;
  white-space: nowrap;
}
.icy-phase-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.icy-phase-dot.phase-0 { background: #52c41a; }
.icy-phase-dot.phase-1 { background: #1890ff; }
.icy-phase-dot.phase-2 { background: #faad14; }
.icy-phase-dot.phase-3 { background: #ff4d4f; }

/* 警示信号 */
.icy-warning-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.icy-warning-item {
  padding: 12px 16px;
  background: rgba(250, 173, 20, 0.08);
  border: 1px solid rgba(250, 173, 20, 0.3);
  border-radius: 8px;
  font-size: 13px;
  color: #ffc53d;
  line-height: 1.6;
}

/* 综合结论 */
.icy-summary {
  padding: 20px 24px;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
}
.icy-summary-text {
  font-size: 14px;
  color: #c0d0e7;
  line-height: 1.8;
}

/* AI原始返回 */
.icy-raw {
  padding: 20px 24px;
  background: rgba(26, 35, 53, 0.6);
  border-radius: 12px;
  border: 1px solid rgba(58, 74, 107, 0.5);
}
.icy-raw-content {
  font-size: 13px;
  color: #8ba4c7;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow-y: auto;
}

/* 空状态 */
.icy-empty {
  text-align: center;
  padding: 60px 20px;
}
.icy-empty-icon {
  font-size: 3rem;
  margin-bottom: 12px;
}
.icy-empty-text {
  font-size: 16px;
  color: #8ba4c7;
  margin-bottom: 8px;
}
.icy-empty-sub {
  font-size: 13px;
  color: #5a6a8a;
}

/* 加载动画 */
.icy-spinner {
  display: inline-block;
  width: 16px;
  height: 16px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: icy-spin 0.8s linear infinite;
  vertical-align: middle;
  margin-right: 4px;
}
@keyframes icy-spin {
  to { transform: rotate(360deg); }
}

/* 页脚 */
.icy-footer {
  text-align: center;
  padding: 14px;
  color: #6b7d99;
  font-size: 0.8rem;
  margin-top: 24px;
  line-height: 1.7;
}

@media (max-width: 640px) {
  .icy-signals-grid {
    grid-template-columns: 1fr;
  }
  .icy-input-row {
    flex-direction: column;
  }
  .icy-comparison-info {
    flex-direction: column;
    gap: 8px;
  }
  .icy-header {
    flex-direction: column;
    text-align: center;
  }
  .icy-header h1 {
    font-size: 1.05rem;
  }
}

/* 已诊断行业下拉框 */
.icy-history {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.icy-history-label {
  color: #8899aa;
  font-size: 13px;
  white-space: nowrap;
}
.icy-history-select {
  background: rgba(30, 42, 62, 0.9);
  color: #e0e6f0;
  border: 1px solid rgba(80, 100, 140, 0.6);
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
  outline: none;
  max-width: 180px;
}
.icy-history-select:hover {
  border-color: var(--accent-main, #60a5fa);
}
.icy-history-select:focus {
  border-color: var(--accent-main, #60a5fa);
  box-shadow: 0 0 0 2px rgba(96, 165, 250, 0.2);
}
</style>
