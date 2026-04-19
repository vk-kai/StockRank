import { getLogList, getLogContent, getLogLevels } from '../../services/apiService'

export default {
  name: 'LogPage',
  data() {
    return {
      logList: [],
      logLevels: [],
      activeLog: 'system',
      selectedLevel: '',
      searchKeyword: '',
      pageSize: 100,
      logLines: [],
      totalLines: 0,
      loading: false,
      autoRefresh: false,
      refreshTimer: null,
      currentPage: 1,
      gotoPageNum: 1,
      showModal: false,
      selectedLog: null,
      maxMessageLength: 100,
      toast: {
        show: false,
        message: '',
        type: 'success'
      }
    }
  },
  computed: {
    totalPages() {
      return Math.ceil(this.totalLines / this.pageSize) || 1
    },
    paginatedLines() {
      const start = (this.currentPage - 1) * this.pageSize
      const end = start + this.pageSize
      return this.logLines.slice(start, end)
    },
    visiblePages() {
      const pages = []
      const total = this.totalPages
      const current = this.currentPage
      
      let start = Math.max(1, current - 2)
      let end = Math.min(total, current + 2)
      
      if (end - start < 4) {
        if (start === 1) {
          end = Math.min(total, start + 4)
        } else if (end === total) {
          start = Math.max(1, end - 4)
        }
      }
      
      for (let i = start; i <= end; i++) {
        pages.push(i)
      }
      
      return pages
    }
  },
  mounted() {
    this.loadLogList()
    this.loadLogLevels()
    this.loadLogContent()
  },
  beforeUnmount() {
    this.stopAutoRefresh()
  },
  watch: {
    autoRefresh(newVal) {
      if (newVal) {
        this.startAutoRefresh()
      } else {
        this.stopAutoRefresh()
      }
    }
  },
  methods: {
    goBack() {
      this.$router.go(-1)
    },

    async loadLogList() {
      try {
        const response = await getLogList()
        if (response.success) {
          this.logList = response.data
        }
      } catch (error) {
        this.showToast('加载日志列表失败', 'error')
      }
    },

    async loadLogLevels() {
      try {
        const response = await getLogLevels()
        if (response.success) {
          this.logLevels = response.data
        }
      } catch (error) {
        console.error('加载日志级别失败:', error)
      }
    },

    async loadLogContent() {
      this.loading = true
      try {
        const response = await getLogContent(this.activeLog, this.selectedLevel, 5000, this.searchKeyword)
        if (response.success) {
          this.logLines = response.data.lines
          this.totalLines = response.data.total
          if (this.currentPage > this.totalPages) {
            this.currentPage = this.totalPages
          }
        }
      } catch (error) {
        this.showToast('加载日志内容失败', 'error')
      } finally {
        this.loading = false
      }
    },

    async switchLog(logType) {
      this.activeLog = logType
      this.currentPage = 1
      await this.loadLogContent()
    },

    onFilterChange() {
      this.currentPage = 1
      this.loadLogContent()
    },

    onSearch() {
      this.currentPage = 1
      this.loadLogContent()
    },

    clearSearch() {
      this.searchKeyword = ''
      this.currentPage = 1
      this.loadLogContent()
    },

    onPageSizeChange() {
      this.currentPage = 1
      this.loadLogContent()
    },

    goToPage(page) {
      if (page >= 1 && page <= this.totalPages) {
        this.currentPage = page
      }
    },

    jumpToPage() {
      const page = parseInt(this.gotoPageNum)
      if (page >= 1 && page <= this.totalPages) {
        this.goToPage(page)
      } else {
        this.showToast(`请输入 1-${this.totalPages} 之间的页码`, 'error')
      }
      this.gotoPageNum = this.currentPage
    },

    async refreshLogs() {
      await Promise.all([this.loadLogList(), this.loadLogContent()])
      this.showToast('日志已刷新', 'success')
    },

    startAutoRefresh() {
      this.refreshTimer = setInterval(() => {
        this.loadLogContent()
      }, 5000)
    },

    stopAutoRefresh() {
      if (this.refreshTimer) {
        clearInterval(this.refreshTimer)
        this.refreshTimer = null
      }
    },

    truncateMessage(message) {
      if (!message) return ''
      if (message.length <= this.maxMessageLength) {
        return message
      }
      return message.substring(0, this.maxMessageLength) + '...'
    },

    showDetail(log) {
      this.selectedLog = log
      this.showModal = true
    },

    closeModal() {
      this.showModal = false
      this.selectedLog = null
    },

    async copyToClipboard() {
      if (!this.selectedLog) return
      
      const text = `时间: ${this.selectedLog.timestamp}
级别: ${this.selectedLog.level || '-'}
来源: ${this.selectedLog.source}:${this.selectedLog.lineno}
消息: ${this.selectedLog.message}`
      
      try {
        await navigator.clipboard.writeText(text)
        this.showToast('已复制到剪贴板', 'success')
      } catch (error) {
        this.showToast('复制失败', 'error')
      }
    },

    getLogIcon(type) {
      const icons = {
        'error': '❌',
        'data': '📊',
        'system': '⚙️'
      }
      return icons[type] || '📄'
    },

    getLogName(type) {
      const names = {
        'error': '错误日志',
        'data': '数据日志',
        'system': '系统日志'
      }
      return names[type] || type
    },

    formatSize(bytes) {
      if (bytes < 1024) return bytes + ' B'
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
      return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
    },

    getLevelClass(level) {
      if (!level) return ''
      return `level-${level.toLowerCase()}`
    },

    showToast(message, type = 'success') {
      this.toast = { show: true, message, type }
      setTimeout(() => {
        this.toast.show = false
      }, 3000)
    }
  }
}
