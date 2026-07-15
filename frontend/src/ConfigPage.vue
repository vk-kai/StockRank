<template>
  <div class="config-page">
    <header class="config-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>⚙️ 系统配置</h1>
      <div class="header-spacer"></div>
    </header>

    <div class="config-tabs">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="['tab-button', { 'active': activeTab === tab.id }]"
        @click="activeTab = tab.id"
      >
        {{ tab.icon }} {{ tab.name }}
      </button>
    </div>

    <!-- 推送设置子页签 -->
    <div v-if="activeTab === 'push'" class="sub-tabs">
      <button
        v-for="sub in tabs.find(t => t.id === 'push').subTabs"
        :key="sub.id"
        :class="['sub-tab-button', { 'active': activePushTab === sub.id }]"
        @click="activePushTab = sub.id"
      >
        {{ sub.icon }} {{ sub.name }}
      </button>
    </div>

    <div class="config-content">
      <div v-if="activeTab === 'ai'" class="config-section">
        <h2>🤖 AI大模型配置</h2>
        <div class="config-form">
          <div class="form-group">
            <label>启用AI分析</label>
            <div class="toggle-switch">
              <input type="checkbox" v-model="aiConfig.enabled" id="ai-enabled">
              <label for="ai-enabled"></label>
            </div>
          </div>

          <div class="form-group">
            <label>API地址</label>
            <div class="url-mode-toggle">
              <div class="toggle-switch">
                <input type="checkbox" v-model="aiConfig.full_url" id="ai-full-url">
                <label for="ai-full-url"></label>
              </div>
              <span class="url-mode-label">{{ aiConfig.full_url ? '完整URL模式' : '自动补全模式' }}</span>
            </div>
            <input 
              type="text" 
              v-model="aiConfig.api_url" 
              :placeholder="aiConfig.full_url ? 'https://api.example.com/v1/chat/completions' : 'https://api.openai.com/v1'"
            >
            <span class="hint" v-if="aiConfig.full_url">完整URL模式：直接使用输入的URL地址，不进行任何补全</span>
            <span class="hint" v-else>自动补全模式：将自动在URL后追加 /chat/completions</span>
          </div>

          <div class="form-group">
            <label>API密钥</label>
            <input 
              type="password" 
              v-model="aiConfig.api_key" 
              placeholder="sk-xxxxxxxxxxxxxxxx"
            >
            <span class="hint">您的API密钥，以sk-开头</span>
          </div>

          <div class="form-group">
            <label>模型名称</label>
            <input 
              type="text" 
              v-model="aiConfig.model" 
              placeholder="gpt-3.5-turbo"
            >
            <span class="hint">如：gpt-3.5-turbo, gpt-4等</span>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>温度参数</label>
              <input 
                type="number" 
                v-model.number="aiConfig.temperature" 
                min="0" 
                max="1" 
                step="0.1"
              >
              <span class="hint">0-1之间，建议0.7</span>
            </div>

            <div class="form-group">
              <label>最大Token数</label>
              <input 
                type="number" 
                v-model.number="aiConfig.max_tokens" 
                min="100" 
                max="4000"
              >
              <span class="hint">建议1000</span>
            </div>

            <div class="form-group">
              <label>超时时间(秒)</label>
              <input 
                type="number" 
                v-model.number="aiConfig.timeout" 
                min="10" 
                max="120"
              >
              <span class="hint">建议30</span>
            </div>
          </div>

          <div class="form-actions">
            <button @click="saveAIConfig" class="btn-primary">保存配置</button>
            <button @click="testAIConfig" class="btn-secondary">测试连接</button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'push' && activePushTab === 'feishu'" class="config-section">
        <h2>📢 飞书机器人配置</h2>
        <div class="config-form">
          <div class="form-group">
            <label>启用飞书推送</label>
            <div class="toggle-switch">
              <input type="checkbox" v-model="feishuConfig.enabled" id="feishu-enabled">
              <label for="feishu-enabled"></label>
            </div>
          </div>

          <div class="form-group">
            <label>Webhook地址</label>
            <input 
              type="text" 
              v-model="feishuConfig.webhook_url" 
              placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/xxxxxxxxx"
            >
            <span class="hint">飞书群机器人Webhook地址</span>
          </div>

          <div class="form-group">
            <label>网站域名URL</label>
            <input 
              type="text" 
              v-model="feishuConfig.base_url" 
              placeholder="http://localhost:5000"
            >
            <span class="hint">用于飞书消息中的详情链接，如：https://your-domain.com</span>
          </div>

          <div class="form-group">
            <label>签名密钥(可选)</label>
            <input 
              type="password" 
              v-model="feishuConfig.secret" 
              placeholder="留空表示不使用签名验证"
            >
            <span class="hint">创建机器人时显示的签名密钥</span>
          </div>

          <div class="form-group">
            <label>消息类型</label>
            <select v-model="feishuConfig.msg_type">
              <option value="interactive">卡片消息(推荐)</option>
              <option value="text">文本消息</option>
            </select>
          </div>

          <div class="form-group">
            <label>新闻推送策略</label>
            <select v-model="feishuConfig.news_push_mode">
              <option
                v-for="option in newsPushModeOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </option>
            </select>
            <span class="hint">控制新闻采集时哪些消息会进入飞书推送</span>
          </div>

          <div class="form-actions">
            <button @click="saveFeishuConfig" class="btn-primary">保存配置</button>
            <button @click="testFeishuConfig" class="btn-secondary">测试推送</button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'push' && activePushTab === 'wechat'" class="config-section">
        <h2>💬 企业微信机器人配置</h2>
        <div class="config-form">
          <div class="form-group">
            <label>启用企业微信推送</label>
            <div class="toggle-switch">
              <input type="checkbox" v-model="wechatConfig.enabled" id="wechat-enabled">
              <label for="wechat-enabled"></label>
            </div>
          </div>

          <div class="form-group">
            <label>Webhook地址</label>
            <input
              type="text"
              v-model="wechatConfig.webhook_url"
              placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxxxxxx"
            >
            <span class="hint">企业微信群机器人Webhook地址</span>
          </div>

          <div class="form-group">
            <label>网站域名URL</label>
            <input
              type="text"
              v-model="wechatConfig.base_url"
              placeholder="http://localhost:5000"
            >
            <span class="hint">用于企业微信消息中的详情链接，如：https://your-domain.com</span>
          </div>

          <div class="form-group">
            <label>消息类型</label>
            <select v-model="wechatConfig.msg_type">
              <option value="markdown">Markdown消息(推荐)</option>
              <option value="text">文本消息</option>
            </select>
          </div>

          <div class="form-group">
            <label>新闻推送策略</label>
            <select v-model="wechatConfig.news_push_mode">
              <option
                v-for="option in newsPushModeOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </option>
            </select>
            <span class="hint">控制新闻采集时哪些消息会进入企业微信推送</span>
          </div>

          <div class="form-actions">
            <button @click="saveWechatConfig" class="btn-primary">保存配置</button>
            <button @click="testWechatConfig" class="btn-secondary">测试推送</button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'datasource'" class="config-section">
        <h2>🔌 数据源设置</h2>
        <div class="config-form">
          <div class="form-group">
            <label>外部数据源URL配置</label>
            <span class="hint">修改数据源URL后保存即可生效。角色标注：<b class="role-primary">主</b>=主要数据源，<b class="role-backup">备</b>=备用数据源(主源失败时启用)，<b class="role-complement">互补</b>=补充数据源(提供主源没有的部分数据)</span>
          </div>

          <div v-for="group in datasourceGroups" :key="group.category" class="ds-group">
            <div class="ds-group-header">{{ group.category }}</div>
            <div v-for="ds in group.items" :key="ds.key" class="ds-item">
              <div class="ds-item-header">
                <span class="datasource-dot"
                  :class="{
                    'dot-ok': datasourceTestResults[ds.key]?.ok === true,
                    'dot-fail': datasourceTestResults[ds.key]?.ok === false,
                    'dot-skip': datasourceTestResults[ds.key]?.ok === null,
                    'dot-unknown': datasourceTestResults[ds.key] === undefined
                  }"
                ></span>
                <span class="ds-item-name">{{ ds.provider }}</span>
                <span class="datasource-role" :class="datasourceRoleClass(ds.role)">{{ ds.role }}</span>
                <span v-if="datasourceTestResults[ds.key]" class="ds-test-badge"
                  :class="{'ds-test-ok': datasourceTestResults[ds.key].ok === true, 'ds-test-fail': datasourceTestResults[ds.key].ok === false}">
                  <template v-if="datasourceTestResults[ds.key].ok === true">{{ datasourceTestResults[ds.key].latency_ms }}ms</template>
                  <template v-else-if="datasourceTestResults[ds.key].ok === false">{{ datasourceTestResults[ds.key].error }}</template>
                  <template v-else>{{ datasourceTestResults[ds.key].error }}</template>
                </span>
              </div>
              <input type="text" v-model="ds.url" class="datasource-url-input">
            </div>
          </div>

          <div class="form-actions">
            <button @click="saveDatasourceConfigCfg" class="btn-primary">保存配置</button>
            <button @click="testDatasourceCfg" class="btn-secondary" :disabled="datasourceTesting">
              {{ datasourceTesting ? '测试中...' : '一键测试连通性' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'stock'" class="config-section">
        <h2>📈 股票监控配置</h2>
        <div class="config-form">
          <div class="form-group">
            <label>启用自选股价格监控</label>
            <div class="toggle-switch">
              <input type="checkbox" v-model="stockConfig.enabled" id="stock-enabled">
              <label for="stock-enabled"></label>
            </div>
          </div>

          <div class="form-group" style="display:flex;gap:12px;align-items:center;">
            <label style="margin:0;">轮询频率(秒)</label>
            <input type="number" v-model.number="stockConfig.poll_interval_seconds" min="10" style="width:90px;">
            <label style="margin:0 0 0 16px;">去重冷却(分钟)</label>
            <input type="number" v-model.number="stockConfig.cooldown_minutes" min="1" style="width:90px;">
          </div>

          <div class="stock-list">
            <div class="stock-header">
              <h3>监控列表（每个股可独立开关：价格监控 / 新闻监控）</h3>
            </div>

            <!-- 添加：模式切换 -->
            <div class="add-mode-tabs">
              <button class="add-tab" :class="{ active: newWatch.mode==='stock' }" @click="switchWatchMode('stock')">📈 添加个股</button>
              <button class="add-tab" :class="{ active: newWatch.mode==='keyword' }" @click="switchWatchMode('keyword')">📰 添加关键词</button>
            </div>

            <!-- 个股：实时搜索，只能从结果选 -->
            <div v-if="newWatch.mode==='stock'" class="stock-card add-row" style="position:relative;">
              <input type="text" v-model="newWatch.search" class="search-input"
                     placeholder="输入名字或代码搜索（如 长电科技 / 600584），只能从结果选"
                     @input="onSearchInput" @keydown="onSearchKeydown"
                     @focus="newWatch.showResults = true" @blur="blurSearch">
              <span v-if="newWatch.searching" class="search-hint">搜索中…</span>
              <div v-if="newWatch.showResults && (newWatch.results.length || (newWatch.search && !newWatch.searching))" class="search-dropdown">
                <div v-if="newWatch.search && !newWatch.results.length && !newWatch.searching" class="search-empty">无匹配结果</div>
                <div v-for="(r, idx) in newWatch.results" :key="r.code"
                     class="search-result" :class="{ active: newWatch.highlight===idx }"
                     @mousedown.prevent="selectStock(r)">
                  <span class="sr-name">{{ r.name }}</span>
                  <span class="sr-code">{{ r.code }}</span>
                </div>
              </div>
            </div>

            <!-- 关键词：自由输入 -->
            <div v-else class="stock-card add-row">
              <input type="text" v-model="newWatch.keyword" class="search-input"
                     placeholder="新闻关键词（任意文本，如 纳斯达克中国金龙）" @keyup.enter="addKeywordItem">
              <button @click="addKeywordItem" class="btn-add">＋ 添加</button>
            </div>

            <div v-for="w in stockConfig.watchlist" :key="w.id" class="stock-card watch-item">
              <!-- 头部：勾选 + 类型 + 名字 + 代码 + 开关 + 删除 -->
              <div class="watch-head">
                <input type="checkbox" :value="w.id" v-model="selectedIds" class="watch-check">
                <span class="type-badge" :class="w.type">{{ w.type==='keyword' ? '关键词' : '个股' }}</span>
                <strong class="watch-name">{{ w.value }}</strong>
                <span v-if="w.type!=='keyword' && w.resolved_code" class="watch-code">{{ w.resolved_code }}</span>
                <div class="toggle-switch small head-toggle">
                  <input type="checkbox" v-model="w.enabled" :id="'w-'+w.id">
                  <label :for="'w-'+w.id"></label>
                </div>
                <button @click="removeWatchItem(w.id)" class="btn-remove">删除</button>
              </div>

              <!-- 个股：价格监控 + 新闻监控 双区块 -->
              <template v-if="w.type !== 'keyword'">
                <div class="monitor-block">
                  <div class="monitor-head">
                    <label class="monitor-label">💹 价格监控<span class="monitor-sub">（{{ enabledCount(w) }}/{{ PRICE_TYPES.length }} 项）</span></label>
                    <div class="toggle-switch small">
                      <input type="checkbox" v-model="w.price_monitor" :id="'pm-'+w.id">
                      <label :for="'pm-'+w.id"></label>
                    </div>
                  </div>
                  <details v-if="w.price_monitor && w.price_alerts" class="price-details">
                    <summary>价格预警细项设置</summary>
                    <div class="price-grid">
                      <div v-for="t in PRICE_TYPES" :key="t.key" class="price-cell">
                        <label class="price-cell-label">
                          <input type="checkbox" v-model="w.price_alerts[t.key].enabled"> {{ t.label }}
                        </label>
                        <span v-for="f in t.fields" :key="f.k" class="price-field">
                          {{ f.label }}<input type="number" step="0.1" v-model.number="w.price_alerts[t.key][f.k]" class="price-num">
                        </span>
                      </div>
                    </div>
                  </details>
                </div>
                <div class="monitor-block">
                  <div class="monitor-head">
                    <label class="monitor-label">📰 新闻监控<span class="monitor-sub">（命中关键词即提醒）</span></label>
                    <div class="toggle-switch small">
                      <input type="checkbox" v-model="w.news_alerts.enabled" :id="'na-'+w.id" @change="onNewsToggle(w)">
                      <label :for="'na-'+w.id"></label>
                    </div>
                  </div>
                  <div v-if="w.news_alerts.enabled" class="kw-row">
                    <span v-for="(kw, idx) in (w.news_alerts.keywords||[])" :key="idx" class="kw-chip">
                      {{ kw }}<span class="kw-x" @click="removeKeyword(w, idx)">×</span>
                    </span>
                    <input type="text" v-model="w._newKeyword" class="kw-input" placeholder="加关键词…" @keyup.enter="addKeyword(w)">
                    <button @click="addKeyword(w)" class="btn-add kw-add">+</button>
                  </div>
                </div>
              </template>

              <!-- 关键词类型：纯新闻 -->
              <div v-else class="monitor-sub-text">📰 新闻关键词监控（无价格监控）</div>
            </div>

            <div v-if="selectedIds.length" class="batch-bar">
              <span>已选 {{ selectedIds.length }} 项:</span>
              <button @click="batchToggle('limit_up', true)" class="btn-add">开启涨停</button>
              <button @click="batchToggle('limit_up', false)" class="btn-remove">关闭涨停</button>
              <button @click="batchToggle('cum_move', true)" class="btn-add">开启累计涨跌</button>
              <button @click="selectedIds = []" class="btn-remove">取消选择</button>
            </div>
          </div>

          <div class="form-actions">
            <button @click="saveStockConfig" class="btn-primary">保存配置</button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'prompt'" class="config-section">
        <h2>💬 AI提示词配置</h2>
        <div class="config-form">
          <div class="form-group">
            <label>系统提示词</label>
            <textarea 
              v-model="aiPrompt" 
              rows="20"
              placeholder="AI分析新闻时使用的系统提示词..."
            ></textarea>
            <span class="hint">该提示词用于指导AI如何分析新闻</span>
          </div>

          <div class="form-actions">
            <button @click="savePromptConfig" class="btn-primary">保存配置</button>
            <button @click="resetPrompt" class="btn-secondary">恢复默认</button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'daily-prompt'" class="config-section">
        <h2>📊 首页AI分析提示词配置</h2>
        <div class="config-form">
          <div class="form-group">
            <label>首页AI分析提示词</label>
            <textarea 
              v-model="aiDailyPrompt" 
              rows="20"
              placeholder="AI分析全天走势时使用的系统提示词..."
            ></textarea>
            <span class="hint">该提示词用于指导AI如何分析首页的全天资金流向走势数据</span>
          </div>

          <div class="form-actions">
            <button @click="saveDailyPromptConfig" class="btn-primary">保存配置</button>
            <button @click="resetDailyPrompt" class="btn-secondary">恢复默认</button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'security'" class="config-section">
        <h2>🛡️ IP黑名单管理</h2>
        <div class="config-form">
          <div class="banned-header">
            <span class="banned-count">当前封禁IP: {{ bannedIPs.length }} 个</span>
            <button @click="loadBannedIPs" class="btn-refresh"><IconRefresh />刷新</button>
          </div>
          
          <div v-if="bannedIPs.length === 0" class="empty-banned">
            <p>暂无封禁IP</p>
          </div>
          
          <div v-else class="banned-list">
            <div 
              v-for="item in bannedIPs" 
              :key="item.ip"
              class="banned-item"
            >
              <div class="banned-info">
                <div class="banned-ip">{{ item.ip }}</div>
                <div class="banned-details">
                  <span class="banned-type">{{ getAttackTypeName(item.attack_type) }}</span>
                  <span class="banned-time">剩余: {{ formatBanTime(item.remaining_seconds) }}</span>
                  <span class="banned-attempts">尝试次数: {{ item.attempt_count || '-' }}</span>
                </div>
                <div class="banned-timestamp">封禁时间: {{ item.ban_time || '-' }}</div>
              </div>
              <div class="banned-actions">
                <button @click="handleUnbanIP(item.ip)" class="btn-unban">解封</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'anomaly'" class="config-section">
        <h2>🚨 资金异动检测</h2>
        <div class="config-form">
          <div class="form-group">
            <label>启用实时异动推送</label>
            <div class="toggle-switch">
              <input type="checkbox" v-model="anomalyConfig.enabled" id="anomaly-enabled">
              <label for="anomaly-enabled"></label>
            </div>
            <span class="hint">交易时段每5分钟采集后自动检测命中并推送（飞书/企业微信）</span>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>巨量 z-score 阈值</label>
              <input type="number" v-model.number="anomalyConfig.z_threshold" min="1" max="5" step="0.1">
              <span class="hint">默认2.0≈历史前5%，越大越严格</span>
            </div>
            <div class="form-group">
              <label>基线最小样本</label>
              <input type="number" v-model.number="anomalyConfig.min_samples" min="3" max="50">
              <span class="hint">不足则降级为绝对阈值</span>
            </div>
            <div class="form-group">
              <label>绝对量级阈值(亿)</label>
              <input type="number" v-model.number="anomalyConfig.abs_threshold" min="1" step="1">
              <span class="hint">样本不足时按此判定巨量</span>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>背离涨跌幅门槛</label>
              <input type="number" v-model.number="anomalyConfig.divergence_change" min="0.001" max="0.05" step="0.001">
              <span class="hint">5分钟价量背离门槛，0.002=0.2%</span>
            </div>
            <div class="form-group">
              <label>突变 Δnet(亿)</label>
              <input type="number" v-model.number="anomalyConfig.spike_threshold" min="1" step="1">
              <span class="hint">相邻时点净流入变化超此值</span>
            </div>
            <div class="form-group">
              <label>连续同向时点</label>
              <input type="number" v-model.number="anomalyConfig.streak_min" min="2" max="10">
              <span class="hint">4=约20分钟持续流入/流出</span>
            </div>
          </div>

          <div class="form-row">
            <div class="form-group">
              <label>去重冷却(分钟)</label>
              <input type="number" v-model.number="anomalyConfig.cooldown_minutes" min="5" max="120">
              <span class="hint">同板块同类型重复推送间隔</span>
            </div>
            <div class="form-group">
              <label>基线扫描天数</label>
              <input type="number" v-model.number="anomalyConfig.baseline_days" min="5" max="30">
              <span class="hint">重建基线时扫描的历史天数</span>
            </div>
          </div>

          <div class="form-group">
            <label>基线状态</label>
            <span class="hint">
              覆盖 <b>{{ anomalyBaseline.sector_count }}</b> 个板块 ·
              {{ anomalyBaseline.baseline_days }} 天历史 ·
              构建于 {{ anomalyBaseline.built_at ? anomalyBaseline.built_at.slice(0,19) : '—' }}
            </span>
          </div>

          <div class="form-actions">
            <button @click="saveAnomalyConfigCfg" class="btn-primary" :disabled="anomalySaving">
              {{ anomalySaving ? '保存中...' : '保存配置' }}
            </button>
            <button @click="rebuildAnomalyBaselineCfg" class="btn-secondary" :disabled="anomalyRebuilding">
              {{ anomalyRebuilding ? '重建中...' : '🔁 重建基线' }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'notify'" class="config-section">
        <h2>🔔 桌面通知（全局唯一设置）</h2>
        <div class="config-form">
          <div class="form-group">
            <label>开启桌面通知</label>
            <div class="toggle-switch">
              <input type="checkbox" v-model="notifyEnabled" @change="onToggleNotify" id="notify-enabled">
              <label for="notify-enabled"></label>
            </div>
            <span class="hint">新闻与资金异动到达时弹桌面提醒，<b>任意页面都生效</b>（由全局通知服务统一触发，与当前所在页面无关）。</span>
          </div>

          <div class="form-group">
            <label>浏览器权限状态</label>
            <span class="hint">
              当前：<b>{{ notifyPermissionLabel() }}</b> ·
              <a href="javascript:void(0)" @click="requestNotifyPermission" style="color:#4fc3f7;">重新授权</a>
            </span>
          </div>

          <div class="form-group">
            <label>提醒方式</label>
            <select v-model="notifySoundMode" @change="onNotifySoundChange">
              <option value="all">全部提醒（含音效）</option>
              <option value="important">仅重要（含音效）</option>
              <option value="none">静音（只弹窗不响）</option>
            </select>
            <span class="hint">控制是否播放提示音，不影响是否弹窗。仅作用于“新闻”类通知；资金异动默认带音效。</span>
          </div>

          <div class="form-actions">
            <button @click="testNotify" class="btn-secondary">🔔 发送测试通知</button>
          </div>
        </div>
      </div>
    </div>

    <div class="password-modal" v-if="passwordModal.show" @click.self="closePasswordModal">
      <div class="password-modal-content">
        <div class="password-modal-header">
          <h3>🔐 密码验证</h3>
        </div>
        <div class="password-modal-body">
          <p>请输入密码以保存配置</p>
          <input 
            type="password" 
            v-model="passwordModal.password" 
            placeholder="请输入密码"
            @keyup.enter="confirmPassword"
            class="password-input"
          >
        </div>
        <div class="password-modal-footer">
          <button @click="closePasswordModal" class="btn-cancel">取消</button>
          <button @click="confirmPassword" class="btn-confirm">确认</button>
        </div>
      </div>
    </div>

    <div class="toast" v-if="toast.show" :class="toast.type">
      {{ toast.message }}
    </div>

    <SecurityAlert />
  </div>
</template>

<script src="./components/ConfigPage/ConfigPage.script.js"></script>
<style src="./components/ConfigPage/ConfigPage.style.css" scoped></style>
