<template>
  <div class="market-map-page">
    <header class="mm-header">
      <div class="mm-header-left">
        <button @click="goBack" class="mm-back-button">← 返回</button>
        <h1>🗺️ A股大盘云图</h1>
        <div class="mm-search-wrap">
          <input
            class="mm-search"
            v-model="searchQuery"
            @input="onSearchInput"
            @keyup.enter="onSearchInput"
            placeholder="🔍 搜索个股 / 行业，高亮定位"
          />
          <span class="mm-search-count" v-show="searchQuery">{{ matchCount ? matchCount + ' 项' : '无匹配' }}</span>
        </div>
        <button
          @click="toggleIndustryMode"
          class="mm-industry-btn"
          :class="{ active: industryMode }"
          :title="industryMode ? '当前为行业云图（每个色块=一个二级行业），点击切回个股云图' : '切换为行业云图：每个色块=一个二级行业，按行业总市值定大小、涨跌幅上色'"
        >{{ industryMode ? '← 个股云图' : '🏢 行业云图' }}</button>
      </div>
      <div class="mm-header-right">
        <!-- 演示模式徽标：未登录访客只看固定历史快照，点击可登录看实时 -->
        <span
          v-if="demoMode"
          style="display:inline-flex;align-items:center;background:rgba(240,185,11,.12);border:1px solid rgba(240,185,11,.4);color:#f0b90b;padding:3px 12px;border-radius:999px;font-size:12px;cursor:pointer;white-space:nowrap;"
          title="未登录演示：固定历史快照，不实时刷新"
          @click="promptLogin"
        >
          演示数据 · {{ demoDate }} 快照（点击登录看实时）
        </span>
        <span class="mm-stats" v-if="totalSectors">
          <template v-if="industryMode">{{ l2Count }} 个二级行业 · {{ totalStocks }} 只个股</template>
          <template v-else>{{ totalSectors }} 一级行业 · {{ totalStocks }} 只个股</template>
        </span>
        <span class="mm-update" v-if="cacheTime">行业库：{{ cacheTime }}</span>
        <div class="mm-color-mode" :class="{ loading: marginLoading }">
          <span class="mm-color-mode-icon">🎨</span>
          <select
            class="mm-color-select"
            :value="colorMode"
            @change="onColorModeChange($event.target.value)"
            title="切换云图着色维度"
          >
            <option value="change">着色：涨跌幅</option>
            <option value="margin">着色：融资净流入</option>
            <option value="score" v-if="hasScores">着色：AI打分</option>
            <option value="cycle" v-if="hasCycleScores">着色：9维周期雷达</option>
          </select>
          <span class="mm-color-date" v-if="colorMode === 'margin' && marginDate">{{ marginDate }}</span>
          <span class="mm-color-date" v-if="colorMode === 'score' && scoreDate">打分：{{ scoreDate }}</span>
          <span class="mm-color-date" v-if="colorMode === 'cycle' && cycleDate">诊断：{{ cycleDate }}</span>
        </div>
        <button @click="openScoreDialog" class="mm-score-btn" :class="{ running: scoringRunning }" title="调用 AI 给全市场股票打分（耗时较长，结果可反复使用）">
          <span class="mm-score-spin" :class="{ on: scoringRunning }">🤖</span>
          {{ scoringRunning ? '打分中…' : (hasScores ? '重新打分' : 'AI批量打分') }}
        </button>
        <button @click="openCycleDialog" class="mm-cycle-btn" :class="{ running: cycleRunning }" title="调用 AI 对所有二级行业进行9维产业周期雷达分析">
          <span class="mm-cycle-spin" :class="{ on: cycleRunning }">🔬</span>
          {{ cycleRunning ? '雷达扫描中…' : (hasCycleScores ? '重新扫描' : 'AI周期雷达') }}
        </button>
        <span class="mm-push-tag" v-if="pushedOnly && pushedCount">推送股票 {{ pushedCount }} 只</span>
        <button @click="refreshCache" class="mm-cache-btn" :disabled="cacheLoading">
          <IconRefresh v-if="!cacheLoading" />
          {{ cacheLoading ? '更新中...' : '行业库' }}
        </button>
        <button @click="fetchData(true)" class="mm-refresh-btn" :disabled="refreshing">
          <IconRefresh :spin="refreshing" />刷新行情
        </button>
        <button @click="handleClearPushed" class="mm-clear-push-btn" :disabled="pushedLoading" v-if="pushedOnly || pushedCount">
          {{ pushedLoading ? '清空中...' : '清空推送' }}
        </button>
      </div>
    </header>

    <div class="mm-chart-wrapper" ref="wrapperEl">
      <canvas
        ref="canvasEl"
        class="mm-canvas"
        @wheel.prevent="onWheel"
        @mousedown="onMouseDown"
        @mousemove="onMouseMove"
        @mouseup="onMouseUp"
        @mouseleave="onMouseLeave"
        @dblclick="onDblClick"
      ></canvas>
      <div
        ref="tooltipEl"
        class="mm-tooltip"
        v-show="tooltip.visible"
        :style="{ left: tooltip.x + 'px', top: tooltip.y + 'px' }"
      >
        <div class="mm-tooltip-name">
          {{ tooltip.name }}
          <span class="mm-tooltip-code" v-if="tooltip.code">{{ tooltip.code }}</span>
        </div>
        <!-- 当日分时迷你折线：股票名之下、涨跌幅之上；拿不到数据就不占位 -->
        <div
          class="mm-tooltip-spark"
          v-if="sparkline"
          :title="`当日分时 · 截至 ${tooltip.trend.last_time}${tooltip.trend.stale ? '（缓存）' : ''}`"
        >
          <svg :viewBox="`0 0 ${sparkline.w} ${sparkline.h}`" preserveAspectRatio="none">
            <line
              v-if="sparkline.baseY"
              :x1="0" :y1="sparkline.baseY" :x2="sparkline.w" :y2="sparkline.baseY"
              class="mm-spark-base"
            />
            <polyline
              :points="sparkline.points"
              fill="none"
              :stroke="sparkline.color"
              stroke-width="1.5"
              vector-effect="non-scaling-stroke"
            />
          </svg>
        </div>
        <div class="mm-tooltip-spark-loading" v-else-if="tooltip.trendLoading">分时加载中…</div>
        <div class="mm-tooltip-row">
          <span class="mm-tooltip-label">{{ colorMode === 'margin' ? '融资净流入' : (colorMode === 'score' ? 'AI评分' : (colorMode === 'cycle' ? '周期雷达' : '涨跌幅')) }}</span>
          <span class="mm-tooltip-val" :class="tooltip.cls">{{ tooltip.change }}</span>
        </div>
        <div class="mm-tooltip-row">
          <span class="mm-tooltip-label">市值</span>
          <span class="mm-tooltip-val">{{ tooltip.marketCap }}</span>
        </div>
        <div class="mm-tooltip-row">
          <span class="mm-tooltip-label">市盈率</span>
          <span class="mm-tooltip-val">{{ tooltip.pe }}</span>
        </div>
        <div class="mm-tooltip-row" v-if="tooltip.score != null && colorMode !== 'score'">
          <span class="mm-tooltip-label">AI评分</span>
          <span class="mm-tooltip-val" :class="tooltip.scoreCls">{{ tooltip.score }} <small>{{ tooltip.scoreLabel }}</small></span>
        </div>
        <div class="mm-tooltip-score-reason" v-if="tooltip.scoreReason">{{ tooltip.scoreLabel }} · {{ tooltip.scoreReason }}</div>
        <div v-if="tooltip.loading" class="mm-tooltip-extra">摘要加载中...</div>
        <template v-else-if="tooltip.summary">
          <div class="mm-tooltip-divider"></div>
          <div class="mm-tooltip-row">
            <span class="mm-tooltip-label">所属板块</span>
            <span class="mm-tooltip-val small">{{ tooltip.summary.sector_name || '--' }}</span>
          </div>
          <div class="mm-tooltip-row">
            <span class="mm-tooltip-label">板块排名</span>
            <span class="mm-tooltip-val small">
              {{ tooltip.summary.sector_rank ? '第' + tooltip.summary.sector_rank : '--' }}
            </span>
          </div>
          <div class="mm-tooltip-row">
            <span class="mm-tooltip-label">融资净流入</span>
            <span class="mm-tooltip-val small" :class="valueClass(tooltip.summary.margin?.latest_net_inflow)">
              {{ formatMoney(tooltip.summary.margin?.latest_net_inflow) }}
            </span>
          </div>
          <div class="mm-tooltip-row">
            <span class="mm-tooltip-label">融资余额</span>
            <span class="mm-tooltip-val small">{{ formatMoney(tooltip.summary.margin?.latest_balance, true) }}</span>
          </div>
          <div v-if="tooltip.summary.recent_news && tooltip.summary.recent_news.length" class="mm-tooltip-news">
            <div class="mm-tooltip-news-title">相关新闻</div>
            <div
              v-for="item in tooltip.summary.recent_news"
              :key="item.title"
              class="mm-tooltip-news-item"
            >
              {{ item.title }}
            </div>
          </div>
        </template>
      </div>
      <div class="mm-hint">单击看融资趋势 · 双击看雪球 · 滚轮缩放 · 拖动平移</div>
      <div class="mm-changes-loading" v-show="changesLoading && hasData">
        <span class="mm-cl-dot"></span> 实时涨跌加载中…
      </div>
      <div class="mm-filter-badge" v-if="filterBadge" @click="clearFilter" title="点击清除筛选">
        <span>已筛选：{{ filterBadge.desc }}（{{ filterBadge.count }} 只）</span>
        <span class="mm-filter-clear">✕</span>
      </div>
      <div class="mm-replay-watermark" v-if="replayMode">🕐 复盘 {{ replayTime }}</div>
    </div>

    <div class="mm-footer">
      <span class="mm-footer-text">行业分类：东方财富(缓存) · 实时涨跌：新浪财经 · 面积=总市值 · {{ footerColorDesc }}· 仅供投资参考</span>
      <div class="mm-replay-bar" v-if="replayPoints.length">
        <button
          v-for="p in replayPoints"
          :key="p.time"
          class="mm-replay-time"
          :class="{ active: replayMode && replayTime === p.time }"
          :disabled="!p.available"
          @click="enterReplay(p.time)"
          :title="p.available ? '复盘 ' + p.time : '尚未抓取'"
        >{{ p.time }}</button>
        <span class="mm-replay-sep"></span>
        <button class="mm-replay-play" @click="togglePlay" :disabled="!hasReplayAvailable">
          {{ replayPlaying ? '⏸' : '▶' }}{{ replayPlaying ? ' 暂停' : ' 播放' }}
        </button>
        <button
          class="mm-replay-live"
          :class="{ active: replayMode }"
          @click="exitReplay"
          :disabled="!replayMode"
          :title="replayMode ? '返回实时行情' : '当前为实时行情'"
        >🔴 {{ replayMode ? '返回实时' : '实时' }}</button>
      </div>
      <div class="mm-legend">
        <button
          v-if="colorMode === 'change'"
          class="mm-limit-btn up"
          :class="{ active: legendSel.includes('limit_up') }"
          @click="toggleLegendSel('limit_up')"
          :data-tooltip="'涨停：' + legendCounts.limit_up + ' 只'"
          :aria-label="'涨停：' + legendCounts.limit_up + ' 只，勾选后点确定可多选'"
          @mouseenter="showLegendTooltip($event, '涨停：' + legendCounts.limit_up + ' 只')"
          @focus="showLegendTooltip($event, '涨停：' + legendCounts.limit_up + ' 只')"
          @mouseleave="hideLegendTooltip"
          @blur="hideLegendTooltip"
        >
          <span class="mm-legend-label">涨停</span>
          <span class="mm-legend-count">{{ legendCounts.limit_up }}只</span>
        </button>
        <button
          v-if="colorMode === 'change'"
          class="mm-limit-btn down"
          :class="{ active: legendSel.includes('limit_down') }"
          @click="toggleLegendSel('limit_down')"
          :data-tooltip="'跌停：' + legendCounts.limit_down + ' 只'"
          :aria-label="'跌停：' + legendCounts.limit_down + ' 只，勾选后点确定可多选'"
          @mouseenter="showLegendTooltip($event, '跌停：' + legendCounts.limit_down + ' 只')"
          @focus="showLegendTooltip($event, '跌停：' + legendCounts.limit_down + ' 只')"
          @mouseleave="hideLegendTooltip"
          @blur="hideLegendTooltip"
        >
          <span class="mm-legend-label">跌停</span>
          <span class="mm-legend-count">{{ legendCounts.limit_down }}只</span>
        </button>
        <div class="mm-legend-bar" :class="{ 'is-margin': colorMode === 'margin' }">
          <div
            v-for="(s, i) in legendSteps"
            :key="i"
            class="mm-legend-step"
            :class="{ active: legendSel.includes(s.value), checked: legendSel.includes(s.value) }"
            :style="{ background: s.color }"
            :data-tooltip="s.countTitle + '：' + legendCounts[String(s.value)] + ' 只'"
            :aria-label="s.title + '，当前 ' + legendCounts[String(s.value)] + ' 只，勾选后点确定可多选'"
            role="button"
            tabindex="0"
            @click="toggleLegendSel(s.value)"
            @keyup.enter="toggleLegendSel(s.value)"
            @keyup.space.prevent="toggleLegendSel(s.value)"
            @mouseenter="showLegendTooltip($event, s.countTitle + '：' + legendCounts[String(s.value)] + ' 只')"
            @focus="showLegendTooltip($event, s.countTitle + '：' + legendCounts[String(s.value)] + ' 只')"
            @mouseleave="hideLegendTooltip"
            @blur="hideLegendTooltip"
          >
            <span class="mm-legend-step-label">{{ s.label }}</span>
            <span class="mm-legend-step-count">{{ legendCounts[String(s.value)] }}只</span>
          </div>
        </div>
        <button
          class="mm-legend-apply"
          :class="{ pending: legendSel.length > 0, hasFilter: legendApplied.length > 0 }"
          :disabled="legendSel.length === 0 && legendApplied.length === 0"
          :title="legendSel.length === 0 ? '当前无勾选；勾选区间后点此应用多选筛选' : ('应用勾选的 ' + legendSel.length + ' 个区间（可多选，命中任一即显示）')"
          @click="applyLegendFilter"
        >
          <span class="mm-legend-apply-check" v-if="legendSel.length > 0 || legendApplied.length > 0">✓</span>
          确定<span class="mm-legend-apply-n" v-if="legendSel.length > 0">{{ legendSel.length }}</span>
        </button>
        <div
          class="mm-legend-tooltip"
          v-show="legendTooltip.visible"
          :style="{ left: legendTooltip.x + 'px', top: legendTooltip.y + 'px' }"
        >{{ legendTooltip.text }}</div>
      </div>
    </div>
    <!-- 单击个股：融资净买入额趋势弹窗 -->
    <div class="mm-modal-overlay" v-if="finModal.visible" @click="closeFinancing">
      <div class="mm-modal" @click.stop>
        <div class="mm-modal-header">
          <div class="mm-modal-title">
            <span class="mm-modal-name">{{ finModal.name }}</span>
            <span class="mm-modal-code">{{ finModal.code }}</span>
          </div>
          <div class="mm-fin-balance">
            <span class="mm-fin-balance-label">融资总余额</span>
            <span class="mm-fin-balance-value">{{ latestFinBalance }}</span>
          </div>
          <button class="mm-modal-close" @click="closeFinancing">✕</button>
        </div>
        <div class="mm-modal-sub">融资净买入额（数据截至 {{ latestFinDate || '—' }}）</div>
        <div class="mm-fin-periods">
          <button
            v-for="p in finPeriods"
            :key="p"
            class="mm-fin-period"
            :class="{ active: finModal.period === p }"
            @click="switchFinPeriod(p)"
          >
            <span class="mm-fin-period-label">{{ p }}日</span>
            <span class="mm-fin-period-val" :class="finValClass(finModal.totals[p])">{{ finFmt(finModal.totals[p]) }}</span>
          </button>
        </div>
        <div class="mm-fin-chart-wrap">
          <div v-if="finModal.loading" class="mm-fin-status">加载中…</div>
          <div v-else-if="finModal.error" class="mm-fin-status">{{ finModal.error }}</div>
          <div v-else-if="finModal.updating" class="mm-fin-status">融资数据更新中，请稍候…</div>
          <div v-else-if="!finModal.series.length" class="mm-fin-status">暂无融资数据（该股票可能非融资融券标的）</div>
          <div ref="finChartEl" class="mm-fin-chart" v-show="!finModal.loading && !finModal.error && !finModal.updating && finModal.series.length"></div>
        </div>
      </div>
    </div>

    <!-- AI 批量打分弹窗：确认 → 进度 → 完成/失败 -->
    <div class="mm-modal-overlay" v-if="scoreDialog.visible" @click="closeScoreDialog">
      <div class="mm-modal mm-score-modal" @click.stop>
        <div class="mm-modal-header">
          <div class="mm-modal-title"><span class="mm-modal-name">🤖 AI 批量股票打分</span></div>
          <button class="mm-modal-close" @click="closeScoreDialog" v-if="scoreDialog.view !== 'running'">✕</button>
        </div>

        <!-- 确认 -->
        <div v-if="scoreDialog.view === 'confirm'" class="mm-score-body">
          <p class="mm-score-desc">
            将调用你配置的 AI（🤖 AI大模型配置）对全市场约 <b>{{ scoreEstimate.total || '5000+' }}</b> 只股票逐一打分，
            生成 0-100 的综合评分（<span class="up">≥50 红=可考虑</span> / <span class="down">&lt;50 绿=谨慎</span>），
            保存后即可在云图按分数着色、筛选、悬浮查看，<b>一目了然哪些可重仓、哪些需谨慎</b>。
          </p>
          <ul class="mm-score-tips">
            <li>⏱️ 过程漫长：约 <b>{{ scoreEstimate.eta_minutes || '60-180' }} 分钟</b>（{{ scoreEstimate.batches || 500 }} 批，<b>串行调用避免触发 AI 限流</b>）。可中途停止、断点续跑。</li>
            <li>💰 会消耗 AI 额度（全量约百万级 token，成本通常仅几元）。</li>
            <li>💾 每评一只即落盘，中途可随时关闭/停止，已打分结果保留，下次可"仅跑失败项"。</li>
            <li>🔁 打分不频繁，跑完一次长期复用，建议基本面有大变化时再重跑。</li>
            <li>⚙️ 想提速：在 ai_config.json 加 <code>score_max_workers</code>（付费大额度可调到 2-3）、<code>score_batch_interval</code>、<code>score_429_cooldown</code>。</li>
          </ul>
          <p class="mm-score-warn" v-if="!aiEnabled">⚠️ 当前 AI 未启用或配置不完整，请先到「🤖 AI大模型配置」中设置并测试通过。</p>
          <div class="mm-score-actions">
            <button class="mm-score-btn-cancel" @click="closeScoreDialog">取消</button>
            <button class="mm-score-btn-ok" :disabled="!aiEnabled || scoreDialog.busy" @click="confirmStartScoring(false)">
              {{ scoreDialog.busy ? '启动中…' : (hasScores ? '确认重新打分' : '确认开始打分') }}
            </button>
          </div>
        </div>

        <!-- 进行中 -->
        <div v-else-if="scoreDialog.view === 'running'" class="mm-score-body">
          <div class="mm-score-progress">
            <div class="mm-score-progress-bar"><div class="mm-score-progress-fill" :style="{ width: (scoringStatus.progress || 0) + '%' }"></div></div>
            <div class="mm-score-progress-num">{{ scoringStatus.progress || 0 }}%</div>
          </div>
          <div class="mm-score-step">{{ scoringStatus.step || '处理中…' }}</div>
          <div class="mm-score-stat">
            <span>已评分 <b class="up">{{ scoringStatus.done || 0 }}</b> / {{ scoringStatus.total || scoreEstimate.total || '?' }}</span>
            <span v-if="scoringStatus.failed">· 失败 <b class="down">{{ scoringStatus.failed }}</b></span>
          </div>
          <p class="mm-score-note">过程中云图可实时按分数着色（切到「着色：AI打分」查看）。可放心关闭此窗口，打分在后台继续。</p>
          <div class="mm-score-actions">
            <button class="mm-score-btn-cancel" @click="handleStopScoring">停止打分</button>
            <button class="mm-score-btn-ghost" @click="scoreDialog.visible = false">后台运行，关闭窗口</button>
          </div>
        </div>

        <!-- 完成 -->
        <div v-else-if="scoreDialog.view === 'done'" class="mm-score-body">
          <p class="mm-score-result" :class="{ warn: scoringStatus.failed }">
            ✅ {{ scoringStatus.message || '打分完成' }}
          </p>
          <div class="mm-score-actions">
            <button class="mm-score-btn-ghost" v-if="scoringStatus.failed" @click="confirmStartScoring(true)">仅跑失败项（{{ scoringStatus.failed }} 只）</button>
            <button class="mm-score-btn-ok" @click="finishAndSwitchToScore">查看打分云图</button>
            <button class="mm-score-btn-cancel" @click="closeScoreDialog">关闭</button>
          </div>
        </div>

        <!-- 失败/中断 -->
        <div v-else class="mm-score-body">
          <p class="mm-score-result warn">⚠️ {{ scoringStatus.message || '打分未完成' }}</p>
          <p class="mm-score-note" v-if="scoringStatus.status === 'interrupted'">进程可能已重启。已评分的结果仍保留，可重新开始或仅跑未完成部分。</p>
          <div class="mm-score-actions">
            <button class="mm-score-btn-ok" @click="confirmStartScoring(true)">仅跑未完成项</button>
            <button class="mm-score-btn-cancel" @click="confirmStartScoring(false)">重新全部打分</button>
            <button class="mm-score-btn-ghost" @click="closeScoreDialog">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- AI 行业周期诊断弹窗：确认 → 进度 → 完成/失败 -->
    <div class="mm-modal-overlay" v-if="cycleDialog.visible" @click="closeCycleDialog">
      <div class="mm-modal mm-score-modal" @click.stop>
        <div class="mm-modal-header">
          <div class="mm-modal-title"><span class="mm-modal-name">🔬 AI 9维产业周期雷达</span></div>
          <button class="mm-modal-close" @click="closeCycleDialog" v-if="cycleDialog.view !== 'running'">✕</button>
        </div>

        <!-- 确认 -->
        <div v-if="cycleDialog.view === 'confirm'" class="mm-score-body">
          <p class="mm-score-desc">
            将调用 AI 对大盘云图中约 <b>{{ cycleEstimate.total || '?' }}</b> 个二级行业逐一进行"9维产业周期雷达"分析，
        返回 0-100 的见顶风险评分（<span class="up">&lt;50 安全</span> / <span class="down">≥50 危险</span>），
        云图中直接显示风险分（绿=危险/红=安全，与涨跌幅相反）。
          </p>
          <ul class="mm-score-tips">
            <li>⏱️ 每个行业约需 30-60 秒，全量约 <b>{{ cycleEstimate.eta || '20-60' }} 分钟</b>。</li>
            <li>💰 会消耗 AI 额度（约几十个行业，每行业一次 AI 调用）。</li>
            <li>💾 诊断结果持久保存，可反复使用。重新诊断会清除旧结果。</li>
            <li>🔄 雷达扫描期间云图可实时着色（切到「着色：9维周期雷达」查看）。</li>
          </ul>
          <p class="mm-score-warn" v-if="!aiEnabled">⚠️ 当前 AI 未启用或配置不完整，请先到「🤖 AI大模型配置」中设置并测试通过。</p>
          <div class="mm-score-actions">
            <button class="mm-score-btn-cancel" @click="closeCycleDialog">取消</button>
            <button class="mm-score-btn-ok" :disabled="!aiEnabled || cycleDialog.busy" @click="confirmStartCycle">{{ cycleDialog.busy ? '启动中…' : (hasCycleScores ? '确认重新扫描' : '确认开始扫描') }}</button>
          </div>
        </div>

        <!-- 进行中 -->
        <div v-else-if="cycleDialog.view === 'running'" class="mm-score-body">
          <div class="mm-score-progress">
            <div class="mm-score-progress-bar"><div class="mm-score-progress-fill" :style="{ width: (cycleStatus.progress || 0) + '%' }"></div></div>
            <div class="mm-score-progress-num">{{ cycleStatus.progress || 0 }}%</div>
          </div>
          <div class="mm-score-step">{{ cycleStatus.step || cycleStatus.current || '处理中…' }}</div>
          <div class="mm-score-stat">
            <span>已诊断 <b class="up">{{ cycleStatus.done || 0 }}</b> / {{ cycleStatus.total || '?' }}</span>
            <span v-if="cycleStatus.failed">· 失败 <b class="down">{{ cycleStatus.failed }}</b></span>
          </div>
          <p class="mm-score-note">过程中可切到"着色：9维周期雷达"实时查看。可关闭此窗口，扫描在后台继续。</p>
          <div class="mm-score-actions">
            <button class="mm-score-btn-cancel" @click="handleStopCycle">停止诊断</button>
            <button class="mm-score-btn-ghost" @click="cycleDialog.visible = false">后台运行，关闭窗口</button>
          </div>
        </div>

        <!-- 完成 -->
        <div v-else-if="cycleDialog.view === 'done'" class="mm-score-body">
          <p class="mm-score-result" :class="{ warn: cycleStatus.failed }">
            ✅ {{ cycleStatus.message || '诊断完成' }}
          </p>
          <div class="mm-score-actions">
            <button class="mm-score-btn-ok" @click="finishAndSwitchToCycle">查看雷达云图</button>
            <button class="mm-score-btn-warn" v-if="cycleStatus.failed && cycleStatus.failed_industries && cycleStatus.failed_industries.length" @click="retryFailedCycle">
              重试失败行业（{{ cycleStatus.failed_industries.length }}个）
            </button>
            <button class="mm-score-btn-cancel" @click="closeCycleDialog">关闭</button>
          </div>
        </div>

        <!-- 失败/中断 -->
        <div v-else class="mm-score-body">
          <p class="mm-score-result warn">⚠️ {{ cycleStatus.message || '诊断未完成' }}</p>
          <div class="mm-score-actions">
            <button class="mm-score-btn-warn" v-if="cycleStatus.failed_industries && cycleStatus.failed_industries.length" @click="retryFailedCycle">
              重试失败行业（{{ cycleStatus.failed_industries.length }}个）
            </button>
            <button class="mm-score-btn-ok" v-else @click="confirmStartCycle">重新诊断</button>
            <button class="mm-score-btn-cancel" @click="closeCycleDialog">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <SecurityAlert />
  </div>
