<template>
  <div class="log-page">
    <header class="log-header">
      <button @click="goBack" class="back-button">← 返回</button>
      <h1>📋 系统日志</h1>
      <div class="header-actions">
        <button @click="refreshLogs" class="refresh-button" :disabled="loading">
          {{ loading ? '刷新中...' : '🔄 刷新' }}
        </button>
      </div>
    </header>

    <div class="log-tabs">
      <button 
        v-for="log in logList" 
        :key="log.type"
        :class="['tab-button', { 'active': activeLog === log.type }]"
        @click="switchLog(log.type)"
      >
        {{ getLogIcon(log.type) }} {{ getLogName(log.type) }}
        <span v-if="log.size > 0" class="log-size">({{ formatSize(log.size) }})</span>
      </button>
    </div>

    <div class="log-controls">
      <div class="level-filter">
        <label>日志级别：</label>
        <select v-model="selectedLevel" @change="onFilterChange">
          <option value="">全部</option>
          <option v-for="level in logLevels" :key="level" :value="level">{{ level }}</option>
        </select>
      </div>
      <div class="module-filter" v-if="activeLog === 'data' || activeLog === 'system'">
        <label>功能模块：</label>
        <select v-model="selectedModule" @change="onFilterChange">
          <option value="">全部</option>
          <option v-for="(info, key) in logModules" :key="key" :value="key">{{ info.desc }}</option>
        </select>
      </div>
      <div class="search-box">
        <input 
          type="text" 
          v-model="searchKeyword" 
          placeholder="搜索日志内容..." 
          @keyup.enter="onSearch"
          class="search-input"
        >
        <button class="search-btn" @click="onSearch">🔍 搜索</button>
        <button v-if="searchKeyword" class="clear-btn" @click="clearSearch">✕ 清除</button>
      </div>
      <div class="lines-control">
        <label>每页行数：</label>
        <select v-model="pageSize" @change="onPageSizeChange">
          <option :value="50">50行</option>
          <option :value="100">100行</option>
          <option :value="200">200行</option>
          <option :value="500">500行</option>
        </select>
      </div>
      <div class="auto-refresh">
        <label>
          <input type="checkbox" v-model="autoRefresh">
          自动刷新 (5秒)
        </label>
      </div>
    </div>

    <div class="log-content">
      <div v-if="loading" class="loading">
        <div class="spinner"></div>
        <p>加载中...</p>
      </div>
      
      <div v-else-if="logLines.length === 0" class="empty">
        <p>暂无日志内容</p>
      </div>
      
      <div v-else class="log-lines">
        <div class="log-header-row">
          <span class="log-timestamp">时间</span>
          <span class="log-level-header">级别</span>
          <span class="log-module-header" v-if="activeLog === 'data' || activeLog === 'system'">模块</span>
          <span class="log-source">来源</span>
          <span class="log-message">消息</span>
          <span class="log-action">操作</span>
        </div>
        <div class="log-body">
          <div 
            v-for="(line, index) in logLines" 
            :key="index"
            :class="['log-line', getLevelClass(line.level)]"
          >
            <span class="log-timestamp">{{ line.timestamp }}</span>
            <span :class="['log-level', (line.level || '').toLowerCase()]">{{ line.level || '-' }}</span>
            <span class="log-module" v-if="activeLog === 'data' || activeLog === 'system'" :style="{ color: getModuleColor(line.module) }">{{ line.module_display || line.module || '-' }}</span>
            <span class="log-source">{{ line.source }}:{{ line.lineno }}</span>
            <span class="log-message" :title="line.message" v-html="highlightKeywords(truncateMessage(line.message))"></span>
            <span class="log-action">
              <button class="detail-btn" @click="showDetail(line)" title="查看详情">
                📋
              </button>
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="pagination" v-if="totalLines > 0">
      <div class="pagination-info">
        共 {{ totalLines }} 条，当前第 {{ currentPage }}/{{ totalPages }} 页
      </div>
      <div class="pagination-controls">
        <button 
          class="page-btn" 
          :disabled="currentPage <= 1" 
          @click="goToPage(1)"
        >首页</button>
        <button 
          class="page-btn" 
          :disabled="currentPage <= 1" 
          @click="goToPage(currentPage - 1)"
        >上一页</button>
        <div class="page-numbers">
          <button 
            v-for="page in visiblePages" 
            :key="page"
            :class="['page-num', { 'active': page === currentPage }]"
            @click="goToPage(page)"
          >{{ page }}</button>
        </div>
        <button 
          class="page-btn" 
          :disabled="currentPage >= totalPages" 
          @click="goToPage(currentPage + 1)"
        >下一页</button>
        <button 
          class="page-btn" 
          :disabled="currentPage >= totalPages" 
          @click="goToPage(totalPages)"
        >末页</button>
        <div class="goto-page">
          <span>跳转到</span>
          <input 
            type="number" 
            v-model.number="gotoPageNum" 
            :min="1" 
            :max="totalPages"
            @keyup.enter="jumpToPage"
          >
          <span>页</span>
          <button class="page-btn" @click="jumpToPage">GO</button>
        </div>
      </div>
    </div>

    <div class="modal-overlay" v-if="showModal" @click.self="closeModal">
      <div class="modal">
        <div class="modal-header">
          <h3>📋 日志详情</h3>
          <button class="modal-close" @click="closeModal">×</button>
        </div>
        <div class="modal-body" v-if="selectedLog">
          <div class="detail-row">
            <span class="detail-label">时间：</span>
            <span class="detail-value">{{ selectedLog.timestamp }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">级别：</span>
            <span :class="['detail-value', 'level-badge', (selectedLog.level || '').toLowerCase()]">{{ selectedLog.level || '-' }}</span>
          </div>
          <div class="detail-row" v-if="activeLog === 'data' || activeLog === 'system'">
            <span class="detail-label">模块：</span>
            <span class="detail-value" :style="{ color: getModuleColor(selectedLog.module) }">{{ selectedLog.module_display || selectedLog.module || '-' }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">来源：</span>
            <span class="detail-value">{{ selectedLog.source }}:{{ selectedLog.lineno }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">消息：</span>
            <pre class="detail-message">{{ selectedLog.message }}</pre>
          </div>
        </div>
        <div class="modal-footer">
          <button class="copy-btn" @click="copyToClipboard">📋 复制内容</button>
          <button class="close-btn" @click="closeModal">关闭</button>
        </div>
      </div>
    </div>

    <div class="toast" v-if="toast.show" :class="toast.type">
      {{ toast.message }}
    </div>
  </div>
</template>

<script src="./components/LogPage/LogPage.script.js"></script>
<style src="./components/LogPage/LogPage.style.css" scoped></style>
