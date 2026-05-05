/**
 * API服务封装
 */
import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 10000
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const response = error.response?.data
    
    if (response && (response.error === 'security_violation' || response.error === 'access_denied')) {
      const event = new CustomEvent('security-error', {
        detail: { error, response }
      })
      window.dispatchEvent(event)
    } else if (!error.response) {
      console.error('网络错误或请求被拦截:', error.message)
    }
    
    return Promise.reject(error)
  }
)

export function isSecurityError(error) {
  return error.response && 
         error.response.data && 
         (error.response.data.error === 'security_violation' || error.response.data.error === 'access_denied')
}

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
 * 获取大盘概览数据
 * @returns {Promise<Object>} 大盘数据
 */
export async function getMarketData() {
  try {
    const response = await apiClient.get('/flow/market')
    return response.data
  } catch (error) {
    console.error('获取大盘数据失败:', error)
    throw error
  }
}

/**
 * 获取累计流入TOP板块
 * @param {number} days - 天数
 * @returns {Promise<Object>} 累计流入TOP板块数据
 */
export async function getAccumulatedFlow(days) {
  try {
    const response = await apiClient.get('/flow/accumulated', {
      params: { days: days }
    })
    return response.data
  } catch (error) {
    console.error('获取累计流入数据失败:', error)
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
 * @param {number} page - 页码
 * @param {number} pageSize - 每页数量
 * @param {string} importance - 重要性筛选 (可选，如 '3' 表示重要新闻)
 * @returns {Promise<Object>} 新闻数据
 */
export async function getNews(page = 1, pageSize = 40, importance = null) {
  try {
    const params = { page: page, page_size: pageSize }
    if (importance) {
      params.importance = importance
    }
    const response = await apiClient.get('/news', {
      params: params
    })
    return response.data
  } catch (error) {
    console.error('获取新闻数据失败:', error)
    throw error
  }
}

/**
 * 搜索新闻
 * @param {string} keyword - 搜索关键词
 * @param {number} page - 页码
 * @param {number} pageSize - 每页数量
 * @param {string} importance - 重要性筛选 (可选，如 '3' 表示重要新闻)
 * @returns {Promise<Object>} 搜索结果
 */
export async function searchNews(keyword, page = 1, pageSize = 40, importance = null) {
  try {
    const params = { keyword: keyword, page: page, page_size: pageSize }
    if (importance) {
      params.importance = importance
    }
    const response = await apiClient.get('/news/search', {
      params: params
    })
    return response.data
  } catch (error) {
    console.error('搜索新闻失败:', error)
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
    const response = await apiClient.post('/config/ai/test', {}, {
      timeout: 30000
    })
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

export async function getHealthStatus() {
  try {
    const response = await apiClient.get('/health/status')
    return response.data
  } catch (error) {
    console.error('获取健康状态失败:', error)
    throw error
  }
}

export async function triggerHealthCheck() {
  try {
    const response = await apiClient.post('/health/check')
    return response.data
  } catch (error) {
    console.error('触发健康检测失败:', error)
    throw error
  }
}

export async function getCrawlerStatus() {
  try {
    const response = await apiClient.get('/crawler/status')
    return response.data
  } catch (error) {
    console.error('获取爬虫状态失败:', error)
    throw error
  }
}

export async function resetCrawler(crawlerName) {
  try {
    const response = await apiClient.post('/crawler/reset', { crawler: crawlerName })
    return response.data
  } catch (error) {
    console.error('重置爬虫状态失败:', error)
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

export const fetchSecurityEvents = async (limit = 100) => {
  try {
    const response = await apiClient.get('/api/jarvis/events', {
      params: { limit }
    })
    return response.data
  } catch (error) {
    console.error('获取安全日志失败:', error)
    throw error
  }
}

export const getBannedIPs = async () => {
  try {
    const response = await apiClient.get('/jarvis/banned')
    return response.data
  } catch (error) {
    console.error('获取IP黑名单失败:', error)
    throw error
  }
}

export const unbanIP = async (ip) => {
  try {
    const response = await apiClient.post('/jarvis/unban', { ip })
    return response.data
  } catch (error) {
    console.error('解封IP失败:', error)
    throw error
  }
}

export async function getLogContent(logType, page = 1, pageSize = 100, level = '', search = '', module = '') {
  try {
    const params = { page, page_size: pageSize }
    if (level) {
      params.level = level
    }
    if (search) {
      params.search = search
    }
    if (module) {
      params.module = module
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

export async function getLogModules() {
  try {
    const response = await apiClient.get('/log/modules')
    return response.data
  } catch (error) {
    console.error('获取功能模块失败:', error)
    throw error
  }
}

export async function getDailyReport(date) {
  try {
    const response = await apiClient.get('/flow/daily-report', {
      params: { date: date }
    })
    return response.data
  } catch (error) {
    console.error('获取每日报表失败:', error)
    throw error
  }
}

export async function getSectorStocks(sectorUrl) {
  try {
    const response = await apiClient.get('/flow/sector-stocks', {
      params: { url: sectorUrl }
    })
    return response.data
  } catch (error) {
    console.error('获取个股详情失败:', error)
    throw error
  }
}

export async function getHouseKline() {
  try {
    const response = await apiClient.get('/house/kline')
    return response.data
  } catch (error) {
    console.error('获取房价K线数据失败:', error)
    throw error
  }
}