</template>

<script>
import { getMarketMap, getMarketMapStructure, refreshMarketMapCache, getStockFinancing, getStockHoverSummary, getStockIntradaySeries, getMarketMapSnapshots, getMarketMapSnapshot, getMarketMapPush, clearMarketMapPush, getMarketMapMargin, getStockScores, startStockScoring, getStockScoringStatus, stopStockScoring, getAIConfig, startIndustryCycleBatch, getIndustryCycleBatchStatus, stopIndustryCycleBatch, getIndustryCycleAllScores, getAuthSession, getDemoMarketMap } from './services/apiService'
import SecurityAlert from './components/SecurityAlert.vue'
import * as echarts from 'echarts'

// 配色色阶：涨跌幅(%) → [R,G,B]。跌=绿、涨=红、0%=灰。
// 颜色按参考云图逐块读真实涨跌幅锚点后插值得到（红：+0.33/+1.51/+2.88%、绿：-0.87/-2.04/-3.97%），
// 渐变在 0% 附近较陡，超过 ±4% 饱和到两端满色（亮绿/亮红）；interpColor 把 change 钳制在 ±4。
const COLOR_STOPS = [
  [-4, [59, 204, 95]],
  [-3, [56, 170, 87]],
  [-2, [53, 136, 80]],
  [-1, [58, 101, 79]],
  [0, [76, 68, 84]],
  [1, [122, 68, 81]],
  [2, [165, 64, 75]],
  [3, [202, 58, 69]],
  [4, [243, 47, 61]]
]

function interpColor(change) {
  const c = Math.max(-4, Math.min(4, change)) // 超过 ±4% 饱和到两端满色
  for (let i = 0; i < COLOR_STOPS.length - 1; i++) {
    const [p1, col1] = COLOR_STOPS[i]
    const [p2, col2] = COLOR_STOPS[i + 1]
    if (c >= p1 && c <= p2) {
      const t = p2 === p1 ? 0 : (c - p1) / (p2 - p1)
      const r = Math.round(col1[0] + (col2[0] - col1[0]) * t)
      const g = Math.round(col1[1] + (col2[1] - col1[1]) * t)
      const b = Math.round(col1[2] + (col2[2] - col1[2]) * t)
      return `rgb(${r},${g},${b})`
    }
  }
  return 'rgb(66,68,83)'
}

// 筛选灰显色（未命中个股）与整板块变暗面纱（某行业一只都没命中时叠加）
const DIM_COLOR = '#1b2330'
const VEIL_COLOR = 'rgba(8,14,24,0.78)'

// 融资净流入着色：非融资标的（无数据）的中性色，区别于"被筛选灰显"
const NO_MARGIN_COLOR = '#3a4458'
// 净流入排名→深浅色锚：正流入红、净流出绿，排名越靠前(绝对值越大)越深
const MARGIN_RED_LIGHT = [122, 64, 66]
const MARGIN_RED_DEEP = [240, 45, 55]
const MARGIN_GREEN_LIGHT = [48, 110, 80]
const MARGIN_GREEN_DEEP = [44, 188, 88]
function marginDepthColor(depth, light, deep) {
  const t = Math.max(0, Math.min(1, depth))
  const r = Math.round(light[0] + (deep[0] - light[0]) * t)
  const g = Math.round(light[1] + (deep[1] - light[1]) * t)
  const b = Math.round(light[2] + (deep[2] - light[2]) * t)
  return `rgb(${r},${g},${b})`
}

// 融资净流入金额分档（单位：元）。沿用 9 格图例，边界按当前缓存的分布取整；
// 两端保留开放区间承接大额异常值，中心区间保留给小额流入和流出。
const MARGIN_LEGEND_STEPS = [
  { value: 'margin-1', label: '≤-2000万', countTitle: '净流出 ≥ 2000万', max: -2e7, color: '#2cbc58' },
  { value: 'margin-2', label: '-2000~-1000万', countTitle: '净流出 1000万 ~ 2000万', min: -2e7, max: -1e7, color: '#278c50' },
  { value: 'margin-3', label: '-1000~-500万', countTitle: '净流出 500万 ~ 1000万', min: -1e7, max: -5e6, color: '#266f50' },
  { value: 'margin-4', label: '-500~-200万', countTitle: '净流出 200万 ~ 500万', min: -5e6, max: -2e6, color: '#334d42' },
  { value: 'margin-5', label: '-200~0万', countTitle: '净流出 0万 ~ 200万', min: -2e6, max: 0, color: '#4c4454' },
  { value: 'margin-6', label: '0~200万', countTitle: '净流入 0万 ~ 200万', min: 0, max: 2e6, color: '#6d404d' },
  { value: 'margin-7', label: '200~500万', countTitle: '净流入 200万 ~ 500万', min: 2e6, max: 5e6, color: '#a5404b' },
  { value: 'margin-8', label: '500~1000万', countTitle: '净流入 500万 ~ 1000万', min: 5e6, max: 1e7, color: '#ca3a45' },
  { value: 'margin-9', label: '>1000万', countTitle: '净流入 > 1000万', min: 1e7, color: '#f02d37' }
]

// AI 打分着色：0-100 分，50 为红绿分界。<50 绿（谨慎），≥50 红（可考虑），深浅=分值大小。
// 与后端 stock_scorer.SCORE_BUCKETS 一一对应（图例 9 格 + 点击筛选）；单元格用连续渐变 SCORE_COLOR_STOPS。
const SCORE_LEGEND_STEPS = [
  { value: 'score-1', label: '≤10',   countTitle: '极谨慎 0-10',    max: 10,           color: '#2cbc58' },
  { value: 'score-2', label: '11-25', countTitle: '谨慎 11-25',     min: 10, max: 25,  color: '#2a9a55' },
  { value: 'score-3', label: '26-40', countTitle: '偏谨慎 26-40',   min: 25, max: 40,  color: '#3d7a55' },
  { value: 'score-4', label: '41-49', countTitle: '中性偏空 41-49', min: 40, max: 49,  color: '#5a5a4a' },
  { value: 'score-5', label: '50-59', countTitle: '中性偏多 50-59', min: 49, max: 59,  color: '#6a4050' },
  { value: 'score-6', label: '60-69', countTitle: '尚可 60-69',     min: 59, max: 69,  color: '#963c48' },
  { value: 'score-7', label: '70-79', countTitle: '较优 70-79',     min: 69, max: 79,  color: '#c03843' },
  { value: 'score-8', label: '80-89', countTitle: '优秀 80-89',     min: 79, max: 89,  color: '#e2323d' },
  { value: 'score-9', label: '≥90',   countTitle: '顶级 90-100',    min: 89,           color: '#f02d37' }
]
// 连续色阶：0(深绿/极谨慎) → 50(暗中性，红绿分界) → 100(深红/顶级)
const SCORE_COLOR_STOPS = [
  [0,   [44, 188, 88]],
  [10,  [42, 154, 85]],
  [25,  [61, 122, 85]],
  [40,  [90, 90, 74]],
  [50,  [106, 64, 80]],
  [60,  [150, 60, 72]],
  [75,  [192, 56, 67]],
  [89,  [226, 50, 61]],
  [100, [243, 47, 61]]
]
const NO_SCORE_COLOR = '#3a4458'  // 未评分个股的中性色（区别于"被筛选灰显"）
function interpScoreColor(score) {
  if (typeof score !== 'number' || isNaN(score)) return NO_SCORE_COLOR
  const s = Math.max(0, Math.min(100, score))
  for (let i = 0; i < SCORE_COLOR_STOPS.length - 1; i++) {
    const [p1, col1] = SCORE_COLOR_STOPS[i]
    const [p2, col2] = SCORE_COLOR_STOPS[i + 1]
    if (s >= p1 && s <= p2) {
      const t = p2 === p1 ? 0 : (s - p1) / (p2 - p1)
      const r = Math.round(col1[0] + (col2[0] - col1[0]) * t)
      const g = Math.round(col1[1] + (col2[1] - col1[1]) * t)
      const b = Math.round(col1[2] + (col2[2] - col1[2]) * t)
      return `rgb(${r},${g},${b})`
    }
  }
  return NO_SCORE_COLOR
}
// 打分命中筛选区间（与 inMarginFilter 同构的半开区间）
function inScoreFilter(value, active) {
  if (active == null) return true
  if (typeof value !== 'number' || isNaN(value)) return false
  const step = SCORE_LEGEND_STEPS.find(item => item.value === active)
  if (!step) return false
  if (step.min == null) return value <= step.max
  if (step.max == null) return value > step.min
  return value > step.min && value <= step.max
}

// 行业周期诊断着色：直接用 overall_score（0-100，越高越危险）
// >50 绿色逐渐加深（越危险越绿），<50 红色逐渐加深（越安全越红），类似涨跌幅
const CYCLE_COLOR_STOPS = [
  [0,   [226, 50, 61]],    // 深红：极安全 0
  [10,  [192, 56, 67]],
  [25,  [150, 60, 72]],
  [40,  [106, 64, 80]],
  [49,  [90, 90, 74]],     // 暗中性：接近50
  [51,  [61, 122, 85]],    // 暗中性：刚过50
  [60,  [42, 154, 85]],
  [75,  [34, 172, 78]],
  [89,  [30, 190, 82]],
  [100, [22, 204, 86]]     // 深绿：极危险 100
]
const CYCLE_LEGEND_STEPS = [
  { value: 'cycle-1', label: '≤10',   countTitle: '极安全 0-10',     max: 10,           color: '#e2323d' },
  { value: 'cycle-2', label: '11-25', countTitle: '安全 11-25',      min: 10, max: 25,  color: '#c03843' },
  { value: 'cycle-3', label: '26-40', countTitle: '偏安全 26-40',    min: 25, max: 40,  color: '#963c48' },
  { value: 'cycle-4', label: '41-49', countTitle: '中性偏安全 41-49', min: 40, max: 49,  color: '#6a4050' },
  { value: 'cycle-5', label: '50-59', countTitle: '中性偏危险 50-59', min: 49, max: 59,  color: '#3d7a55' },
  { value: 'cycle-6', label: '60-69', countTitle: '偏危险 60-69',    min: 59, max: 69,  color: '#2a9a55' },
  { value: 'cycle-7', label: '70-79', countTitle: '危险 70-79',      min: 69, max: 79,  color: '#22ac4e' },
  { value: 'cycle-8', label: '80-89', countTitle: '很危险 80-89',    min: 79, max: 89,  color: '#1ebe52' },
  { value: 'cycle-9', label: '≥90',   countTitle: '极度危险 90-100', min: 89,           color: '#16cc56' }
]
const NO_CYCLE_COLOR = '#3a4458'  // 未诊断行业的中性色

function interpCycleColor(score) {
  if (typeof score !== 'number' || isNaN(score)) return NO_CYCLE_COLOR
  const s = Math.max(0, Math.min(100, score))
  for (let i = 0; i < CYCLE_COLOR_STOPS.length - 1; i++) {
    const [p1, col1] = CYCLE_COLOR_STOPS[i]
    const [p2, col2] = CYCLE_COLOR_STOPS[i + 1]
    if (s >= p1 && s <= p2) {
      const t = p2 === p1 ? 0 : (s - p1) / (p2 - p1)
      const r = Math.round(col1[0] + (col2[0] - col1[0]) * t)
      const g = Math.round(col1[1] + (col2[1] - col1[1]) * t)
      const b = Math.round(col1[2] + (col2[2] - col1[2]) * t)
      return `rgb(${r},${g},${b})`
    }
  }
  return NO_CYCLE_COLOR
}

function inCycleFilter(value, active) {
  if (active == null) return true
  if (typeof value !== 'number' || isNaN(value)) return false
  const step = CYCLE_LEGEND_STEPS.find(item => item.value === active)
  if (!step) return false
  if (step.min == null) return value <= step.max
  if (step.max == null) return value > step.min
  return value > step.min && value <= step.max
}

