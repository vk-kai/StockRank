<template>
  <!-- 始终渲染页面：未登录也能看到首页骨架/按钮，数据区由各页面自行提示 -->
  <router-view v-slot="{ Component }">
    <transition name="route" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>

  <!-- 右上角登录态入口 + 北京时间（所有页面共用） -->
  <div :class="['top-actions', isMarketMapRoute ? 'market-map-entry' : '']">
    <span class="beijing-clock" :title="'北京时间 ' + beijingTime">{{ beijingTime }}</span>
    <button v-if="authenticated" :class="authEntryClass" @click="submitLogout">退出登录</button>
    <button v-else :class="authEntryClass" @click="openLogin">登录</button>
  </div>

  <!-- 登录弹窗（未登录访问受保护数据时由 auth-required 事件触发，或点击按钮主动唤起） -->
  <Teleport to="body">
    <Transition name="auth-modal">
      <div v-if="showLogin" class="auth-overlay" @click.self="closeLogin">
        <div class="auth-card">
          <button class="auth-close" @click="closeLogin" aria-label="关闭">×</button>
          <div class="auth-brand">StockRank</div>
          <h1>登录后查看数据</h1>
          <p>首页、新闻、资金流、云图、配置和日志都需要登录后使用。</p>
          <form class="auth-form" @submit.prevent="submitLogin">
            <input
              v-model="username"
              autocomplete="username"
              placeholder="用户名"
              :disabled="loading"
            />
            <input
              v-model="password"
              autocomplete="current-password"
              placeholder="密码"
              type="password"
              :disabled="loading"
            />
            <input
              v-if="otpRequired"
              v-model="otpCode"
              autocomplete="one-time-code"
              inputmode="numeric"
              maxlength="6"
              placeholder="动态口令（6位数字）"
              :disabled="loading"
            />
            <button type="submit" :disabled="loading">
              {{ loading ? '登录中...' : '登录' }}
            </button>
          </form>
          <!-- 兑换码入口（兜底：分享链接被 IM 截断时手动粘贴） -->
          <div class="auth-divider"><span>或</span></div>
          <div v-if="!showRedeemBox" class="auth-redeem-toggle" @click="showRedeemBox = true; message = ''">
            用兑换码体验
          </div>
          <form v-else class="auth-form" @submit.prevent="submitRedeem">
            <input
              v-model="redeemInput"
              placeholder="粘贴兑换码（如 AB12-CD34-EF56）"
              :disabled="loading"
            />
            <button type="submit" :disabled="loading">
              {{ loading ? '兑换中...' : '兑换并进入' }}
            </button>
          </form>
          <div v-if="message" class="auth-message">{{ message }}</div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script>
import { getAuthSession, getOtpRequired, login, logout, redeemCode } from './services/apiService'

