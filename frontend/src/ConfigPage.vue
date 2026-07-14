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

      <div v-if="activeTab === 'feishu'" class="config-section">
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

      <div v-if="activeTab === 'wechat'" class="config-section">
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
            <div style="display:flex;gap:8px;margin-bottom:10px;">
              <button :class="['btn-add', newWatch.mode==='stock'?'':'btn-ghost']" @click="switchWatchMode('stock')">📈 添加个股</button>
              <button :class="['btn-add', newWatch.mode==='keyword'?'':'btn-ghost']" @click="switchWatchMode('keyword')">📰 添加新闻关键词</button>
            </div>

            <!-- 个股：实时搜索，只能从结果选 -->
            <div v-if="newWatch.mode==='stock'" class="stock-item" style="flex-direction:column;align-items:stretch;position:relative;">
              <div style="display:flex;gap:10px;align-items:center;width:100%;">
                <input type="text" v-model="newWatch.search"
                       placeholder="输入股票名字或代码搜索（如 长电科技 / 600584），只能从结果里点选"
                       style="flex:1;"
                       @input="onSearchInput"
                       @keydown="onSearchKeydown"
                       @focus="newWatch.showResults = true"
                       @blur="blurSearch">
                <span v-if="newWatch.searching" style="color:#8ba4c7;font-size:12px;white-space:nowrap;">搜索中…</span>
              </div>
              <div v-if="newWatch.showResults && (newWatch.results.length || (newWatch.search && !newWatch.searching))"
                   style="position:absolute;top:44px;left:0;right:0;max-height:260px;overflow-y:auto;background:#16263b;border:1px solid rgba(255,255,255,.12);border-radius:6px;z-index:50;box-shadow:0 6px 20px rgba(0,0,0,.4);">
                <div v-if="newWatch.search && !newWatch.results.length && !newWatch.searching" style="padding:10px 12px;color:#8ba4c7;font-size:13px;">无匹配结果</div>
                <div v-for="(r, idx) in newWatch.results" :key="r.code"
                     @mousedown.prevent="selectStock(r)"
                     :style="{padding:'8px 12px',cursor:'pointer',display:'flex',justifyContent:'space-between',alignItems:'center',background:newWatch.highlight===idx?'rgba(24,144,255,.25)':'transparent',color:'#cfe0f5',fontSize:'13px',borderBottom:'1px solid rgba(255,255,255,.05)'}">
                  <span>{{ r.name }}</span>
                  <span style="color:#6f8fb3;">{{ r.code }}</span>
                </div>
              </div>
            </div>

            <!-- 关键词：自由输入 -->
            <div v-else class="stock-item" style="align-items:center;">
              <input type="text" v-model="newWatch.keyword"
                     placeholder="新闻关键词（任意文本，不受搜索限制，如 纳斯达克中国金龙）"
                     style="flex:1;" @keyup.enter="addKeywordItem">
              <button @click="addKeywordItem" class="btn-add">＋ 添加关键词</button>
            </div>

            <div v-for="w in stockConfig.watchlist" :key="w.id" class="stock-item" style="flex-direction:column;align-items:stretch;">
              <div style="display:flex;gap:10px;align-items:center;width:100%;">
                <input type="checkbox" :value="w.id" v-model="selectedIds">
                <span :style="{padding:'2px 8px',borderRadius:'10px',fontSize:'12px',background:w.type==='keyword'?'rgba(250,140,22,.2)':'rgba(24,144,255,.2)',color:w.type==='keyword'?'#fa8c16':'#40a9ff'}">{{ w.type==='keyword' ? '关键词' : '个股' }}</span>
                <strong style="flex:1;">{{ w.value }}</strong>
                <span v-if="w.type!=='keyword' && w.resolved_code" style="color:#6f8fb3;font-size:12px;">{{ w.resolved_code }}</span>
                <div class="toggle-switch small">
                  <input type="checkbox" v-model="w.enabled" :id="'w-'+w.id">
                  <label :for="'w-'+w.id"></label>
                </div>
                <button @click="removeWatchItem(w.id)" class="btn-remove">删除</button>
              </div>

              <!-- 个股：价格监控 + 新闻监控 双区块 -->
              <template v-if="w.type !== 'keyword'">
                <div style="width:100%;margin-top:8px;border-top:1px dashed rgba(255,255,255,.08);padding-top:8px;">
                  <div style="display:flex;align-items:center;justify-content:space-between;">
                    <label style="font-size:13px;color:#a9bfd8;">
                      💹 价格监控
                      <span style="color:#6f8fb3;font-size:11px;">（{{ enabledCount(w) }}/{{ PRICE_TYPES.length }} 项细项）</span>
                    </label>
                    <div class="toggle-switch small">
                      <input type="checkbox" v-model="w.price_monitor" :id="'pm-'+w.id">
                      <label :for="'pm-'+w.id"></label>
                    </div>
                  </div>
                  <details v-if="w.price_monitor && w.price_alerts" style="margin-top:6px;">
                    <summary style="font-size:12px;color:#8ba4c7;cursor:pointer;">价格预警细项设置</summary>
                    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin-top:6px;">
                      <div v-for="t in PRICE_TYPES" :key="t.key" style="background:rgba(255,255,255,.04);padding:4px 8px;border-radius:4px;font-size:13px;">
                        <label style="display:flex;align-items:center;gap:4px;">
                          <input type="checkbox" v-model="w.price_alerts[t.key].enabled"> {{ t.label }}
                        </label>
                        <span v-for="f in t.fields" :key="f.k" style="margin-left:10px;font-size:12px;">
                          {{ f.label }}<input type="number" step="0.1" v-model.number="w.price_alerts[t.key][f.k]" style="width:56px;margin-left:4px;">
                        </span>
                      </div>
                    </div>
                  </details>
                </div>
                <div style="width:100%;margin-top:8px;border-top:1px dashed rgba(255,255,255,.08);padding-top:8px;">
                  <div style="display:flex;align-items:center;justify-content:space-between;">
                    <label style="font-size:13px;color:#a9bfd8;">📰 新闻监控（新闻命中关键词即提醒）</label>
                    <div class="toggle-switch small">
                      <input type="checkbox" v-model="w.news_alerts.enabled" :id="'na-'+w.id" @change="onNewsToggle(w)">
                      <label :for="'na-'+w.id"></label>
                    </div>
                  </div>
                  <div v-if="w.news_alerts.enabled" style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;">
                    <span v-for="(kw, idx) in (w.news_alerts.keywords||[])" :key="idx"
                          style="background:rgba(250,140,22,.18);color:#ffb066;padding:2px 8px;border-radius:10px;font-size:12px;display:inline-flex;align-items:center;gap:4px;">
                      {{ kw }}
                      <span @click="removeKeyword(w, idx)" style="cursor:pointer;opacity:.7;font-weight:bold;">×</span>
                    </span>
                    <input type="text" v-model="w._newKeyword" placeholder="加关键词…" style="width:120px;padding:3px 6px;font-size:12px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);color:#cfe0f5;border-radius:4px;" @keyup.enter="addKeyword(w)">
                    <button @click="addKeyword(w)" class="btn-add" style="padding:2px 10px;font-size:12px;">+</button>
                  </div>
                </div>
              </template>

              <!-- 关键词类型：纯新闻 -->
              <div v-else style="color:#8ba4c7;font-size:12px;margin-top:4px;">📰 新闻关键词监控（无价格监控）</div>
            </div>

            <div v-if="selectedIds.length" style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
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
