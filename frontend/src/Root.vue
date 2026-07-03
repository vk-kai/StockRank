<template>
  <template v-if="authenticated">
    <button class="auth-logout" @click="submitLogout">退出登录</button>
    <router-view></router-view>
  </template>
  <div v-else class="auth-shell">
    <div class="auth-card">
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
</template>

<script>
import { getAuthSession, login, logout } from './services/apiService'

export default {
  name: 'Root',
  data() {
    return {
      authenticated: false,
      username: '',
      password: '',
      loading: true,
      message: ''
    }
  },
  async mounted() {
    window.addEventListener('auth-required', this.handleAuthRequired)
    await this.checkSession()
  },
  beforeUnmount() {
    window.removeEventListener('auth-required', this.handleAuthRequired)
  },
  methods: {
    async checkSession() {
      this.loading = true
      this.message = ''
      try {
        const session = await getAuthSession()
        this.authenticated = !!session.authenticated
      } catch (err) {
        this.authenticated = false
      } finally {
        this.loading = false
      }
    },
    async submitLogin() {
      this.loading = true
      this.message = ''
      try {
        const res = await login(this.username.trim(), this.password)
        if (res && res.authenticated) {
          this.authenticated = true
          this.password = ''
          this.message = ''
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
      this.message = '已退出登录'
    },
    handleAuthRequired() {
      this.authenticated = false
      this.message = '请先登录后查看数据'
    }
  }
}
</script>

<style scoped>
.auth-shell {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #08111f;
  color: #e5edf7;
  padding: 20px;
  box-sizing: border-box;
}

.auth-card {
  width: min(420px, 100%);
  background: #101827;
  border: 1px solid rgba(111, 142, 190, 0.28);
  border-radius: 8px;
  padding: 28px;
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
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

.auth-logout {
  position: fixed;
  right: 14px;
  top: 14px;
  z-index: 1000;
  border: 1px solid rgba(111, 142, 190, 0.4);
  background: rgba(16, 24, 39, 0.9);
  color: #d7e4f5;
  border-radius: 6px;
  padding: 7px 12px;
  cursor: pointer;
}
</style>