export default {
  name: 'Root',
  data() {
    return {
      authenticated: false,
      showLogin: false,
      username: '',
      password: '',
      otpCode: '',
      otpRequired: false,
      loading: false,
      message: '',
      // 兑换码（体验访问）
      isAdmin: false,            // vk 登录态才为 true（决定是否显示体验码管理入口）
      redeemInput: '',           // 登录框里的"粘贴兑换码"输入
      showRedeemBox: false,      // 是否展开兑换码输入框
      _prevAuthed: false,        // 上一轮轮询的认证态，用于检测过期掉线
      redeemPollTimer: null,     // 5 分钟全局轮询定时器
      beijingTime: '',           // 右上角北京时间显示（YYYY-MM-DD HH:mm:ss）
      clockTimer: null           // 每秒刷新北京时间的定时器
    }
  },
  computed: {
    isMarketMapRoute() {
      return this.$route?.name === 'MarketMap'
    },
    authEntryClass() {
      return [
        'auth-entry',
        this.authenticated ? 'auth-logout' : 'auth-login-btn'
      ]
    }
  },
  async mounted() {
    window.addEventListener('auth-required', this.handleAuthRequired)
    window.addEventListener('auth-request-login', this.openLogin)
    await this.checkSession()
    // 链接带 ?redeem=XXXX → 自动兑换（分享链接进入）；兑换后清掉 URL 参数避免刷新重兑
    await this.tryAutoRedeemFromUrl()
    // 5 分钟全局轮询：无论在哪个页面都查会话有效性（有的页面没有定时请求），
    // 体验码过期/被撤销 → checkSession 发现掉线 → 走 auth-required 链路回到锁定态。
    this.redeemPollTimer = setInterval(() => this.checkSession(), 5 * 60 * 1000)
    // 北京时间每秒刷新
    this.updateBeijingClock()
    this.clockTimer = setInterval(() => this.updateBeijingClock(), 1000)
  },
  beforeUnmount() {
    window.removeEventListener('auth-required', this.handleAuthRequired)
    window.removeEventListener('auth-request-login', this.openLogin)
    if (this.redeemPollTimer) clearInterval(this.redeemPollTimer)
    if (this.clockTimer) clearInterval(this.clockTimer)
  },
  methods: {
    updateBeijingClock() {
      // 按 Asia/Shanghai 时区取值，客户端本地时区不影响显示；hourCycle h23 避免出现 24 点
      const parts = new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        hourCycle: 'h23',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit'
      }).formatToParts(new Date())
      const get = (type) => {
        const p = parts.find((item) => item.type === type)
        return p ? p.value.padStart(2, '0') : '00'
      }
      this.beijingTime = `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`
    },
    async checkSession() {
      try {
        const session = await getAuthSession()
        this.isAdmin = !!(session && session.is_admin)
        const nowAuthed = !!(session && session.authenticated)
        // 检测掉线：上一轮是认证态、本轮变未认证 → 体验码过期或会话失效 → 触发登录提示
        if (this._prevAuthed && !nowAuthed && !this.showLogin) {
          this.authenticated = false
          window.dispatchEvent(new CustomEvent('auth-required'))
        }
        this._prevAuthed = nowAuthed
        this.authenticated = nowAuthed
      } catch (err) {
        this.authenticated = false
        this._prevAuthed = false
      }
    },
    async tryAutoRedeemFromUrl() {
      try {
        const code = new URLSearchParams(window.location.search).get('redeem')
        if (!code) return
        await this.doRedeem(code, { auto: true })
        // 清掉 URL 里的 ?redeem=，避免刷新/分享时重兑
        const url = new URL(window.location.href)
        url.searchParams.delete('redeem')
        window.history.replaceState({}, document.title, url.pathname + url.search + url.hash)
      } catch (e) { /* 忽略 */ }
    },
    async submitRedeem() {
      const code = (this.redeemInput || '').trim()
      if (!code) { this.message = '请输入兑换码'; return }
      this.loading = true
      try {
        await this.doRedeem(code, { auto: false })
      } finally {
        this.loading = false
      }
    },
    async doRedeem(code, { auto }) {
      try {
        const res = await redeemCode(code)
        if (res && res.success) {
          this.authenticated = true
          this.isAdmin = false
          this.showLogin = false
          this.showRedeemBox = false
          this.redeemInput = ''
          this.message = ''
          this._prevAuthed = true
          // 复用现有登录成功链路：通知各页面已可加载数据
          window.dispatchEvent(new CustomEvent('auth-login-success'))
          // 跳到码绑定的落地页（首页码则留原地）
          if (res.page && res.page !== '/' && this.$router) {
            try { this.$router.push(res.page) } catch (e) { /* 忽略重复导航 */ }
          }
        } else {
          this.message = (res && res.message) || '兑换码无效或已被使用'
          if (!auto) this.showRedeemBox = true
        }
      } catch (err) {
        const data = err && err.response && err.response.data
        this.message = (data && data.message) || '兑换码无效或已被使用'
        if (!auto) this.showRedeemBox = true
        throw err
      }
    },
    openLogin() {
      this.message = ''
      this.showLogin = true
      // 预判是否需要 OTP 输入框（OTP 未开启时不显示）
      this.refreshOtpRequired()
    },
    async refreshOtpRequired() {
      try {
        const res = await getOtpRequired()
        this.otpRequired = !!(res && res.otp_required)
      } catch (e) {
        this.otpRequired = false
      }
    },
    closeLogin() {
      this.showLogin = false
      this.password = ''
      this.otpCode = ''
      this.redeemInput = ''
      this.showRedeemBox = false
      this.message = ''
    },
    async submitLogin() {
      this.loading = true
      this.message = ''
      try {
        const res = await login(this.username.trim(), this.password, this.otpCode || '')
        if (res && res.authenticated) {
          this.authenticated = true
          this.showLogin = false
          this.password = ''
          this.otpCode = ''
          this.message = ''
          // 通知所有页面：已登录，重新加载数据
          window.dispatchEvent(new CustomEvent('auth-login-success'))
        } else if (res && res.error === 'otp_required') {
          this.otpRequired = true
          this.message = res.message || '请输入动态口令'
        } else {
          this.message = (res && res.message) || '账号或密码错误'
        }
      } catch (err) {
        // 后端返回 401 时 axios 抛错；区分 OTP 缺失与其他错误
        const data = err && err.response && err.response.data
        if (data && data.error === 'otp_required') {
          this.otpRequired = true
          this.message = data.message || '请输入动态口令'
        } else if (data && data.error === 'invalid_credentials') {
          this.message = data.message || '账号或密码错误'
        } else {
          this.message = '账号或密码错误'
        }
      } finally {
        this.loading = false
      }
    },
    async submitLogout() {
      await logout()
      this.authenticated = false
      this.username = ''
      this.password = ''
      this.otpCode = ''
      // 通知所有页面：已登出，回到登录提示态
      window.dispatchEvent(new CustomEvent('auth-logout'))
    },
    handleAuthRequired() {
      this.authenticated = false
      this.openLogin()
      this.message = '请先登录后查看数据'
    }
  }
}
</script>

