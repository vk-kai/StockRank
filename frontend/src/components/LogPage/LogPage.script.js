import { getLogList, getLogContent, getLogLevels, getLogModules } from '../../services/apiService'

export default {
  name: 'LogPage',
  data() {
    return {
      logList: [],
      logLevels: [],
      logModules: {},
      activeLog: 'data',
      selectedLevel: '',
      selectedModule: '',
      searchKeyword: '',
      pageSize: 100,
      logLines: [],
      totalLines: 0,
      totalPages: 0,
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
    this.loadLogModules()
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

    async loadLogModules() {
      try {
        const response = await getLogModules()
        if (response.success) {
          this.logModules = response.data
        }
      } catch (error) {
        console.error('加载功能模块失败:', error)
      }
    },

    async loadLogContent() {
      this.loading = true
      try {
        const response = await getLogContent(
          this.activeLog, 
          this.currentPage, 
          this.pageSize, 
          this.selectedLevel, 
          this.searchKeyword, 
          this.selectedModule
        )
        if (response.success) {
          this.logLines = response.data.lines
          this.totalLines = response.data.total
          this.totalPages = response.data.total_pages
          if (this.currentPage > this.totalPages) {
            this.currentPage = Math.max(1, this.totalPages)
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
      this.selectedModule = ''
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
      if (page >= 1 && page <= this.totalPages && page !== this.currentPage) {
        this.currentPage = page
        this.loadLogContent()
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
      
      let text = `时间: ${this.selectedLog.timestamp}
级别: ${this.selectedLog.level || '-'}`
      
      if ((this.activeLog === 'data' || this.activeLog === 'system') && this.selectedLog.module) {
        text += `\n模块: ${this.selectedLog.module_display || this.selectedLog.module}`
      }
      
      text += `\n来源: ${this.selectedLog.source}:${this.selectedLog.lineno}
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
        'system': '⚙️',
        'nginx': '🌐'
      }
      return icons[type] || '📄'
    },

    getLogName(type) {
      const names = {
        'error': '错误日志',
        'data': '数据日志',
        'system': '系统日志',
        'nginx': 'Nginx日志'
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

    getMessageHighlightClass(message) {
      if (!message) return ''
      if (message.includes('新增重要新闻但忽略')) return 'highlight-ignore'
      if (message.includes('推送成功') || message.includes('已推送')) return 'highlight-push'
      return ''
    },

    getModuleColor(module) {
      const colors = {
        'data': '#67c23a',
        'news': '#e6a23c',
        'news_important': '#ff9800',
        'ai': '#909399',
        'system': '#409eff',
        'error': '#f56c6c',
        'monitor': '#b37feb'
      }
      if (colors[module]) {
        return colors[module]
      }
      if (module && module.startsWith('news_important')) return '#ff9800'
      if (module && module.startsWith('news')) return '#e6a23c'
      if (module && module.startsWith('data')) return '#67c23a'
      if (module && module.startsWith('ai')) return '#909399'
      if (module && module.startsWith('system')) return '#409eff'
      if (module && module.startsWith('monitor')) return '#b37feb'
      return '#606266'
    },

    showToast(message, type = 'success') {
      this.toast = { show: true, message, type }
      setTimeout(() => {
        this.toast.show = false
      }, 3000)
    }
  }
}
