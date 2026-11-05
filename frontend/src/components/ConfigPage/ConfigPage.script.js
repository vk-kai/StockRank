import {
  getAIConfig,
  saveAIConfig,
  testAIConnection,
  getFeishuConfig,
  saveFeishuConfig,
  testFeishuConnection,
  getWechatConfig,
  saveWechatConfig,
  testWechatConnection,
  getStockMonitorConfig,
  saveStockMonitorConfig,
  searchStocks,
  getAIPrompt,
  saveAIPrompt,
  getAIDailyPrompt,
  saveAIDailyPrompt,
  getBannedIPs,
  unbanIP,
  getAnomalyConfig,
  saveAnomalyConfig,
  getAnomalyBaseline,
  rebuildAnomalyBaseline,
  getDatasourceConfig,
  testDatasource,
  getOtpStatus,
  getOtpSetup,
  enableOtp,
  disableOtp,
  deployDockerRestart
  , getDeployVersionInfo
  , getDeployStatus
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
      activePushTab: 'feishu',
      tabs: [
        { id: 'ai', name: 'AI配置', icon: '🤖' },
        { id: 'push', name: '推送设置', icon: '📢', subTabs: [
          { id: 'feishu', name: '飞书推送', icon: '📢' },
          { id: 'wechat', name: '企业微信推送', icon: '💬' }
        ]},
        { id: 'datasource', name: '数据源设置', icon: '🔌' },
        { id: 'stock', name: '股票监控', icon: '📈' },
        { id: 'prompt', name: 'AI提示词', icon: '💬' },
        { id: 'daily-prompt', name: '首页AI分析提示词', icon: '📊' },
        { id: 'security', name: 'IP黑名单', icon: '🛡️' },
        { id: 'otp', name: '动态口令', icon: '🔑' },
        { id: 'anomaly', name: '异动检测', icon: '🚨' },
        { id: 'notify', name: '桌面通知', icon: '🔔' },
        { id: 'deploy', name: '部署运维', icon: '🚀' }
      ],
      // 全局桌面通知设置（与 services/notificationManager 共享 localStorage key）
      notifyEnabled: true,
      notifySoundMode: 'all',
      notifyNewsLevel: 'all', // 'all' = 全部新闻, 'important' = 仅重要新闻
      notifyPermission: 'default',
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
        base_url: 'http://localhost:5000',
        news_push_mode: 'important_ai_filter'
      },
      wechatConfig: {
        enabled: false,
        webhook_url: '',
        msg_type: 'markdown',
        base_url: 'http://localhost:5000',
        news_push_mode: 'important_ai_filter'
      },
      newsPushModeOptions: [
        { value: 'important_ai_filter', label: '重要新闻AI筛选后推送' },
        { value: 'important_direct', label: '重要新闻直接推送' },
        { value: 'all_direct', label: '全部新闻直接推送' },
        { value: 'all_ai_filter', label: '全部新闻AI筛选后推送' }
      ],
      stockConfig: {
        enabled: false,
        poll_interval_seconds: 25,
        cooldown_minutes: 30,
        watchlist: [],
      },
      newWatch: {
        mode: 'stock',          // 'stock' 实时搜索选个股 | 'keyword' 自由关键词
        keyword: '',            // 关键词模式输入(不受搜索限制)
        search: '',             // 股票搜索输入(只能从结果选)
        results: [],            // 搜索结果 [{name, code, board}]
        searching: false,
        highlight: -1,          // 键盘上下选高亮索引
        showResults: false,     // 下拉是否展开
      },
      selectedIds: [],
      _searchTimer: null,
      PRICE_TYPES: [
        { key: 'limit_up', label: '触及涨停', fields: [], defaults: {} },
        { key: 'limit_down', label: '触及跌停', fields: [], defaults: {} },
        { key: 'rapid_rise', label: '急速拉升', fields: [{ k: 'pct', label: '阈值%' }, { k: 'win_min', label: '窗口分钟' }], defaults: { pct: 3, win_min: 3 } },
        { key: 'rapid_drop', label: '急速打压', fields: [{ k: 'pct', label: '阈值%' }, { k: 'win_min', label: '窗口分钟' }], defaults: { pct: 3, win_min: 3 } },
        { key: 'cum_move', label: '累计大涨/大跌', fields: [{ k: 'pct', label: '阈值%' }, { k: 'reset', label: '回落至%' }], defaults: { pct: 3, reset: 1 } },
        { key: 'spike_fade', label: '冲高回落', fields: [{ k: 'peak', label: '曾涨%' }, { k: 'back', label: '回落%' }], defaults: { peak: 3, back: 2 } },
        { key: 'dip_rebound', label: '探底回升', fields: [{ k: 'trough', label: '曾跌%' }, { k: 'back', label: '反弹%' }], defaults: { trough: 3, back: 2 } },
        { key: 'gap_open', label: '大幅高/低开', fields: [{ k: 'pct', label: '阈值%' }], defaults: { pct: 3 } },
        { key: 'amplitude', label: '振幅过大', fields: [{ k: 'pct', label: '阈值%' }], defaults: { pct: 7 } },
        { key: 'limit_break', label: '炸板/撬板', fields: [{ k: 'back', label: '回落%' }], defaults: { back: 1 } },
      ],
      aiPrompt: '',
      aiDailyPrompt: '',
      bannedIPs: [],
      passwordModal: {
        show: false,
        password: '',
        callback: null,
        hint: ''
      },
      deployStatus: {
        phase: 'idle',   // idle | recovering | done
        message: ''
      },
      deployVersion: {
        loading: false,
        data: null,
        error: null
      },
      toast: {
        show: false,
        message: '',
        type: 'success'
      },
      anomalyConfig: {
        enabled: true,
        z_threshold: 2.0,
        min_samples: 8,
        abs_threshold: 50,
        divergence_change: 0.002,
        min_net_for_divergence: 2,
        spike_threshold: 20,
        streak_min: 4,
        min_net_for_streak: 3,
        cooldown_minutes: 30,
        baseline_days: 20,
        rank_top_net: 30
      },
      anomalyBaseline: { sector_count: 0, built_at: '', baseline_days: 0 },
      anomalySaving: false,
      anomalyRebuilding: false,
      datasourceList: [],
      datasourceTestResults: {},
      datasourceTesting: false,
      // OTP 动态口令（TOTP）二次验证
      otpConfig: { enabled: false, enrolled_at: '' },
      otpSetup: { secret: '', qr_data_url: '', otpauth_uri: '' },
      otpCodeInput: '',
      otpLoading: false
    }
  },
  mounted() {
    this.loadConfigs()
    this.loadAnomalyConfig()
    this.loadNotifySettings()
    this.loadDatasourceConfig()
    this.loadOtpStatus()
  },
  watch: {
    // 部署运维页签激活期间轮询版本信息(60s,只读,无需密码);离开页签即停
    activeTab(tab) {
      if (tab === 'deploy') this.startDeployVersionPolling()
      else this.stopDeployVersionPolling()
    }
  },
  beforeUnmount() {
    this.stopDeployVersionPolling()
  },
  computed: {
    datasourceGroups() {
      const map = new Map()
      for (const ds of this.datasourceList) {
        const cat = ds.category || '其他'
        if (!map.has(cat)) map.set(cat, [])
        map.get(cat).push(ds)
      }
      const groups = []
      for (const [category, items] of map) {
        // 排序：主 > 备 > 互补
        const order = { '主': 0, '备': 1, '互补': 2 }
        items.sort((a, b) => (order[a.role] ?? 9) - (order[b.role] ?? 9))
        groups.push({ category, items })
      }
      return groups
    }
  },
  methods: {
    goBack() {
      this.$router.go(-1)
    },

    // ===== 桌面通知（全局唯一设置入口；触发由 services/notificationManager 负责）=====
    loadNotifySettings() {
      this.notifyEnabled = localStorage.getItem('newsNotificationEnabled') !== 'false'
      const sm = localStorage.getItem('newsSoundMode')
      this.notifySoundMode = ['none', 'important', 'all'].includes(sm) ? sm : 'all'
      const nl = localStorage.getItem('newsNotificationLevel')
      this.notifyNewsLevel = ['all', 'important'].includes(nl) ? nl : 'all'
      if (typeof Notification === 'undefined') this.notifyPermission = 'unsupported'
      else this.notifyPermission = Notification.permission
    },
    notifyPermissionLabel() {
      return ({ granted: '已允许', denied: '已被拒绝', default: '未授权', unsupported: '浏览器不支持' })[this.notifyPermission] || '未知'
    },
    onToggleNotify() {
      // v-model 已翻转 notifyEnabled，这里持久化；开启时若未授权则请求权限
      localStorage.setItem('newsNotificationEnabled', this.notifyEnabled ? 'true' : 'false')
      if (this.notifyEnabled && typeof Notification !== 'undefined' && Notification.permission !== 'granted') {
        this.requestNotifyPermission()
      } else if (!this.notifyEnabled) {
        this.showToast('已关闭桌面通知', 'info')
      } else if (this.notifyPermission === 'granted') {
        this.showToast('已开启桌面通知', 'success')
      }
    },
    onNotifySoundChange() {
      localStorage.setItem('newsSoundMode', this.notifySoundMode)
      this.showToast('提醒方式已保存', 'success')
    },
    onNotifyNewsLevelChange() {
      localStorage.setItem('newsNotificationLevel', this.notifyNewsLevel)
      this.showToast('桌面通知级别已保存', 'success')
    },
    async requestNotifyPermission() {
      if (typeof Notification === 'undefined') {
        this.notifyPermission = 'unsupported'
        this.showToast('浏览器不支持通知', 'error')
        return
      }
      const res = await Notification.requestPermission()
      this.notifyPermission = res
      if (res !== 'granted') {
        this.notifyEnabled = false
        localStorage.setItem('newsNotificationEnabled', 'false')
        this.showToast('未授权通知权限，请在浏览器地址栏左侧“锁”图标里允许通知', 'error')
      } else {
        this.showToast('通知权限已授予', 'success')
      }
    },
    testNotify() {
      if (typeof Notification === 'undefined' || Notification.permission !== 'granted') {
        this.showToast('请先授权通知权限', 'error')
        return
      }
      try {
        const n = new Notification('🔔 测试通知', {
          body: '新闻 / 资金异动到达时会这样提醒你（任意页面都生效）',
          icon: 'https://pic.0vk.top/%E8%82%A1%E7%A8%BF.png'
        })
        n.onclick = () => { window.focus(); n.close() }
        this.showToast('已发送测试通知', 'success')
      } catch (e) {
        this.showToast('发送失败：' + e.message, 'error')
      }
    },

    async loadConfigs() {
      try {
        const [aiRes, feishuRes, wechatRes, stockRes, promptRes, dailyPromptRes] = await Promise.all([
          getAIConfig(),
          getFeishuConfig(),
          getWechatConfig(),
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
        if (wechatRes.success) {
          this.wechatConfig = { ...this.wechatConfig, ...wechatRes.data }
        }
        if (stockRes.success) {
          const d = stockRes.data || {}
          this.stockConfig = {
            enabled: d.enabled || false,
            poll_interval_seconds: d.poll_interval_seconds || 25,
            cooldown_minutes: d.cooldown_minutes || 30,
            watchlist: d.watchlist || [],
          }
          this.normalizeWatchlist()
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
        // 密码校验交由服务端（今日动态密码 vk666+月日），前端不再硬编码
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

    async loadAnomalyConfig() {
      try {
        const [cfgRes, blRes] = await Promise.all([getAnomalyConfig(), getAnomalyBaseline()])
        if (cfgRes.success && cfgRes.data) Object.assign(this.anomalyConfig, cfgRes.data)
        if (blRes.success && blRes.data) this.anomalyBaseline = blRes.data
      } catch (e) { /* 401 已由拦截器处理 */ }
    },
    async saveAnomalyConfigCfg() {
      this.anomalySaving = true
      try {
        const res = await saveAnomalyConfig(this.anomalyConfig)
        if (res.success) this.showToast('异动检测配置已保存', 'success')
        else this.showToast(res.message || '保存失败', 'error')
      } catch (e) {
        this.showToast(e.response?.data?.message || '保存失败', 'error')
      } finally { this.anomalySaving = false }
    },
    async rebuildAnomalyBaselineCfg() {
      this.anomalyRebuilding = true
      this.showToast('正在重建基线，需扫描历史数据...', 'info')
      try {
        const res = await rebuildAnomalyBaseline(this.anomalyConfig.baseline_days)
        if (res.success && res.data) {
          this.anomalyBaseline = { ...this.anomalyBaseline, ...res.data }
          this.showToast(`基线重建完成：${res.data.sector_count} 个板块`, 'success')
        } else this.showToast(res.message || '重建失败', 'error')
      } catch (e) {
        this.showToast('重建失败', 'error')
      } finally { this.anomalyRebuilding = false }
    },

    // ===== 数据源设置 =====
    async loadDatasourceConfig() {
      try {
        const res = await getDatasourceConfig()
        if (res.success) {
          this.datasourceList = res.data || []
        }
      } catch (e) { /* 401 handled by interceptor */ }
    },
    async testDatasourceCfg() {
      this.datasourceTesting = true
      this.datasourceTestResults = {}
      this.showToast('正在测试所有数据源...', 'info')
      try {
        const res = await testDatasource()
        if (res.success) {
          this.datasourceTestResults = res.data || {}
          const total = Object.keys(this.datasourceTestResults).length
          const ok = Object.values(this.datasourceTestResults).filter(r => r.ok === true).length
          const fail = Object.values(this.datasourceTestResults).filter(r => r.ok === false).length
          const skip = Object.values(this.datasourceTestResults).filter(r => r.ok === null).length
          this.showToast(`测试完成：${ok}可用 / ${fail}不可用 / ${skip}跳过`, 'success')
        } else {
          this.showToast(res.message || '测试失败', 'error')
        }
      } catch (e) {
        // 区分超时与普通失败：超时时后端可能仍在测，圆点保持未知而非误报
        const msg = e && e.code === 'ECONNABORTED'
          ? '测试超时：请稍后重试（个别数据源响应过慢）'
          : '测试失败'
        this.showToast(msg, 'error')
      } finally { this.datasourceTesting = false }
    },
    datasourceRoleClass(role) {
      if (role === '主') return 'role-primary'
      if (role === '备') return 'role-backup'
      if (role === '互补') return 'role-complement'
      return ''
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

    async saveWechatConfig() {
      this.showPasswordModal(async (password) => {
        try {
          const response = await saveWechatConfig({
            ...this.wechatConfig,
            password: password
          })
          if (response.success) {
            this.showToast('企业微信配置保存成功', 'success')
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

    async testWechatConfig() {
      this.showToast('正在测试企业微信连接...', 'info')

      try {
        const response = await testWechatConnection()

        if (response.success) {
          this.showToast('✅ 企业微信连接测试成功', 'success')
        } else {
          const errorInfo = response.data?.errmsg || JSON.stringify(response.data)
          this.showToast(`❌ HTTP ${response.status_code}: ${errorInfo}`, 'error')
        }
      } catch (error) {
        const message = error.response?.data?.error || error.response?.data?.message || '测试失败，请检查网络连接'
        this.showToast('❌ ' + message, 'error')
      }
    },

    defaultPriceAlerts() {
      const o = {}
      this.PRICE_TYPES.forEach(t => {
        o[t.key] = { enabled: true, ...(t.defaults || {}) }
      })
      return o
    },

    // ---- 添加个股:实时搜索,只能从结果选 ----
    onSearchInput() {
      this.newWatch.highlight = -1
      const kw = (this.newWatch.search || '').trim()
      this.newWatch.showResults = true
      if (this._searchTimer) clearTimeout(this._searchTimer)
      if (!kw) { this.newWatch.results = []; this.newWatch.searching = false; return }
      this.newWatch.searching = true
      this._searchTimer = setTimeout(async () => {
        try {
          const res = await searchStocks(kw)
          this.newWatch.results = (res && res.success ? res.data : []) || []
        } catch (e) {
          this.newWatch.results = []
        } finally {
          this.newWatch.searching = false
        }
      }, 280)
    },
    onSearchKeydown(e) {
      const n = this.newWatch.results.length
      if (!n) return
      if (e.key === 'ArrowDown') { e.preventDefault(); this.newWatch.highlight = (this.newWatch.highlight + 1) % n }
      else if (e.key === 'ArrowUp') { e.preventDefault(); this.newWatch.highlight = (this.newWatch.highlight - 1 + n) % n }
      else if (e.key === 'Enter') { e.preventDefault(); const it = this.newWatch.results[this.newWatch.highlight]; if (it) this.selectStock(it) }
      else if (e.key === 'Escape') { this.newWatch.showResults = false }
    },
    selectStock(item) {
      if (!item || !item.code) return
      // 去重:已存在同代码则提示
      if (this.stockConfig.watchlist.some(w => (w.resolved_code || '') === item.code)) {
        this.showToast(`${item.name} 已在监控列表`, 'error'); return
      }
      const watchItem = {
        id: Math.random().toString(36).slice(2, 12),
        type: 'name', value: item.name, enabled: true,
        resolved_name: item.name, resolved_code: item.code,
        price_monitor: true,
        price_alerts: JSON.parse(JSON.stringify(this.defaultPriceAlerts())),
        news_alerts: { enabled: true, keywords: [item.name, item.code] },
      }
      this.stockConfig.watchlist.unshift(watchItem)
      this.newWatch.search = ''
      this.newWatch.results = []
      this.newWatch.showResults = false
      this.newWatch.highlight = -1
      this.showToast(`已添加 ${item.name}(${item.code})`, 'success')
    },
    addKeywordItem() {
      const kw = (this.newWatch.keyword || '').trim()
      if (!kw) { this.showToast('请输入关键词', 'error'); return }
      if (this.stockConfig.watchlist.some(w => w.type === 'keyword' && w.value === kw)) {
        this.showToast('该关键词已存在', 'error'); return
      }
      this.stockConfig.watchlist.unshift({
        id: Math.random().toString(36).slice(2, 12),
        type: 'keyword', value: kw, enabled: true,
        news_alerts: { enabled: true, keywords: [kw] },
      })
      this.newWatch.keyword = ''
      this.showToast(`已添加关键词「${kw}」`, 'success')
    },
    addWatchItem() { // 兼容保留:当前模式触发对应添加
      if (this.newWatch.mode === 'keyword') this.addKeywordItem()
    },
    switchWatchMode(m) {
      this.newWatch.mode = m
      this.newWatch.results = []
      this.newWatch.showResults = false
    },
    blurSearch() { setTimeout(() => { this.newWatch.showResults = false }, 180) },

    // ---- 新闻关键词管理 ----
    addKeyword(w) {
      const kw = (w._newKeyword || '').trim()
      if (!kw) return
      if (!w.news_alerts) w.news_alerts = { enabled: true, keywords: [] }
      if (!w.news_alerts.keywords.includes(kw)) w.news_alerts.keywords.push(kw)
      w._newKeyword = ''
    },
    removeKeyword(w, idx) {
      if (w.news_alerts && w.news_alerts.keywords) w.news_alerts.keywords.splice(idx, 1)
    },
    onNewsToggle(w) {
      // 开启新闻监控时确保有默认关键词(名字+代码)
      if (w.news_alerts && w.news_alerts.enabled && (!w.news_alerts.keywords || !w.news_alerts.keywords.length)) {
        const base = [w.resolved_name, w.resolved_code].filter(x => x)
        if (base.length) w.news_alerts.keywords = base
      }
    },

    // 兜底:确保已加载的 watchlist item 都有 news_alerts/price_monitor 结构
    normalizeWatchlist() {
      for (const w of this.stockConfig.watchlist) {
        if (!w.news_alerts || typeof w.news_alerts !== 'object') {
          const base = w.type === 'keyword' ? [w.value].filter(x => x)
            : [w.resolved_name, w.resolved_code].filter(x => x)
          w.news_alerts = { enabled: w.type === 'keyword', keywords: base }
        }
        if (w.type !== 'keyword' && w.price_monitor === undefined) w.price_monitor = true
      }
    },

    removeWatchItem(id) {
      this.stockConfig.watchlist = this.stockConfig.watchlist.filter(w => w.id !== id)
      this.selectedIds = this.selectedIds.filter(x => x !== id)
    },

    enabledCount(w) {
      if (!w.price_alerts) return 0
      return this.PRICE_TYPES.filter(t => w.price_alerts[t.key] && w.price_alerts[t.key].enabled).length
    },

    batchToggle(field, value) {
      this.stockConfig.watchlist
        .filter(w => this.selectedIds.includes(w.id) && w.price_alerts && w.price_alerts[field])
        .forEach(w => { w.price_alerts[field].enabled = value })
    },

    async saveStockConfig() {
      this.showPasswordModal(async (password) => {
        try {
          // 剥离临时 UI 字段(_newKeyword),只持久化数据
          const watchlist = this.stockConfig.watchlist.map(w => {
            const { _newKeyword, ...rest } = w
            return rest
          })
          const config = { ...this.stockConfig, watchlist, password: password }
          const response = await saveStockMonitorConfig(config)
          if (response.success) {
            this.showToast('股票监控配置保存成功', 'success')
          } else {
            this.showToast(response.message || '保存失败', 'error')
          }
        } catch (error) {
          if (error.response?.status === 401) {
            this.showToast('密码错误', 'error')
          } else {
            this.showToast(error.response?.data?.message || '保存失败', 'error')
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

    // ===== OTP 动态口令（TOTP）二次验证 =====
    async loadOtpStatus() {
      try {
        const res = await getOtpStatus()
        if (res && res.success) {
          this.otpConfig = { enabled: !!res.data?.enabled, enrolled_at: res.data?.enrolled_at || '' }
        }
      } catch (e) {
        // 静默失败：不影响其他配置加载
      }
    },
    async startOtpSetup() {
      if (this.otpLoading) return
      this.otpLoading = true
      this.otpCodeInput = ''
      try {
        const res = await getOtpSetup()
        if (res && res.success && res.data) {
          this.otpSetup = {
            secret: res.data.secret || '',
            qr_data_url: res.data.qr_data_url || '',
            otpauth_uri: res.data.otpauth_uri || ''
          }
          this.showToast('请用手机 Authenticator 扫描二维码', 'info')
        } else {
          this.showToast(res?.message || '生成二维码失败', 'error')
        }
      } catch (e) {
        this.showToast(e.response?.data?.message || '生成二维码失败', 'error')
      } finally {
        this.otpLoading = false
      }
    },
    cancelOtpSetup() {
      this.otpSetup = { secret: '', qr_data_url: '', otpauth_uri: '' }
      this.otpCodeInput = ''
    },
    confirmEnableOtpClick() {
      // 先校验前端输入，再走密码弹窗收集日密码
      if (!this.otpSetup.secret) {
        this.showToast('请先点击「生成二维码」', 'error')
        return
      }
      if (!this.otpCodeInput || this.otpCodeInput.length < 6) {
        this.showToast('请输入手机上显示的 6 位动态口令', 'error')
        return
      }
      this.showPasswordModal((password) => this.confirmEnableOtp(password))
    },
    async confirmEnableOtp(password) {
      if (this.otpLoading) return
      this.otpLoading = true
      try {
        const res = await enableOtp(password, this.otpSetup.secret, this.otpCodeInput)
        if (res && res.success) {
          this.showToast(res.message || 'OTP 已开启，需要重新登录', 'success')
          this.cancelOtpSetup()
          // 开启后后端已旋转密钥并清空会话：此处刷新状态会 401，
          // 触发全局 auth-required 事件 → 自动唤起带 OTP 输入框的登录弹窗。
          await this.loadOtpStatus()
        } else {
          this.showToast(res?.message || '开启失败', 'error')
        }
      } catch (e) {
        this.showToast(e.response?.data?.message || '开启失败', 'error')
      } finally {
        this.otpLoading = false
      }
    },
    confirmDisableOtpClick() {
      if (!this.otpConfig.enabled) return
      if (!this.otpCodeInput || this.otpCodeInput.length < 6) {
        this.showToast('请输入当前手机上显示的 6 位动态口令', 'error')
        return
      }
      this.showPasswordModal((password) => this.doDisableOtp(password))
    },
    async doDisableOtp(password) {
      if (this.otpLoading) return
      this.otpLoading = true
      try {
        const res = await disableOtp(password, this.otpCodeInput)
        if (res && res.success) {
          this.showToast(res.message || 'OTP 已关闭', 'success')
          this.otpCodeInput = ''
          await this.loadOtpStatus()
        } else {
          this.showToast(res?.message || '关闭失败', 'error')
        }
      } catch (e) {
        this.showToast(e.response?.data?.message || '关闭失败', 'error')
      } finally {
        this.otpLoading = false
      }
    },

    showPasswordModal(callback, hint = '') {
      this.passwordModal = {
        show: true,
        password: '',
        callback: callback,
        hint: hint
      }
    },

    closePasswordModal() {
      this.passwordModal = {
        show: false,
        password: '',
        callback: null,
        hint: ''
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
    },

    // ===== 部署运维:页面按钮触发 SSH 部署(deploy_remote.py 的页面化) =====
    startDeploy() {
      if (this.deployStatus.phase === 'recovering') return
      this.showPasswordModal(
        (password) => this.confirmDeploy(password),
        '请输入服务器 SSH 密码以触发部署'
      )
    },

    async confirmDeploy(password) {
      this.deployStatus = { phase: 'recovering', message: '🚀 正在触发部署…' }
      try {
        const res = await deployDockerRestart(password)
        if (!res || !res.success) {
          this.deployStatus = { phase: 'idle', message: '' }
          this.showToast((res && res.message) || '触发失败', 'error')
          return
        }
        this.deployStatus = {
          phase: 'recovering',
          message: '🚀 部署已触发,服务中断 1-3 分钟,正在等待恢复(每 10 秒探测)…'
        }
        this.pollDeployRecovery()
      } catch (e) {
        // 网络层错误有两种:密码错(后端 401 已带 message)或部署已启动、连接被断。
        // 后者其实是常态竞态:远程脚本 git pull 很快时,`docker compose down` 可能在
        // HTTP 响应送回前端之前就杀掉了本容器 → axios 报 network error →
        // 若直接报"触发失败"用户会误以为部署失败(实际宿主机脚本在后台继续,
        // 最终部署成功)。因此 network error(无 response)不报红字,转入恢复轮询
        // 让 /deploy/status 说话:failed 会如实显示死因,done 显示成功。
        const msg = (e && e.response && e.response.data && e.response.data.message)
        if (!e.response) {
          this.deployStatus = {
            phase: 'recovering',
            message: '⚠️ 触发后连接中断(部署脚本通常已在后台执行),正在探测实际状态…'
          }
          this.pollDeployRecovery()
          return
        }
        this.deployStatus = { phase: 'idle', message: '' }
        this.showToast(msg || '触发失败:连接异常', 'error')
      }
    },

    pollDeployRecovery(attempt = 0) {
      // 部署真实进度以 /deploy/status 为准(宿主机脚本每步写状态文件,volume
      // 挂载可见):pull 失败等"容器根本没重启"的场景,状态会停在 failed——
      // 页面立刻显示死因,而不是永远"部署中"。仅当状态不可读(后端随容器
      // 重启/暂时失联)时,退回 /health 探测:动态接口,nginx+backend 都活着
      // 才 200;连续 2 次 OK = 已恢复;上限 10 分钟。
      // fetch 必须带超时:容器 down 期间端口可能黑洞式挂起,一个不超时的
      // fetch 会把整条轮询链卡住数分钟——表现为"页面明明能访问了,按钮一直
      // '部署中'"。
      if (attempt >= 60) {
        this.deployStatus = {
          phase: 'done',
          message: '⏱ 等待超时(10 分钟),请手动刷新页面确认服务状态'
        }
        return
      }
      setTimeout(() => {
        getDeployStatus()
          .then((res) => {
            if (res && res.success) {
              if (res.phase === 'failed') {
                this._deployOkCount = 0
                this.deployStatus = {
                  phase: 'failed',
                  message: '❌ 部署失败: ' + (res.detail || '未知原因') +
                    '(可在服务器 /root/manual_deploy.log 看完整日志)'
                }
                return   // 停止轮询;按钮未禁用,可直接重试
              }
              if (res.phase === 'done') {
                this._deployOkCount = 0
                this.deployStatus = {
                  phase: 'done',
                  message: '✅ 部署完成!刷新页面即可使用最新版本'
                }
                this.loadDeployVersion(true)
                return
              }
              // triggered/pulling/pull_retry/building:真实进行中,显示阶段并继续
              const labels = {
                triggered: '🚀 已触发,正在启动部署脚本…',
                pulling: '⬇️ 正在拉取最新代码…',
                pull_retry: '⚠️ 拉取失败重试中',
                building: '🔧 正在重建容器(1-3 分钟)…'
              }
              this.deployStatus = {
                phase: 'recovering',
                message: (labels[res.phase] || '部署中') +
                  (res.phase === 'pull_retry' && res.detail ? '(' + res.detail + ')' : '')
              }
              this.pollDeployRecovery(attempt + 1)
              return
            }
            // 状态接口返回异常:退回 /health 探测
            this._pollByHealth(attempt)
          })
          .catch(() => {
            // 后端不可达(容器重启中):/health 探测恢复
            this._pollByHealth(attempt)
          })
      }, 10000)
    },

    _pollByHealth(attempt) {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 8000)
      fetch('/health', { method: 'HEAD', cache: 'no-store', signal: ctrl.signal })
        .then((r) => {
          clearTimeout(timer)
          if (!r.ok) throw new Error('not-ok')   // 5xx/CDN 错误页不算恢复
          this._deployOkCount = (this._deployOkCount || 0) + 1
          if (this._deployOkCount >= 2) {
            this._deployOkCount = 0
            this.deployStatus = {
              phase: 'done',
              message: '✅ 服务已恢复,部署完成!刷新页面即可使用最新版本'
            }
            this.loadDeployVersion(true)
          } else {
            this.pollDeployRecovery(attempt + 1)
          }
        })
        .catch(() => {
          clearTimeout(timer)
          this._deployOkCount = 0
          this.pollDeployRecovery(attempt + 1)
        })
    },

    // ===== 部署运维:版本信息(当前部署 vs GitHub main,只读) =====
    startDeployVersionPolling() {
      if (this._deployVersionTimer) return
      if (!this.deployVersion.data && !this.deployVersion.loading) this.loadDeployVersion()
      // 不带 fresh:命中后端 180s 缓存,轮询不消耗 GitHub API 限额(匿名仅 60/h);
      // 立即拉新用面板"刷新"按钮或部署完成回调(均带 fresh)
      this._deployVersionTimer = setInterval(() => {
        // 部署进行中后端随容器重启,请求必然失败:跳过,恢复完成时单独拉新
        if (this.deployStatus.phase === 'recovering') return
        this.loadDeployVersion()
      }, 60000)
    },
    stopDeployVersionPolling() {
      if (this._deployVersionTimer) {
        clearInterval(this._deployVersionTimer)
        this._deployVersionTimer = null
      }
    },

    async loadDeployVersion(fresh = false) {
      this.deployVersion = { loading: true, data: this.deployVersion.data, error: null }
      try {
        const res = await getDeployVersionInfo(fresh)
        if (res && res.success) {
          this.deployVersion = { loading: false, data: res, error: null }
        } else {
          // 失败保留上一份好数据(轮询期间网络抖动不闪空白),仅换错误横幅
          this.deployVersion = {
            loading: false, data: this.deployVersion.data,
            error: (res && res.message) || '获取版本信息失败'
          }
        }
      } catch (e) {
        this.deployVersion = {
          loading: false, data: this.deployVersion.data,
          error: '获取版本信息失败:连接异常'
        }
      }
    },
    fmtCommitTime(iso) {
      if (!iso) return ''
      const d = new Date(iso)
      if (isNaN(d.getTime())) return iso
      const p = (n) => String(n).padStart(2, '0')
      return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
    }
  }
}
