import { getDailyReport, getSectorStocks } from '../../services/apiService'
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
      aiAnalysis: null,
      showStockModal: false,
      selectedSector: null,
      sectorStocks: [],
      loadingStocks: false,
      stocksError: null,
      stockSortField: 'change',
      stockSortOrder: 'desc'
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

    async openStockModal(sector) {
      if (!sector.sector_url) {
        alert('该板块暂无个股详情链接')
        return
      }
      
      this.showStockModal = true
      this.selectedSector = sector
      this.loadingStocks = true
      this.stocksError = null
      this.sectorStocks = []
      
      try {
        const response = await getSectorStocks(sector.sector_url)
        
        if (response.success) {
          this.sectorStocks = response.data
          this.sortStocks()
        } else {
          this.stocksError = response.message || '获取个股数据失败'
        }
      } catch (err) {
        console.error('获取个股数据失败:', err)
        this.stocksError = '获取个股数据失败: ' + err.message
      } finally {
        this.loadingStocks = false
      }
    },

    closeStockModal() {
      this.showStockModal = false
      this.selectedSector = null
      this.sectorStocks = []
      this.stocksError = null
    },

    sortStocks() {
      if (!this.sectorStocks || this.sectorStocks.length === 0) return
      
      const sorted = [...this.sectorStocks].sort((a, b) => {
        let valueA = a[this.stockSortField]
        let valueB = b[this.stockSortField]
        
        if (typeof valueA === 'string') {
          valueA = parseFloat(valueA.replace(/[^\d.-]/g, '')) || 0
          valueB = parseFloat(valueB.replace(/[^\d.-]/g, '')) || 0
        }
        
        if (this.stockSortOrder === 'desc') {
          return valueB - valueA
        } else {
          return valueA - valueB
        }
      })
      
      this.sectorStocks = sorted
    },

    toggleSortOrder() {
      this.stockSortOrder = this.stockSortOrder === 'desc' ? 'asc' : 'desc'
      this.sortStocks()
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
