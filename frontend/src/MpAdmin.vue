<template>
  <div class="mpadmin-page">
    <header class="mpadmin-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>📱 小程序数据后台</h1>
      <nav class="tab-nav">
        <span class="tab active">数据趋势</span>
        <span class="tab" @click="goManage">数据管理</span>
      </nav>
      <button class="export-btn" :disabled="exporting || !overview" @click="exportExcel">
        {{ exporting ? '导出中…' : '⬇ 导出Excel' }}
      </button>
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
      <!-- 总量卡片（运营视角，直白叫法） -->
      <section class="stat-cards">
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.players }}</div>
          <div class="stat-label">参与人数 <small>（玩过测试的人数，去重）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.tests }}</div>
          <div class="stat-label">测试完成次数 <small>（每完成一次 +1，重复测试也计入）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.tool_usage }}</div>
          <div class="stat-label">工具使用次数 <small>（每使用一次 +1）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ avgTestsPerPlayer }}</div>
          <div class="stat-label">人均玩过测试 <small>（平均每人玩过几个不同测试）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.quizzes }}</div>
          <div class="stat-label">有人玩的测试 <small>（有玩家提交过成绩的测试数）</small></div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ overview.totals.rooms }}</div>
          <div class="stat-label">PK房间 <small>（已完成 {{ overview.totals.rooms_finished }} 场）</small></div>
        </div>
      </section>

      <!-- 图表区：测试榜 + 工具榜 -->
      <section class="card">
        <h2>各测试完成次数</h2>
        <div v-if="!overview.test_counts.length" class="empty">暂无测试计数数据</div>
        <div v-else ref="testChart" class="chart-box"></div>
      </section>

      <section class="card">
        <h2>各工具使用次数</h2>
        <div v-if="!overview.tool_counts.length" class="empty">暂无工具计数数据</div>
        <div v-else ref="toolChart" class="chart-box"></div>
      </section>

      <section class="card">
        <h2>今日按小时趋势（北京时间）</h2>
        <div ref="hourlyChart" class="chart-box"></div>
      </section>

      <section class="card">
        <h2>今日各小时最热 Top15 <small class="dim">（行=今天最活跃的测试/工具，列=小时，颜色越亮次数越多；行首「测」=测试、「具」=工具）</small></h2>
        <div v-if="!hourlyTopItems.length" class="empty">今天还没有使用记录</div>
        <div v-else ref="hourlyTopChart" class="chart-box"></div>
      </section>

      <section class="card">
        <h2>近30天最热 Top15 <small class="dim">（行=近30天最活跃的测试/工具，列=日期，一天总结一次，颜色越亮次数越多）</small></h2>
        <div v-if="!dailyTopItems.length" class="empty">近30天还没有使用记录</div>
        <div v-else ref="dailyTopChart" class="chart-box"></div>
      </section>

      <section class="card">
        <h2>近30天每日趋势（北京时间）</h2>
        <div ref="dailyChart" class="chart-box"></div>
      </section>

      <!-- 热度排行 -->
      <section class="card">
        <h2>测试参与人数排行 <small class="dim">（点击测试名称查看排行榜）</small></h2>
        <div v-if="!overview.quiz_top.length" class="empty">暂无成绩数据</div>
        <table v-else class="data-table">
          <thead>
            <tr><th>#</th><th>测试</th><th>参与人数</th><th>平均得分率</th></tr>
          </thead>
          <tbody>
            <tr v-for="(q, i) in overview.quiz_top" :key="q.quiz_id">
              <td>{{ i + 1 }}</td>
              <td>
                <button class="quiz-link" :title="'查看 ' + q.name + ' 排行榜'"
                        @click="openQuizRank(q)">{{ q.name }}</button>
                <small class="dim">{{ q.quiz_id }}</small>
              </td>
              <td>{{ q.players }}</td>
              <td>{{ q.avg_score }}%</td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 综合排名榜 -->
      <section class="card">
        <h2>综合排名榜 <small class="dim">（达标 {{ overallTotal }} 人 · 参与≥3个测试）</small></h2>
        <div v-if="!overallTop.length" class="empty">暂无达标玩家（参与至少3个不同测试）</div>
        <table v-else class="data-table">
          <thead>
            <tr><th>#</th><th>玩家</th><th>平均击败率</th><th>参与测试数</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in overallTop" :key="p.rank">
              <td>{{ p.rank }}</td>
              <td>{{ p.nickname }}</td>
              <td>{{ p.avg_beat }}%</td>
              <td>{{ p.quizzes }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <div class="footnote">
        说明：「测试完成次数 / 工具使用次数」每用一次就 +1，重复使用照常计入；
        「参与人数 / 人均玩过测试 / 有人玩的测试」按成绩表统计，同一人同一测试只记最好一次。
        「每日趋势 / 近30天最热」自后台上线后开始逐日记录，此前无历史数据；「今日按小时 / 今日最热」为当天各时间点的实时分布；两张最热图行首「测」=测试、「具」=工具。
        综合排名 = 各测试击败率的平均值（跨测试可比，非总分加总），参与≥3个测试才上榜，同分时参与多者在前。
      </div>
    </div>

    <!-- 测试排行榜弹窗 -->
    <div v-if="rankModal.show" class="rank-overlay" @click.self="rankModal.show = false">
      <div class="rank-card">
        <div class="rank-head">
          <h3>{{ rankModal.name }} · 排行榜</h3>
          <button class="rank-close" @click="rankModal.show = false">×</button>
        </div>
        <p class="rank-sub">
          <small v-if="rankModal.name !== rankModal.quizId" class="dim">{{ rankModal.quizId }} · </small>
          共 {{ rankModal.total }} 条成绩 · 排序与小程序端一致（分数优先，同分用时短优先）
        </p>
        <div v-if="rankModal.error" class="rank-error">{{ rankModal.error }}</div>
        <div v-else-if="rankModal.loading" class="empty">排行榜加载中…</div>
        <div v-else-if="!rankModal.items.length" class="empty">该测试暂无成绩数据</div>
        <table v-else class="data-table">
          <thead>
            <tr><th>#</th><th>昵称</th><th>分数</th><th>用时</th><th>测试时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in rankModal.items" :key="i">
              <td>{{ (rankModal.page - 1) * rankModal.pageSize + i + 1 }}</td>
              <td>{{ row.nickname }}</td>
              <td>{{ row.score }}/{{ row.full_score }}</td>
              <td>{{ fmtDuration(row.duration_ms) }}</td>
              <td>{{ fmtUtc(row.created_at) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="rankModal.totalPages > 1" class="pager">
          <button :disabled="rankModal.page <= 1 || rankModal.loading"
                  @click="loadQuizRank(rankModal.page - 1)">上一页</button>
          <span>{{ rankModal.page }} / {{ rankModal.totalPages }} 页 · 共 {{ rankModal.total }} 条</span>
          <button :disabled="rankModal.page >= rankModal.totalPages || rankModal.loading"
                  @click="loadQuizRank(rankModal.page + 1)">下一页</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script src="./components/MpAdmin/MpAdmin.script.js"></script>
<style src="./components/MpAdmin/MpAdmin.style.css" scoped></style>
