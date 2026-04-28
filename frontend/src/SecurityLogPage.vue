<template>
  <div class="security-log-page">
    <div class="security-log-header">
      <h1>🔒 安全日志</h1>
      <button class="refresh-btn" @click="refreshLogs">
        🔄 刷新
      </button>
    </div>
    
    <div class="security-log-content">
      <div class="log-filters">
        <select v-model="filterType" @change="filterLogs">
          <option value="all">全部类型</option>
          <option value="attack_attempt">攻击尝试</option>
          <option value="ip_banned">IP封禁</option>
          <option value="ip_unbanned">IP解封</option>
        </select>
        
        <select v-model="filterAttackType" @change="filterLogs">
          <option value="all">全部攻击类型</option>
          <option value="sql_injection">SQL注入</option>
          <option value="xss">XSS</option>
          <option value="command_injection">命令注入</option>
          <option value="path_traversal">路径遍历</option>
          <option value="ldap_injection">LDAP注入</option>
          <option value="xxe">XXE</option>
          <option value="ssrf">SSRF</option>
        </select>
      </div>
      
      <div class="log-stats">
        <div class="stat-item">
          <span class="stat-label">总攻击尝试:</span>
          <span class="stat-value">{{ stats.totalAttempts }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">已封禁IP:</span>
          <span class="stat-value">{{ stats.bannedIps }}</span>
        </div>
        <div class="stat-item">
          <span class="stat-label">今日攻击:</span>
          <span class="stat-value">{{ stats.todayAttempts }}</span>
        </div>
      </div>
      
      <div class="log-list">
        <div v-for="(log, index) in filteredLogs" :key="index" class="log-item" :class="logClass(log.type)">
          <div class="log-header">
            <span class="log-type">{{ getLogTypeName(log.type) }}</span>
            <span class="log-time">{{ formatTime(log.timestamp) }}</span>
          </div>
          <div class="log-details">
            <div class="log-detail">
              <span class="detail-label">IP:</span>
              <span class="detail-value">{{ log.ip }}</span>
            </div>
            <div class="log-detail" v-if="log.attack_type">
              <span class="detail-label">攻击类型:</span>
              <span class="detail-value">{{ getAttackTypeName(log.attack_type) }}</span>
            </div>
            <div class="log-detail" v-if="log.details">
              <span class="detail-label">详情:</span>
              <span class="detail-value">{{ log.details.matched || log.details.reason || 'N/A' }}</span>
            </div>
          </div>
        </div>
        
        <div v-if="filteredLogs.length === 0" class="no-logs">
          📋 暂无安全日志
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, onMounted, computed } from 'vue'
import { fetchSecurityEvents } from './services/apiService'

export default {
  name: 'SecurityLogPage',
  setup() {
    const logs = ref([])
    const filterType = ref('all')
    const filterAttackType = ref('all')
    const stats = ref({
      totalAttempts: 0,
      bannedIps: 0,
      todayAttempts: 0
    })
    
    const attackTypeNames = {
      'sql_injection': 'SQL注入',
      'xss': 'XSS',
      'command_injection': '命令注入',
      'path_traversal': '路径遍历',
      'ldap_injection': 'LDAP注入',
      'xxe': 'XXE',
      'ssrf': 'SSRF',
      'unknown': '未知'
    }
    
    const logTypeNames = {
      'attack_attempt': '攻击尝试',
      'ip_banned': 'IP封禁',
      'ip_unbanned': 'IP解封',
      'ip_banned_manual': '手动封禁'
    }
    
    const getAttackTypeName = (type) => {
      return attackTypeNames[type] || type
    }
    
    const getLogTypeName = (type) => {
      return logTypeNames[type] || type
    }
    
    const logClass = (type) => {
      if (type === 'attack_attempt') return 'attack-attempt'
      if (type === 'ip_banned') return 'ip-banned'
      if (type === 'ip_unbanned') return 'ip-unbanned'
      return ''
    }
    
    const formatTime = (timestamp) => {
      const date = new Date(timestamp)
      return date.toLocaleString('zh-CN')
    }
    
    const filteredLogs = computed(() => {
      return logs.value.filter(log => {
        const matchesType = filterType.value === 'all' || log.type === filterType.value
        const matchesAttackType = filterAttackType.value === 'all' || log.attack_type === filterAttackType.value
        return matchesType && matchesAttackType
      })
    })
    
    const filterLogs = () => {
      // 过滤已在 computed 中处理
    }
    
    const refreshLogs = async () => {
      try {
        const response = await fetchSecurityEvents(100)
        if (response.success) {
          logs.value = response.data
          calculateStats()
        }
      } catch (error) {
        console.error('获取安全日志失败:', error)
      }
    }
    
    const calculateStats = () => {
      const today = new Date()
      today.setHours(0, 0, 0, 0)
      
      const totalAttempts = logs.value.filter(log => log.type === 'attack_attempt').length
      const bannedIps = logs.value.filter(log => log.type === 'ip_banned').length
      const todayAttempts = logs.value.filter(log => 
        log.type === 'attack_attempt' && new Date(log.timestamp) >= today
      ).length
      
      stats.value = {
        totalAttempts,
        bannedIps,
        todayAttempts
      }
    }
    
    onMounted(() => {
      refreshLogs()
      setInterval(refreshLogs, 60000)
    })
    
    return {
      logs,
      filterType,
      filterAttackType,
      stats,
      filteredLogs,
      getAttackTypeName,
      getLogTypeName,
      logClass,
      formatTime,
      filterLogs,
      refreshLogs
    }
  }
}
</script>

<style scoped>
.security-log-page {
  padding: 20px;
  background-color: #f5f5f5;
  min-height: 100vh;
}

.security-log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 2px solid #e0e0e0;
}

.security-log-header h1 {
  margin: 0;
  color: #333;
}

.refresh-btn {
  padding: 8px 16px;
  background-color: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.refresh-btn:hover {
  background-color: #45a049;
}

.security-log-content {
  background-color: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.log-filters {
  display: flex;
  gap: 20px;
  margin-bottom: 20px;
}

.log-filters select {
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.log-stats {
  display: flex;
  gap: 40px;
  margin-bottom: 20px;
  padding: 10px 0;
  border-bottom: 1px solid #eee;
}

.stat-item {
  display: flex;
  gap: 8px;
}

.stat-label {
  font-weight: 600;
  color: #666;
}

.stat-value {
  font-weight: 700;
  color: #333;
}

.log-list {
  max-height: 600px;
  overflow-y: auto;
  border: 1px solid #eee;
  border-radius: 4px;
}

.log-item {
  padding: 15px;
  border-bottom: 1px solid #eee;
  transition: background-color 0.2s;
}

.log-item:hover {
  background-color: #fafafa;
}

.log-item:last-child {
  border-bottom: none;
}

.log-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
}

.log-type {
  font-weight: 700;
  font-size: 16px;
}

.log-time {
  color: #999;
  font-size: 12px;
}

.log-details {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.log-detail {
  display: flex;
  gap: 8px;
}

.detail-label {
  color: #666;
  font-size: 14px;
}

.detail-value {
  font-weight: 600;
  color: #333;
}

.attack-attempt {
  border-left: 4px solid #ff9800;
}

.ip-banned {
  border-left: 4px solid #f44336;
}

.ip-unbanned {
  border-left: 4px solid #4CAF50;
}

.no-logs {
  text-align: center;
  padding: 40px;
  color: #999;
  font-size: 16px;
}
</style>