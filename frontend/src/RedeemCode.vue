<template>
  <div class="redeem-page">
    <header class="redeem-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>🎟️ 体验码管理</h1>
      <div class="header-spacer"></div>
    </header>

    <!-- 非 vk 提示 -->
    <div v-if="!loading && !isAdmin" class="redeem-forbidden">
      <p>仅管理员（vk 登录）可访问此页面。</p>
    </div>

    <div v-else-if="loading" class="redeem-loading">加载中…</div>

    <div v-else class="redeem-body">
      <!-- 生成区 -->
      <section class="card">
        <h2>生成体验码</h2>
        <div class="gen-row">
          <label>标签
            <input v-model="form.label" placeholder="如：大盘云图" />
          </label>
          <label>落地页
            <select v-model="form.page">
              <option v-for="p in pageOptions" :key="p.path" :value="p.path">{{ p.name }}</option>
            </select>
          </label>
          <label>时长
            <select v-model="form.duration">
              <option value="10min">10 分钟</option>
              <option value="30min">半小时</option>
              <option value="1day">一天</option>
              <option value="permanent">永久（首个兑换者终身访问）</option>
            </select>
          </label>
          <label>数量
            <input v-model.number="form.count" type="number" min="1" :max="canGenerate" />
          </label>
        </div>
        <div class="gen-hint">池容量 {{ poolSize }}，当前可用 {{ activeCodes.length }} 张，还可生成 {{ canGenerate }} 张。</div>
        <button class="gen-btn" :disabled="generating || canGenerate < 1" @click="onGenerateClick">
          {{ generating ? '生成中…' : '生成并复制链接' }}
        </button>
      </section>

      <!-- 新生成的码（复制区） -->
      <section v-if="newCodes.length" class="card">
        <h2>新生成的码（已可分享）</h2>
        <div v-for="c in newCodes" :key="c.code" class="code-line">
          <span class="code-text">{{ c.code }}</span>
          <button class="copy-btn" @click="copyLink(c.link)">复制链接</button>
        </div>
      </section>

      <!-- 可用码列表 -->
      <section class="card">
        <h2>可用码（{{ activeCodes.length }}）</h2>
        <div v-if="!activeCodes.length" class="empty">暂无可用码</div>
        <table v-else class="code-table">
          <thead>
            <tr><th>兑换码</th><th>标签</th><th>落地页</th><th>时长</th><th>生成时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in activeCodes" :key="c.code">
              <td class="code-text">{{ c.code }}</td>
              <td>{{ c.label }}</td>
              <td>{{ pageName(c.page) }}</td>
              <td>{{ durationName(c.duration) }}</td>
              <td>{{ c.created_at }}</td>
              <td>
                <button class="copy-btn" @click="copyLink(shareLink(c.code))">复制链接</button>
                <button class="revoke-btn" @click="onRevokeClick(c.code)">撤销</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 历史记录 -->
      <section class="card">
        <h2>历史记录（{{ usedCodes.length }}）</h2>
        <div v-if="!usedCodes.length" class="empty">暂无历史</div>
        <table v-else class="code-table">
          <thead>
            <tr><th>兑换码</th><th>标签</th><th>时长</th><th>兑换时间</th><th>到期</th><th>状态</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="c in usedCodes" :key="c.code">
              <td class="code-text">{{ c.code }}</td>
              <td>{{ c.label }}</td>
              <td>{{ durationName(c.duration) }}</td>
              <td>{{ c.redeemed_at }}</td>
              <td>{{ c.duration === 'permanent' ? '永久' : formatExpire(c.expire_at) }}</td>
              <td><span :class="['status', c.status]">{{ statusName(c.status) }}</span></td>
              <td>
                <button class="del-btn" @click="onDeleteClick(c.code)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <!-- 密码确认弹窗（生成/撤销/删除均需 vk 日密码） -->
    <div v-if="pwdModal.show" class="pwd-overlay" @click.self="pwdModal.show = false">
      <div class="pwd-card">
        <h3>{{ pwdModal.title }}</h3>
        <p v-if="pwdModal.desc" class="pwd-desc">{{ pwdModal.desc }}</p>
        <input v-model="pwdModal.password" type="password" placeholder="今日动态密码" />
        <div class="pwd-actions">
          <button class="cancel-btn" @click="pwdModal.show = false">取消</button>
          <button class="ok-btn" :disabled="pwdModal.busy" @click="pwdModal.confirm">
            {{ pwdModal.busy ? '处理中…' : '确认' }}
          </button>
        </div>
      </div>
    </div>

    <!-- toast -->
    <div v-if="toast.show" class="toast" :class="toast.type">{{ toast.message }}</div>
  </div>
</template>

<script src="./components/RedeemCode/RedeemCode.script.js"></script>
<style src="./components/RedeemCode/RedeemCode.style.css" scoped></style>
