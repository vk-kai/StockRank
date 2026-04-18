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
  saveAIPrompt
} from '../../services/apiService'

export default {
  name: 'ConfigPage',
  data() {
    return {
      activeTab: 'ai',
      tabs: [
        { id: 'ai', name: 'AI配置', icon: '🤖' },
        { id: 'feishu', name: '飞书推送', icon: '📢' },
        { id: 'stock', name: '股票监控', icon: '📈' },
        { id: 'prompt', name: 'AI提示词', icon: '💬' }
      ],
      aiConfig: {
        enabled: false,
        api_url: '',
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
        msg_type: 'interactive'
      },
      stockConfig: {
        enabled: false,
        stocks: []
      },
      aiPrompt: '',
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
        const [aiRes, feishuRes, stockRes, promptRes] = await Promise.all([
          getAIConfig(),
          getFeishuConfig(),
          getStockMonitorConfig(),
          getAIPrompt()
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
      } catch (error) {
        this.showToast('加载配置失败', 'error')
      }
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
        const response = await testAIConnection()
        
        if (response.success) {
          this.showToast('✅ AI连接测试成功', 'success')
        } else {
          const errorInfo = response.data?.error?.message || JSON.stringify(response.data)
          this.showToast(`❌ HTTP ${response.status_code}: ${errorInfo}`, 'error')
        }
      } catch (error) {
        const message = error.response?.data?.error || error.response?.data?.message || '测试失败，请检查网络连接'
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
