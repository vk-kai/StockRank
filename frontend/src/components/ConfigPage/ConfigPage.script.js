import {
  getAIConfig,
  saveAIConfig,
  testAIConnection,
  getFeishuConfig,
  saveFeishuConfig,
  testFeishuConnection,
  getStockMonitorConfig,
  saveStockMonitorConfig,
  getAIPrompt,
  saveAIPrompt,
  getAIDailyPrompt,
  saveAIDailyPrompt,
  getBannedIPs,
  unbanIP
} from '../../services/apiService'
import SecurityAlert from '../SecurityAlert.vue'

export default {
  name: 'ConfigPage',
  components: {
    SecurityAlert
  },
  data() {
    return {
      activeTab: 'ai',
      tabs: [
        { id: 'ai', name: 'AI配置', icon: '🤖' },
        { id: 'feishu', name: '飞书推送', icon: '📢' },
        { id: 'stock', name: '股票监控', icon: '📈' },
        { id: 'prompt', name: 'AI提示词', icon: '💬' },
        { id: 'daily-prompt', name: '首页AI分析提示词', icon: '📊' },
        { id: 'security', name: 'IP黑名单', icon: '🛡️' }
      ],
      aiConfig: {
        enabled: false,
        api_url: '',
        full_url: false,
        api_key: '',
        model: 'gpt-3.5-turbo',
        temperature: 0.7,
        max_tokens: 1000,
        timeout: 30
      },
      feishuConfig: {
        enabled: false,
        webhook_url: '',
        secret: '',
        msg_type: 'interactive',
        base_url: 'http://localhost:5000'
      },
      stockConfig: {
        enabled: false,
        stocks: []
      },
      aiPrompt: '',
      aiDailyPrompt: '',
      bannedIPs: [],
      passwordModal: {
        show: false,
        password: '',
        callback: null
      },
      toast: {
        show: false,
        message: '',
        type: 'success'
      }
    }
  },
  mounted() {
    this.loadConfigs()
  },
  methods: {
    goBack() {
      this.$router.go(-1)
    },

    async loadConfigs() {
      try {
        const [aiRes, feishuRes, stockRes, promptRes, dailyPromptRes] = await Promise.all([
          getAIConfig(),
          getFeishuConfig(),
          getStockMonitorConfig(),
          getAIPrompt(),
          getAIDailyPrompt()
        ])

        if (aiRes.success) {
          this.aiConfig = { ...this.aiConfig, ...aiRes.data }
        }
        if (feishuRes.success) {
          this.feishuConfig = { ...this.feishuConfig, ...feishuRes.data }
        }
        if (stockRes.success) {
          this.stockConfig = { ...this.stockConfig, ...stockRes.data }
          this.stockConfig.stocks = this.stockConfig.stocks.map(stock => ({
            ...stock,
            keywordsString: stock.keywords.join(', ')
          }))
        }
        if (promptRes.success) {
          this.aiPrompt = promptRes.data
        }
        if (dailyPromptRes.success) {
          this.aiDailyPrompt = dailyPromptRes.data
        }
        
        await this.loadBannedIPs()
      } catch (error) {
        this.showToast('加载配置失败', 'error')
      }
    },

    async loadBannedIPs() {
      try {
        const response = await getBannedIPs()
        if (response.success) {
          this.bannedIPs = response.data || []
        }
      } catch (error) {
        console.error('加载IP黑名单失败:', error)
      }
    },

    async handleUnbanIP(ip) {
      this.showPasswordModal(async (password) => {
        if (password !== 'vk666') {
          this.showToast('密码错误', 'error')
          return
        }
        
        try {
          const response = await unbanIP(ip)
          if (response.success) {
            this.showToast(`已解封IP: ${ip}`, 'success')
            await this.loadBannedIPs()
          } else {
            this.showToast(response.message || '解封失败', 'error')
          }
        } catch (error) {
          this.showToast('解封失败', 'error')
        }
      })
    },

    formatBanTime(seconds) {
      if (!seconds || seconds <= 0) return '已过期'
      const minutes = Math.floor(seconds / 60)
      const hours = Math.floor(minutes / 60)
      const days = Math.floor(hours / 24)
      
      if (days > 0) return `${days}天${hours % 24}小时`
      if (hours > 0) return `${hours}小时${minutes % 60}分钟`
      if (minutes > 0) return `${minutes}分钟`
      return `${seconds}秒`
    },

    getAttackTypeName(type) {
      const names = {
        'sql_injection': 'SQL注入',
        'xss': 'XSS攻击',
        'command_injection': '命令注入',
        'path_traversal': '路径遍历',
        'ldap_injection': 'LDAP注入',
        'xxe': 'XXE攻击',
        'ssrf': 'SSRF攻击'
      }
      return names[type] || type || '未知'
    },

    async saveAIConfig() {
      this.showPasswordModal(async (password) => {
        try {
          const response = await saveAIConfig({
            ...this.aiConfig,
            password: password
          })
          if (response.success) {
            this.showToast('AI配置保存成功', 'success')
            await this.loadConfigs()
          } else {
            this.showToast(response.message || '保存失败', 'error')
          }
        } catch (error) {
          if (error.response?.status === 401) {
            this.showToast('密码错误', 'error')
          } else {
            const message = error.response?.data?.message || '保存失败'
            this.showToast(message, 'error')
          }
        }
      })
    },

    async testAIConfig() {
      this.showToast('正在测试AI连接...', 'info')

      try {
        const response = await testAIConnection({
          api_url: this.aiConfig.api_url,
          api_key: this.aiConfig.api_key,
          model: this.aiConfig.model,
          full_url: this.aiConfig.full_url
        })
        
        if (response.success) {
          this.showToast('✅ AI连接测试成功', 'success')
        } else {
          const steps = response.steps || []
          const failedStep = steps.find(s => !s.success) || steps[steps.length - 1]
          const errorMsg = failedStep?.message || response.message || '测试失败'
          this.showToast(`❌ ${errorMsg}`, 'error')
        }
      } catch (error) {
        const message = error.response?.data?.message || error.response?.data?.error || '测试失败，请检查网络连接'
        this.showToast('❌ ' + message, 'error')
      }
    },

    async saveFeishuConfig() {
      this.showPasswordModal(async (password) => {
        try {
          const response = await saveFeishuConfig({
            ...this.feishuConfig,
            password: password
          })
          if (response.success) {
            this.showToast('飞书配置保存成功', 'success')
            await this.loadConfigs()
          } else {
            this.showToast(response.message || '保存失败', 'error')
          }
        } catch (error) {
          if (error.response?.status === 401) {
            this.showToast('密码错误', 'error')
          } else {
            const message = error.response?.data?.message || '保存失败'
            this.showToast(message, 'error')
          }
        }
      })
    },

    async testFeishuConfig() {
      this.showToast('正在测试飞书连接...', 'info')

      try {
        const response = await testFeishuConnection()
        
        if (response.success) {
          this.showToast('✅ 飞书连接测试成功', 'success')
        } else {
          const errorInfo = response.data?.msg || JSON.stringify(response.data)
          this.showToast(`❌ HTTP ${response.status_code}: ${errorInfo}`, 'error')
        }
      } catch (error) {
        const message = error.response?.data?.error || error.response?.data?.message || '测试失败，请检查网络连接'
        this.showToast('❌ ' + message, 'error')
      }
    },

    addStock() {
      this.stockConfig.stocks.push({
        name: '',
        code: '',
        keywords: [],
        keywordsString: '',
        enabled: true
      })
    },

    removeStock(index) {
      this.stockConfig.stocks.splice(index, 1)
    },

    updateKeywords(index) {
      const stock = this.stockConfig.stocks[index]
      stock.keywords = stock.keywordsString.split(',').map(k => k.trim()).filter(k => k)
    },

    async saveStockConfig() {
      this.showPasswordModal(async (password) => {
        try {
          const config = {
            ...this.stockConfig,
            stocks: this.stockConfig.stocks.map(stock => ({
              name: stock.name,
              code: stock.code,
              keywords: stock.keywords,
              enabled: stock.enabled
            })),
            password: password
          }
          const response = await saveStockMonitorConfig(config)
          if (response.success) {
            this.showToast('股票监控配置保存成功', 'success')
            await this.loadConfigs()
          } else {
            this.showToast(response.message || '保存失败', 'error')
          }
        } catch (error) {
          if (error.response?.status === 401) {
            this.showToast('密码错误', 'error')
          } else {
            const message = error.response?.data?.message || '保存失败'
            this.showToast(message, 'error')
          }
        }
      })
    },

    async savePromptConfig() {
      this.showPasswordModal(async (password) => {
        try {
          const response = await saveAIPrompt(this.aiPrompt, password)
          if (response.success) {
            this.showToast('AI提示词保存成功', 'success')
            await this.loadConfigs()
          } else {
            this.showToast(response.message || '保存失败', 'error')
          }
        } catch (error) {
          if (error.response?.status === 401) {
            this.showToast('密码错误', 'error')
          } else {
            const message = error.response?.data?.message || '保存失败'
            this.showToast(message, 'error')
          }
        }
      })
    },

    resetPrompt() {
      this.aiPrompt = `你是一个专业A股交易信息分析助手。 

你的任务是：判断一条信息（新闻或行情异动）是否对A股产生"实质性影响"，包括【盘中即时影响】和【阶段性影响】。 

【信息类型】 

输入信息可能来自： 
1. 新闻事件（政策、国际、行业、公司） 
2. 行情异动（全球市场：股票、指数、期货、大宗商品、外汇等） 

你需要统一判断其对A股的影响价值。`
      this.showToast('已恢复默认提示词', 'info')
    },

    async saveDailyPromptConfig() {
      this.showPasswordModal(async (password) => {
        try {
          const response = await saveAIDailyPrompt(this.aiDailyPrompt, password)
          if (response.success) {
            this.showToast('首页AI分析提示词保存成功', 'success')
            await this.loadConfigs()
          } else {
            this.showToast(response.message || '保存失败', 'error')
          }
        } catch (error) {
          if (error.response?.status === 401) {
            this.showToast('密码错误', 'error')
          } else {
            const message = error.response?.data?.message || '保存失败'
            this.showToast(message, 'error')
          }
        }
      })
    },

    resetDailyPrompt() {
      this.aiDailyPrompt = `你是一个专业的A股资金流向分析师。

请根据以下全天板块资金流入数据和走势图数据，分析今日市场的资金流向特征、热点板块、市场情绪和潜在机会。

请从以下几个方面进行分析：
1. 整体市场资金流向趋势（流入/流出整体情况）
2. 烆点板块分析（资金流入最多的板块及原因推测）
3. 资金流出板块分析（资金流出最多的板块及原因推测）
4. 盘中资金流向变化特点（早盘、午盘、尾盘的资金流向变化）
5. 市场情绪判断（乐观/谨慎/恐慌等）
6. 次日展望和建议

请用简洁专业的语言进行分析，输出格式为纯文本，不要使用JSON格式。`
      this.showToast('已恢复默认首页AI分析提示词', 'info')
    },

    showToast(message, type = 'success') {
      this.toast = { show: true, message, type }
      setTimeout(() => {
        this.toast.show = false
      }, 3000)
    },

    showPasswordModal(callback) {
      this.passwordModal = {
        show: true,
        password: '',
        callback: callback
      }
    },

    closePasswordModal() {
      this.passwordModal = {
        show: false,
        password: '',
        callback: null
      }
    },

    async confirmPassword() {
      if (!this.passwordModal.password) {
        this.showToast('请输入密码', 'error')
        return
      }

      const password = this.passwordModal.password
      const callback = this.passwordModal.callback
      
      this.closePasswordModal()
      
      if (callback) {
        callback(password)
      }
    }
  }
}
