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
      <!-- 总量卡片（口径已区分） -->
      <section class="stat-cards">
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.tests }}</div>
          <div class="stat-label">总测试人次 <small>（计数求和，同人重测也+1）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.tool_usage }}</div>
          <div class="stat-label">工具使用人次 <small>（计数求和）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.players }}</div>
          <div class="stat-label">参与玩家 <small>（有成绩记录的去重人数）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.scores }}</div>
          <div class="stat-label">去重参与记录 <small>（同人同测试只记最佳）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.quizzes }}</div>
          <div class="stat-label">有成绩记录的测试数 <small>（≠上线测试总数）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.rooms }}</div>
          <div class="stat-label">PK房间 <small>（完成 {{ overview.totals.rooms_finished }}）</small></div>
        </div>
      </section>

      <!-- 图表区：测试榜 + 工具榜 -->
      <section class="card">
        <h2>测试参与榜</h2>
        <div v-if="!overview.test_counts.length" class="empty">暂无测试计数数据</div>
        <div v-else ref="testChart" class="chart-box"></div>
      </section>

      <section class="card">
        <h2>工具使用榜</h2>
        <div v-if="!overview.tool_counts.length" class="empty">暂无工具计数数据</div>
        <div v-else ref="toolChart" class="chart-box"></div>
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
            <tr><th>#</th><th>测试</th><th>参与人数</th><th>平均得分率</th></tr>
          </thead>
          <tbody>
            <tr v-for="(q, i) in overview.quiz_top" :key="q.quiz_id">
              <td>{{ i + 1 }}</td>
              <td>{{ q.name }} <small class="dim">{{ q.quiz_id }}</small></td>
              <td>{{ q.players }}</td>
              <td>{{ q.avg_score }}%</td>
            </tr>
          </tbody>
        </table>
      </section>

      <div class="footnote">
        口径说明：「总测试人次 / 工具使用人次」为计数接口求和（不去重，同人重复使用照常 +1）；
        「去重参与记录」来自成绩表（同人同测试只记最佳）。「每日测试/工具人次」自后台上线后开始逐日记录，此前无历史流水。
      </div>
    </div>
  </div>
</template>

<script src="./components/MpAdmin/MpAdmin.script.js"></script>
<style src="./components/MpAdmin/MpAdmin.style.css" scoped></style>
