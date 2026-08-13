import {
  getAuthSession,
  listRedeemCodes,
  createRedeemCodes,
  revokeRedeemCode,
  deleteRedeemCode
} from '../../services/apiService'

// 落地页选项（对应前端路由）
const PAGE_OPTIONS = [
  { path: '/', name: '首页' },
  { path: '/market-map', name: '大盘云图' },
  { path: '/news', name: '新闻' },
  { path: '/flow-alert', name: '异动预警' },
  { path: '/ai-chain', name: 'AI链条' },
  { path: '/industry-cycle', name: '行业见顶诊断' },
  { path: '/house-kline', name: '房价K线' },
  { path: '/global-market', name: '全球股市' }
]

export default {
  name: 'RedeemCode',
  data() {
    return {
      loading: true,
      isAdmin: false,
      poolSize: 10,
      activeCodes: [],
      usedCodes: [],
      newCodes: [],
      generating: false,
      pageOptions: PAGE_OPTIONS,
      form: {
        label: '',
        page: '/market-map',
        duration: '10min',
        count: 1
      },
      pwdModal: {
        show: false,
        title: '',
        desc: '',
        password: '',
        busy: false,
        confirm: () => {}
      },
      toast: { show: false, message: '', type: 'info', timer: null }
    }
  },
  computed: {
    canGenerate() {
      return Math.max(0, this.poolSize - this.activeCodes.length)
    }
  },
  async mounted() {
    try {
      const session = await getAuthSession()
      this.isAdmin = !!(session && session.is_admin)
      if (this.isAdmin) {
        await this.refresh()
      }
    } catch (e) {
      this.isAdmin = false
    } finally {
      this.loading = false
    }
  },
  methods: {
    goBack() {
      if (this.$router) this.$router.push('/')
    },
    async refresh() {
      try {
        const data = await listRedeemCodes()
        if (data && data.success) {
          this.poolSize = data.pool_size || 10
          this.activeCodes = data.active || []
          this.usedCodes = data.used || []
        }
      } catch (e) {
        this.showToast('加载失败', 'error')
      }
    },
    pageName(path) {
      const p = PAGE_OPTIONS.find(x => x.path === path)
      return p ? p.name : path
    },
    durationName(d) {
      return ({ '10min': '10分钟', '30min': '半小时', '1day': '一天', 'permanent': '永久' })[d] || d
    },
    statusName(s) {
      return ({ active: '使用中', expired: '已过期', revoked: '已撤销' })[s] || s
    },
    formatExpire(ts) {
      if (!ts) return '--'
      try {
        const d = new Date(ts * 1000)
        // 按北京时间展示
        return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
      } catch (e) {
        return '--'
      }
    },
    shareLink(code) {
      return `${window.location.origin}/?redeem=${code}`
    },
    async copyLink(link) {
      try {
        await navigator.clipboard.writeText(link)
        this.showToast('链接已复制', 'ok')
      } catch (e) {
        // 降级：选中文本
        this.showToast('复制失败，请手动复制：' + link, 'error')
      }
    },
    onGenerateClick() {
      if (!this.form.label.trim()) { this.showToast('请填写标签', 'error'); return }
      if (this.form.count < 1) { this.showToast('数量至少 1', 'error'); return }
      if (this.form.count > this.canGenerate) {
        this.showToast(`最多还可生成 ${this.canGenerate} 个`, 'error'); return
      }
      // 永久档二次确认
      if (this.form.duration === 'permanent') {
        if (!window.confirm('「永久」意味着首个兑换者获得终身访问，与限时体验初衷不同。确认生成永久码？')) {
          return
        }
      }
      this.openPwdModal('生成体验码', `将生成 ${this.form.count} 张「${this.form.label}」${this.durationName(this.form.duration)}体验码`, this.doGenerate)
    },
    async doGenerate() {
      const password = this.pwdModal.password
      this.pwdModal.busy = true
      try {
        const res = await createRedeemCodes(password, this.form.label.trim(), this.form.page, this.form.duration, this.form.count)
        if (res && res.success) {
          this.newCodes = res.codes || []
          this.pwdModal.show = false
          this.pwdModal.password = ''
          this.showToast(`已生成 ${this.newCodes.length} 张`, 'ok')
          await this.refresh()
        } else {
          this.showToast((res && res.message) || '生成失败', 'error')
        }
      } catch (e) {
        const data = e && e.response && e.response.data
        this.showToast((data && data.message) || '生成失败', 'error')
      } finally {
        this.pwdModal.busy = false
      }
    },
    onRevokeClick(code) {
      this.openPwdModal('撤销体验码', `撤销 ${code}：若有人正凭此码在线，将立即失去访问权限。`, async () => {
        this.pwdModal.busy = true
        try {
          const res = await revokeRedeemCode(this.pwdModal.password, code)
          if (res && res.success) {
            this.pwdModal.show = false
            this.pwdModal.password = ''
            this.showToast('已撤销', 'ok')
            await this.refresh()
          } else {
            this.showToast((res && res.message) || '撤销失败', 'error')
          }
        } catch (e) {
          const data = e && e.response && e.response.data
          this.showToast((data && data.message) || '撤销失败', 'error')
        } finally {
          this.pwdModal.busy = false
        }
      })
    },
    onDeleteClick(code) {
      this.openPwdModal('删除历史记录', `彻底删除 ${code}（从历史移除，不可恢复）。`, async () => {
        this.pwdModal.busy = true
        try {
          const res = await deleteRedeemCode(this.pwdModal.password, code)
          if (res && res.success) {
            this.pwdModal.show = false
            this.pwdModal.password = ''
            this.showToast('已删除', 'ok')
            await this.refresh()
          } else {
            this.showToast((res && res.message) || '删除失败', 'error')
          }
        } catch (e) {
          const data = e && e.response && e.response.data
          this.showToast((data && data.message) || '删除失败', 'error')
        } finally {
          this.pwdModal.busy = false
        }
      })
    },
    openPwdModal(title, desc, confirmFn) {
      this.pwdModal.title = title
      this.pwdModal.desc = desc || ''
      this.pwdModal.password = ''
      this.pwdModal.busy = false
      this.pwdModal.confirm = confirmFn
      this.pwdModal.show = true
    },
    showToast(message, type) {
      this.toast.message = message
      this.toast.type = type || 'info'
      this.toast.show = true
      if (this.toast.timer) clearTimeout(this.toast.timer)
      this.toast.timer = setTimeout(() => { this.toast.show = false }, 2500)
    }
  }
}
