/**
 * API服务封装
 */
import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 10000
})

/**
 * 获取当前板块资金流入数据
 * @returns {Promise<Object>} 资金流入数据
 */
export async function getCurrentFlow() {
  try {
    const response = await apiClient.get('/flow/current')
    return response.data
  } catch (error) {
    console.error('获取当前数据失败:', error)
    throw error
  }
}

/**
 * 获取历史资金流入数据
 * @param {number} days - 天数
 * @returns {Promise<Object>} 历史数据
 */
export async function getHistoryData(days) {
  try {
    const response = await apiClient.get('/flow/history', {
      params: { days: days }
    })
    return response.data
  } catch (error) {
    console.error('获取历史数据失败:', error)
    throw error
  }
}

/**
 * 获取分钟级资金流入数据
 * @param {number} hours - 小时数
 * @returns {Promise<Object>} 分钟数据
 */
export async function getMinuteData(hours) {
  try {
    const response = await apiClient.get('/flow/minute', {
      params: { hours: hours }
    })
    return response.data
  } catch (error) {
    console.error('获取分钟数据失败:', error)
    throw error
  }
}

/**
 * 获取最新资金流入数据
 * @returns {Promise<Object>} 最新数据
 */
export async function getLatestData() {
  try {
    const response = await apiClient.get('/flow/latest')
    return response.data
  } catch (error) {
    console.error('获取最新数据失败:', error)
    throw error
  }
}

/**
 * 获取新闻数据
 * @param {number} limit - 数量限制
 * @returns {Promise<Object>} 新闻数据
 */
export async function getNews(limit = 50) {
  try {
    const response = await apiClient.get('/news', {
      params: { limit: limit }
    })
    return response.data
  } catch (error) {
    console.error('获取新闻数据失败:', error)
    throw error
  }
}

export async function getAIConfig() {
  try {
    const response = await apiClient.get('/config/ai')
    return response.data
  } catch (error) {
    console.error('获取AI配置失败:', error)
    throw error
  }
}

export async function saveAIConfig(config) {
  try {
    const response = await apiClient.post('/config/ai', config)
    return response.data
  } catch (error) {
    console.error('保存AI配置失败:', error)
    throw error
  }
}

export async function testAIConnection() {
  try {
    const response = await apiClient.post('/config/ai/test', {})
    return response.data
  } catch (error) {
    console.error('测试AI连接失败:', error)
    throw error
  }
}

export async function getFeishuConfig() {
  try {
    const response = await apiClient.get('/config/feishu')
    return response.data
  } catch (error) {
    console.error('获取飞书配置失败:', error)
    throw error
  }
}

export async function saveFeishuConfig(config) {
  try {
    const response = await apiClient.post('/config/feishu', config)
    return response.data
  } catch (error) {
    console.error('保存飞书配置失败:', error)
    throw error
  }
}

export async function testFeishuConnection() {
  try {
    const response = await apiClient.post('/config/feishu/test', {})
    return response.data
  } catch (error) {
    console.error('测试飞书连接失败:', error)
    throw error
  }
}

export async function getStockMonitorConfig() {
  try {
    const response = await apiClient.get('/config/stock-monitor')
    return response.data
  } catch (error) {
    console.error('获取股票监控配置失败:', error)
    throw error
  }
}

export async function saveStockMonitorConfig(config) {
  try {
    const response = await apiClient.post('/config/stock-monitor', config)
    return response.data
  } catch (error) {
    console.error('保存股票监控配置失败:', error)
    throw error
  }
}

export async function getAIPrompt() {
  try {
    const response = await apiClient.get('/config/prompt')
    return response.data
  } catch (error) {
    console.error('获取AI提示词失败:', error)
    throw error
  }
}

export async function saveAIPrompt(prompt, password) {
  try {
    const response = await apiClient.post('/config/prompt', { prompt, password })
    return response.data
  } catch (error) {
    console.error('保存AI提示词失败:', error)
    throw error
  }
}

export async function getSystemHealth() {
  try {
    const response = await axios.get('/health')
    return response.data
  } catch (error) {
    console.error('获取系统健康状态失败:', error)
    throw error
  }
}

export async function getSSLStatus() {
  try {
    const response = await apiClient.get('/system/ssl-status')
    return response.data
  } catch (error) {
    console.error('获取SSL证书状态失败:', error)
    throw error
  }
}

export async function getLogList() {
  try {
    const response = await apiClient.get('/log/list')
    return response.data
  } catch (error) {
    console.error('获取日志列表失败:', error)
    throw error
  }
}

export async function getLogContent(logType, level = '', lines = 200, search = '') {
  try {
    const params = { lines }
    if (level) {
      params.level = level
    }
    if (search) {
      params.search = search
    }
    const response = await apiClient.get(`/log/content/${logType}`, { params })
    return response.data
  } catch (error) {
    console.error('获取日志内容失败:', error)
    throw error
  }
}

export async function getLogLevels() {
  try {
    const response = await apiClient.get('/log/levels')
    return response.data
  } catch (error) {
    console.error('获取日志级别失败:', error)
    throw error
  }
}