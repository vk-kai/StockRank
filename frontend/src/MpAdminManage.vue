<template>
  <div class="mpadmin-page">
    <header class="mpadmin-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>📱 小程序数据后台</h1>
      <nav class="tab-nav">
        <span class="tab" @click="goTrend">数据趋势</span>
        <span class="tab active">数据管理</span>
      </nav>
    </header>

    <!-- 非 vk 提示 -->
    <div v-if="!loading && !isAdmin" class="mpadmin-forbidden">
      <p>仅管理员（vk 登录）可访问此页面。</p>
    </div>

    <div v-else-if="loading" class="mpadmin-loading">加载中…</div>

    <div v-else class="mpadmin-body">
      <!-- 数据类切换 -->
      <nav class="sub-tabs">
        <span :class="['sub-tab', { active: tab === 'scores' }]" @click="switchTab('scores')">成绩记录</span>
        <span :class="['sub-tab', { active: tab === 'stats' }]" @click="switchTab('stats')">参与计数</span>
        <span :class="['sub-tab', { active: tab === 'rooms' }]" @click="switchTab('rooms')">PK房间</span>
        <span :class="['sub-tab', { active: tab === 'echo' }]" @click="switchTab('echo')">弹幕墙</span>
        <span :class="['sub-tab', { active: tab === 'subs' }]" @click="switchTab('subs')">订阅额度</span>
      </nav>

      <!-- ===== 成绩记录 ===== -->
      <section v-if="tab === 'scores'" class="card">
        <div class="toolbar">
          <input v-model="scoresFilter" placeholder="按测试ID过滤，如 test_caiyun" class="filter-input"
                 @keyup.enter="loadScores(1)" />
          <button class="gen-btn" @click="loadScores(1)">查询</button>
          <button class="gen-btn" @click="openScoreCreate">新增成绩</button>
        </div>
        <div v-if="!scores.items.length" class="empty">暂无成绩</div>
        <table v-else class="data-table">
          <thead>
            <tr><th>测试</th><th>玩家</th><th>昵称</th><th>分数</th><th>用时</th><th>提交时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in scores.items" :key="row.quiz_id + '/' + row.openid">
              <td>
                <template v-if="row.name && row.name !== row.quiz_id">
                  {{ row.name }} <small class="dim">{{ row.quiz_id }}</small>
                </template>
                <span v-else class="code-text">{{ row.quiz_id }}</span>
              </td>
              <td class="code-text">{{ shortOpenid(row.openid) }}</td>
              <td>{{ row.nickname }}</td>
              <td>{{ row.score }}/{{ row.full_score }}</td>
              <td>{{ fmtDuration(row.duration_ms) }}</td>
              <td>{{ fmtUtc(row.created_at) }}</td>
              <td>
                <button class="copy-btn" @click="openScoreEdit(row)">编辑</button>
                <button class="del-btn" @click="onScoreDelete(row)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="scores.totalPages > 1" class="pager">
          <button :disabled="scores.page <= 1" @click="loadScores(scores.page - 1)">上一页</button>
          <span>{{ scores.page }} / {{ scores.totalPages }} 页 · 共 {{ scores.total }} 条</span>
          <button :disabled="scores.page >= scores.totalPages" @click="loadScores(scores.page + 1)">下一页</button>
        </div>
      </section>

      <!-- ===== 参与计数 ===== -->
      <section v-if="tab === 'stats'" class="card">
        <nav class="sub-tabs">
          <span :class="['sub-tab', { active: statsType === 'test' }]" @click="switchStatsType('test')">测试（test_）</span>
          <span :class="['sub-tab', { active: statsType === 'tool' }]" @click="switchStatsType('tool')">工具（tool_）</span>
          <span :class="['sub-tab', { active: statsType === 'article' }]" @click="switchStatsType('article')">文章（article_）</span>
        </nav>
        <div class="toolbar">
          <input v-model="newStat.key" placeholder="新key，如 test_xxx（小写字母数字下划线）" class="filter-input" />
          <input v-model.number="newStat.count" type="number" min="0" class="count-input" placeholder="次数" />
          <button class="gen-btn" @click="onStatAdd">新增计数</button>
          <button class="warn-btn" @click="onCleanupClick">清理联调数据</button>
        </div>
        <div v-if="stats.items.length" class="stats-sum">
          共 {{ stats.items.length }} 个{{ statsTypeName }} ·
          累计 {{ stats.sum }} 人次
        </div>
        <div v-if="!stats.items.length" class="empty">暂无{{ statsTypeName }}计数</div>
        <table v-else class="data-table">
          <thead>
            <tr><th>名称</th><th>key</th><th>参与人次</th><th>最后更新</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in stats.items" :key="row.key">
              <td>{{ row.name }} <small v-if="row.name !== row.key" class="dim">{{ row.key }}</small></td>
              <td class="code-text">{{ row.key }}</td>
              <td>{{ row.count }}</td>
              <td>{{ fmtEpoch(row.updated_at) }}</td>
              <td>
                <button class="copy-btn" @click="openStatEdit(row)">改数值</button>
                <button class="del-btn" @click="onStatDelete(row)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- ===== PK房间 ===== -->
      <section v-if="tab === 'rooms'" class="card">
        <div class="toolbar">
          <select v-model.number="roomsDays" class="count-input" @change="loadRooms(1)">
            <option :value="7">近7天</option>
            <option :value="30">近30天</option>
            <option :value="0">全部</option>
          </select>
          <button class="gen-btn" @click="loadRooms(rooms.page)">刷新</button>
          <span class="toolbar-hint">过期房间保留7天后自动从库中清除</span>
        </div>
        <div v-if="!rooms.items.length" class="empty">暂无房间</div>
        <table v-else class="data-table">
          <thead>
            <tr><th>房间码</th><th>测试</th><th>状态</th><th>人数</th><th>交卷</th><th>合拍度</th><th>创建时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in rooms.items" :key="row.room_code">
              <td class="code-text">{{ row.room_code }}</td>
              <td>
                <template v-if="row.name && row.name !== row.quiz_id">
                  {{ row.name }} <small class="dim">{{ row.quiz_id }}</small>
                </template>
                <span v-else class="code-text">{{ row.quiz_id }}</span>
              </td>
              <td><span :class="['status', row.state]">{{ stateName(row.state) }}</span></td>
              <td>{{ row.players }}</td>
              <td>{{ row.a_submitted ? 'A✓' : 'A…' }} {{ row.b_submitted ? 'B✓' : 'B…' }}</td>
              <td>{{ row.match_percent == null ? '--' : row.match_percent + '%' }}</td>
              <td>{{ fmtUtc(row.created_at) }}</td>
              <td>
                <button class="del-btn" @click="onRoomDelete(row)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="rooms.totalPages > 1" class="pager">
          <button :disabled="rooms.page <= 1" @click="loadRooms(rooms.page - 1)">上一页</button>
          <span>{{ rooms.page }} / {{ rooms.totalPages }} 页 · 共 {{ rooms.total }} 条</span>
          <button :disabled="rooms.page >= rooms.totalPages" @click="loadRooms(rooms.page + 1)">下一页</button>
        </div>
      </section>

      <!-- ===== 弹幕墙 ===== -->
      <section v-if="tab === 'echo'" class="card">
        <div class="toolbar">
          <input v-model="echoWall" placeholder="按 wall_id 过滤，如 20260906" class="filter-input"
                 @keyup.enter="loadEcho(1)" />
          <select v-model.number="echoDays" class="count-input" @change="loadEcho(1)">
            <option :value="7">近7天</option>
            <option :value="30">近30天</option>
            <option :value="0">全部</option>
          </select>
          <button class="gen-btn" @click="loadEcho(1)">查询</button>
          <button class="gen-btn" @click="openEchoCreate">补录留言</button>
          <button class="gen-btn" @click="onEchoSeed">导入种子</button>
        </div>
        <div v-if="!echo.items.length" class="empty">
          {{ echoWall.trim() ? `该 wall_id 下暂无留言（清空过滤可看全部）` : '暂无留言' }}
        </div>
        <table v-else class="data-table">
          <thead>
            <tr><th>ID</th><th>墙</th><th>留言</th><th>分类</th><th>昵称</th><th>抱抱</th><th>发布时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in echo.items" :key="row.id">
              <td class="code-text">{{ row.id }}</td>
              <td class="code-text">{{ row.wall_id }}</td>
              <td class="echo-text" :title="row.text">{{ row.text }}</td>
              <td><span class="cat-tag">{{ row.category }}</span></td>
              <td>{{ row.nickname }} <small class="dim">{{ shortOpenid(row.openid) }}</small>
                <span v-if="row.is_seed" class="seed-tag" title="冷启动种子数据，非真实用户">种子</span></td>
              <td>🤗 {{ row.hugs }}</td>
              <td>{{ fmtEpoch(row.ts) }}</td>
              <td>
                <button class="del-btn" @click="onEchoDelete(row)">删除</button>
                <button :class="row.banned ? 'unban-btn' : 'del-btn'"
                        @click="row.banned ? onEchoUnban(row) : openEchoBan(row)">
                  {{ row.banned ? '解封' : '封禁' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="echo.totalPages > 1" class="pager">
          <button :disabled="echo.page <= 1" @click="loadEcho(echo.page - 1)">上一页</button>
          <span>{{ echo.page }} / {{ echo.totalPages }} 页 · 共 {{ echo.total }} 条</span>
          <button :disabled="echo.page >= echo.totalPages" @click="loadEcho(echo.page + 1)">下一页</button>
        </div>

        <!-- 封禁列表:封禁后该用户无法发布留言,抱抱等其他功能不受影响 -->
        <div class="toolbar" style="margin-top: 18px;">
          <strong>留言封禁</strong>
          <span class="dim">共 {{ bans.total }} 人</span>
          <button class="gen-btn" @click="openEchoBan()">手动封禁</button>
        </div>
        <div v-if="!bans.items.length" class="empty">暂无封禁记录</div>
        <table v-else class="data-table">
          <thead>
            <tr><th>openid</th><th>状态</th><th>原因</th><th>封禁时间</th><th>到期时间</th><th>操作</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in bans.items" :key="row.openid">
              <td class="code-text">{{ shortOpenid(row.openid) }}</td>
              <td>{{ banStatusName(row) }}</td>
              <td>{{ row.reason || '--' }}</td>
              <td>{{ fmtEpoch(row.created_at) }}</td>
              <td>{{ row.expires_at == null ? '永不' : fmtEpoch(row.expires_at) }}</td>
              <td><button class="unban-btn" @click="onEchoUnban(row)">解封</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="bans.totalPages > 1" class="pager">
          <button :disabled="bans.page <= 1" @click="loadBans(bans.page - 1)">上一页</button>
          <span>{{ bans.page }} / {{ bans.totalPages }} 页 · 共 {{ bans.total }} 人</span>
          <button :disabled="bans.page >= bans.totalPages" @click="loadBans(bans.page + 1)">下一页</button>
        </div>
      </section>

      <!-- ===== 订阅额度 ===== -->
      <section v-if="tab === 'subs'" class="card">
        <div class="toolbar">
          <span class="toolbar-hint">抱抱推送订阅额度：剩余额度 &gt; 0 的用户才可收到「有人抱了你的心声」推送；授权一次可推一条，推送成功即扣减</span>
          <button class="gen-btn" @click="loadSubs()">刷新</button>
        </div>
        <div v-if="subs.items.length" class="stats-sum">
          共 {{ subs.total }} 人订阅 · 剩余额度 {{ subs.totalQuota }} 条
        </div>
        <div v-if="!subs.items.length" class="empty">还没有订阅用户</div>
        <table v-else class="data-table">
          <thead>
            <tr><th>openid</th><th>剩余额度</th><th>首次订阅</th><th>最近订阅</th></tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in subs.items" :key="i">
              <td class="code-text">{{ shortOpenid(row.openid) }}</td>
              <td>{{ row.quota }}</td>
              <td>{{ fmtEpoch(row.first_ts) }}</td>
              <td>{{ fmtEpoch(row.last_ts) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>

    <!-- 新增成绩弹窗 -->
    <div v-if="scoreCreate.show" class="pwd-overlay" @click.self="scoreCreate.show = false">
      <div class="pwd-card">
        <h3>新增成绩</h3>
        <p class="pwd-desc">管理员手动补录，昵称不过内容安全检测</p>
        <label class="edit-row">测试ID <input v-model="scoreCreate.quiz_id" placeholder="如 childIntelligence" /></label>
        <label class="edit-row">openid <input v-model="scoreCreate.openid" placeholder="玩家 openid" /></label>
        <label class="edit-row">昵称 <input v-model="scoreCreate.nickname" maxlength="12" /></label>
        <label class="edit-row">分数 <input v-model.number="scoreCreate.score" type="number" min="0" /></label>
        <label class="edit-row">满分 <input v-model.number="scoreCreate.full_score" type="number" min="1" /></label>
        <label class="edit-row">用时(ms) <input v-model.number="scoreCreate.duration_ms" type="number" min="0" /></label>
        <div class="pwd-actions">
          <button class="cancel-btn" @click="scoreCreate.show = false">取消</button>
          <button class="ok-btn" :disabled="scoreCreate.busy" @click="doScoreCreate">
            {{ scoreCreate.busy ? '处理中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 改成绩弹窗 -->
    <div v-if="scoreEdit.show" class="pwd-overlay" @click.self="scoreEdit.show = false">
      <div class="pwd-card">
        <h3>编辑成绩</h3>
        <p class="pwd-desc">{{ scoreEdit.quiz_id }} / {{ shortOpenid(scoreEdit.openid) }}</p>
        <label class="edit-row">昵称 <input v-model="scoreEdit.nickname" maxlength="12" /></label>
        <label class="edit-row">分数 <input v-model.number="scoreEdit.score" type="number" min="0" /></label>
        <label class="edit-row">满分 <input v-model.number="scoreEdit.full_score" type="number" min="1" /></label>
        <label class="edit-row">用时(ms) <input v-model.number="scoreEdit.duration_ms" type="number" min="0" /></label>
        <div class="pwd-actions">
          <button class="cancel-btn" @click="scoreEdit.show = false">取消</button>
          <button class="ok-btn" :disabled="scoreEdit.busy" @click="doScoreEdit">
            {{ scoreEdit.busy ? '处理中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 补录留言弹窗 -->
    <div v-if="echoCreate.show" class="pwd-overlay" @click.self="echoCreate.show = false">
      <div class="pwd-card">
        <h3>补录留言</h3>
        <p class="pwd-desc">管理员内容不过微信检测，但本地敏感词/注入检测照拦</p>
        <label class="edit-row">wall_id <input v-model="echoCreate.wall_id" placeholder="如 20260906" /></label>
        <label class="edit-row">昵称 <input v-model="echoCreate.nickname" maxlength="12" placeholder="默认 匿名测试者" /></label>
        <label class="edit-row">留言 <input v-model="echoCreate.text" maxlength="50" placeholder="最多50字" /></label>
        <label class="edit-row">分类
          <select v-model="echoCreate.category">
            <option v-for="cat in echoCats" :key="cat" :value="cat">{{ cat }}</option>
          </select>
        </label>
        <div class="pwd-actions">
          <button class="cancel-btn" @click="echoCreate.show = false">取消</button>
          <button class="ok-btn" :disabled="echoCreate.busy" @click="doEchoCreate">
            {{ echoCreate.busy ? '处理中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 封禁留言用户弹窗 -->
    <div v-if="banEdit.show" class="pwd-overlay" @click.self="banEdit.show = false">
      <div class="pwd-card">
        <h3>封禁留言用户</h3>
        <p class="pwd-desc">封禁后该用户无法发布留言，抱抱等其他功能不受影响</p>
        <label class="edit-row">openid <input v-model="banEdit.openid" placeholder="完整 openid" /></label>
        <label class="edit-row">时长
          <select v-model.number="banEdit.days">
            <option :value="0">永久</option>
            <option :value="1">1 天</option>
            <option :value="3">3 天</option>
            <option :value="7">7 天</option>
            <option :value="30">30 天</option>
          </select>
        </label>
        <label class="edit-row">原因 <input v-model="banEdit.reason" maxlength="100" placeholder="选填，仅后台可见" /></label>
        <div class="pwd-actions">
          <button class="cancel-btn" @click="banEdit.show = false">取消</button>
          <button class="ok-btn" :disabled="banEdit.busy" @click="doEchoBan">
            {{ banEdit.busy ? '处理中…' : '封禁' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 改计数弹窗 -->
    <div v-if="statEdit.show" class="pwd-overlay" @click.self="statEdit.show = false">
      <div class="pwd-card">
        <h3>修改参与人次</h3>
        <p class="pwd-desc">{{ statEdit.key }}</p>
        <label class="edit-row">参与人次 <input v-model.number="statEdit.count" type="number" min="0" /></label>
        <div class="pwd-actions">
          <button class="cancel-btn" @click="statEdit.show = false">取消</button>
          <button class="ok-btn" :disabled="statEdit.busy" @click="doStatEdit">
            {{ statEdit.busy ? '处理中…' : '保存' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 二次确认弹窗（删除/清理等破坏性操作；后台仅 vk 可见，不再二次输密码） -->
    <div v-if="confirmBox.show" class="pwd-overlay" @click.self="confirmBox.show = false">
      <div class="pwd-card">
        <h3>{{ confirmBox.title }}</h3>
        <p v-if="confirmBox.desc" class="pwd-desc">{{ confirmBox.desc }}</p>
        <div class="pwd-actions">
          <button class="cancel-btn" @click="confirmBox.show = false">取消</button>
          <button class="ok-btn" :disabled="confirmBox.busy" @click="confirmBox.confirm">
            {{ confirmBox.busy ? '处理中…' : '确认' }}
          </button>
        </div>
      </div>
    </div>

    <!-- toast -->
    <div v-if="toast.show" class="toast" :class="toast.type">{{ toast.message }}</div>
  </div>
</template>

<script src="./components/MpAdminManage/MpAdminManage.script.js"></script>
<style src="./components/MpAdminManage/MpAdminManage.style.css" scoped></style>
