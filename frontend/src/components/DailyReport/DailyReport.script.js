import { getDailyReport } from '../../services/apiService'
import SecurityAlert from '../SecurityAlert.vue'

export default {
  name: 'DailyReport',
  components: {
    SecurityAlert
  },
  data() {
    return {
      selectedDate: this.$route.query.date || new Date().toISOString().split('T')[0],
      reportData: null,
      loading: false,
      error: null,
      lastUpdate: null,
      aiAnalysis: null
    }
  },
  mounted() {
    this.fetchReport()
  },
  methods: {
    goBack() {
      window.location.href = '/'
    },

    async fetchReport() {
      try {
        this.loading = true
        this.error = null
        
        const response = await getDailyReport(this.selectedDate)
        
        if (response.success) {
          this.reportData = response.data
          this.lastUpdate = new Date(response.timestamp).toLocaleString('zh-CN')
        } else {
          this.error = response.message || '获取数据失败'
        }
      } catch (err) {
        console.error('获取每日报表失败:', err)
        this.error = '获取数据失败: ' + err.message
      } finally {
        this.loading = false
      }
    },

    formatFlow(value) {
      if (value === null || value === undefined) return '-'
      if (Math.abs(value) >= 10000) {
        return (value / 10000).toFixed(2) + ' 亿'
      } else {
        return value.toFixed(2) + ' 万'
      }
    },

    formatChange(value) {
      if (value === null || value === undefined) return '-'
      const percent = value * 100
      const sign = percent >= 0 ? '+' : ''
      return `${sign}${percent.toFixed(2)}%`
    },

    getChangeClass(value) {
      if (value === null || value === undefined) return ''
      return value >= 0 ? 'positive' : 'negative'
    },

    getStrengthClass(strength) {
      switch (strength) {
        case '增强':
          return 'strength-strong'
        case '减弱':
          return 'strength-weak'
        case '持平':
          return 'strength-neutral'
        default:
          return 'strength-new'
      }
    },

    getStrengthIcon(strength) {
      switch (strength) {
        case '增强':
          return '🟢'
        case '减弱':
          return '🔴'
        case '持平':
          return '🟡'
        default:
          return '🆕'
      }
    }
  }
}
