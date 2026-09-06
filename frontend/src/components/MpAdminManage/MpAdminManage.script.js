import {
  getAuthSession,
  getMpAdminScores, mpAdminScoreUpdate, mpAdminScoreDelete, mpAdminScoreCreate,
  getMpAdminStats, mpAdminStatSave, mpAdminStatDelete,
  getMpAdminRooms, mpAdminRoomDelete, mpAdminCleanupDevData,
  getMpAdminEcho, mpAdminEchoCreate, mpAdminEchoDelete, mpAdminEchoSeed,
  getMpAdminEchoBans, mpAdminEchoBan, mpAdminEchoUnban, getMpAdminEchoSubs
} from '../../services/apiService'

export default {
  name: 'MpAdminManage',
  data() {
    return {
      loading: true,
      isAdmin: false,
      tab: 'scores',
      scoresFilter: '',
      scores: { items: [], page: 1, totalPages: 1, total: 0 },
      stats: { items: [], sum: 0 },
      statsType: 'test',   // 参与计数子分类:test测试 / tool工具 / article文章
      rooms: { items: [], page: 1, totalPages: 1, total: 0 },
      roomsDays: 7,
      echo: { items: [], page: 1, totalPages: 1, total: 0 },
      echoWall: '',
      echoDays: 7,
      echoCreate: { show: false, busy: false, wall_id: '', nickname: '', text: '', category: '其他' },
      echoCats: ['情感', '压力', '成长', '校园', '生活', '职场', '树洞', '其他'],
      bans: { items: [], page: 1, totalPages: 1, total: 0, loaded: false },
      banEdit: { show: false, busy: false, openid: '', days: 0, reason: '' },
      // 抱抱推送订阅额度(剩余额度>0的用户;loaded 防止重复拉取)
      subs: { items: [], total: 0, totalQuota: 0, loaded: false },
      newStat: { key: '', count: 0 },
      scoreEdit: {
        show: false, busy: false, quiz_id: '', openid: '',
        nickname: '', score: 0, full_score: 100, duration_ms: 0
      },
      scoreCreate: {
        show: false, busy: false, quiz_id: '', openid: '',
        nickname: '', score: 0, full_score: 100, duration_ms: 0
      },
      statEdit: { show: false, busy: false, key: '', count: 0 },
      // 二次确认框(删除/清理等破坏性操作):后台仅 vk 可见,不再二次输密码
      confirmBox: { show: false, title: '', desc: '', busy: false, confirm: () => {} },
      toast: { show: false, message: '', type: 'info', timer: null }
    }
  },
  computed: {
    // 参与计数子分类中文名(模板汇总/空态共用)
    statsTypeName() {
      return { test: '测试', tool: '工具', article: '文章' }[this.statsType] || '计数'
    }
  },
  async mounted() {
    try {
      const session = await getAuthSession()
      this.isAdmin = !!(session && session.is_admin)
      if (this.isAdmin) {
        await this.loadScores(1)
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
    goTrend() {
      this.$router.push('/mp-admin')
    },
    switchTab(tab) {
      this.tab = tab
      if (tab === 'scores' && !this.scores.items.length) this.loadScores(1)
      if (tab === 'stats' && !this.stats.items.length) this.loadStats()
      if (tab === 'rooms' && !this.rooms.items.length) this.loadRooms(1)
      if (tab === 'echo') {
        if (!this.echo.items.length) this.loadEcho(1)
        if (!this.bans.loaded) {
          this.bans.loaded = true
          this.loadBans(1)
        }
      }
      if (tab === 'subs' && !this.subs.loaded) {
        this.subs.loaded = true
        this.loadSubs()
      }
    },
    switchStatsType(type) {
      if (this.statsType === type) return
      this.statsType = type
      this.loadStats()
    },

    // ---- 数据加载 ----
    async loadScores(page = 1) {
      if (page < 1) return
      try {
        const res = await getMpAdminScores({
          quizId: this.scoresFilter.trim(), page, pageSize: 20
        })
        if (res && res.success) {
          const d = res.data
          this.scores = {
            items: d.items,
            page: d.page,
            totalPages: d.total_pages,
            total: d.total
          }
        } else {
          this.showToast((res && res.message) || '加载失败', 'error')
        }
      } catch (e) {
        this.showReqError(e, '加载失败')
      }
    },
    async loadStats() {
      try {
        const res = await getMpAdminStats(this.statsType)
        if (res && res.success) {
          this.stats = { items: res.data.items, sum: res.data.sum || 0 }
        }
      } catch (e) {
        this.showReqError(e, '加载失败')
      }
    },
    async loadRooms(page = 1) {
      if (page < 1) return
      try {
        const res = await getMpAdminRooms({ page, pageSize: 20, days: this.roomsDays })
        if (res && res.success) {
          const d = res.data
          this.rooms = {
            items: d.items,
            page: d.page,
            totalPages: d.total_pages,
            total: d.total
          }
        }
      } catch (e) {
        this.showReqError(e, '加载失败')
      }
    },
    async loadEcho(page = 1) {
      if (page < 1) return
      try {
        const res = await getMpAdminEcho({
          page, pageSize: 20, days: this.echoDays,
          wallId: this.echoWall.trim()
        })
        if (res && res.success) {
          const d = res.data
          // 删除末页最后一条后当前页越界:后端按空页返回,这里退回最后一页重查
          if (page > 1 && d.total_pages && d.page > d.total_pages) {
            return this.loadEcho(d.total_pages)
          }
          this.echo = {
            items: d.items,
            page: d.page,
            totalPages: d.total_pages,
            total: d.total
          }
        }
      } catch (e) {
        this.showReqError(e, '加载失败')
      }
    },

    // ---- 弹幕墙留言管理 ----
    openEchoCreate() {
      this.echoCreate = {
        show: true, busy: false,
        wall_id: this.echoWall.trim() || String(new Date().toISOString().slice(0, 10).replace(/-/g, '')),
        nickname: '', text: '', category: '其他'
      }
    },
    async doEchoCreate() {
      const s = this.echoCreate
      if (!s.wall_id.trim()) { this.showToast('请填写 wall_id', 'error'); return }
      if (!s.text.trim()) { this.showToast('请填写留言内容', 'error'); return }
      if (s.text.trim().length > 50) { this.showToast('留言最多50字', 'error'); return }
      s.busy = true
      try {
        const res = await mpAdminEchoCreate({
          wall_id: s.wall_id.trim(),
          text: s.text.trim(),
          nickname: s.nickname.trim(),
          category: this.echoCats.includes(s.category) ? s.category : '其他'
        })
        if (res && res.success) {
          s.show = false
          s.text = ''
          this.showToast('已发布', 'ok')
          await this.loadEcho(1)
        } else {
          this.showToast((res && res.message) || '发布失败', 'error')
        }
      } catch (e) {
        this.showReqError(e, '发布失败')
      } finally {
        s.busy = false
      }
    },
    onEchoDelete(row) {
      this.openConfirm('删除留言', `删除「${row.text.slice(0, 20)}${row.text.length > 20 ? '…' : ''}」（抱抱 ${row.hugs}，不可恢复）`, async () => {
        this.confirmBox.busy = true
        try {
          const res = await mpAdminEchoDelete(row.id)
          if (res && res.success) {
            this.confirmBox.show = false
            this.showToast('已删除', 'ok')
            await this.loadEcho(this.echo.page)
          } else {
            this.showToast((res && res.message) || '删除失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '删除失败')
        } finally {
          this.confirmBox.busy = false
        }
      })
    },

    onEchoSeed() {
      const wallId = this.echoWall.trim() ||
        String(new Date().toISOString().slice(0, 10).replace(/-/g, ''))
      this.openConfirm('导入种子数据',
        `向墙 ${wallId} 写入 20 条内置共鸣留言（昵称/内容/抱抱数固定，标记为种子数据，全局仅可导入一次）`,
        async () => {
          this.confirmBox.busy = true
          try {
            const res = await mpAdminEchoSeed(wallId)
            if (res && res.success) {
              this.confirmBox.show = false
              this.showToast(`已导入 ${res.count} 条种子留言`, 'ok')
              await this.loadEcho(1)
            } else {
              this.showToast((res && res.message) || '导入失败', 'error')
            }
          } catch (e) {
            this.showReqError(e, '导入失败')
          } finally {
            this.confirmBox.busy = false
          }
        })
    },

    // ---- 弹幕墙用户封禁 ----
    async loadBans(page = 1) {
      if (page < 1) return
      try {
        const res = await getMpAdminEchoBans({ page, pageSize: 20 })
        if (res && res.success) {
          const d = res.data
          // 删除末页最后一条后当前页越界:退回最后一页重查(与 loadEcho 同策略)
          if (page > 1 && d.total_pages && d.page > d.total_pages) {
            return this.loadBans(d.total_pages)
          }
          this.bans = {
            ...this.bans,
            items: d.items,
            page: d.page,
            totalPages: d.total_pages,
            total: d.total
          }
        }
      } catch (e) {
        this.showReqError(e, '加载封禁列表失败')
      }
    },
    openEchoBan(row) {
      // row 传入=从留言行封禁(带出该用户 openid);不传=手动输入
      this.banEdit = { show: true, busy: false, openid: row ? row.openid : '', days: 0, reason: '' }
    },
    async doEchoBan() {
      const s = this.banEdit
      if (!/^[A-Za-z0-9_-]{1,64}$/.test(s.openid.trim())) {
        this.showToast('openid 不合法（字母/数字/-/_，1~64位）', 'error'); return
      }
      s.busy = true
      try {
        const res = await mpAdminEchoBan({
          openid: s.openid.trim(),
          days: s.days || undefined,
          reason: s.reason.trim() || undefined
        })
        if (res && res.success) {
          s.show = false
          this.showToast(s.days ? `已封禁 ${s.days} 天` : '已永久封禁', 'ok')
          // 同步刷新两处:封禁列表 + 留言行按钮变「解封」
          const jobs = [this.loadBans(1)]
          if (this.echo.items.length) jobs.push(this.loadEcho(this.echo.page))
          await Promise.all(jobs)
        } else {
          this.showToast((res && res.message) || '封禁失败', 'error')
        }
      } catch (e) {
        this.showReqError(e, '封禁失败')
      } finally {
        s.busy = false
      }
    },
    onEchoUnban(row) {
      this.openConfirm('解封用户', `解封 ${this.shortOpenid(row.openid)}，恢复其发布留言权限`, async () => {
        this.confirmBox.busy = true
        try {
          const res = await mpAdminEchoUnban(row.openid)
          if (res && res.success) {
            this.confirmBox.show = false
            this.showToast(res.message || '已解封', 'ok')
            // 同步刷新两处:封禁列表移除该行 + 留言行按钮变回「封禁」
            const jobs = [this.loadBans(this.bans.page)]
            if (this.echo.items.length) jobs.push(this.loadEcho(this.echo.page))
            await Promise.all(jobs)
          } else {
            this.showToast((res && res.message) || '解封失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '解封失败')
        } finally {
          this.confirmBox.busy = false
        }
      })
    },
    banStatusName(row) {
      if (row.expires_at == null) return '永久'
      const left = row.expires_at - Math.floor(Date.now() / 1000)
      if (left <= 0) return '已过期'
      return `剩余${Math.ceil(left / 86400)}天`
    },

    // ---- 抱抱推送订阅额度 ----
    async loadSubs() {
      try {
        const res = await getMpAdminEchoSubs()
        if (res && res.success) {
          this.subs = {
            ...this.subs,
            items: res.data.items,
            total: res.data.total,
            totalQuota: res.data.total_quota
          }
        }
      } catch (e) {
        this.showReqError(e, '加载订阅额度失败')
      }
    },

    // ---- 成绩新增/编辑/删除 ----
    openScoreCreate() {
      this.scoreCreate = {
        show: true, busy: false,
        quiz_id: this.scoresFilter.trim(), openid: '',
        nickname: '', score: 0, full_score: 100, duration_ms: 0
      }
    },
    async doScoreCreate() {
      const s = this.scoreCreate
      if (!s.quiz_id.trim() || !s.openid.trim()) {
        this.showToast('测试ID 和 openid 必填', 'error'); return
      }
      if (!s.nickname || !s.nickname.trim() || s.nickname.trim().length > 12) {
        this.showToast('昵称不合法（1~12字）', 'error'); return
      }
      if (s.score < 0 || s.full_score < 1 || s.score > s.full_score) {
        this.showToast('分数不合法（0 ≤ 分数 ≤ 满分）', 'error'); return
      }
      if (s.duration_ms < 0) {
        this.showToast('用时不合法', 'error'); return
      }
      s.busy = true
      try {
        const res = await mpAdminScoreCreate({
          quiz_id: s.quiz_id.trim(), openid: s.openid.trim(),
          nickname: s.nickname.trim(), score: s.score,
          full_score: s.full_score, duration_ms: s.duration_ms
        })
        if (res && res.success) {
          s.show = false
          this.showToast('已新增', 'ok')
          await this.loadScores(1)
        } else {
          this.showToast((res && res.message) || '新增失败', 'error')
        }
      } catch (e) {
        this.showReqError(e, '新增失败')
      } finally {
        s.busy = false
      }
    },
    openScoreEdit(row) {
      this.scoreEdit = {
        show: true, busy: false,
        quiz_id: row.quiz_id, openid: row.openid,
        nickname: row.nickname, score: row.score,
        full_score: row.full_score, duration_ms: row.duration_ms
      }
    },
    async doScoreEdit() {
      const s = this.scoreEdit
      if (s.score < 0 || s.full_score < 1 || s.score > s.full_score) {
        this.showToast('分数不合法（0 ≤ 分数 ≤ 满分）', 'error'); return
      }
      if (!s.nickname || !s.nickname.trim() || s.nickname.trim().length > 12) {
        this.showToast('昵称不合法（1~12字）', 'error'); return
      }
      s.busy = true
      try {
        const res = await mpAdminScoreUpdate({
          quiz_id: s.quiz_id, openid: s.openid,
          nickname: s.nickname.trim(), score: s.score,
          full_score: s.full_score, duration_ms: s.duration_ms
        })
        if (res && res.success) {
          s.show = false
          this.showToast('已保存', 'ok')
          await this.loadScores(this.scores.page)
        } else {
          this.showToast((res && res.message) || '保存失败', 'error')
        }
      } catch (e) {
        this.showReqError(e, '保存失败')
      } finally {
        s.busy = false
      }
    },
    onScoreDelete(row) {
      this.openConfirm('删除成绩', `删除 ${row.quiz_id} / ${this.shortOpenid(row.openid)} 的成绩（不可恢复）`, async () => {
        this.confirmBox.busy = true
        try {
          const res = await mpAdminScoreDelete(row.quiz_id, row.openid)
          if (res && res.success) {
            this.confirmBox.show = false
            this.showToast('已删除', 'ok')
            await this.loadScores(this.scores.page)
          } else {
            this.showToast((res && res.message) || '删除失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '删除失败')
        } finally {
          this.confirmBox.busy = false
        }
      })
    },

    // ---- 计数管理 ----
    async onStatAdd() {
      const key = this.newStat.key.trim()
      if (!key) { this.showToast('请填写 key', 'error'); return }
      if (!/^[a-z0-9_]{1,64}$/.test(key.toLowerCase())) {
        this.showToast('key 只能是小写字母/数字/下划线', 'error'); return
      }
      try {
        const res = await mpAdminStatSave(key, this.newStat.count)
        if (res && res.success) {
          this.newStat = { key: '', count: 0 }
          this.showToast('已保存', 'ok')
          await this.loadStats()
        } else {
          this.showToast((res && res.message) || '保存失败', 'error')
        }
      } catch (e) {
        this.showReqError(e, '保存失败')
      }
    },
    openStatEdit(row) {
      this.statEdit = { show: true, busy: false, key: row.key, count: row.count }
    },
    async doStatEdit() {
      const s = this.statEdit
      if (!(s.count >= 0)) { this.showToast('数值不合法', 'error'); return }
      s.busy = true
      try {
        const res = await mpAdminStatSave(s.key, s.count)
        if (res && res.success) {
          s.show = false
          this.showToast('已保存', 'ok')
          await this.loadStats()
        } else {
          this.showToast((res && res.message) || '保存失败', 'error')
        }
      } catch (e) {
        this.showReqError(e, '保存失败')
      } finally {
        s.busy = false
      }
    },
    onStatDelete(row) {
      this.openConfirm('删除计数', `删除 ${row.key}（当前 ${row.count} 次，不可恢复）`, async () => {
        this.confirmBox.busy = true
        try {
          const res = await mpAdminStatDelete(row.key)
          if (res && res.success) {
            this.confirmBox.show = false
            this.showToast('已删除', 'ok')
            await this.loadStats()
          } else {
            this.showToast((res && res.message) || '删除失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '删除失败')
        } finally {
          this.confirmBox.busy = false
        }
      })
    },

    // ---- 房间管理 ----
    onRoomDelete(row) {
      this.openConfirm('删除房间', `删除房间 ${row.room_code}（不可恢复）`, async () => {
        this.confirmBox.busy = true
        try {
          const res = await mpAdminRoomDelete(row.room_code)
          if (res && res.success) {
            this.confirmBox.show = false
            this.showToast('已删除', 'ok')
            await this.loadRooms(this.rooms.page)
          } else {
            this.showToast((res && res.message) || '删除失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '删除失败')
        } finally {
          this.confirmBox.busy = false
        }
      })
    },

    // ---- 清理开发联调数据 ----
    onCleanupClick() {
      this.openConfirm('清理联调数据',
        '删除遗留 quiz（selftest_tmp / wealth）、联调 openid（vkself* / otest*）的成绩与房间、按流水回滚其计数、tool_probe_diag 清零。可重复执行。',
        async () => {
          this.confirmBox.busy = true
          try {
            const res = await mpAdminCleanupDevData()
            if (res && res.success) {
              this.confirmBox.show = false
              const r = res.result || {}
              const dec = Object.keys(r.decremented || {})
                .map(k => `${k} -${r.decremented[k]}`).join('、')
              this.showToast(
                `清理完成：成绩 ${r.scores} 条、房间 ${r.rooms} 个` +
                (dec ? `；计数回滚 ${dec}` : '') +
                (r.probe_cleared ? '；探针已清零' : ''), 'ok')
              await this.loadStats()
            } else {
              this.showToast((res && res.message) || '清理失败', 'error')
            }
          } catch (e) {
            this.showReqError(e, '清理失败')
          } finally {
            this.confirmBox.busy = false
          }
        })
    },

    // ---- 工具 ----
    stateName(s) {
      return ({ waiting: '等待中', ready: '已就绪', finished: '已完成', expired: '已过期' })[s] || s
    },
    shortOpenid(id) {
      return id && id.length > 10 ? id.slice(0, 6) + '…' + id.slice(-4) : (id || '--')
    },
    fmtDuration(ms) {
      if (ms == null) return '--'
      const sec = Math.round(ms / 1000)
      return sec >= 60 ? `${Math.floor(sec / 60)}分${sec % 60}秒` : `${sec}秒`
    },
    fmtUtc(s) {
      // 后端存的是 UTC 文本 'YYYY-MM-DD HH:MM:SS',转北京时间展示
      if (!s) return '--'
      try {
        const d = new Date(s.replace(' ', 'T') + 'Z')
        return d.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
      } catch (e) {
        return s
      }
    },
    fmtEpoch(ts) {
      if (!ts) return '--'
      try {
        return new Date(ts * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
      } catch (e) {
        return '--'
      }
    },
    openConfirm(title, desc, confirmFn) {
      this.confirmBox.title = title
      this.confirmBox.desc = desc || ''
      this.confirmBox.busy = false
      this.confirmBox.confirm = confirmFn
      this.confirmBox.show = true
    },
    showReqError(e, fallback) {
      const data = e && e.response && e.response.data
      this.showToast((data && data.message) || fallback, 'error')
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