// 按股票代码前缀判断涨跌停限幅(%)：主板 10 / 创业板·科创板 20 / 北交所 30
function limitThreshold(code) {
  const m = String(code || '').match(/(\d{6})/)
  const d = m ? m[1] : ''
  if (!d) return 10
  if (d.startsWith('688') || d.startsWith('300') || d.startsWith('301')) return 20
  if (d[0] === '8' || d[0] === '4') return 30
  return 10
}

// 个股是否命中当前筛选。active 取值：null(无) / 数值 -4..4(色块区间) / 'limit_up' / 'limit_down'
// 区间为半开 (L-1, L]，两极延伸：-4 → change≤-4；+4 → change>3
function extractDigits(c) {
  const m = String(c || '').match(/(\d{6})/)
  return m ? m[1] : String(c || '')
}

function inChangeFilter(change, code, active) {
  if (active == null) return true
  if (typeof change !== 'number' || isNaN(change)) return false
  if (active === 'limit_up') return change >= limitThreshold(code) - 0.1
  if (active === 'limit_down') return change <= -(limitThreshold(code) - 0.1)
  const L = active
  if (L <= -4) return change <= -4
  if (L >= 4) return change > 3
  return change > (L - 1) && change <= L
}

function inMarginFilter(value, active) {
  if (active == null) return true
  if (typeof value !== 'number' || isNaN(value)) return false
  const step = MARGIN_LEGEND_STEPS.find(item => item.value === active)
  if (!step) return false
  if (step.min == null) return value <= step.max
  if (step.max == null) return value > step.min
  return value > step.min && value <= step.max
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v))
const fmtPct = c => (c >= 0 ? '+' : '') + c + '%'
// 市值格式化：元 → 万亿/亿/万
const fmtCap = v => {
  if (!v || v <= 0) return '-'
  const yi = v / 1e8
  if (yi >= 10000) return (yi / 10000).toFixed(2) + '万亿'
  if (yi >= 100) return yi.toFixed(0) + '亿'
  if (yi >= 1) return yi.toFixed(1) + '亿'
  return (v / 1e4).toFixed(0) + '万'
}
// 市盈率格式化：负值=亏损，无数据=-
const fmtPE = pe => {
  if (pe == null || pe === '' || isNaN(pe)) return '-'
  if (pe < 0) return '亏损'
  return Number(pe).toFixed(1)
}

// 股票代码 → 雪球个股页：https://xueqiu.com/S/SH601288 （交易所前缀大写 + 6 位代码）
function xueqiuUrl(code) {
  if (!code) return ''
  const c = String(code).trim()
  let m = c.match(/^(sh|sz|bj)(\d{6})$/i)
  if (m) return `https://xueqiu.com/S/${m[1].toUpperCase()}${m[2]}`
  m = c.match(/(\d{6})/)
  if (m) {
    const d = m[1]
    const prefix = d[0] === '6' ? 'SH' : (d[0] === '8' || d[0] === '4') ? 'BJ' : 'SZ'
    return `https://xueqiu.com/S/${prefix}${d}`
  }
  return `https://xueqiu.com/S/${c.toUpperCase()}`
}

// Squarified Treemap（Bruls 等人算法）：把 items 按 value 比例铺满 rect，
// 尽量让每个矩形接近正方形。直接给每个 item 写入 x/y/w/h（布局坐标）。
function squarify(items, x, y, w, h) {
  if (!items.length || w <= 0 || h <= 0) return
  const positives = items.filter(it => it.value > 0)
  if (!positives.length) return
  const total = positives.reduce((s, it) => s + it.value, 0)
  if (total <= 0) return
  const scale = (w * h) / total
  let curX = x, curY = y, curW = w, curH = h
  // 不在此处重排：尊重调用方传入的顺序（buildLayout 已按市值降序排好 L1/L2/个股）
  let queue = positives.map(it => ({ a: it.value * scale, ref: it }))

  const worst = (arr, len) => {
    let sum = 0, mx = -Infinity, mn = Infinity
    for (const a of arr) { sum += a; if (a > mx) mx = a; if (a < mn) mn = a }
    if (mn <= 0) return Infinity
    const l2 = len * len
    return Math.max((l2 * mx) / (sum * sum), (sum * sum) / (l2 * mn))
  }

  while (queue.length && curW > 0 && curH > 0) {
    const short = Math.min(curW, curH)
    let row = [queue[0]]
    let rowWorst = worst(row.map(t => t.a), short)
    let i = 1
    while (i < queue.length) {
      const tw = worst(row.concat(queue[i]).map(t => t.a), short)
      if (tw <= rowWorst) { row = row.concat(queue[i]); rowWorst = tw; i++ }
      else break
    }
    const rowSum = row.reduce((s, t) => s + t.a, 0)
    if (curW >= curH) {
      const stripW = rowSum / curH
      let oy = curY
      for (const t of row) {
        const ih = t.a / stripW
        t.ref.x = curX; t.ref.y = oy; t.ref.w = stripW; t.ref.h = ih
        oy += ih
      }
      curX += stripW; curW -= stripW
    } else {
      const stripH = rowSum / curW
      let ox = curX
      for (const t of row) {
        const iw = t.a / stripH
        t.ref.x = ox; t.ref.y = curY; t.ref.w = iw; t.ref.h = stripH
        ox += iw
      }
      curY += stripH; curH -= stripH
    }
    queue = queue.slice(i)
  }
}

