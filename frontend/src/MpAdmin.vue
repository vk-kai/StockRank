<template>
  <div class="mpadmin-page">
    <header class="mpadmin-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>📱 小程序数据后台</h1>
      <nav class="tab-nav">
        <span class="tab active">数据趋势</span>
        <span class="tab" @click="goManage">数据管理</span>
      </nav>
    </header>

    <!-- 非 vk 提示 -->
    <div v-if="!loading && !isAdmin" class="mpadmin-forbidden">
      <p>仅管理员（vk 登录）可访问此页面。</p>
    </div>

    <div v-else-if="loading" class="mpadmin-loading">加载中…</div>

    <div v-else-if="error" class="mpadmin-error">
      <p>{{ error }}</p>
      <button @click="fetchOverview">重试</button>
    </div>

    <div v-else class="mpadmin-body">
      <!-- 总量卡片 -->
      <section class="stat-cards">
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.tests }}</div>
          <div class="stat-label">总测试人次</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.players }}</div>
          <div class="stat-label">参与玩家</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.quizzes }}</div>
          <div class="stat-label">上线测试数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.rooms }}</div>
          <div class="stat-label">PK房间 <small>（完成 {{ overview.totals.rooms_finished }}）</small></div>
        </div>
      </section>

      <!-- 图表区 -->
      <section class="card">
        <h2>各测试参与人次</h2>
        <div v-if="!overview.stat_counts.length" class="empty">暂无计数数据</div>
        <div v-else ref="statChart" class="chart-box"></div>
      </section>

      <section class="card">
        <h2>近30天每日趋势（北京时间）</h2>
        <div ref="dailyChart" class="chart-box"></div>
      </section>

      <!-- 热度排行 -->
      <section class="card">
        <h2>测试热度排行</h2>
        <div v-if="!overview.quiz_top.length" class="empty">暂无成绩数据</div>
        <table v-else class="data-table">
          <thead>
            <tr><th>#</th><th>测试 ID</th><th>参与人数</th><th>平均得分率</th></tr>
          </thead>
          <tbody>
            <tr v-for="(q, i) in overview.quiz_top" :key="q.quiz_id">
              <td>{{ i + 1 }}</td>
              <td class="code-text">{{ q.quiz_id }}</td>
              <td>{{ q.players }}</td>
              <td>{{ q.avg_score }}%</td>
            </tr>
          </tbody>
        </table>
      </section>

      <div class="footnote">
        「每日测试人次」自后台上线后开始逐日记录，此前无历史流水；「新增成绩 / 新建房间」按记录时间统计。
      </div>
    </div>
  </div>
</template>

<script src="./components/MpAdmin/MpAdmin.script.js"></script>
<style src="./components/MpAdmin/MpAdmin.style.css" scoped></style>