<style scoped>
.top-actions {
  position: fixed;
  right: 14px;
  top: 14px;
  z-index: 1000;
  display: flex;
  align-items: center;
  gap: 8px;
}

.top-actions.market-map-entry {
  top: 18px;
  right: 18px;
}

.beijing-clock {
  border: 1px solid rgba(111, 142, 190, 0.4);
  background: rgba(16, 24, 39, 0.9);
  color: #d7e4f5;
  border-radius: 6px;
  padding: 7px 12px;
  font-size: 13px;
  white-space: nowrap;
  font-variant-numeric: tabular-nums; /* 等宽数字，秒级跳动不抖动 */
  user-select: none;
}

.auth-entry {
  border: 1px solid rgba(111, 142, 190, 0.4);
  background: rgba(16, 24, 39, 0.9);
  color: #d7e4f5;
  border-radius: 6px;
  padding: 7px 14px;
  cursor: pointer;
  font-size: 13px;
}

.auth-login-btn {
  background: #1677ff;
  border-color: #1677ff;
  color: #fff;
  font-weight: 600;
}

.auth-login-btn:hover {
  background: #4096ff;
}

.auth-logout:hover {
  background: rgba(40, 50, 70, 0.95);
}

.auth-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.auth-card {
  position: relative;
  width: min(420px, 100%);
  background: #101827;
  border: 1px solid rgba(111, 142, 190, 0.28);
  border-radius: 8px;
  padding: 28px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.45);
  color: #e5edf7;
}

.auth-close {
  position: absolute;
  right: 12px;
  top: 10px;
  width: 28px;
  height: 28px;
  border: 0;
  background: transparent;
  color: #9db0ca;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  border-radius: 4px;
}

.auth-close:hover {
  color: #e5edf7;
  background: rgba(255, 255, 255, 0.06);
}

.auth-brand {
  color: #7cc4ff;
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 10px;
}

.auth-card h1 {
  margin: 0 0 10px;
  font-size: 24px;
  letter-spacing: 0;
}

.auth-card p {
  margin: 0 0 22px;
  color: #9db0ca;
  line-height: 1.6;
}

.auth-form {
  display: grid;
  gap: 12px;
}

.auth-form input {
  height: 40px;
  border-radius: 6px;
  border: 1px solid rgba(111, 142, 190, 0.42);
  background: #08111f;
  color: #e5edf7;
  padding: 0 12px;
  font-size: 14px;
}

.auth-form button {
  height: 40px;
  border: 0;
  border-radius: 6px;
  background: #1677ff;
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.auth-form button:disabled,
.auth-form input:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

.auth-message {
  margin-top: 12px;
  color: #ff8a8a;
  font-size: 13px;
}

.auth-divider {
  display: flex;
  align-items: center;
  text-align: center;
  margin: 16px 0 10px;
  color: #5b6b85;
  font-size: 12px;
}
.auth-divider::before,
.auth-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: rgba(111, 142, 190, 0.22);
}
.auth-divider span {
  padding: 0 10px;
}

.auth-redeem-toggle {
  text-align: center;
  color: #7cc4ff;
  font-size: 13px;
  cursor: pointer;
  padding: 6px 0;
  border-radius: 6px;
}
.auth-redeem-toggle:hover {
  background: rgba(124, 196, 255, 0.08);
}

.auth-modal-enter-active,
.auth-modal-leave-active {
  transition: opacity 0.25s ease;
}

.auth-modal-enter-from,
.auth-modal-leave-to {
  opacity: 0;
}
</style>