export default {
  name: 'MarketMap',
  components: { SecurityAlert },
  data() {
    return {
      cacheLoading: false,
      // 演示模式：未登录访客只读固定快照，不进任何实时链路（15s轮询/复盘/AI打分/周期诊断）
      demoMode: false,
      demoDate: '',
      liveStarted: false,
      refreshing: false,
      changesLoading: false,
      tree: [],
      totalSectors: 0,
      totalStocks: 0,
      cacheTime: '',
      pushedOnly: false,
      pushedCodes: [],
      pushedCount: 0,
      pushedUpdatedAt: '',
      pushedLoading: false,
      sourceTree: [],
      sourceTotals: { totalSectors: 0, totalStocks: 0, cacheTime: '' },
      // 复盘/回放
      replayMode: false,        // true=复盘态（暂停实时轮询，显示历史快照）
      replayTime: '',           // 当前复盘的时间点，如 '10:00'
      replayPlaying: false,     // 是否正在自动播放
      replayPoints: ['09:30','10:00','10:30','11:00','11:30','13:00','13:30','14:00','14:30','15:00'].map(time => ({ time, available: false })),
      // 行业云图模式：true=只画二级行业色块(扁平,不展开个股)，false=默认三级个股云图
      industryMode: false,
      // 着色维度：'change'(涨跌幅,默认) | 'margin'(融资净流入) | 'score'(AI打分)
      colorMode: 'change',
      marginMap: {},            // {裸6位code: 最新一日融资净流入额}
      marginDate: '',
      marginLoading: false,
      marginLoaded: false,
      // AI 打分维度
      scoreMap: {},             // {裸6位code: {score,label,reason}}
      scoreDate: '',
      scoreLoading: false,
      scoreLoaded: false,
      aiEnabled: true,          // AI 是否已配置启用（控制打分按钮可用性）
      scoringRunning: false,
      scoringTimer: null,
      scoringStatus: { status: 'idle', progress: 0, step: '', total: 0, done: 0, failed: 0, message: '' },
      scoreEstimate: { total: 0, batches: 0, workers: 1, eta_minutes: '60-180' },
      scoreDialog: { visible: false, view: 'confirm', busy: false },
      // 行业周期诊断维度
      cycleMap: {},            // {行业名: {overall_score, overall_verdict, ...}}
      cycleDate: '',
      cycleLoading: false,
      cycleLoaded: false,
      cycleRunning: false,
      cycleTimer: null,
      cycleStatus: { status: 'idle', progress: 0, step: '', current: '', total: 0, done: 0, failed: 0, message: '' },
      cycleEstimate: { total: 0, eta: '20-60' },
      cycleDialog: { visible: false, view: 'confirm', busy: false },
      tooltip: { visible: false, name: '', code: '', change: '', cls: '', marketCap: '', pe: '', x: 0, y: 0, loading: false, summary: null, summaryKey: '', trend: null, trendLoading: false },
      legendTooltip: { visible: false, text: '', x: 0, y: 0 },
      searchQuery: '',
      matchCount: 0,
      activeLegend: null,     // 兼容旧引用（已弃用，保留避免外部报错）
      legendSel: [],          // 多选草稿：已勾选的区间值（涨停/跌停/各色块/score-N/margin-N），点"确定"前只影响勾选高亮
      legendApplied: [],      // 已应用的筛选集（实际过滤云图）；为空=不过滤(全显示)。命中任一即显示
      finPeriods: [3, 5, 10, 20, 60],
      finModal: {
        visible: false,
        code: '',
        name: '',
        loading: false,
        error: '',
        updating: false,
        period: 60,
        latestBalance: null,
        latestBalanceDate: '',
        series: [],   // [{d,j,b}]，d=YYYYMMDD，j=融资净买入额(元)，b=融资余额(元)
        totals: {}    // {3:val,5:val,...} 各区间净买入额之和
      }
    }
  },
  computed: {
    // 悬浮卡当日分时迷你折线：有 pct(昨收基准)时画 0% 基线并按涨跌上色，
    // 拿不到昨收时退化为价格归一化折线；点数不足则返回 null 不占位
    sparkline() {
      const pts = (this.tooltip.trend && this.tooltip.trend.points) || []
      if (pts.length < 2) return null
      const w = 240, h = 52, pad = 4
      const usePct = pts.some(p => p.pct !== null && p.pct !== undefined)
      const vals = pts.map(p => (usePct ? p.pct : p.price)).filter(v => v !== null && v !== undefined && !isNaN(v))
      if (vals.length < 2) return null
      let min = Math.min(...vals), max = Math.max(...vals)
      if (usePct) { min = Math.min(min, 0); max = Math.max(max, 0) }
      if (max === min) max = min + 1
      const xAt = i => pad + (i / (pts.length - 1)) * (w - pad * 2)
      const yAt = v => h - pad - ((v - min) / (max - min)) * (h - pad * 2)
      const points = pts.map((p, i) => {
        const v = usePct ? p.pct : p.price
        if (v === null || v === undefined || isNaN(v)) return null
        return `${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`
      }).filter(Boolean).join(' ')
      const last = vals[vals.length - 1]
      const up = usePct ? last >= 0 : last >= vals[0]
      return { w, h, points, baseY: usePct ? yAt(0).toFixed(1) : null, color: up ? '#ff4d4f' : '#52c41a' }
    },
    hasData() {
      return this.tree.length > 0
    },
    // 二级行业总数（行业云图模式统计用）
    l2Count() {
      let n = 0
      for (const l1 of this.tree) n += (l1.children || []).length
      return n
    },
    // 是否已有 AI 打分数据（决定下拉框是否出现"着色：AI打分"选项）
    hasScores() {
      return this.scoreLoaded && Object.keys(this.scoreMap || {}).length > 0
    },
    hasCycleScores() {
      return this.cycleLoaded && Object.keys(this.cycleMap || {}).length > 0
    },
    // 是否有可播放的复盘快照（至少一个时间点已抓取）
    hasReplayAvailable() {
      return this.replayPoints.some(p => p.available)
    },
    // 页脚颜色说明（随当前着色维度切换）
    footerColorDesc() {
      if (this.colorMode === 'margin') return '颜色=融资净流入金额（红=净流入多 / 绿=净流出多）'
      if (this.colorMode === 'score') return '颜色=AI打分（红=高分可考虑 / 绿=低分需谨慎，50 为界）'
      if (this.colorMode === 'cycle') return '颜色=9维周期雷达（绿=危险/红=安全，见顶风险分）'
      return '颜色=涨跌幅（红涨绿跌）'
    },
    // 融资弹窗：序列最新日期（YYYY/MM/DD），用于副标题"数据截至"
    latestFinDate() {
      const s = this.finModal.series
      if (!s || !s.length) return ''
      const d = String(s[s.length - 1].d)
      return d.length === 8 ? d.replace(/(\d{4})(\d{2})(\d{2})/, '$1/$2/$3') : d
    },
    latestFinBalance() {
      if (this.finModal.latestBalance != null && !isNaN(this.finModal.latestBalance)) {
        return this.finFmt(this.finModal.latestBalance, true)
      }
      const s = this.finModal.series
      if (!s || !s.length) return '--'
      for (let i = s.length - 1; i >= 0; i--) {
        const x = s[i]
        if (x && x.b != null && !isNaN(x.b)) return this.finFmt(x.b, true)
      }
      return '--'
    },
    // 图例：与 COLOR_STOPS 一一对应，每块标注涨跌幅阈值（左=跌/绿 → 中=0/灰 → 右=涨/红）
    legendSteps() {
      if (this.colorMode === 'margin') {
        return MARGIN_LEGEND_STEPS.map(step => ({
          ...step,
          title: '点击只看 ' + step.countTitle + '，再次点击复原'
        }))
      }
      if (this.colorMode === 'score') {
        return SCORE_LEGEND_STEPS.map(step => ({
          ...step,
          title: '点击只看 ' + step.countTitle + '，再次点击复原'
        }))
      }
      if (this.colorMode === 'cycle') {
        return CYCLE_LEGEND_STEPS.map(step => ({
          ...step,
          title: '点击只看 ' + step.countTitle + '，再点复原'
        }))
      }
      const labels = ['-4%', '-3%', '-2%', '-1%', '0%', '1%', '2%', '3%', '4%']
      const titles = ['跌幅 ≤ -4%', '-4% ~ -3%', '-3% ~ -2%', '-2% ~ -1%', '-1% ~ 0%', '0% ~ 1%', '1% ~ 2%', '2% ~ 3%', '涨幅 > 3%']
      return COLOR_STOPS.map(([v, rgb], i) => ({
        value: v,
        label: labels[i],
        countTitle: titles[i],
        title: '点击只看 ' + titles[i] + '，再点复原',
        color: `rgb(${rgb[0]},${rgb[1]},${rgb[2]})`
      }))
    },
    // 当前筛选状态条：legendApplied 非空时返回 {desc, count}，供顶部徽标展示（支持多选）
    filterBadge() {
      const applied = this.legendApplied
      if ((!applied || applied.length === 0) && !this.pushedOnly) return null
      if (this.pushedOnly && (!applied || applied.length === 0)) {
        return { desc: '推送股票', count: this.pushedCount }
      }
      let count = 0
      for (const s of this.tree) {
        for (const l2 of (s.children || [])) {
          for (const st of (l2.children || [])) {
            if (this.stockMatchesActiveFilter(st)) count++
          }
        }
      }
      let desc
      if (applied.length === 1) {
        const a = applied[0]
        if (this.colorMode === 'margin') {
          desc = (MARGIN_LEGEND_STEPS.find(step => step.value === a) || {}).label || '融资净流入'
        } else if (this.colorMode === 'score') {
          desc = ((SCORE_LEGEND_STEPS.find(step => step.value === a) || {}).countTitle) || 'AI打分'
        } else if (this.colorMode === 'cycle') {
          desc = ((CYCLE_LEGEND_STEPS.find(step => step.value === a) || {}).countTitle) || '9维周期雷达'
        } else if (a === 'limit_up') desc = '涨停'
        else if (a === 'limit_down') desc = '跌停'
        else if (a <= -4) desc = '跌幅 ≤ -4%'
        else if (a >= 4) desc = '涨幅 > 3%'
        else desc = `${a - 1}% ~ ${a}%`
      } else {
        desc = `已勾选 ${applied.length} 档`
      }
      return { desc, count }
    },
    // 统计各个涨跌幅区间的股票数量
    legendCounts() {
      if (this.colorMode === 'margin') {
        const counts = Object.fromEntries(MARGIN_LEGEND_STEPS.map(step => [step.value, 0]))
        for (const s of this.tree) {
          for (const l2 of (s.children || [])) {
            for (const st of (l2.children || [])) {
              const step = MARGIN_LEGEND_STEPS.find(item => inMarginFilter(this.marginValue(st), item.value))
              if (step) counts[step.value]++
            }
          }
        }
        return counts
      }
      if (this.colorMode === 'score') {
        const counts = Object.fromEntries(SCORE_LEGEND_STEPS.map(step => [step.value, 0]))
        for (const s of this.tree) {
          for (const l2 of (s.children || [])) {
            for (const st of (l2.children || [])) {
              const step = SCORE_LEGEND_STEPS.find(item => inScoreFilter(this.scoreValue(st), item.value))
              if (step) counts[step.value]++
            }
          }
        }
        return counts
      }
      if (this.colorMode === 'cycle') {
        const counts = Object.fromEntries(CYCLE_LEGEND_STEPS.map(step => [step.value, 0]))
        for (const s of this.tree) {
          for (const l2 of (s.children || [])) {
            for (const st of (l2.children || [])) {
              const step = CYCLE_LEGEND_STEPS.find(item => inCycleFilter(this.cycleValue(st), item.value))
              if (step) counts[step.value]++
            }
          }
        }
        return counts
      }
      const counts = {
        limit_up: 0,
        limit_down: 0,
        '-4': 0,
        '-3': 0,
        '-2': 0,
        '-1': 0,
        '0': 0,
        '1': 0,
        '2': 0,
        '3': 0,
        '4': 0
      }

      for (const s of this.tree) {
        for (const l2 of (s.children || [])) {
          for (const st of (l2.children || [])) {
            // 统计涨停
            if (inChangeFilter(st.change, st.code, 'limit_up')) counts.limit_up++
            // 统计跌停
            if (inChangeFilter(st.change, st.code, 'limit_down')) counts.limit_down++
            // 统计各色块区间
            if (inChangeFilter(st.change, st.code, -4)) counts['-4']++
            if (inChangeFilter(st.change, st.code, -3)) counts['-3']++
            if (inChangeFilter(st.change, st.code, -2)) counts['-2']++
            if (inChangeFilter(st.change, st.code, -1)) counts['-1']++
            if (inChangeFilter(st.change, st.code, 0)) counts['0']++
            if (inChangeFilter(st.change, st.code, 1)) counts['1']++
            if (inChangeFilter(st.change, st.code, 2)) counts['2']++
            if (inChangeFilter(st.change, st.code, 3)) counts['3']++
            if (inChangeFilter(st.change, st.code, 4)) counts['4']++
          }
        }
      }

      return counts
    }
  },
  async mounted() {
    // 非响应式实例属性（频繁变化的缩放/布局，不放 data 避免响应式开销）
    this.view = { k: 1, tx: 0, ty: 0 }
    this.layout = null
    this.cssW = 0
    this.cssH = 0
    this.dpr = window.devicePixelRatio || 1
    this.dragging = false
    this.lastX = 0
    this.lastY = 0
    this._raf = 0
    this._hlUntil = 0      // 搜索高亮截止时间戳(ms)
    this._hlTimer = null   // 高亮5秒后自动清除的定时器
    this._matches = null   // { stocks:Set(code), l1s:Set(name), l2s:Set(name) }
    this.clickTimer = null // 单击防抖定时器（用于区分"单击弹窗"与"双击跳雪球"）
    this.hoverSummaryCache = new Map()
    this.hoverSummaryTimer = null
    this.hoverSummarySeq = 0
    // 悬浮分时迷你图：按 code 缓存（60s TTL，失败也缓存防打爆）
    this.hoverTrendCache = new Map()
    this.hoverTrendTimer = null
    this.hoverTrendSeq = 0
    this.finChart = null   // 融资弹窗 ECharts 实例
    this._downX = 0        // mousedown 落点（判定单击/拖拽用）
    this._pushedCodeSet = null  // 推送股票代码Set，用于高亮筛选
    this._marginColor = {}      // {裸6位code: 融资净流入排名色}（colorMode=margin 时由 computeMarginColors 填充）
    this._downY = 0
    this._finRetry = 0     // 按需更新无数据时的自动重试计数
    this.replayTimer = null        // 复盘自动播放定时器
    this.replayPointsTimer = null  // 复盘时间点状态刷新定时器

    this.syncSize()
    this.ro = new ResizeObserver(() => this.onResize())
    if (this.$refs.wrapperEl) this.ro.observe(this.$refs.wrapperEl)

    // 登录态检查：未登录访客进演示模式（只读一次固定快照，跳过全部实时链路）
    window.addEventListener('auth-login-success', this.onAuthLogin)
    window.addEventListener('auth-logout', this.onAuthLogout)
    try {
      const session = await getAuthSession()
      if (session && session.authenticated) {
        this.startLiveMode()
        return
      }
    } catch (e) { /* 会话检查失败按未登录处理，走演示 */ }
    await this.loadDemoMap()
  },
  beforeUnmount() {
    window.removeEventListener('auth-login-success', this.onAuthLogin)
    window.removeEventListener('auth-logout', this.onAuthLogout)
    clearInterval(this.timer)
    clearInterval(this.replayPointsTimer)
    if (this.scoringTimer) clearInterval(this.scoringTimer)
    if (this.cycleTimer) clearInterval(this.cycleTimer)
    if (this.replayTimer) clearTimeout(this.replayTimer)
    if (this._raf) cancelAnimationFrame(this._raf)
    if (this._hlTimer) clearTimeout(this._hlTimer)
    if (this._flyAnim) cancelAnimationFrame(this._flyAnim)
    if (this._flyDebounce) clearTimeout(this._flyDebounce)
    if (this.clickTimer) clearTimeout(this.clickTimer)
    if (this.finChart) { this.finChart.dispose(); this.finChart = null }
    if (this.ro) this.ro.disconnect()
  },
  methods: {
    goBack() {
      this.$router.push('/')
    },

    // ===== 演示模式（未登录访客）：只读固定快照，永远不刷新 =====
    // 唤起登录框（Root.vue 全局监听 auth-request-login）
    promptLogin() {
      window.dispatchEvent(new CustomEvent('auth-request-login'))
    },
    async loadDemoMap() {
      try {
        const res = await getDemoMarketMap()
        const d = res && res.success ? res.data : null
        if (d && d.available && d.data) {
          this.demoMode = true
          this.demoDate = d.date || ''
          this.applyData(d.data)
        }
      } catch (e) {
        console.error('云图演示数据加载失败:', e)
      }
    },
    onAuthLogin() {
      // 演示态/实时链路未启动 → 登录成功后补齐全部实时链路（已在实时态则不动）
      if (this.liveStarted) return
      this.demoMode = false
      this.startLiveMode()
    },
    onAuthLogout() {
      // 登出：停掉全部实时链路，回到演示快照
      this.stopLiveTimers()
      this.liveStarted = false
      this.demoMode = false
      this.loadDemoMap()
    },
    stopLiveTimers() {
      if (this.timer) { clearInterval(this.timer); this.timer = null }
      if (this.replayPointsTimer) { clearInterval(this.replayPointsTimer); this.replayPointsTimer = null }
      if (this.scoringTimer) { clearInterval(this.scoringTimer); this.scoringTimer = null }
      if (this.cycleTimer) { clearInterval(this.cycleTimer); this.cycleTimer = null }
      if (this.replayTimer) { clearTimeout(this.replayTimer); this.replayTimer = null }
    },
    // 实时全链路（原 mounted 尾部整体搬来；登录态启动与"演示→登录"补齐共用）
    startLiveMode() {
      this.liveStarted = true
      this.loadPushedStateFromQuery()
      this.fetchData(true)
      // 实时轮询：复盘态下暂停，避免历史快照画面被实时数据覆盖
      // 新浪行情源本身约3-6秒更新一次，15秒轮询已足够跟手；后端每请求现拉无缓存，再快只是徒增请求
      this.timer = setInterval(() => { if (!this.replayMode) this.fetchData(false) }, 15000)
      // 复盘时间点状态：首拉一次 + 每 5 分钟刷新（盘中陆续点亮新抓取的按钮）
      this.refreshReplayPoints()
      this.replayPointsTimer = setInterval(() => this.refreshReplayPoints(), 5 * 60 * 1000)
      // AI 打分：恢复在跑任务轮询 + 预载已评分缓存（决定下拉是否出现"着色：AI打分"）+ 检查 AI 配置
      this.checkScoringStatus()
      this.loadScoreData()
      this.checkAiEnabled()
      this.checkCycleStatus()
      this.loadCycleData()
    },

    // 图例多选：点击区间只切换"勾选"状态（不立即过滤），可勾多个；点"确定"才应用到云图
    toggleLegendSel(v) {
      const i = this.legendSel.indexOf(v)
      if (i >= 0) this.legendSel.splice(i, 1)
      else this.legendSel.push(v)
    },
    // 应用当前勾选（多选 OR：命中任一区间即显示）；勾选为空时=清空筛选(全显示)
    applyLegendFilter() {
      this.legendApplied = this.legendSel.slice()
      this.render()
    },
    clearFilter() {
      if (this.legendApplied.length === 0 && this.legendSel.length === 0 && !this.pushedOnly) return
      this.legendSel = []
      this.legendApplied = []
      if (this.pushedOnly) this.handleClearPushed()
      else this.render()
    },
    showLegendTooltip(e, text) {
      const r = e.currentTarget.getBoundingClientRect()
      this.legendTooltip = {
        visible: true,
        text,
        x: Math.min(window.innerWidth - 10, r.right),
        y: Math.max(10, r.top - 8)
      }
    },
    hideLegendTooltip() {
      this.legendTooltip.visible = false
    },

    // 搜索：模糊匹配个股(名称/代码)与行业(一/二级)。命中后自动放大定位到命中区域，
    // 小市值股的格子也能看清；高亮在搜索词存在期间持续显示（不再只闪5秒）。
    onSearchInput() {
      if (!this.layout) { this.matchCount = 0; return }
      const q = (this.searchQuery || '').trim()
      const m = q ? this.computeMatches(q) : null
      this._matches = m
      this.matchCount = m ? (m.stocks.size + m.l1s.size + m.l2s.size) : 0
      // 不再用限时高亮，清掉旧的5秒定时器
      if (this._hlTimer) { clearTimeout(this._hlTimer); this._hlTimer = null }
      this._hlUntil = 0
      // 取消进行中的飞行动画 / 防抖
      if (this._flyAnim) { cancelAnimationFrame(this._flyAnim); this._flyAnim = 0 }
      if (this._flyDebounce) { clearTimeout(this._flyDebounce); this._flyDebounce = null }

      if (!m) {
        // 清空搜索词：回到全图；有词但无命中：保持当前视图不动
        if (!q) this.view = { k: 1, tx: 0, ty: 0 }
        this.render()
        return
      }
      // 防抖200ms：打字停顿后一次性平滑飞到命中区域，避免逐键抖动
      this._flyDebounce = setTimeout(() => { this._flyDebounce = null; this.flyToMatches(m) }, 200)
      this.render()
    },
    // 命中项在 layout 基坐标系下的包围盒（个股 + 二级 + 一级并集）
    matchesBBox(m) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
      const expand = (n) => {
        if (!n) return
        if (n.x < minX) minX = n.x
        if (n.y < minY) minY = n.y
        if (n.x + n.w > maxX) maxX = n.x + n.w
        if (n.y + n.h > maxY) maxY = n.y + n.h
      }
      if (this.industryMode) {
        for (const t of this.layout) {
          if (t && (m.l2s.has(t.name) || m.l1s.has(t.l1Name))) expand(t)
        }
      } else {
        for (const s of this.layout) {
          if (m.l1s.has(s.name)) expand(s)
          for (const l2 of s.children) {
            if (m.l2s.has(l2.name)) expand(l2)
            for (const st of l2.children) {
              if (m.stocks.has(st.code)) expand(st)
            }
          }
        }
      }
      if (minX === Infinity) return null
      return { minX, minY, maxX, maxY }
    },
    // 由包围盒算“恰好框住并居中”的目标视图（留28%边距；过小格子上限12倍）
    computeFitView(bbox) {
      const bw = Math.max(1e-3, bbox.maxX - bbox.minX)
      const bh = Math.max(1e-3, bbox.maxY - bbox.minY)
      let k = Math.min(this.cssW / bw, this.cssH / bh) * 0.72
      // 命中区域很小时，至少放大到目标在屏幕上约96px（再受12倍上限约束）
      const needK = 96 / Math.min(bw, bh)
      if (k < needK) k = needK
      k = clamp(k, 1, 12)
      const cx = (bbox.minX + bbox.maxX) / 2
      const cy = (bbox.minY + bbox.maxY) / 2
      const view = { k, tx: this.cssW / 2 - cx * k, ty: this.cssH / 2 - cy * k }
      // 复刻 clampView 的平移边界（此处不写 this.view，交给 animateView 过渡）
      view.tx = clamp(view.tx, this.cssW * (1 - k), 0)
      view.ty = clamp(view.ty, this.cssH * (1 - k), 0)
      return view
    },
    flyToMatches(m) {
      const bbox = this.matchesBBox(m)
      if (!bbox) return
      this.animateView(this.computeFitView(bbox))
    },
    // 平滑过渡到目标视图（easeOutCubic），动画期间每帧 render
    animateView(target, duration = 460) {
      if (this._flyAnim) cancelAnimationFrame(this._flyAnim)
      const start = { k: this.view.k, tx: this.view.tx, ty: this.view.ty }
      const t0 = Date.now()
      const lerp = (a, b, e) => a + (b - a) * e
      const step = () => {
        const t = Math.min(1, (Date.now() - t0) / duration)
        const e = 1 - Math.pow(1 - t, 3)
        this.view.k = lerp(start.k, target.k, e)
        this.view.tx = lerp(start.tx, target.tx, e)
        this.view.ty = lerp(start.ty, target.ty, e)
        this.clampView()
        this.render()
        if (t < 1) this._flyAnim = requestAnimationFrame(step)
        else this._flyAnim = 0
      }
      this._flyAnim = requestAnimationFrame(step)
    },
    computeMatches(q) {
      const ql = (q || '').trim().toLowerCase()
      if (!ql) return null
      const stocks = new Set(), l1s = new Set(), l2s = new Set()
      if (this.industryMode) {
        // 行业云图：layout 为扁平的二级行业色块（无 children）
        for (const t of this.layout) {
          if (!t) continue
          if ((t.name || '').toLowerCase().includes(ql)) l2s.add(t.name)
          if ((t.l1Name || '').toLowerCase().includes(ql)) l1s.add(t.l1Name)
        }
      } else {
        for (const s of this.layout) {
          if (s.name.toLowerCase().includes(ql)) l1s.add(s.name)
          for (const l2 of s.children) {
            if (l2.name.toLowerCase().includes(ql)) l2s.add(l2.name)
            for (const st of l2.children) {
              if (st.name.toLowerCase().includes(ql) || (st.code || '').toLowerCase().includes(ql)) stocks.add(st.code)
            }
          }
        }
      }
      if (!stocks.size && !l1s.size && !l2s.size) return null
      return { stocks, l1s, l2s }
    },
    async fetchData(showLoading) {
      // 演示态不拉实时行情，点刷新即唤起登录
      if (this.demoMode) { this.promptLogin(); return }
      if (this.refreshing) return
      this.refreshing = true
      try {
        // 首屏两阶段：先读行业+市值缓存秒开灰色(0%)云图，再请求实时涨跌幅二次上色
        if (showLoading && !this.hasData) {
          try {
            const skel = await getMarketMapStructure()
            if (skel.success) {
              this.applyData(skel.data)
              this.changesLoading = true // 灰图已出，实时涨跌幅加载中
            }
          } catch (e) { /* 骨架失败则忽略，继续走全量 */ }
        }
        const res = await getMarketMap()
        if (res.success) this.applyData(res.data)
      } catch (e) {
        console.error('获取大盘云图失败', e)
      } finally {
        this.changesLoading = false
        this.refreshing = false
      }
    },
    applyData(data) {
      this.sourceTree = data.tree || []
      this.sourceTotals = {
        totalSectors: data.total_sectors || 0,
        totalStocks: data.total_stocks || 0,
        cacheTime: data.cache_time || ''
      }
      this.rebuildTreeFromSource()
    },
    rebuildTreeFromSource() {
      this.tree = Array.isArray(this.sourceTree) ? this.sourceTree : []
      this.totalSectors = this.sourceTotals.totalSectors || 0
      this.totalStocks = this.sourceTotals.totalStocks || 0
      this.cacheTime = this.sourceTotals.cacheTime || ''
      this.$nextTick(() => { this.buildLayout(); this.render() })
    },
    async loadPushedStateFromQuery() {
      const pushedFlag = this.$route?.query?.pushed
      if (String(pushedFlag || '') !== '1') return
      this.pushedLoading = true
      try {
        const res = await getMarketMapPush()
        const stocks = (res && res.success && res.data && Array.isArray(res.data.stocks)) ? res.data.stocks : []
        this.pushedCodes = stocks.map(item => extractDigits(item.code)).filter(Boolean)
        this.pushedCount = this.pushedCodes.length
        this.pushedUpdatedAt = (res && res.success && res.data && res.data.updated_at) || ''
        this.pushedOnly = this.pushedCount > 0
        this._pushedCodeSet = this.pushedOnly ? new Set(this.pushedCodes) : null
        // 不在此处调用 rebuildTreeFromSource，等 fetchData 完成后由 applyData 触发
      } catch (e) {
        console.error('加载推送股票失败', e)
      } finally {
        this.pushedLoading = false
      }
    },
    async handleClearPushed() {
      this.pushedLoading = true
      try {
        const res = await clearMarketMapPush()
        if (res && res.success) {
          this.pushedOnly = false
          this.pushedCodes = []
          this.pushedCount = 0
          this.pushedUpdatedAt = ''
          this._pushedCodeSet = null
          this.render()
          if (this.$route?.query?.pushed) {
            const nextQuery = { ...(this.$route.query || {}) }
            delete nextQuery.pushed
            this.$router.replace({ path: this.$route.path, query: nextQuery })
          }
        }
      } catch (e) {
        console.error('清空推送股票失败', e)
      } finally {
        this.pushedLoading = false
      }
    },
    async refreshCache() {
      if (this.demoMode) { this.promptLogin(); return }
      // 行业库更新要从东方财富重抓全市场约5000只股票的行业+市值，耗时较长且低频需要，
      // 加二次确认防止误触（按钮和"刷新行情"挨得近，容易点错）。
      if (!window.confirm('确认更新行业库？\n\n将重新抓取全市场约5000只股票的行业分类与市值，耗时约1-2分钟，期间云图继续用旧缓存显示。\n\n行业分类变化极少，通常无需频繁更新；如只是想看最新涨跌，请点「刷新行情」。')) {
        return
      }
      this.cacheLoading = true
      try {
        const res = await refreshMarketMapCache()
        if (res.success) await this.fetchData(true)
      } catch (e) {
        console.error('刷新行业库失败', e)
      } finally {
        this.cacheLoading = false
      }
    },

    // ===== 复盘 / 回放 =====
    // 拉取今天各时间点快照的抓取状态（决定时间按钮亮/灰）
    async refreshReplayPoints() {
      try {
        const res = await getMarketMapSnapshots()
        if (res && res.success && Array.isArray(res.points)) {
          this.replayPoints = res.points
        }
      } catch (e) {
        // 静默：复盘状态拉取失败不影响主图实时行情
      }
    },
    // 点时间按钮：进入复盘态，加载该时刻快照（复用 applyData 渲染）
    async enterReplay(time) {
      if (!time) return
      this.stopPlay()
      try {
        const res = await getMarketMapSnapshot(time)
        if (res && res.success) {
          this.replayMode = true
          this.replayTime = time
          this.applyData(res.data)
        }
      } catch (e) {
        console.error('加载复盘快照失败', e)
      }
    },
    // 退出复盘，恢复实时
    exitReplay() {
      if (!this.replayMode) return
      this.replayMode = false
      this.replayTime = ''
      this.stopPlay()
      this.fetchData(true)
    },
    // 一键播放：顺序播放全部已抓快照，每 1.5 秒一帧，到最后一帧停止（不循环）
    togglePlay() {
      if (this.replayPlaying) { this.stopPlay(); return }
      const available = this.replayPoints.filter(p => p.available).map(p => p.time)
      if (!available.length) return
      let idx = available.indexOf(this.replayTime)
      // 当前不在列表里、或已是最后一帧 → 从第一帧开始
      if (idx < 0 || idx >= available.length - 1) idx = 0
      this.replayMode = true
      this.replayPlaying = true
      const playFrame = async () => {
        if (!this.replayPlaying) return
        const time = available[idx]
        if (!time) { this.stopPlay(); return }
        try {
          const res = await getMarketMapSnapshot(time)
          if (!this.replayPlaying) return   // 播放途中被停止/手动切帧
          if (res && res.success) {
            this.replayTime = time
            this.applyData(res.data)
          }
        } catch (e) { /* 单帧失败不中断整体播放 */ }
        idx++
        if (idx >= available.length) {
          this.stopPlay()   // 播完最后一帧，停止并停留在该帧
          return
        }
        this.replayTimer = setTimeout(playFrame, 1500)
      }
      playFrame()
    },
    stopPlay() {
      this.replayPlaying = false
      if (this.replayTimer) { clearTimeout(this.replayTimer); this.replayTimer = null }
    },

    // ===== 着色维度（涨跌幅 / 融资净流入）=====
    // 个股取色：融资态用排名色、默认用涨跌幅
    marginValue(stock) {
      const entry = this.marginMap[extractDigits(stock && stock.code)]
      const value = entry && entry.net
      return typeof value === 'number' && isFinite(value) ? value : null
    },
    // 个股 AI 打分（裸6位code 查 scoreMap）；未评分返回 null
    scoreValue(stock) {
      const entry = this.scoreMap[extractDigits(stock && stock.code)]
      const v = entry && entry.score
      return typeof v === 'number' && isFinite(v) ? v : null
    },
    // 个股所属二级行业的周期诊断分（原始分，越高=越危险）
    cycleValue(stock) {
      const l2Name = stock && stock.l2Name
      if (!l2Name) return null
      const entry = this.cycleMap[l2Name]
      if (!entry || typeof entry.overall_score !== 'number') return null
      return entry.overall_score  // 直接用原始分，越高越危险
    },
    stockMatchesActiveFilter(stock) {
      const applied = this.legendApplied
      if (!applied || applied.length === 0) return true   // 无应用筛选 → 全显示
      // 多选 OR：命中任一已勾选区间即显示
      if (this.colorMode === 'margin') return applied.some(a => inMarginFilter(this.marginValue(stock), a))
      if (this.colorMode === 'score') return applied.some(a => inScoreFilter(this.scoreValue(stock), a))
      if (this.colorMode === 'cycle') return applied.some(a => inCycleFilter(this.cycleValue(stock), a))
      return applied.some(a => inChangeFilter(stock.change, stock.code, a))
    },
    stockMetricLabel(stock) {
      if (this.colorMode === 'margin') return this.formatMoney(this.marginValue(stock))
      if (this.colorMode === 'score') {
        const v = this.scoreValue(stock)
        return v == null ? '--' : String(v)
      }
      if (this.colorMode === 'cycle') {
        return ''  // 行业周期模式个股不显示分数，分数在大区域显示
      }
      return fmtPct(stock.change)
    },
    stockColor(s) {
      if (this.colorMode === 'margin') {
        return this._marginColor[extractDigits(s.code)] || NO_MARGIN_COLOR
      }
      if (this.colorMode === 'score') {
        const v = this.scoreValue(s)
        return v == null ? NO_SCORE_COLOR : interpScoreColor(v)
      }
      if (this.colorMode === 'cycle') {
        const v = this.cycleValue(s)
        return v == null ? NO_CYCLE_COLOR : interpCycleColor(v)
      }
      return interpColor(s.change)
    },
    // 行业云图：二级行业色块颜色。周期维度按行业雷达分；其余维度（含涨跌幅/融资/AI打分，
    // 后两者为个股级数据、行业级暂无聚合）统一按二级行业聚合涨跌幅上色，保证云图可读。
    industryColor(l2) {
      if (this.colorMode === 'cycle') {
        const entry = this.cycleMap[l2.name]
        const v = entry && typeof entry.overall_score === 'number' ? entry.overall_score : null
        return v == null ? NO_CYCLE_COLOR : interpCycleColor(v)
      }
      return interpColor(l2.change)
    },
    toggleIndustryMode() {
      this.industryMode = !this.industryMode
      // 行业云图不适用个股级图例筛选/推送过滤，切换时清空，避免整图被错误灰显
      this.legendSel = []
      this.legendApplied = []
      this.view = { k: 1, tx: 0, ty: 0 }
      this.buildLayout()
      // 按新布局重算搜索高亮/飞行（保留搜索词）；无搜索词则直接重绘
      if (this.searchQuery) this.onSearchInput()
      else this.render()
    },
    async onColorModeChange(mode) {
      if (mode === this.colorMode) return
      // 演示态只允许涨跌幅着色：融资/AI/周期维度都要拉实时鉴权数据
      if (this.demoMode && mode !== 'change') {
        this.promptLogin()
        return
      }
      this.colorMode = mode
      this.legendSel = []
      this.legendApplied = []
      if (mode === 'margin' && !this.marginLoaded) await this.loadMarginData()
      if (mode === 'score' && !this.scoreLoaded) await this.loadScoreData()
      if (mode === 'cycle' && !this.cycleLoaded) await this.loadCycleData()
      this.buildLayout()
      this.render()
    },
    async loadMarginData() {
      this.marginLoading = true
      try {
        const res = await getMarketMapMargin()
        if (res && res.success) {
          this.marginMap = res.map || {}
          this.marginDate = res.latest_date || ''
          this.marginLoaded = true
          this.computeMarginColors()
        }
      } catch (e) {
        console.error('融资净流入加载失败', e)
      } finally {
        this.marginLoading = false
      }
    },
    // 按净流入大小排名映射深浅：正流入→红、净流出→绿，排名越靠前(绝对值越大)越深
    computeMarginColors() {
      const map = {}
      // 必须先按净流入大小排序再赋深度：否则对象 key(整型字符串)按数字升序遍历，
      // depth≈1 的深色全落到 000xxx/600xxx(大盘股=treemap 左上角)，300xxx/688xxx(小盘)depth≈0 暗成灰色 → "只有左上角亮"
      const pos = [], neg = []
      for (const code in this.marginMap) {
        // 按 净流入/昨日融资余额(相对增速) 排名：消除大市值股绝对额对深色的统治(否则亮的永远是左上角大盘)
        const entry = this.marginMap[code]
        const net = entry && typeof entry.net === 'number' && isFinite(entry.net) ? entry.net : null
        if (net == null) continue
        if (net > 0) pos.push([code, net])
        else if (net < 0) neg.push([code, Math.abs(net)])
        else map[code] = 'rgb(76,68,84)'
      }
      pos.sort((a, b) => b[1] - a[1])                       // 净流入多 → 前 → 深
      neg.sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))  // 净流出多 → 前 → 深
      const assign = (arr, light, deep) => {
        if (!arr.length) return
        const sorted = arr.map(item => item[1]).sort((a, b) => a - b)
        const cap = sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)] || sorted[sorted.length - 1]
        for (const [code, amount] of arr) {
          const depth = cap > 0 ? Math.min(1, Math.log1p(amount) / Math.log1p(cap)) : 0
          map[code] = marginDepthColor(depth, light, deep)
        }
      }
      assign(pos, MARGIN_RED_LIGHT, MARGIN_RED_DEEP)
      assign(neg, MARGIN_GREEN_LIGHT, MARGIN_GREEN_DEEP)
      this._marginColor = map
    },

    // ===== AI 打分维度：拉取已评分缓存（只读，不触发打分）=====
    async loadScoreData() {
      this.scoreLoading = true
      try {
        const res = await getStockScores()
        if (res && res.success) {
          this.scoreMap = res.map || {}
          this.scoreDate = res.scored_at ? String(res.scored_at).slice(0, 10) : ''
          this.scoreLoaded = true
        }
      } catch (e) {
        console.error('AI打分加载失败', e)
      } finally {
        this.scoreLoading = false
      }
    },

    // ===== AI 批量打分：弹窗 / 启动 / 轮询 / 停止（镜像 App.script.js 的 analyze-daily 轮询）=====
    openScoreDialog() {
      if (this.demoMode) { this.promptLogin(); return }
      this.scoreDialog.busy = false
      // 按当前任务状态决定首屏视图
      if (this.scoringRunning || this.scoringStatus.status === 'running') {
        this.scoreDialog.view = 'running'
      } else if (this.scoringStatus.status === 'completed') {
        this.scoreDialog.view = 'done'
      } else if (this.scoringStatus.status === 'failed' || this.scoringStatus.status === 'interrupted') {
        this.scoreDialog.view = 'error'
      } else {
        this.scoreDialog.view = 'confirm'
      }
      this.scoreDialog.visible = true
    },
    closeScoreDialog() {
      this.scoreDialog.visible = false
    },
    async confirmStartScoring(onlyFailed = false) {
      this.scoreDialog.busy = true
      try {
        const res = await startStockScoring(onlyFailed)
        if (res && res.success) {
          if (res.estimate) this.scoreEstimate = { ...this.scoreEstimate, ...res.estimate }
          this.scoringRunning = true
          this.scoringStatus = {
            ...this.scoringStatus,
            status: 'running',
            progress: res.progress || 0,
            total: (res.estimate && res.estimate.total) || this.scoringStatus.total || 0,
            step: res.message || '已启动'
          }
          this.scoreDialog.view = 'running'
          this.startScoringPolling()
        } else {
          // 启动被拒（已在运行）或失败（AI 未配置等）
          if (res && res.status === 'running') {
            this.scoringRunning = true
            this.scoringStatus = { ...this.scoringStatus, status: 'running', progress: res.progress || 0, step: res.step || '' }
            this.scoreDialog.view = 'running'
            this.startScoringPolling()
          } else {
            if (res && /未启用|配置不完整/.test(res.message || '')) this.aiEnabled = false
            this.scoringStatus = { ...this.scoringStatus, status: 'failed', message: (res && res.message) || '启动失败' }
            this.scoreDialog.view = 'error'
          }
        }
      } catch (e) {
        this.scoringStatus = { ...this.scoringStatus, status: 'failed', message: '启动失败：' + ((e && e.message) || '网络错误') }
        this.scoreDialog.view = 'error'
      } finally {
        this.scoreDialog.busy = false
      }
    },
    startScoringPolling() {
      if (this.scoringTimer) clearInterval(this.scoringTimer)
      this.scoringTimer = setInterval(() => { this.pollScoringOnce() }, 5000)
    },
    async pollScoringOnce() {
      try {
        const res = await getStockScoringStatus()
        if (!res || !res.success) return
        const st = res.status
        this.scoringStatus = { ...this.scoringStatus, ...res }
        if (st === 'running') {
          this.scoringRunning = true
          if (this.scoreDialog.visible) this.scoreDialog.view = 'running'
          // 进行中：分数实时累加，若处于打分维度则刷新着色
          if (this.colorMode === 'score') {
            await this.loadScoreData()
            this.buildLayout()
            this.render()
          }
        } else if (st === 'completed') {
          this.scoringRunning = false
          if (this.scoringTimer) { clearInterval(this.scoringTimer); this.scoringTimer = null }
          await this.loadScoreData()
          if (this.colorMode === 'score') { this.buildLayout(); this.render() }
          if (this.scoreDialog.visible) this.scoreDialog.view = 'done'
        } else if (st === 'failed' || st === 'interrupted') {
          this.scoringRunning = false
          if (this.scoringTimer) { clearInterval(this.scoringTimer); this.scoringTimer = null }
          await this.loadScoreData()
          if (this.scoreDialog.visible) this.scoreDialog.view = 'error'
        }
      } catch (e) { /* 轮询失败，继续 */ }
    },
    async handleStopScoring() {
      try { await stopStockScoring() } catch (e) { /* noop */ }
      // 不立即改状态：等下一轮轮询确认 interrupted（当前批次完成后才停）
    },
    finishAndSwitchToScore() {
      this.scoreDialog.visible = false
      if (!this.hasScores) return
      this.colorMode = 'score'
      this.legendSel = []
      this.legendApplied = []
      this.buildLayout()
      this.render()
    },

    // ===== 行业周期诊断维度 =====
    async loadCycleData() {
      this.cycleLoading = true
      try {
        const res = await getIndustryCycleAllScores()
        if (res && res.success) {
          this.cycleMap = res.scores || {}
          this.cycleDate = res.analyzed_at ? String(res.analyzed_at).slice(0, 10) : ''
          this.cycleLoaded = true
        }
      } catch (e) {
        console.error('行业周期诊断加载失败', e)
      } finally {
        this.cycleLoading = false
      }
    },

    // 批量诊断弹窗
    openCycleDialog() {
      if (this.demoMode) { this.promptLogin(); return }
      this.cycleDialog.busy = false
      // 统计二级行业数量
      const l2Names = this._collectL2Names()
      this.cycleEstimate.total = l2Names.length
      this.cycleEstimate.eta = l2Names.length > 30 ? '30-90' : '10-30'

      if (this.cycleRunning || this.cycleStatus.status === 'running') {
        this.cycleDialog.view = 'running'
      } else if (this.cycleStatus.status === 'completed') {
        this.cycleDialog.view = 'done'
      } else if (this.cycleStatus.status === 'failed' || this.cycleStatus.status === 'interrupted') {
        this.cycleDialog.view = 'error'
      } else {
        this.cycleDialog.view = 'confirm'
      }
      this.cycleDialog.visible = true
    },
    closeCycleDialog() {
      this.cycleDialog.visible = false
    },
    _collectL2Names() {
      const names = []
      for (const s of this.tree) {
        for (const l2 of (s.children || [])) {
          if (l2.name) names.push(l2.name)
        }
      }
      return [...new Set(names)]
    },
    async confirmStartCycle() {
      this.cycleDialog.busy = true
      try {
        const industries = this._collectL2Names()
        if (!industries.length) {
          this.cycleStatus = { ...this.cycleStatus, status: 'failed', message: '未找到二级行业，请先更新行业库' }
          this.cycleDialog.view = 'error'
          return
        }
        const res = await startIndustryCycleBatch(industries)
        if (res && res.success) {
          this.cycleRunning = true
          this.cycleStatus = {
            ...this.cycleStatus,
            status: 'running',
            progress: 0,
            total: res.total || industries.length,
            done: 0,
            failed: 0,
            step: '已启动',
            current: ''
          }
          this.cycleDialog.view = 'running'
          this.startCyclePolling()
        } else {
          if (res && res.status === 'running') {
            this.cycleRunning = true
            this.cycleStatus = { ...this.cycleStatus, status: 'running', progress: res.progress || 0 }
            this.cycleDialog.view = 'running'
            this.startCyclePolling()
          } else {
            this.cycleStatus = { ...this.cycleStatus, status: 'failed', message: (res && res.message) || '启动失败' }
            this.cycleDialog.view = 'error'
          }
        }
      } catch (e) {
        this.cycleStatus = { ...this.cycleStatus, status: 'failed', message: '启动失败：' + ((e && e.message) || '网络错误') }
        this.cycleDialog.view = 'error'
      } finally {
        this.cycleDialog.busy = false
      }
    },
    startCyclePolling() {
      if (this.cycleTimer) clearInterval(this.cycleTimer)
      this.cycleTimer = setInterval(() => { this.pollCycleOnce() }, 5000)
    },
    async pollCycleOnce() {
      try {
        const res = await getIndustryCycleBatchStatus()
        if (!res || !res.success) return
        const st = res.status
        this.cycleStatus = { ...this.cycleStatus, ...res }
        if (st === 'running') {
          this.cycleRunning = true
          if (this.cycleDialog.visible) this.cycleDialog.view = 'running'
          if (this.colorMode === 'cycle') {
            await this.loadCycleData()
            this.buildLayout()
            this.render()
          }
        } else if (st === 'completed') {
          this.cycleRunning = false
          if (this.cycleTimer) { clearInterval(this.cycleTimer); this.cycleTimer = null }
          await this.loadCycleData()
          if (this.colorMode === 'cycle') { this.buildLayout(); this.render() }
          if (this.cycleDialog.visible) this.cycleDialog.view = 'done'
        } else if (st === 'failed' || st === 'interrupted') {
          this.cycleRunning = false
          if (this.cycleTimer) { clearInterval(this.cycleTimer); this.cycleTimer = null }
          await this.loadCycleData()
          if (this.cycleDialog.visible) this.cycleDialog.view = 'error'
        }
      } catch (e) { /* 轮询失败继续 */ }
    },
    async handleStopCycle() {
      try { await stopIndustryCycleBatch() } catch (e) { /* noop */ }
    },
    finishAndSwitchToCycle() {
      this.cycleDialog.visible = false
      if (!this.hasCycleScores) return
      this.colorMode = 'cycle'
      this.legendSel = []
      this.legendApplied = []
      this.buildLayout()
      this.render()
    },
    async retryFailedCycle() {
      const failedList = this.cycleStatus.failed_industries || []
      if (!failedList.length) return
      this.cycleDialog.busy = true
      try {
        const res = await startIndustryCycleBatch(failedList)
        if (res && res.success) {
          this.cycleRunning = true
          this.cycleStatus = {
            ...this.cycleStatus,
            status: 'running',
            progress: 0,
            total: res.total || failedList.length,
            done: 0,
            failed: 0,
            step: `重试失败行业：${failedList.length}个`,
            current: '',
            failed_industries: []
          }
          this.cycleDialog.view = 'running'
          this.startCyclePolling()
        } else {
          this.cycleStatus = { ...this.cycleStatus, status: 'failed', message: (res && res.message) || '启动重试失败' }
          this.cycleDialog.view = 'error'
        }
      } catch (e) {
        this.cycleStatus = { ...this.cycleStatus, status: 'failed', message: '启动重试失败：' + ((e && e.message) || '网络错误') }
        this.cycleDialog.view = 'error'
      } finally {
        this.cycleDialog.busy = false
      }
    },
    // 挂载时检查周期诊断任务状态
    async checkCycleStatus() {
      try {
        const res = await getIndustryCycleBatchStatus()
        if (res && res.success && res.status === 'running') {
          this.cycleRunning = true
          this.cycleStatus = { ...this.cycleStatus, ...res }
          this.startCyclePolling()
        }
      } catch (e) { /* noop */ }
    },
    // 挂载时检查打分任务状态：running 则恢复轮询（刷新页面不丢失在跑任务）
    async checkScoringStatus() {
      try {
        const res = await getStockScoringStatus()
        if (!res || !res.success) return
        this.scoringStatus = { ...this.scoringStatus, ...res }
        if (res.status === 'running') {
          this.scoringRunning = true
          this.startScoringPolling()
        }
      } catch (e) { /* noop */ }
    },
    async checkAiEnabled() {
      try {
        const res = await getAIConfig()
        const cfg = (res && res.success && res.data) || {}
        this.aiEnabled = !!(cfg.enabled && cfg.api_url && cfg.api_key)
      } catch (e) { /* 默认 true，不阻塞 */ }
    },

    onResize() {
      this.syncSize()
      this.buildLayout()
      this.view = { k: 1, tx: 0, ty: 0 } // 容器尺寸变化后重置缩放
      this.render()
    },
    syncSize() {
      const wrap = this.$refs.wrapperEl
      const canvas = this.$refs.canvasEl
      if (!wrap || !canvas) return
      // 用容器内容区尺寸算布局，并显式设置 canvas 显示尺寸，
      // 保证 布局坐标 == 屏幕可用面积，treemap 正好铺满、不会溢出屏幕
      const pad = 4
      const w = Math.max(0, wrap.clientWidth - pad * 2)
      const h = Math.max(0, wrap.clientHeight - pad * 2)
      this.cssW = w
      this.cssH = h
      this.dpr = window.devicePixelRatio || 1
      canvas.style.width = w + 'px'
      canvas.style.height = h + 'px'
      canvas.width = Math.round(w * this.dpr)
      canvas.height = Math.round(h * this.dpr)
    },

    // 行业云图布局：把全部二级行业扁平化为一张 treemap（无一级分组、无标题条）。
    // 每个色块=一个二级行业，按行业总市值(value)定大小、按 industryColor 上色。
    buildIndustryLayout() {
      const tiles = []
      for (const l1 of this.tree) {
        for (const l2 of (l1.children || [])) {
          tiles.push({
            name: l2.name,
            change: l2.change,
            value: l2.value || 0,
            l1Name: l1.name,
            l2Name: l2.name,
            sectorCode: l2.code || '',
            color: this.industryColor(l2)
          })
        }
      }
      tiles.sort((a, b) => b.value - a.value)
      squarify(tiles, 0, 6, this.cssW, this.cssH - 6)
      this.layout = tiles
    },
    // 三级嵌套布局：申万一级 → 申万二级 → 个股，每级顶部留一条标题条
    buildLayout() {
      if (!this.tree.length || this.cssW <= 0) { this.layout = null; return }
      if (this.industryMode) { this.buildIndustryLayout(); return }
      const useMargin = (this.colorMode === 'margin')
      const sectors = this.tree.map(l1 => {
        const children = (l1.children || []).map(l2 => {
          const stocks = (l2.children || []).map(s => ({
            name: s.name, code: s.code, change: s.change, value: s.value || 0, pe: s.pe,
            marginNet: this.marginValue(s),
            l1Name: l1.name, l2Name: l2.name, sectorCode: l2.code || l1.code || '',
            color: this.stockColor(s)
          }))
          let marginAgg = null
          if (useMargin) {
            let sum = 0, has = false
            for (const st of stocks) {
              if (st.marginNet != null) { sum += st.marginNet; has = true }
            }
            marginAgg = has ? sum : null
          }
          return { name: l2.name, change: l2.change, value: l2.value || 0, headerH: 0, marginAgg, children: stocks }
        })
        let marginAgg = null
        if (useMargin) {
          let sum = 0, has = false
          for (const l2 of children) {
            if (l2.marginAgg != null) { sum += l2.marginAgg; has = true }
          }
          marginAgg = has ? sum : null
        }
        return { name: l1.name, change: l1.change, value: l1.value || 0, headerH: 0, marginAgg, children }
      })
      sectors.sort((a, b) => b.value - a.value)
      for (const s of sectors) {
        s.children.sort((a, b) => b.value - a.value)
        for (const l2 of s.children) l2.children.sort((a, b) => b.value - a.value)
      }

      // 顶部留 6px 边距，避免最上面一级行业的标题被画布上沿截断
      squarify(sectors, 0, 6, this.cssW, this.cssH - 6)
      for (const s of sectors) {
        s.headerH = s.h > 26 ? Math.min(18, s.h * 0.35) : 0
        squarify(s.children, s.x, s.y + s.headerH, s.w, s.h - s.headerH)
        for (const l2 of s.children) {
          l2.headerH = l2.h > 22 ? Math.min(13, l2.h * 0.3) : 0
          squarify(l2.children, l2.x, l2.y + l2.headerH, l2.w, l2.h - l2.headerH)
        }
      }
      this.layout = sectors
    },

    // 行业云图渲染：扁平二级行业色块（每个色块=一个二级行业）。
    renderIndustry(ctx) {
      const { k, tx, ty } = this.view
      const cw = this.cssW, ch = this.cssH
      ctx.lineWidth = 1
      ctx.strokeStyle = '#070b13'
      for (const t of this.layout) {
        const x = t.x * k + tx, y = t.y * k + ty, w = t.w * k, h = t.h * k
        if (w < 0.5 || h < 0.5) continue
        if (x >= cw || x + w <= 0 || y >= ch || y + h <= 0) continue
        ctx.fillStyle = t.color
        ctx.fillRect(x, y, w, h)
        if (w >= 2.5 && h >= 2.5) ctx.strokeRect(x, y, w, h)
        // 标签：大格=名称+涨跌幅(或周期分)，中格=仅名称，小格不显示
        let metric
        if (this.colorMode === 'cycle') {
          const ce = this.cycleMap[t.name]
          metric = ce && typeof ce.overall_score === 'number' ? `${ce.overall_score}分` : ''
        } else {
          metric = fmtPct(t.change)
        }
        if (w >= 50 && h >= 26) this.drawStockLabel(ctx, t.name, metric, x, y, w, h, true)
        else if (w >= 32 && h >= 12) this.drawStockLabel(ctx, t.name, '', x, y, w, h, false)
      }
      // 搜索高亮：命中行业（二级名或其一级名）叠加黄色边框
      if (this._matches) {
        const { l1s, l2s } = this._matches
        ctx.save()
        ctx.strokeStyle = '#FFE100'
        ctx.lineWidth = 3
        for (const t of this.layout) {
          if (!t || (!l2s.has(t.name) && !l1s.has(t.l1Name))) continue
          const X = t.x * k + tx, Y = t.y * k + ty, W = t.w * k, H = t.h * k
          if (W >= 1 && H >= 1) ctx.strokeRect(X + 1.5, Y + 1.5, Math.max(1, W - 3), Math.max(1, H - 3))
        }
        ctx.restore()
      }
    },

    render() {
      const canvas = this.$refs.canvasEl
      if (!canvas) return
      const ctx = canvas.getContext('2d')
      const dpr = this.dpr
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.fillStyle = '#0a1220'
      ctx.fillRect(0, 0, this.cssW, this.cssH)
      if (!this.layout) return
      if (this.industryMode) { this.renderIndustry(ctx); return }

      const pushedSet = this.pushedOnly ? this._pushedCodeSet : null
      const { k, tx, ty } = this.view
      const cw = this.cssW, ch = this.cssH
      ctx.lineWidth = 1
      ctx.strokeStyle = '#070b13'

      for (const s of this.layout) {
        // 一级 sector 视口剔除：整个板块在视口外则跳过其全部子级
        const sx = s.x * k + tx, sy = s.y * k + ty, sw = s.w * k, sh = s.h * k
        if (sx >= cw || sx + sw <= 0 || sy >= ch || sy + sh <= 0) continue
        let sectorHasMatch = false  // 本板块是否有命中个股（无则整块变暗）
        for (const l2 of s.children) {
          const lx = l2.x * k + tx, ly = l2.y * k + ty, lw = l2.w * k, lh = l2.h * k
          if (lx >= cw || lx + lw <= 0 || ly >= ch || ly + lh <= 0) continue
          // 个股
          for (const st of l2.children) {
            const x = st.x * k + tx, y = st.y * k + ty, w = st.w * k, h = st.h * k
            if (w < 0.5 || h < 0.5) continue
            if (x >= cw || x + w <= 0 || y >= ch || y + h <= 0) continue
            let matched = this.stockMatchesActiveFilter(st)
            if (matched && pushedSet) matched = pushedSet.has(extractDigits(st.code))
            // 搜索命中的个股强制上色，避免被图例筛选灰显、淹没在背景里
            if (this._matches && this._matches.stocks.has(st.code)) matched = true
            if (matched) sectorHasMatch = true
            ctx.fillStyle = matched ? st.color : DIM_COLOR
            ctx.fillRect(x, y, w, h)
            // 个股间隙：描边贴边(内缩0)，相邻个股共用1条1px细缝（原内缩0.5时各画各的、拼成2px）。
            // 行业L1(2.5px)/二级L2(1.5px)板块边框在下方单独描边，缝隙不受影响。
            if (w >= 2.5 && h >= 2.5) ctx.strokeRect(x, y, w, h)
            // 未命中(灰显)的个股不画文字标签，突出命中的
            if (matched) {
              if (w >= 50 && h >= 26) this.drawStockLabel(ctx, st.name, this.stockMetricLabel(st), x, y, w, h, true)
              else if (w >= 32 && h >= 12) this.drawStockLabel(ctx, st.name, this.stockMetricLabel(st), x, y, w, h, false)
            }
          }
          // 二级标题条
          if (l2.headerH > 0) {
            const hh = l2.headerH * k
            ctx.fillStyle = '#171f2e'
            ctx.fillRect(lx, ly, lw, hh)
            let l2Txt
            if (this.colorMode === 'cycle') {
              const cycleEntry = this.cycleMap[l2.name]
              const displayScore = cycleEntry ? cycleEntry.overall_score : null
              l2Txt = displayScore != null ? `${l2.name}  ${displayScore}分` : `${l2.name}`
            } else if (this.colorMode === 'margin') {
              l2Txt = `${l2.name}  ${this.formatMoney(l2.marginAgg)}`
            } else {
              l2Txt = `${l2.name}  ${fmtPct(l2.change)}`
            }
            this.drawHeaderText(ctx, l2Txt, lx + 5, ly, lw, hh, clamp(hh * 0.6, 9, 13))
          }
          ctx.lineWidth = 1.5
          ctx.strokeStyle = '#05080f'
          ctx.strokeRect(lx + 0.75, ly + 0.75, lw - 1.5, lh - 1.5)
          ctx.lineWidth = 1
          ctx.strokeStyle = '#070b13'
          // 行业周期诊断：在L2区域中央显示大字号分数和总体判断
          if (this.colorMode === 'cycle' && lw > 60 && lh > 40) {
            const cycleEntry = this.cycleMap[l2.name]
            if (cycleEntry && typeof cycleEntry.overall_score === 'number') {
              const displayScore = cycleEntry.overall_score
              const verdict = cycleEntry.overall_verdict || ''
              const cx = lx + lw / 2
              const cy = ly + lh / 2 + l2.headerH * k / 2
              // 大字号分数
              const fontSize = clamp(Math.min(lw * 0.15, (lh - l2.headerH * k) * 0.25), 14, 36)
              ctx.textAlign = 'center'
              ctx.textBaseline = 'middle'
              ctx.fillStyle = interpCycleColor(displayScore)
              ctx.font = `900 ${fontSize}px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
              ctx.fillText(String(displayScore), cx, cy - fontSize * 0.3)
              // 总体判断（小字）
              if (verdict && lh > 60) {
                const vFontSize = clamp(fontSize * 0.4, 9, 14)
                ctx.font = `600 ${vFontSize}px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
                ctx.fillStyle = 'rgba(224, 230, 240, 0.7)'
                ctx.fillText(verdict, cx, cy + fontSize * 0.5)
              }
            }
          }
        }
        // 一级标题条 + 边框
        if (s.headerH > 0) {
          const hh = s.headerH * k
          ctx.fillStyle = '#10151f'
          ctx.fillRect(sx, sy, sw, hh)
          const sTxt = this.colorMode === 'margin' ? `${s.name}    ${this.formatMoney(s.marginAgg)}` : this.colorMode === 'cycle' ? `${s.name}` : `${s.name}    ${fmtPct(s.change)}`
          this.drawHeaderText(ctx, sTxt, sx + 8, sy, sw, hh, clamp(hh * 0.72, 11, 17))
        }
        ctx.lineWidth = 2.5
        ctx.strokeStyle = '#3a4a6b'
        ctx.strokeRect(sx + 1.25, sy + 1.25, sw - 2.5, sh - 2.5)
        ctx.lineWidth = 1
        ctx.strokeStyle = '#070b13'
        // 该板块一只都没命中：叠加暗色面纱，整块（含标题条/二级/边框）统一变暗
        if ((this.legendApplied.length > 0 || pushedSet) && !sectorHasMatch) {
          ctx.fillStyle = VEIL_COLOR
          ctx.fillRect(sx, sy, sw, sh)
        }
      }

      // 搜索高亮：搜索词存在期间持续叠加醒目黄色边框（不再限时5秒）
      if (this._matches) {
        const { stocks, l1s, l2s } = this._matches
        ctx.save()
        ctx.strokeStyle = '#FFE100'
        ctx.lineWidth = 4
        for (const s of this.layout) {              // 一级行业（最显眼）
          if (l1s.has(s.name)) {
            const SX = s.x * k + tx, SY = s.y * k + ty, SW = s.w * k, SH = s.h * k
            ctx.strokeRect(SX + 2, SY + 2, Math.max(1, SW - 4), Math.max(1, SH - 4))
          }
        }
        ctx.lineWidth = 3
        for (const s of this.layout) for (const l2 of s.children) {   // 二级行业
          if (l2s.has(l2.name)) {
            const LX = l2.x * k + tx, LY = l2.y * k + ty, LW = l2.w * k, LH = l2.h * k
            ctx.strokeRect(LX + 1.5, LY + 1.5, Math.max(1, LW - 3), Math.max(1, LH - 3))
          }
        }
        ctx.lineWidth = 2.5
        for (const s of this.layout) for (const l2 of s.children) for (const st of l2.children) {  // 个股
          if (stocks.has(st.code)) {
            const X = st.x * k + tx, Y = st.y * k + ty, W = st.w * k, H = st.h * k
            if (W >= 1 && H >= 1) ctx.strokeRect(X + 1, Y + 1, Math.max(1, W - 2), Math.max(1, H - 2))
          }
        }
        ctx.restore()
        // 极小命中格（屏幕尺寸不足14px，即便放大后仍可能看不清）补一个“图钉”圆点，
        // 保证小市值股也一定能定位到
        for (const s of this.layout) for (const l2 of s.children) for (const st of l2.children) {
          if (!stocks.has(st.code)) continue
          const X = st.x * k + tx, Y = st.y * k + ty, W = st.w * k, H = st.h * k
          if (W < 14 || H < 14) {
            const cx = X + W / 2, cy = Y + H / 2
            ctx.beginPath()
            ctx.arc(cx, cy, 6, 0, Math.PI * 2)
            ctx.fillStyle = '#FFE100'
            ctx.fill()
            ctx.lineWidth = 2
            ctx.strokeStyle = '#0a1220'
            ctx.stroke()
          }
        }
      }
    },

    // 个股标签（分级）：面积够大→名称+涨跌幅；中等→仅名称；太小→不显示（调用方按阈值过滤）
    drawStockLabel(ctx, name, metric, x, y, w, h, withMetric) {
      const cx = x + w / 2
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillStyle = '#fff'
      const font = s => `bold ${s}px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
      if (withMetric) {
        const nameSize = clamp(Math.min(w, h) * 0.19, 10, 15)
        const pctSize = nameSize * 0.8
        const cy = y + h / 2
        ctx.font = font(nameSize)
        ctx.fillText(name, cx, cy - nameSize * 0.55)
        ctx.font = font(pctSize)
        ctx.fillText(metric, cx, cy + pctSize * 0.6)
      } else {
        // 仅名称：按宽高自适应字号，保证名称能放进格子
        const n = Math.max(name.length, 2)
        const size = Math.round(clamp(Math.min((w / n) * 0.95, h * 0.6), 8, 14))
        ctx.font = font(size)
        ctx.fillText(name, cx, y + h / 2)
      }
    },
    drawHeaderText(ctx, text, x, y, w, hh, size) {
      if (w < 30) return
      ctx.textAlign = 'left'
      ctx.textBaseline = 'middle'
      ctx.fillStyle = '#fff'
      ctx.font = `bold ${size}px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`
      ctx.fillText(text, x, y + hh / 2)
    },

    scheduleRender() {
      if (this._raf) return
      this._raf = requestAnimationFrame(() => { this._raf = 0; this.render() })
    },

    // 限制平移范围：缩放 k>=1 时地图始终覆盖整个视口，绝不出现虚无空白；
    // k=1（最小）时 tx/ty 锁死为 0，即初始全图、不能拖。
    clampView() {
      const k = this.view.k
      this.view.tx = clamp(this.view.tx, this.cssW * (1 - k), 0)
      this.view.ty = clamp(this.view.ty, this.cssH * (1 - k), 0)
    },

    // 滚轮缩放（以鼠标位置为中心），限定 1~12 倍，永远不会触发空白 bug
    onWheel(e) {
      const r = this.$refs.canvasEl.getBoundingClientRect()
      const mx = e.clientX - r.left, my = e.clientY - r.top
      const f = Math.exp(-e.deltaY * 0.0015)
      const nk = clamp(this.view.k * f, 1, 12)
      if (nk === this.view.k) return
      const Lx = (mx - this.view.tx) / this.view.k
      const Ly = (my - this.view.ty) / this.view.k
      this.view.k = nk
      this.view.tx = mx - Lx * nk
      this.view.ty = my - Ly * nk
      this.clampView()
      this.scheduleRender()
    },
    onMouseDown(e) {
      this.dragging = true
      const r = this.$refs.canvasEl.getBoundingClientRect()
      this.lastX = e.clientX - r.left
      this.lastY = e.clientY - r.top
      this._downX = this.lastX
      this._downY = this.lastY
      this.$refs.canvasEl.style.cursor = 'grabbing'
    },
    onMouseMove(e) {
      const r = this.$refs.canvasEl.getBoundingClientRect()
      const mx = e.clientX - r.left, my = e.clientY - r.top
      if (this.dragging) {
        this.view.tx += mx - this.lastX
        this.view.ty += my - this.lastY
        this.lastX = mx
        this.lastY = my
        this.clampView()
        this.scheduleRender()
        return
      }
      this.updateHover(mx, my)
    },
    onMouseUp(e) {
      const wasDragging = this.dragging
      this.dragging = false
      if (this.$refs.canvasEl) this.$refs.canvasEl.style.cursor = 'grab'
      // 单击判定：未发生拖拽（落点↔抬起点距离<5px）且命中个股 → 防抖280ms后弹融资窗。
      // 双击会在280ms内触发 onDblClick 并取消该定时器，从而跳雪球而不弹窗。
      if (wasDragging && e && this.layout) {
        const r = this.$refs.canvasEl.getBoundingClientRect()
        const ux = e.clientX - r.left, uy = e.clientY - r.top
        if (Math.hypot(ux - this._downX, uy - this._downY) < 5) {
          const Lx = (ux - this.view.tx) / this.view.k
          const Ly = (uy - this.view.ty) / this.view.k
          const hit = this.hitTest(Lx, Ly)
          if (hit && hit.node && hit.node.code) {
            if (this.clickTimer) clearTimeout(this.clickTimer)
            const node = hit.node
            this.clickTimer = setTimeout(() => {
              this.clickTimer = null
              this.openFinancing(node)
            }, 280)
          } else if (hit && hit.node && !hit.node.code && hit.node.children && this.colorMode === 'cycle') {
            // 点击了二级行业标题条 → 跳转到9维产业周期雷达
            this.$router.push({ path: '/industry-cycle', query: { industry: hit.node.name, from: 'market-map' } })
          }
        }
      }
    },
    onMouseLeave() {
      this.dragging = false
      this.tooltip.visible = false
      if (this.$refs.canvasEl) this.$refs.canvasEl.style.cursor = 'grab'
    },
    resetZoom() {
      this.view = { k: 1, tx: 0, ty: 0 }
      this.render()
    },

    // ===== 融资趋势弹窗（单击个股触发）=====
    async openFinancing(node) {
      this.finModal.code = node.code || ''
      this.finModal.name = node.name || ''
      this.finModal.period = 60
      this.finModal.latestBalance = null
      this.finModal.latestBalanceDate = ''
      this.finModal.series = []
      this.finModal.totals = {}
      this.finModal.error = ''
      this.finModal.updating = false
      this.finModal.visible = true
      this._finRetry = 0
      await this.loadFinancing()
    },
    async loadFinancing() {
      this.finModal.loading = true
      this.finModal.error = ''
      try {
        const res = await getStockFinancing(this.finModal.code)
        if (res && res.success) {
          const series = (res.data && res.data.series) || []
          this.finModal.series = series
          this.finModal.latestBalance = res.data.latest_balance
          this.finModal.latestBalanceDate = res.data.latest_balance_date || ''
          if (res.data && res.data.name) this.finModal.name = res.data.name
          this.computeFinTotals()
          // 后台正按需更新（每天一次）且当前仍无数据 → 提示并稍后自动重试
          if (res.updating && !series.length) {
            this.finModal.updating = true
            if (this._finRetry < 6) {
              this._finRetry++
              setTimeout(() => { if (this.finModal.visible) this.loadFinancing() }, 6000)
            }
          } else {
            this.finModal.updating = false
            this._finRetry = 0
          }
          this.$nextTick(() => this.renderFinChart())
        } else {
          this.finModal.error = (res && res.error) || '获取融资数据失败'
        }
      } catch (err) {
        this.finModal.error = '获取融资数据失败'
      } finally {
        this.finModal.loading = false
      }
    },
    closeFinancing() {
      this.finModal.visible = false
      this._finRetry = 0
      if (this.clickTimer) { clearTimeout(this.clickTimer); this.clickTimer = null }
      // 弹窗是 v-if，关闭即销毁图表容器 DOM；保留实例会指向已分离的旧 canvas，
      // 下次打开画到旧容器 → 第二只股票柱状图不显示。故关闭即销毁实例。
      if (this.finChart) { this.finChart.dispose(); this.finChart = null }
    },
    switchFinPeriod(p) {
      this.finModal.period = p
      this.renderFinChart()
    },
    // 各区间（3/5/10/20/60日）融资净买入额之和
    computeFinTotals() {
      const s = this.finModal.series
      const totals = {}
      for (const p of this.finPeriods) {
        let sum = 0, has = false
        const slice = s.slice(Math.max(0, s.length - p))
        for (const x of slice) {
          if (x.j != null && !isNaN(x.j)) { sum += x.j; has = true }
        }
        totals[p] = has ? sum : null
      }
      this.finModal.totals = totals
    },
    // 元 → 亿/万 文本（axis=true 用于坐标轴，正数不带 + 号）
    finFmt(v, axis) {
      if (v == null || isNaN(v)) return '--'
      const abs = Math.abs(v)
      const sign = v < 0 ? '-' : (axis ? '' : '+')
      if (abs >= 1e8) return sign + (abs / 1e8).toFixed(2) + '亿'
      if (abs >= 1e4) return sign + (abs / 1e4).toFixed(2) + '万'
      return sign + abs.toFixed(0)
    },
    finValClass(v) {
      return v == null ? '' : (v >= 0 ? 'up' : 'down')
    },
    valueClass(v) {
      if (v == null || isNaN(v)) return ''
      return v >= 0 ? 'up' : 'down'
    },
    formatMoney(v, noSign) {
      if (v == null || isNaN(v)) return '--'
      const abs = Math.abs(Number(v))
      const sign = Number(v) < 0 ? '-' : (noSign ? '' : '+')
      if (abs >= 1e8) return sign + (abs / 1e8).toFixed(2) + '亿'
      if (abs >= 1e4) return sign + (abs / 1e4).toFixed(2) + '万'
      return sign + abs.toFixed(0)
    },
    renderFinChart() {
      if (!this.finModal.visible || !this.finModal.series.length) return
      const el = this.$refs.finChartEl
      if (!el || el.offsetWidth === 0) return  // 容器隐藏（更新中态）→ 跳过，待重试时再画
      // 防御：弹窗 v-if 重建过容器时，旧实例已脱离 DOM → 销毁后重新绑定当前容器
      if (this.finChart && this.finChart.getDom && this.finChart.getDom() !== el) {
        try { this.finChart.dispose() } catch (e) { /* noop */ }
        this.finChart = null
      }
      if (!this.finChart) this.finChart = echarts.init(el)
      const all = this.finModal.series
      const data = all.slice(Math.max(0, all.length - this.finModal.period))
      const xData = data.map(x => {
        const d = String(x.d)
        return d.length === 8 ? d.slice(4, 6) + '/' + d.slice(6, 8) : d
      })
      this.finChart.setOption({
        animation: false,
        grid: { left: 60, right: 16, top: 20, bottom: 30 },
        tooltip: {
          trigger: 'axis',
          backgroundColor: 'rgba(20,25,45,0.95)',
          borderColor: '#3a4a6b',
          textStyle: { color: '#fff', fontSize: 12 },
          formatter: (params) => {
            const x = data[params[0].dataIndex]
            if (!x) return ''
            const d = String(x.d).replace(/(\d{4})(\d{2})(\d{2})/, '$1/$2/$3')
            const cls = x.j == null ? '#8ba4c7' : (x.j >= 0 ? '#ff4d4f' : '#52c41a')
            return '<div style="font-size:12px;line-height:1.8">'
              + `<div style="color:#8ba4c7">${d}</div>`
              + `<div>融资净买入额：<b style="color:${cls}">${this.finFmt(x.j)}</b></div>`
              + `<div>融资买入额：<b style="color:#ff4d4f">${this.finFmt(x.buy, true)}</b></div>`
              + `<div>融资偿还额：<b style="color:#52c41a">${this.finFmt(x.repay, true)}</b></div>`
              + '</div>'
          }
        },
        xAxis: {
          type: 'category', data: xData,
          axisLabel: { color: '#8ba4c7', fontSize: 10 },
          axisLine: { lineStyle: { color: '#3a4a6b' } },
          axisTick: { show: false }
        },
        yAxis: {
          type: 'value',
          axisLabel: { color: '#8ba4c7', fontSize: 10, formatter: (v) => this.finFmt(v, true) },
          splitLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } }
        },
        series: [{
          type: 'bar',
          barWidth: '60%',
          data: data.map(x => ({
            value: x.j,
            itemStyle: { color: (x.j == null) ? '#4a5670' : (x.j >= 0 ? '#ef4444' : '#22c55e') }
          }))
        }]
      }, true)
    },
    // 双击：落在个股上 → 新标签页打开雪球；落在行业/空白 → 复位缩放
    onDblClick(e) {
      // 取消待弹的融资窗定时器，确保双击只跳雪球、不弹窗
      if (this.clickTimer) { clearTimeout(this.clickTimer); this.clickTimer = null }
      if (!this.layout) return
      const r = this.$refs.canvasEl.getBoundingClientRect()
      const mx = e.clientX - r.left, my = e.clientY - r.top
      const Lx = (mx - this.view.tx) / this.view.k
      const Ly = (my - this.view.ty) / this.view.k
      const hit = this.hitTest(Lx, Ly)
      if (hit && hit.node && hit.node.code) {
        const url = xueqiuUrl(hit.node.code)
        if (url) window.open(url, '_blank')
        return
      }
      this.resetZoom()
    },

    updateHover(mx, my) {
      if (!this.layout) return
      const Lx = (mx - this.view.tx) / this.view.k
      const Ly = (my - this.view.ty) / this.view.k
      const hit = this.hitTest(Lx, Ly)
      if (hit) {
        const n = hit.node
        const summaryKey = n.code ? `${n.code}|${n.sectorCode || ''}|${n.l2Name || n.l1Name || ''}` : ''
        const keepSummary = summaryKey && this.tooltip.summaryKey === summaryKey
        // 分时只与 code 相关：同一只股票上移动鼠标不清掉已加载的分时
        const keepTrend = n.code && this.tooltip.code === n.code
        // AI 打分：分数 + 颜色档 + 一句话理由（仅评分维度或已有分数时展示）
        const sv = this.scoreValue(n)
        const sEntry = sv != null ? this.scoreMap[extractDigits(n.code)] : null
        const sBucket = sv != null ? (SCORE_LEGEND_STEPS.find(item => inScoreFilter(sv, item.value)) || {}).countTitle : ''
        this.tooltip = {
          visible: true,
          name: n.name,
          code: n.code || '',
          change: this.stockMetricLabel(n),
          cls: this.colorMode === 'margin' ? this.valueClass(this.marginValue(n))
            : this.colorMode === 'score' ? (sv == null ? '' : (sv >= 50 ? 'up' : 'down'))
            : this.colorMode === 'cycle' ? (() => { const cv = this.cycleValue(n); return cv == null ? '' : (cv >= 50 ? 'up' : 'down') })()
            : (n.change >= 0 ? 'up' : 'down'),
          marketCap: fmtCap(n.value),
          pe: fmtPE(n.pe),
          score: sv != null ? sv : null,
          scoreCls: sv == null ? '' : (sv >= 50 ? 'up' : 'down'),
          scoreLabel: sBucket,
          scoreReason: (sEntry && sEntry.reason) || '',
          x: mx + 14,
          y: my + 14,
          loading: keepSummary ? this.tooltip.loading : false,
          summary: keepSummary ? this.tooltip.summary : null,
          summaryKey: keepSummary ? this.tooltip.summaryKey : '',
          trend: keepTrend ? this.tooltip.trend : null,
          trendLoading: keepTrend ? this.tooltip.trendLoading : false
        }
        if (n.code) this.queueHoverSummary(n)
        if (n.code) this.queueHoverTrend(n)
        this.$refs.canvasEl.style.cursor = 'pointer'
      } else {
        this.tooltip.visible = false
        this.tooltip.summary = null
        this.tooltip.loading = false
        this.tooltip.trend = null
        this.tooltip.trendLoading = false
        if (this.hoverSummaryTimer) clearTimeout(this.hoverSummaryTimer)
        if (this.hoverTrendTimer) clearTimeout(this.hoverTrendTimer)
        this.$refs.canvasEl.style.cursor = 'grab'
      }
    },
    queueHoverSummary(node) {
      const key = `${node.code}|${node.sectorCode || ''}|${node.l2Name || node.l1Name || ''}`
      if (this.tooltip.summaryKey === key && (this.tooltip.summary || this.tooltip.loading)) return
      this.tooltip.summaryKey = key
      const cached = this.hoverSummaryCache.get(key)
      if (cached) {
        this.tooltip.summary = cached
        this.tooltip.loading = false
        return
      }
      this.tooltip.loading = true
      this.tooltip.summary = null
      if (this.hoverSummaryTimer) clearTimeout(this.hoverSummaryTimer)
      const seq = ++this.hoverSummarySeq
      this.hoverSummaryTimer = setTimeout(async () => {
        try {
          const res = await getStockHoverSummary(
            node.code,
            node.sectorCode || '',
            node.name || '',
            node.l2Name || node.l1Name || ''
          )
          if (seq !== this.hoverSummarySeq || !this.tooltip.visible || this.tooltip.summaryKey !== key) return
          const summary = res && res.success ? res.data : null
          if (summary) this.hoverSummaryCache.set(key, summary)
          this.tooltip.summary = summary
        } catch (err) {
          if (seq === this.hoverSummarySeq && this.tooltip.summaryKey === key) {
            this.tooltip.summary = null
          }
        } finally {
          if (seq === this.hoverSummarySeq && this.tooltip.summaryKey === key) {
            this.tooltip.loading = false
          }
        }
      }, 180)
    },
    // 悬浮分时迷你图：与 queueHoverSummary 同款防抖+缓存+序号防竞态，
    // 失败结果也缓存 60s，避免在坏代码上反复打接口
    queueHoverTrend(node) {
      if (!node.code) return
      const code = node.code
      if (this.tooltip.code === code && (this.tooltip.trend || this.tooltip.trendLoading)) return
      const cached = this.hoverTrendCache.get(code)
      if (cached && Date.now() - cached.t < 60000) {
        this.tooltip.trend = cached.data
        this.tooltip.trendLoading = false
        return
      }
      this.tooltip.trendLoading = true
      this.tooltip.trend = null
      if (this.hoverTrendTimer) clearTimeout(this.hoverTrendTimer)
      const seq = ++this.hoverTrendSeq
      this.hoverTrendTimer = setTimeout(async () => {
        try {
          const res = await getStockIntradaySeries(code)
          if (seq !== this.hoverTrendSeq || !this.tooltip.visible || this.tooltip.code !== code) return
          const trend = res && res.success ? res.data : null
          this.hoverTrendCache.set(code, { t: Date.now(), data: trend })
          this.tooltip.trend = trend
        } catch (err) {
          if (seq === this.hoverTrendSeq && this.tooltip.code === code) {
            this.hoverTrendCache.set(code, { t: Date.now(), data: null })
            this.tooltip.trend = null
          }
        } finally {
          if (seq === this.hoverTrendSeq && this.tooltip.code === code) {
            this.tooltip.trendLoading = false
          }
        }
      }, 120)
    },
    hitTest(Lx, Ly) {
      if (this.industryMode) {
        // 行业云图：扁平色块，直接命中二级行业
        for (const t of this.layout) {
          if (t.w == null || t.h == null) continue
          if (Lx >= t.x && Lx <= t.x + t.w && Ly >= t.y && Ly <= t.y + t.h) return { node: t }
        }
        return null
      }
      for (const s of this.layout) {
        if (Lx < s.x || Lx > s.x + s.w || Ly < s.y || Ly > s.y + s.h) continue
        if (s.headerH > 0 && Ly < s.y + s.headerH) return { node: s }
        for (const l2 of s.children) {
          if (Lx < l2.x || Lx > l2.x + l2.w || Ly < l2.y || Ly > l2.y + l2.h) continue
          if (l2.headerH > 0 && Ly < l2.y + l2.headerH) return { node: l2 }
          // 个股层：精确命中优先；落在子像素缝隙时吸附到中心最近的个股，
          // 避免悬停缝隙时错误地回退到二级行业、显示成"别的股票"
          let hit = null, near = null, nearD = Infinity
          for (const st of l2.children) {
            if (st.w == null || st.h == null) continue
            if (!hit && Lx >= st.x && Lx <= st.x + st.w && Ly >= st.y && Ly <= st.y + st.h) hit = st
            const dx = Lx - (st.x + st.w / 2), dy = Ly - (st.y + st.h / 2)
            const d = dx * dx + dy * dy
            if (d < nearD) { nearD = d; near = st }
          }
          if (hit) return { node: hit }
          if (near) return { node: near }
          return { node: l2 }
        }
        return { node: s }
      }
      return null
    }
  }
}
</script>

<style scoped>
.market-map-page {
  height: 100vh;
  background:
    radial-gradient(ellipse at 20% 20%, rgba(228, 48, 56, 0.06) 0%, transparent 50%),
    radial-gradient(ellipse at 80% 80%, rgba(28, 168, 86, 0.05) 0%, transparent 50%),
    linear-gradient(135deg, #050a14 0%, #0a1628 40%, #08101e 100%);
  color: #e0e6f0;
  padding: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.mm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 290px 6px 14px; /* 右侧避让固定北京时间+登录入口 */
  background: rgba(26, 35, 53, 0.8);
  border-radius: 8px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  backdrop-filter: blur(10px);
  margin-bottom: 8px;
  flex-shrink: 0;
}
.mm-header h1 { font-size: 1.05rem; color: #fff; margin: 0; text-shadow: 0 2px 4px rgba(0,0,0,0.3); white-space: nowrap; }
.mm-header-left { display: flex; align-items: center; gap: 12px; min-width: 0; flex-wrap: wrap; }
.mm-search-wrap { position: relative; display: flex; align-items: center; }
.mm-search {
  width: 200px;
  padding: 6px 44px 6px 10px;
  background: rgba(13, 19, 32, 0.8);
  border: 1px solid #3a4a6b;
  border-radius: 6px;
  color: #e0e6f0;
  font-size: 13px;
  outline: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.mm-search:focus { border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.15); }
.mm-search::placeholder { color: #5a6b8c; }
.mm-search-count { position: absolute; right: 8px; font-size: 11px; color: #8ba4c7; pointer-events: none; white-space: nowrap; }
.mm-industry-btn { padding: 6px 12px; background: linear-gradient(135deg, #13c2c2, #08979c); border: 1px solid #36cfc9; border-radius: 6px; color: #fff; cursor: pointer; font-size: 12px; font-weight: 600; transition: all 0.3s ease; white-space: nowrap; }
.mm-industry-btn:hover { background: linear-gradient(135deg, #36cfc9, #13c2c2); transform: translateY(-1px); }
.mm-industry-btn.active { background: linear-gradient(135deg, #fa8c16, #d4380d); border-color: #ffa940; box-shadow: 0 0 0 2px rgba(250, 140, 22, 0.25); }
.mm-header-right { display: flex; align-items: center; justify-content: flex-end; gap: 10px; flex-wrap: wrap; min-width: 0; }
.mm-push-tag { font-size: 11px; color: #9bdaf0; padding: 4px 8px; border-radius: 999px; background: rgba(69, 183, 209, 0.12); border: 1px solid rgba(69, 183, 209, 0.28); white-space: nowrap; }
.mm-clear-push-btn { order: 10; padding: 6px 10px; background: rgba(239, 83, 80, 0.14); border: 1px solid rgba(239, 83, 80, 0.38); border-radius: 6px; color: #ffb4b2; cursor: pointer; font-size: 11px; font-weight: 600; white-space: nowrap; }
.mm-clear-push-btn:hover:not(:disabled) { background: rgba(239, 83, 80, 0.2); }
.mm-clear-push-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.mm-stats { font-size: 12px; color: #8ba4c7; white-space: nowrap; }
.mm-update { font-size: 11px; color: #8ba4c7; white-space: nowrap; }
.mm-back-button { padding: 6px 14px; background: linear-gradient(135deg, #3a4a6b, #2a3a5b); border: 1px solid #4a5a7b; border-radius: 6px; color: #e0e6f0; cursor: pointer; transition: all 0.3s ease; font-size: 13px; white-space: nowrap; }
.mm-back-button:hover { background: linear-gradient(135deg, #4a5a7b, #3a4a6b); transform: translateY(-1px); }
.mm-refresh-btn { padding: 6px 12px; background: linear-gradient(135deg, #1890ff, #096dd9); border: 1px solid #40a9ff; border-radius: 6px; color: #fff; cursor: pointer; font-size: 12px; transition: all 0.3s ease; white-space: nowrap; }
.mm-cache-btn { padding: 6px 10px; background: rgba(58, 74, 107, 0.6); border: 1px solid #4a5a7b; border-radius: 6px; color: #8ba4c7; cursor: pointer; font-size: 11px; transition: all 0.3s ease; white-space: nowrap; }
.mm-cache-btn:hover:not(:disabled) { background: rgba(58, 74, 107, 0.9); color: #e0e6f0; }
.mm-cache-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.mm-refresh-btn:hover:not(:disabled) { background: linear-gradient(135deg, #40a9ff, #1890ff); transform: translateY(-1px); }
.mm-refresh-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.mm-refresh-spin { display: inline-block; margin-right: 3px; font-size: 13px; line-height: 1; }
.mm-refresh-spin.on { animation: mm-btn-spin 0.8s linear infinite; }
@keyframes mm-btn-spin { to { transform: rotate(360deg); } }

.mm-chart-wrapper {
  flex: 1;
  position: relative;
  background: rgba(10, 18, 32, 0.6);
  border-radius: 8px;
  border: 1px solid rgba(58, 74, 107, 0.5);
  min-height: 300px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  overflow: hidden;
}
.mm-canvas {
  position: absolute;
  top: 4px; left: 4px; right: 4px; bottom: 4px;
  display: block;
  cursor: grab;
}

.mm-tooltip {
  position: absolute;
  pointer-events: none;
  z-index: 20;
  min-width: 190px;
  max-width: 320px;
  background: rgba(20, 25, 45, 0.96);
  border: 1px solid #3a4a6b;
  border-radius: 6px;
  padding: 8px 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
}
.mm-tooltip-name { font-size: 14px; font-weight: bold; color: #fff; margin-bottom: 5px; }
.mm-tooltip-code { font-weight: normal; font-size: 12px; color: #8ba4c7; margin-left: 6px; }
/* 当日分时迷你折线：股票名之下、涨跌幅之上；宽度随 tooltip 自适应拉伸 */
.mm-tooltip-spark {
  width: 100%;
  height: 52px;
  margin: 0 0 6px;
  background: rgba(10, 14, 23, 0.6);
  border: 1px solid rgba(58, 74, 107, 0.5);
  border-radius: 4px;
  overflow: hidden;
}
.mm-tooltip-spark svg { display: block; width: 100%; height: 100%; }
.mm-spark-base { stroke: rgba(139, 164, 199, 0.35); stroke-width: 1; }
.mm-tooltip-spark-loading { font-size: 11px; color: #6a7a99; margin: 0 0 4px; }
.mm-tooltip-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
.mm-tooltip-label { font-size: 12px; color: #8ba4c7; }
.mm-tooltip-val { font-size: 15px; font-weight: bold; }
.mm-tooltip-val.small { font-size: 12px; max-width: 170px; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mm-tooltip-val.up { color: #ff4d4f; }
.mm-tooltip-val.down { color: #52c41a; }
.mm-tooltip-extra {
  margin-top: 7px;
  padding-top: 7px;
  border-top: 1px solid rgba(139, 164, 199, 0.22);
  color: #8ba4c7;
  font-size: 12px;
}
.mm-tooltip-divider {
  margin: 7px 0;
  border-top: 1px solid rgba(139, 164, 199, 0.22);
}
.mm-tooltip-news {
  margin-top: 7px;
  padding-top: 7px;
  border-top: 1px dashed rgba(139, 164, 199, 0.22);
}
.mm-tooltip-news-title {
  color: #8ba4c7;
  font-size: 12px;
  margin-bottom: 4px;
}
.mm-tooltip-news-item {
  color: #dbeafe;
  font-size: 12px;
  line-height: 1.35;
  margin-top: 3px;
}

.mm-hint {
  position: absolute;
  top: 8px; right: 12px;
  z-index: 15;
  font-size: 11px;
  color: #5a6b8c;
  background: rgba(13, 19, 32, 0.6);
  padding: 3px 8px;
  border-radius: 4px;
  pointer-events: none;
}

.mm-changes-loading {
  position: absolute;
  top: 8px; left: 12px;
  z-index: 15;
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: #b0c4e0;
  background: rgba(13, 19, 32, 0.72);
  border: 1px solid rgba(58, 74, 107, 0.5);
  padding: 3px 10px;
  border-radius: 10px;
  pointer-events: none;
}
.mm-cl-dot { width: 6px; height: 6px; border-radius: 50%; background: #1890ff; animation: mm-cl-pulse 1s ease-in-out infinite; }
@keyframes mm-cl-pulse { 0%, 100% { opacity: 0.3; } 50% { opacity: 1; } }

.mm-legend {
  flex-shrink: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}
.mm-legend-tooltip {
  position: fixed;
  z-index: 60;
  transform: translate(-100%, -100%);
  padding: 5px 8px;
  background: rgba(13, 19, 32, 0.96);
  border: 1px solid rgba(139, 164, 199, 0.36);
  border-radius: 5px;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.36);
  color: #e0e6f0;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.2;
  white-space: nowrap;
  pointer-events: none;
}
.mm-legend-bar {
  display: flex;
  gap: 1px;
  width: 360px;
  max-width: 100%;
  height: 28px;
  border-radius: 2px;
  overflow: visible; /* 让激活/悬停色块能上抬放大，不被裁切 */
}
/* 融资净流入模式：标签更长（"-2000~-1000万"）且无涨/跌停按钮占位，
   放宽色条宽度容纳文字，避免右侧色块溢出屏幕 */
.mm-legend-bar.is-margin {
  width: 500px;
}
.mm-legend-step {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  color: #fff;
  height: 100%;
  white-space: nowrap;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.mm-legend-step-label {
  font-size: 9px;
  line-height: 1;
  font-weight: bold;
}
.mm-legend-step-count {
  padding: 1px 4px;
  border-radius: 7px;
  background: rgba(9, 13, 22, 0.42);
  border: 1px solid rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.92);
  font-size: 8px;
  line-height: 1;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.mm-legend-step:hover { transform: translateY(-2px); z-index: 1; }
.mm-legend-step.active {
  transform: translateY(-3px);
  box-shadow: 0 0 0 2px #fff, 0 0 10px rgba(255, 255, 255, 0.7);
  z-index: 2;
}
/* 多选勾选标记：右上角小白勾，区分"已勾选(待确定)"和普通悬停 */
.mm-legend-step.checked::after {
  content: '✓';
  position: absolute;
  top: -5px;
  right: -5px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #fff;
  color: #0f1626;
  font-size: 10px;
  font-weight: 900;
  line-height: 14px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.5);
  z-index: 3;
}
.mm-legend-step { position: relative; }

/* "确定"按钮：应用多选筛选。有勾选时高亮提示 */
.mm-legend-apply {
  height: 28px;
  padding: 0 12px;
  flex-shrink: 0;
  border: 1px solid #3a4a6b;
  border-radius: 6px;
  background: rgba(13, 19, 32, 0.8);
  color: #b0c4e0;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.15s ease;
}
.mm-legend-apply:hover:not(:disabled) { border-color: #1890ff; color: #fff; }
.mm-legend-apply:disabled { opacity: 0.4; cursor: not-allowed; }
.mm-legend-apply.pending {
  border-color: #1890ff;
  background: linear-gradient(135deg, #1890ff, #096dd9);
  color: #fff;
  box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.25);
  animation: mm-apply-pulse 1.4s ease-in-out infinite;
}
.mm-legend-apply.hasFilter:not(.pending) {
  border-color: #52c41a;
  color: #b7eb8f;
}
@keyframes mm-apply-pulse {
  0%, 100% { box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.25); }
  50% { box-shadow: 0 0 0 4px rgba(24, 144, 255, 0.45); }
}
.mm-legend-apply-check { font-size: 13px; line-height: 1; }
.mm-legend-apply-n {
  display: inline-block;
  min-width: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.25);
  font-size: 10px;
  line-height: 14px;
  text-align: center;
}

/* 涨停/跌停按钮：红涨绿跌，与图例配色一致 */
.mm-limit-btn {
  height: 26px;
  padding: 0 8px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: bold;
  color: #fff;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.mm-limit-btn.up { background: linear-gradient(135deg, #f32f3d, #c91a26); }
.mm-limit-btn.down { background: linear-gradient(135deg, #3bcc5f, #1ea645); }
.mm-legend-label {
  line-height: 1;
}
.mm-legend-count {
  min-width: 28px;
  padding: 2px 5px;
  border-radius: 8px;
  background: rgba(9, 13, 22, 0.34);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: rgba(255, 255, 255, 0.94);
  font-size: 10px;
  line-height: 1;
  font-weight: 800;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.mm-limit-btn:hover { transform: translateY(-1px); }
.mm-limit-btn.active {
  transform: translateY(-2px);
  box-shadow: 0 0 0 2px #fff, 0 0 10px rgba(255, 255, 255, 0.7);
}

/* 筛选状态条：画布顶部居中，点击清除 */
.mm-filter-badge {
  position: absolute;
  top: 8px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 15;
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(13, 19, 32, 0.88);
  border: 1px solid #3a4a6b;
  border-radius: 12px;
  padding: 4px 12px;
  font-size: 12px;
  color: #e0e6f0;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
.mm-filter-badge:hover { border-color: #1890ff; box-shadow: 0 0 0 2px rgba(24, 144, 255, 0.18); }
.mm-filter-clear { color: #8ba4c7; font-weight: bold; }

.mm-footer { display: flex; align-items: center; justify-content: space-between; flex-wrap: nowrap; gap: 10px 12px; padding: 5px 8px; color: #8ba4c7; font-size: 0.72rem; margin-top: 6px; flex-shrink: 0; }
.mm-footer-text { min-width: 0; flex: 0 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 复盘工具条：页脚说明文字右边 */
.mm-replay-bar { display: flex; align-items: center; gap: 4px; flex: 0 0 auto; flex-wrap: wrap; justify-content: flex-end; }
.mm-replay-time {
  min-width: 40px; height: 22px; padding: 0 5px;
  border: 1px solid rgba(139,164,199,0.3); border-radius: 4px;
  background: rgba(13,19,32,0.6); color: #b0c4e0;
  font-size: 10px; font-weight: 600; cursor: pointer;
  transition: all 0.15s ease; font-variant-numeric: tabular-nums;
}
.mm-replay-time:hover:not(:disabled) { border-color: #1890ff; color: #fff; background: rgba(24,144,255,0.15); }
.mm-replay-time:disabled { opacity: 0.3; cursor: not-allowed; }
.mm-replay-time.active { border-color: #1890ff; background: #1890ff; color: #fff; box-shadow: 0 0 0 2px rgba(24,144,255,0.3); }
.mm-replay-sep { width: 1px; height: 16px; background: rgba(139,164,199,0.25); margin: 0 3px; }
.mm-replay-play, .mm-replay-live {
  height: 22px; padding: 0 10px; border-radius: 4px;
  font-size: 11px; font-weight: 700; cursor: pointer;
  transition: all 0.15s ease; white-space: nowrap;
}
.mm-replay-play { border: 1px solid #1890ff; background: rgba(24,144,255,0.15); color: #69c0ff; }
.mm-replay-play:hover:not(:disabled) { background: #1890ff; color: #fff; }
.mm-replay-play:disabled { opacity: 0.4; cursor: not-allowed; }
.mm-replay-live { border: 1px solid rgba(255,120,117,0.4); background: rgba(255,120,117,0.1); color: #ff7875; opacity: 0.45; }
.mm-replay-live:disabled { opacity: 0.35; cursor: not-allowed; }
.mm-replay-live.active { opacity: 1; border-color: #ff4d4f; background: rgba(255,77,79,0.2); color: #ffd8d8; box-shadow: 0 0 0 2px rgba(255,77,79,0.25); }
.mm-replay-live.active:hover { background: rgba(255,77,79,0.3); }

/* 复盘水印（画布左上角，复盘态显示，区别于实时） */
.mm-replay-watermark {
  position: absolute; top: 8px; left: 12px; z-index: 15;
  display: flex; align-items: center; gap: 5px;
  padding: 4px 12px;
  background: rgba(24,144,255,0.18); border: 1px solid rgba(24,144,255,0.5);
  border-radius: 12px; color: #69c0ff;
  font-size: 12px; font-weight: 700;
  pointer-events: none; font-variant-numeric: tabular-nums;
}

/* 着色维度下拉 */
.mm-color-mode { display: flex; align-items: center; gap: 4px; }
.mm-color-mode-icon { font-size: 13px; }
.mm-color-select {
  height: 26px; padding: 0 6px;
  background: rgba(13,19,32,0.8); border: 1px solid #3a4a6b; border-radius: 6px;
  color: #e0e6f0; font-size: 12px; outline: none; cursor: pointer;
  transition: border-color 0.2s;
}
.mm-color-select:focus { border-color: #1890ff; }
.mm-color-select option { background: #0f1626; color: #e0e6f0; }
.mm-color-date { font-size: 10px; color: #8ba4c7; white-space: nowrap; }
.mm-color-mode.loading .mm-color-select { opacity: 0.6; }

/* 融资趋势弹窗（单击个股触发） */
.mm-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
}
.mm-modal {
  width: 720px;
  max-width: 94vw;
  background: linear-gradient(135deg, #1a2138, #0f1626);
  border: 1px solid #3a4a6b;
  border-radius: 12px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.6);
  padding: 16px 18px 18px;
  color: #e0e6f0;
}
.mm-modal-header { display: flex; align-items: center; gap: 12px; }
.mm-modal-title { display: flex; align-items: baseline; gap: 10px; min-width: 0; flex: 1; }
.mm-modal-name { font-size: 18px; font-weight: bold; color: #fff; }
.mm-modal-code { font-size: 13px; color: #8ba4c7; }
.mm-fin-balance {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  border-radius: 8px;
  background: rgba(24, 144, 255, 0.1);
  border: 1px solid rgba(24, 144, 255, 0.34);
}
.mm-fin-balance-label {
  color: #8ba4c7;
  font-size: 12px;
  white-space: nowrap;
}
.mm-fin-balance-value {
  color: #e0e6f0;
  font-size: 14px;
  font-weight: 800;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.mm-modal-close {
  width: 30px; height: 30px; flex-shrink: 0;
  border-radius: 50%; border: none;
  background: rgba(255, 255, 255, 0.08); color: #b0c4e0;
  font-size: 15px; cursor: pointer;
}
.mm-modal-close:hover { background: rgba(255, 255, 255, 0.18); color: #fff; }
.mm-modal-sub { font-size: 13px; color: #8ba4c7; margin: 10px 0 8px; }
.mm-fin-periods { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.mm-fin-period {
  flex: 1; min-width: 78px;
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 6px 4px; border-radius: 8px;
  border: 1px solid #2a3550; background: rgba(255, 255, 255, 0.04);
  cursor: pointer; transition: border-color 0.15s ease, background 0.15s ease;
}
.mm-fin-period:hover { border-color: #1890ff; }
.mm-fin-period.active { border-color: #1890ff; background: rgba(24, 144, 255, 0.14); }
.mm-fin-period-label { font-size: 12px; color: #8ba4c7; }
.mm-fin-period-val { font-size: 14px; font-weight: bold; color: #fff; white-space: nowrap; }
.mm-fin-period-val.up { color: #ff4d4f; }
.mm-fin-period-val.down { color: #52c41a; }
.mm-fin-chart-wrap { position: relative; width: 100%; height: 320px; }
.mm-fin-chart { width: 100%; height: 100%; }
.mm-fin-status {
  position: absolute; inset: 0;
  display: flex; align-items: center; justify-content: center;
  color: #8ba4c7; font-size: 14px;
}

/* AI 批量打分按钮 */
.mm-score-btn {
  order: 8; padding: 6px 12px;
  background: linear-gradient(135deg, #722ed1, #531dab);
  border: 1px solid #9254de; border-radius: 6px;
  color: #fff; cursor: pointer; font-size: 12px; font-weight: 600;
  transition: all 0.3s ease; white-space: nowrap;
}
.mm-score-btn:hover:not(.running) { background: linear-gradient(135deg, #9254de, #722ed1); transform: translateY(-1px); }
.mm-score-btn.running { background: linear-gradient(135deg, #531dab, #391085); opacity: 0.95; }
.mm-score-spin { display: inline-block; margin-right: 3px; font-size: 13px; line-height: 1; }
.mm-score-spin.on { animation: mm-score-pulse 1.2s ease-in-out infinite; }
@keyframes mm-score-pulse { 0%, 100% { opacity: 0.5; transform: scale(0.9); } 50% { opacity: 1; transform: scale(1.15); } }

/* AI 行业周期诊断按钮 */
.mm-cycle-btn {
  order: 7; padding: 6px 12px;
  background: linear-gradient(135deg, #d4380d, #ad2102);
  border: 1px solid #ff7a45; border-radius: 6px;
  color: #fff; cursor: pointer; font-size: 12px; font-weight: 600;
  transition: all 0.3s ease; white-space: nowrap;
}
.mm-cycle-btn:hover:not(.running) { background: linear-gradient(135deg, #ff7a45, #d4380d); transform: translateY(-1px); }
.mm-cycle-btn.running { background: linear-gradient(135deg, #ad2102, #871400); opacity: 0.95; }
.mm-cycle-spin { display: inline-block; margin-right: 3px; font-size: 13px; line-height: 1; }
.mm-cycle-spin.on { animation: mm-cycle-pulse 1.2s ease-in-out infinite; }
@keyframes mm-cycle-pulse { 0%, 100% { opacity: 0.5; transform: scale(0.9); } 50% { opacity: 1; transform: scale(1.15); } }

/* 打分 tooltip：分数后的档位标签 + 一句话理由 */
.mm-tooltip-val small { font-size: 11px; font-weight: normal; color: #b0c4e0; margin-left: 4px; }
.mm-tooltip-score-reason {
  margin-top: 4px; color: #dbeafe; font-size: 11px; line-height: 1.35;
  padding-top: 4px; border-top: 1px dashed rgba(139, 164, 199, 0.22);
}

/* AI 批量打分弹窗 */
.mm-score-modal { width: 520px; max-width: 94vw; }
.mm-score-body { padding: 4px 2px 2px; }
.mm-score-desc { font-size: 13px; line-height: 1.7; color: #c0cee0; margin: 8px 0 12px; }
.mm-score-desc .up { color: #ff4d4f; font-weight: 700; }
.mm-score-desc .down { color: #52c41a; font-weight: 700; }
.mm-score-tips { margin: 0 0 14px; padding-left: 18px; font-size: 12px; line-height: 1.8; color: #8ba4c7; }
.mm-score-tips li { list-style: disc; }
.mm-score-warn { color: #ffb4b2; font-size: 12px; background: rgba(239,83,80,0.1); border: 1px solid rgba(239,83,80,0.3); padding: 8px 10px; border-radius: 6px; margin-bottom: 12px; }
.mm-score-actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; margin-top: 14px; }
.mm-score-btn-ok { padding: 7px 16px; background: linear-gradient(135deg, #722ed1, #531dab); border: 1px solid #9254de; border-radius: 6px; color: #fff; cursor: pointer; font-size: 13px; font-weight: 600; }
.mm-score-btn-ok:hover:not(:disabled) { background: linear-gradient(135deg, #9254de, #722ed1); }
.mm-score-btn-ok:disabled { opacity: 0.5; cursor: not-allowed; }
.mm-score-btn-cancel { padding: 7px 16px; background: rgba(255,255,255,0.06); border: 1px solid #3a4a6b; border-radius: 6px; color: #c0cee0; cursor: pointer; font-size: 13px; }
.mm-score-btn-cancel:hover { background: rgba(255,255,255,0.12); }
.mm-score-btn-warn { padding: 7px 16px; background: linear-gradient(135deg, #d4380d, #ad2102); border: 1px solid #ff7a45; border-radius: 6px; color: #fff; cursor: pointer; font-size: 13px; font-weight: 600; }
.mm-score-btn-warn:hover { background: linear-gradient(135deg, #ff7a45, #d4380d); }
.mm-score-btn-ghost { padding: 7px 14px; background: transparent; border: 1px dashed #3a4a6b; border-radius: 6px; color: #8ba4c7; cursor: pointer; font-size: 12px; }
.mm-score-btn-ghost:hover { color: #e0e6f0; border-color: #5a6b8c; }

.mm-score-progress { display: flex; align-items: center; gap: 10px; margin: 10px 0 8px; }
.mm-score-progress-bar { flex: 1; height: 12px; background: rgba(255,255,255,0.08); border-radius: 6px; overflow: hidden; border: 1px solid rgba(58,74,107,0.5); }
.mm-score-progress-fill { height: 100%; background: linear-gradient(90deg, #722ed1, #9254de); transition: width 0.4s ease; }
.mm-score-progress-num { font-size: 16px; font-weight: 800; color: #fff; min-width: 48px; text-align: right; font-variant-numeric: tabular-nums; }
.mm-score-step { font-size: 13px; color: #e0e6f0; margin-bottom: 6px; font-weight: 600; }
.mm-score-stat { font-size: 12px; color: #8ba4c7; margin-bottom: 8px; }
.mm-score-stat .up { color: #ff4d4f; } .mm-score-stat .down { color: #52c41a; }
.mm-score-note { font-size: 11px; color: #5a6b8c; line-height: 1.6; margin: 8px 0; }
.mm-score-result { font-size: 15px; font-weight: 700; color: #52c41a; margin: 12px 0; }
.mm-score-result.warn { color: #ffa39e; }

@media (max-width: 768px) {
  .market-map-page { padding: 6px; }
  .mm-header { flex-direction: column; gap: 8px; align-items: stretch; text-align: center; }
  .mm-header h1 { font-size: 1rem; }
  .mm-header-left,
  .mm-header-right { width: 100%; }
  /* 搜索框铺满整行 */
  .mm-search-wrap { flex: 1 1 100%; width: 100%; }
  .mm-search { width: 100%; }
  /* 右侧 7+ 控件允许换行；次要统计文本移动端隐藏以保持头部紧凑（数据仍可从图表/tooltip 看到） */
  .mm-header-right { flex-wrap: wrap; gap: 8px; justify-content: center; }
  .mm-stats,
  .mm-update { display: none; }
  .mm-chart-wrapper { min-height: 240px; }
}
</style>
