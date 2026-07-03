<template>
  <!-- 始终渲染页面：未登录也能看到首页骨架/按钮，数据区由各页面自行提示 -->
  <router-view></router-view>

  <!-- 右上角登录态入口 -->
  <button v-if="authenticated" class="auth-entry auth-logout" @click="submitLogout">退出登录</button>
  <button v-else class="auth-entry auth-login-btn" @click="openLogin">登录</button>

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
            <button type="submit" :disabled="loading">
              {{ loading ? '登录中...' : '登录' }}
            </button>
          </form>
          <div v-if="message" class="auth-message">{{ message }}</div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script>
import { getAuthSession, login, logout } from './services/apiService'

export default {
  name: 'Root',
  data() {
    return {
      authenticated: false,
      showLogin: false,
      username: '',
      password: '',
      loading: false,
      message: ''
    }
  },
  async mounted() {
    window.addEventListener('auth-required', this.handleAuthRequired)
    window.addEventListener('auth-request-login', this.openLogin)
    await this.checkSession()
  },
  beforeUnmount() {
    window.removeEventListener('auth-required', this.handleAuthRequired)
    window.removeEventListener('auth-request-login', this.openLogin)
  },
  methods: {
    async checkSession() {
      try {
        const session = await getAuthSession()
        this.authenticated = !!session.authenticated
      } catch (err) {
        this.authenticated = false
      }
    },
    openLogin() {
      this.message = ''
      this.showLogin = true
    },
    closeLogin() {
      this.showLogin = false
      this.password = ''
      this.message = ''
    },
    async submitLogin() {
      this.loading = true
      this.message = ''
      try {
        const res = await login(this.username.trim(), this.password)
        if (res && res.authenticated) {
          this.authenticated = true
          this.showLogin = false
          this.password = ''
          this.message = ''
          // 通知所有页面：已登录，重新加载数据
          window.dispatchEvent(new CustomEvent('auth-login-success'))
        } else {
          this.message = '账号或密码错误'
        }
      } catch (err) {
        this.message = '账号或密码错误'
      } finally {
        this.loading = false
      }
    },
    async submitLogout() {
      await logout()
      this.authenticated = false
      this.username = ''
      this.password = ''
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
.auth-entry {
  position: fixed;
  right: 14px;
  top: 14px;
  z-index: 1000;
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

.auth-modal-enter-active,
.auth-modal-leave-active {
  transition: opacity 0.25s ease;
}

.auth-modal-enter-from,
.auth-modal-leave-to {
  opacity: 0;
}

.auth-modal-enter-active .auth-card,
.auth-modal-leave-active .auth-card {
  transition: transform 0.25s ease;
}

.auth-modal-enter-from .auth-card,
.auth-modal-leave-to .auth-card {
  transform: scale(0.94);
}
</style>
