import {
  getAuthSession,
  getMpAdminScores, mpAdminScoreUpdate, mpAdminScoreDelete,
  getMpAdminStats, mpAdminStatSave, mpAdminStatDelete,
  getMpAdminRooms, mpAdminRoomDelete
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
      stats: { items: [] },
      rooms: { items: [], page: 1, totalPages: 1, total: 0 },
      newStat: { key: '', count: 0 },
      scoreEdit: {
        show: false, busy: false, quiz_id: '', openid: '',
        nickname: '', score: 0, full_score: 100, duration_ms: 0
      },
      statEdit: { show: false, busy: false, key: '', count: 0 },
      pwdModal: { show: false, title: '', desc: '', password: '', busy: false, confirm: () => {} },
      toast: { show: false, message: '', type: 'info', timer: null }
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
        const res = await getMpAdminStats()
        if (res && res.success) {
          this.stats = { items: res.data.items }
        }
      } catch (e) {
        this.showReqError(e, '加载失败')
      }
    },
    async loadRooms(page = 1) {
      if (page < 1) return
      try {
        const res = await getMpAdminRooms({ page, pageSize: 20 })
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

    // ---- 成绩编辑/删除 ----
    openScoreEdit(row) {
      this.scoreEdit = {
        show: true, busy: false,
        quiz_id: row.quiz_id, openid: row.openid,
        nickname: row.nickname, score: row.score,
        full_score: row.full_score, duration_ms: row.duration_ms
      }
    },
    doScoreEdit() {
      const s = this.scoreEdit
      if (s.score < 0 || s.full_score < 1 || s.score > s.full_score) {
        this.showToast('分数不合法（0 ≤ 分数 ≤ 满分）', 'error'); return
      }
      if (!s.nickname || !s.nickname.trim() || s.nickname.trim().length > 12) {
        this.showToast('昵称不合法（1~12字）', 'error'); return
      }
      this.openPwdModal('保存成绩', `修改 ${s.quiz_id} 的成绩记录`, async () => {
        this.pwdModal.busy = true
        try {
          const res = await mpAdminScoreUpdate(this.pwdModal.password, {
            quiz_id: s.quiz_id, openid: s.openid,
            nickname: s.nickname.trim(), score: s.score,
            full_score: s.full_score, duration_ms: s.duration_ms
          })
          if (res && res.success) {
            s.show = false
            this.pwdModal.show = false
            this.pwdModal.password = ''
            this.showToast('已保存', 'ok')
            await this.loadScores(this.scores.page)
          } else {
            this.showToast((res && res.message) || '保存失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '保存失败')
        } finally {
          this.pwdModal.busy = false
        }
      })
    },
    onScoreDelete(row) {
      this.openPwdModal('删除成绩', `删除 ${row.quiz_id} / ${this.shortOpenid(row.openid)} 的成绩（不可恢复）`, async () => {
        this.pwdModal.busy = true
        try {
          const res = await mpAdminScoreDelete(this.pwdModal.password, row.quiz_id, row.openid)
          if (res && res.success) {
            this.pwdModal.show = false
            this.pwdModal.password = ''
            this.showToast('已删除', 'ok')
            await this.loadScores(this.scores.page)
          } else {
            this.showToast((res && res.message) || '删除失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '删除失败')
        } finally {
          this.pwdModal.busy = false
        }
      })
    },

    // ---- 计数管理 ----
    onStatAdd() {
      const key = this.newStat.key.trim()
      if (!key) { this.showToast('请填写 key', 'error'); return }
      if (!/^[a-z0-9_]{1,64}$/.test(key.toLowerCase())) {
        this.showToast('key 只能是小写字母/数字/下划线', 'error'); return
      }
      this.openPwdModal('新增计数', `新增 ${key} = ${this.newStat.count}`, async () => {
        this.pwdModal.busy = true
        try {
          const res = await mpAdminStatSave(this.pwdModal.password, key, this.newStat.count)
          if (res && res.success) {
            this.pwdModal.show = false
            this.pwdModal.password = ''
            this.newStat = { key: '', count: 0 }
            this.showToast('已保存', 'ok')
            await this.loadStats()
          } else {
            this.showToast((res && res.message) || '保存失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '保存失败')
        } finally {
          this.pwdModal.busy = false
        }
      })
    },
    openStatEdit(row) {
      this.statEdit = { show: true, busy: false, key: row.key, count: row.count }
    },
    doStatEdit() {
      const s = this.statEdit
      if (!(s.count >= 0)) { this.showToast('数值不合法', 'error'); return }
      this.openPwdModal('修改参与人次', `将 ${s.key} 设为 ${s.count}`, async () => {
        this.pwdModal.busy = true
        try {
          const res = await mpAdminStatSave(this.pwdModal.password, s.key, s.count)
          if (res && res.success) {
            s.show = false
            this.pwdModal.show = false
            this.pwdModal.password = ''
            this.showToast('已保存', 'ok')
            await this.loadStats()
          } else {
            this.showToast((res && res.message) || '保存失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '保存失败')
        } finally {
          this.pwdModal.busy = false
        }
      })
    },
    onStatDelete(row) {
      this.openPwdModal('删除计数', `删除 ${row.key}（当前 ${row.count} 次，不可恢复）`, async () => {
        this.pwdModal.busy = true
        try {
          const res = await mpAdminStatDelete(this.pwdModal.password, row.key)
          if (res && res.success) {
            this.pwdModal.show = false
            this.pwdModal.password = ''
            this.showToast('已删除', 'ok')
            await this.loadStats()
          } else {
            this.showToast((res && res.message) || '删除失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '删除失败')
        } finally {
          this.pwdModal.busy = false
        }
      })
    },

    // ---- 房间管理 ----
    onRoomDelete(row) {
      this.openPwdModal('删除房间', `删除房间 ${row.room_code}（不可恢复）`, async () => {
        this.pwdModal.busy = true
        try {
          const res = await mpAdminRoomDelete(this.pwdModal.password, row.room_code)
          if (res && res.success) {
            this.pwdModal.show = false
            this.pwdModal.password = ''
            this.showToast('已删除', 'ok')
            await this.loadRooms(this.rooms.page)
          } else {
            this.showToast((res && res.message) || '删除失败', 'error')
          }
        } catch (e) {
          this.showReqError(e, '删除失败')
        } finally {
          this.pwdModal.busy = false
        }
      })
    },

    // ---- 工具 ----
    stateName(s) {
      return ({ waiting: '等待中', ready: '已就绪', finished: '已完成' })[s] || s
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
    openPwdModal(title, desc, confirmFn) {
      this.pwdModal.title = title
      this.pwdModal.desc = desc || ''
      this.pwdModal.password = ''
      this.pwdModal.busy = false
      this.pwdModal.confirm = confirmFn
      this.pwdModal.show = true
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
