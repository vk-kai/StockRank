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

          <div class="form-actions">
            <button @click="saveFeishuConfig" class="btn-primary">保存配置</button>
            <button @click="testFeishuConfig" class="btn-secondary">测试推送</button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'stock'" class="config-section">
        <h2>📈 股票监控配置</h2>
        <div class="config-form">
          <div class="form-group">
            <label>启用股票监控</label>
            <div class="toggle-switch">
              <input type="checkbox" v-model="stockConfig.enabled" id="stock-enabled">
              <label for="stock-enabled"></label>
            </div>
          </div>

          <div class="stock-list">
            <div class="stock-header">
              <h3>监控股票列表</h3>
              <button @click="addStock" class="btn-add">+ 添加股票</button>
            </div>

            <div 
              v-for="(stock, index) in stockConfig.stocks" 
              :key="index"
              class="stock-item"
            >
              <div class="stock-info">
                <input 
                  type="text" 
                  v-model="stock.name" 
                  placeholder="股票名称"
                  class="stock-name-input"
                >
                <input 
                  type="text" 
                  v-model="stock.code" 
                  placeholder="股票代码"
                  class="stock-code-input"
                >
              </div>
              <div class="stock-keywords">
                <input 
                  type="text" 
                  v-model="stock.keywordsString" 
                  placeholder="关键词(用逗号分隔)"
                  class="stock-keywords-input"
                  @change="updateKeywords(index)"
                >
              </div>
              <div class="stock-actions">
                <div class="toggle-switch small">
                  <input 
                    type="checkbox" 
                    v-model="stock.enabled" 
                    :id="`stock-enabled-${index}`"
                  >
                  <label :for="`stock-enabled-${index}`"></label>
                </div>
                <button @click="removeStock(index)" class="btn-remove">删除</button>
              </div>
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
            <button @click="loadBannedIPs" class="btn-refresh">🔄 刷新</button>
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
