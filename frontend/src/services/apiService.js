/**
 * API服务封装
 */
import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 10000,
  withCredentials: true
})

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const response = error.response?.data
    
    if (response && response.error === 'auth_required') {
      const event = new CustomEvent('auth-required', {
        detail: { error, response }
      })
      window.dispatchEvent(event)
    } else if (response && (response.error === 'security_violation' || response.error === 'access_denied')) {
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
 * 获取全球主要股市指数
 */
export async function getGlobalIndices() {
  try {
    const response = await apiClient.get('/flow/global-indices')
    return response.data
  } catch (error) {
    console.error('获取全球指数失败:', error)
    throw error
  }
}

/**
 * 获取AI产业链外部环境温度计（7个领先指标 + 综合环境灯）
 */
export async function getAiChain() {
  try {
    const response = await apiClient.get('/flow/ai-chain')
    return response.data
  } catch (error) {
    console.error('获取AI产业链指标失败:', error)
    throw error
  }
}

/**
 * 获取大盘云图行业板块列表
 */
export async function getMarketMap() {
  try {
    const response = await apiClient.get('/flow/market-map')
    return response.data
  } catch (error) {
    console.error('获取大盘云图失败', error)
    throw error
  }
}

/**
 * 获取大盘云图首屏骨架（只读行业+市值缓存，涨跌幅全0%，秒开）
 */
export async function getMarketMapStructure() {
  try {
    const response = await apiClient.get('/flow/market-map-structure')
    return response.data
  } catch (error) {
    console.error('获取大盘云图骨架失败', error)
    throw error
  }
}

/**
 * 刷新大盘云图行业+市值缓存（低频，手动触发）
 */
export async function refreshMarketMapCache() {
  try {
    const response = await apiClient.post('/flow/market-map-refresh-cache')
    return response.data
  } catch (error) {
    console.error('刷新大盘云图缓存失败:', error)
    throw error
  }
}

/**
 * 获取板块下的个股（云图下钻）
 */
export async function getMarketMapStocks(sectorCode) {
  try {
    const response = await apiClient.get('/flow/market-map-stocks', {
      params: { sector: sectorCode }
    })
    return response.data
  } catch (error) {
    console.error('获取板块个股失败:', error)
    throw error
  }
}

/**
 * 获取个股近期融资净买入额时间序列（云图单击弹窗柱状图用）
 * 返回 { success, data:{ name, latest_date, latest_balance, latest_balance_date, series:[{d,j,b}] }, updating }
 * updating=true 表示后端正按需更新（每天一次），前端应提示并稍后重试
 */
export async function getStockFinancing(code) {
  try {
    const response = await apiClient.get('/flow/stock-financing', {
      params: { code }
    })
    return response.data
  } catch (error) {
    console.error('获取个股融资数据失败:', error)
    throw error
  }
}

/**
 * 大盘云图复盘：获取今天 10 个半小时整点的抓取状态（时间按钮亮/灰用）
 * 返回 { success, date, points:[{time, available}] }
 */
export async function getMarketMapSnapshots() {
  try {
    const response = await apiClient.get('/flow/market-map-snapshots')
    return response.data
  } catch (error) {
    console.error('获取大盘云图复盘快照状态失败:', error)
    throw error
  }
}

/**
 * 获取大盘云图复盘：获取某时间点(如 '10:00')的完整快照，data 结构同 getMarketMap
 */
export async function getMarketMapSnapshot(time) {
  try {
    const response = await apiClient.get('/flow/market-map-snapshot', { params: { time } })
    return response.data
  } catch (error) {
    console.error('获取大盘云图复盘快照失败:', error)
    throw error
  }
}

/**
 * 大盘云图融资净流入着色：全市场每只标的最新一日融资净买入额(Δ融资余额)。
 * 返回 { success, latest_date, map:{裸6位code: 净流入额} }。失败返回 { success:false }。
 */
export async function getMarketMapMargin() {
  try {
    const response = await apiClient.get('/flow/market-map-margin')
    return response.data
  } catch (error) {
    console.error('获取大盘云图融资净流入失败:', error)
    return { success: false }
  }
}

/**
 * 大盘云图 AI 打分着色：返回 { success, run_id, scored_at, count, map:{裸6位code:{score,label,reason}}, buckets }。
 * 只读已评分缓存，不触发打分。无打分数据时 count=0、map={}。
 */
export async function getStockScores() {
  try {
    const response = await apiClient.get('/flow/stock-scores')
    return response.data
  } catch (error) {
    console.error('获取股票打分失败:', error)
    return { success: false, count: 0, map: {} }
  }
}

/** 启动一轮 AI 批量打分（异步后台）。body { only_failed?:bool } 只补跑未评分项。
 *  返回 { success, status:'running', run_id, message, estimate:{total,batches,...} }。 */
export async function startStockScoring(onlyFailed = false) {
  try {
    const response = await apiClient.post('/flow/stock-scores/start', { only_failed: onlyFailed })
    return response.data
  } catch (error) {
    console.error('启动股票打分失败:', error)
    throw error
  }
}

/** 查询打分进度：{ success, status: idle|running|completed|failed|interrupted, progress, step, total, done, failed, ... } */
export async function getStockScoringStatus() {
  try {
    const response = await apiClient.get('/flow/stock-scores/status')
    return response.data
  } catch (error) {
    console.error('查询股票打分状态失败:', error)
    return { success: false, status: 'idle' }
  }
}

/** 协作式停止打分：当前批次完成后退出，已评分结果保留。 */
export async function stopStockScoring() {
  try {
    const response = await apiClient.post('/flow/stock-scores/stop')
    return response.data
  } catch (error) {
    console.error('停止股票打分失败:', error)
    throw error
  }
}

export async function getStockScorePrompt() {
  try {
    const response = await apiClient.get('/config/stock-score-prompt')
    return response.data
  } catch (error) {
    console.error('获取股票打分提示词失败:', error)
    throw error
  }
}

export async function saveStockScorePrompt(prompt, password) {
  try {
    const response = await apiClient.post('/config/stock-score-prompt', { prompt, password })
    return response.data
  } catch (error) {
    console.error('保存股票打分提示词失败:', error)
    throw error
  }
}

export async function getMarketMapPush() {
  try {
    const response = await apiClient.get('/flow/market-map-push')
    return response.data
  } catch (error) {
    console.error('获取大盘云图推送股票失败:', error)
    throw error
  }
}

export async function clearMarketMapPush() {
  try {
    const response = await apiClient.delete('/flow/market-map-push')
    return response.data
  } catch (error) {
    console.error('清空大盘云图推送股票失败:', error)
    throw error
  }
}

export async function login(username, password) {
  const response = await apiClient.post('/auth/login', { username, password })
  return response.data
}

export async function logout() {
  const response = await apiClient.post('/auth/logout')
  return response.data
}

export async function getAuthSession() {
  const response = await apiClient.get('/auth/session')
  return response.data
}

export async function getStockHoverSummary(code, sector, name, sectorName) {
  try {
    const response = await apiClient.get('/flow/stock-hover-summary', {
      params: { code, sector, name, sector_name: sectorName }
    })
    return response.data
  } catch (error) {
    console.error('获取个股 hover 摘要失败:', error)
    throw error
  }
}

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
 * 获取指定日期的分钟级资金流入数据
 * @param {string} dateStr - 日期字符串，格式：YYYY-MM-DD
 * @returns {Promise<Object>} 分钟数据
 */
export async function getMinuteDataByDate(dateStr) {
  try {
    const response = await apiClient.get('/flow/minute-by-date', {
      params: { date: dateStr }
    })
    return response.data
  } catch (error) {
    console.error('获取指定日期分钟数据失败:', error)
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
 * 获取首页大盘摘要数据
 * @returns {Promise<Object>} 大盘摘要数据
 */
export async function getMarketSummary() {
  try {
    const response = await apiClient.get('/flow/market-summary')
    return response.data
  } catch (error) {
    console.error('获取大盘摘要失败:', error)
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
export async function getNews(page = 1, pageSize = 40, importance = null, timeRange = null) {
  try {
    const params = { page: page, page_size: pageSize }
    if (importance) {
      params.importance = importance
    }
    if (timeRange && timeRange.start != null) {
      params.start_time = timeRange.start
    }
    if (timeRange && timeRange.end != null) {
      params.end_time = timeRange.end
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

export async function testAIConnection(config = {}) {
  try {
    const response = await apiClient.post('/config/ai/test', config, {
      timeout: 60000
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

export async function getWechatConfig() {
  try {
    const response = await apiClient.get('/config/wechat')
    return response.data
  } catch (error) {
    console.error('获取企业微信配置失败:', error)
    throw error
  }
}

export async function saveWechatConfig(config) {
  try {
    const response = await apiClient.post('/config/wechat', config)
    return response.data
  } catch (error) {
    console.error('保存企业微信配置失败:', error)
    throw error
  }
}

export async function testWechatConnection() {
  try {
    const response = await apiClient.post('/config/wechat/test', {})
    return response.data
  } catch (error) {
    console.error('测试企业微信连接失败:', error)
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

export async function searchStocks(keyword) {
  // 添加个股实时搜索:返回新浪 suggest 候选 [{name, code, board}]
  try {
    const response = await apiClient.get('/config/stock-search', { params: { kw: keyword } })
    return response.data
  } catch (error) {
    console.error('股票搜索失败:', error)
    return { success: false, data: [] }
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

export async function getHealth(triggerCheck = false) {
  try {
    const config = { timeout: 10000 }
    const response = triggerCheck 
      ? await axios.post('/health', null, config) 
      : await axios.get('/health', config)
    return response.data
  } catch (error) {
    console.error('获取健康状态失败:', error)
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

export const unbanIP = async (ip, password) => {
  try {
    const response = await apiClient.post('/jarvis/unban', { ip, password })
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
      params: { url: sectorUrl },
      timeout: 20000
    })
    return response.data
  } catch (error) {
    console.error('获取个股详情失败:', error)
    throw error
  }
}

export async function getHouseKline(id = 'house', period = 'monthly') {
  try {
    const response = await apiClient.get('/house/kline', { params: { id, period } })
    return response.data
  } catch (error) {
    console.error('获取K线数据失败:', error)
    throw error
  }
}

export async function getHouseDatasets() {
  try {
    const response = await apiClient.get('/house/datasets')
    return response.data
  } catch (error) {
    console.error('获取K线数据集列表失败:', error)
    throw error
  }
}

export async function saveHouseDataset(payload) {
  try {
    const response = await apiClient.post('/house/datasets', payload)
    return response.data
  } catch (error) {
    console.error('保存K线数据集失败:', error)
    throw error
  }
}

export async function deleteHouseDataset(id) {
  try {
    const response = await apiClient.delete(`/house/datasets/${id}`)
    return response.data
  } catch (error) {
    console.error('删除K线数据集失败:', error)
    throw error
  }
}

export async function getAIDailyPrompt() {
  try {
    const response = await apiClient.get('/config/daily-prompt')
    return response.data
  } catch (error) {
    console.error('获取首页AI分析提示词失败:', error)
    throw error
  }
}

export async function saveAIDailyPrompt(prompt, password) {
  try {
    const response = await apiClient.post('/config/daily-prompt', { prompt, password })
    return response.data
  } catch (error) {
    console.error('保存首页AI分析提示词失败:', error)
    throw error
  }
}

export async function startAnalyzeDailyFlow() {
  try {
    const response = await apiClient.post('/flow/analyze-daily/start')
    return response.data
  } catch (error) {
    console.error('启动AI分析失败:', error)
    throw error
  }
}

export async function getAnalyzeDailyFlowStatus() {
  try {
    const response = await apiClient.get('/flow/analyze-daily/status')
    return response.data
  } catch (error) {
    console.error('查询AI分析状态失败:', error)
    throw error
  }
}

export async function analyzeNews(title, content, newsId) {
  try {
    const response = await apiClient.post('/flow/analyze-news', { title, content, id: newsId }, { timeout: 120000 })
    return response.data
  } catch (error) {
    console.error('新闻AI分析失败:', error)
    throw error
  }
}

/**
 * 获取新闻AI评分统计（每天的利好/利空/中性数量）
 * @returns {Promise<Object>} 评分统计数据
 */
export async function getNewsScoreSummary() {
  try {
    const response = await apiClient.get('/news/score-summary')
    return response.data
  } catch (error) {
    console.error('获取新闻评分统计失败:', error)
    throw error
  }
}

/**
 * 获取今日按小时分组的利好利空趋势数据
 * @returns {Promise<Object>} 趋势数据
 */
export async function getNewsScoreTrend() {
  try {
    const response = await apiClient.get('/news/score-trend')
    return response.data
  } catch (error) {
    console.error('获取评分趋势数据失败:', error)
    throw error
  }
}

// ============================================================
// 资金异动预警
// ============================================================
/** 有数据的交易日列表（异动预警等页面用） */
export async function getFlowDates() {
  try {
    const response = await apiClient.get('/flow/dates')
    return response.data
  } catch (error) {
    console.error('获取交易日列表失败:', error)
    throw error
  }
}
/** 异动检测手动试跑（不入库、不推送）。time 省略则全天 */
export async function runAnomalyDetection(date, time) {
  try {
    const params = {}
    if (date) params.date = date
    if (time) params.time = time
    const response = await apiClient.get('/flow/anomaly/run', { params, timeout: 30000 })
    return response.data
  } catch (error) {
    console.error('异动检测试跑失败:', error)
    throw error
  }
}

/** 已推送的异动记录 */
export async function getAnomalyAlerts(date) {
  try {
    const response = await apiClient.get('/flow/anomaly/alerts', { params: { date } })
    return response.data
  } catch (error) {
    console.error('获取异动记录失败:', error)
    throw error
  }
}

/** 自选股价格异动当日命中 */
export async function runStockPriceAnomaly(date) {
  try {
    const params = {}
    if (date) params.date = date
    const response = await apiClient.get('/flow/stock-price/run', { params })
    return response.data
  } catch (error) {
    console.error('查询价格异动失败:', error)
    throw error
  }
}

/** 价格异动已推送记录 */
export async function getStockPriceAlerts(date) {
  try {
    const response = await apiClient.get('/flow/stock-price/alerts', { params: { date } })
    return response.data
  } catch (error) {
    console.error('获取价格异动记录失败:', error)
    throw error
  }
}

export async function getAnomalyConfig() {
  try {
    const response = await apiClient.get('/flow/anomaly/config')
    return response.data
  } catch (error) {
    console.error('获取异动配置失败:', error)
    throw error
  }
}

export async function saveAnomalyConfig(config) {
  try {
    const response = await apiClient.post('/flow/anomaly/config', config)
    return response.data
  } catch (error) {
    console.error('保存异动配置失败:', error)
    throw error
  }
}

export async function getAnomalyBaseline() {
  try {
    const response = await apiClient.get('/flow/anomaly/baseline')
    return response.data
  } catch (error) {
    console.error('获取异动基线失败:', error)
    throw error
  }
}

export async function rebuildAnomalyBaseline(days) {
  try {
    const params = {}
    if (days) params.days = days
    const response = await apiClient.post('/flow/anomaly/baseline/rebuild', null, { params, timeout: 30000 })
    return response.data
  } catch (error) {
    console.error('重建异动基线失败:', error)
    throw error
  }
}

// ============================================================
// 数据源配置
// ============================================================
export async function getDatasourceConfig() {
  try {
    const response = await apiClient.get('/config/datasource')
    return response.data
  } catch (error) {
    console.error('获取数据源配置失败:', error)
    throw error
  }
}

export async function saveDatasourceConfig(sources, password) {
  try {
    const response = await apiClient.post('/config/datasource', { sources, password })
    return response.data
  } catch (error) {
    console.error('保存数据源配置失败:', error)
    throw error
  }
}

export async function testDatasource() {
  try {
    const response = await apiClient.post('/config/datasource/test', null, { timeout: 60000 })
    return response.data
  } catch (error) {
    console.error('测试数据源失败:', error)
    throw error
  }
}

export async function testPushNotification() {
  try {
    const response = await apiClient.post('/config/push/test')
    return response.data
  } catch (error) {
    console.error('测试推送失败:', error)
    throw error
  }
}

// ============================================================
// 行业见顶周期分析
// ============================================================
/** 发起行业见顶周期分析（异步AI）。body { industry: 'AI/新能源/医药...' } */
export async function startIndustryCycle(industry) {
  try {
    const response = await apiClient.post('/flow/industry-cycle/start', { industry })
    return response.data
  } catch (error) {
    console.error('发起行业周期分析失败:', error)
    throw error
  }
}

/** 查询行业周期分析状态（含结果） */
export async function getIndustryCycleStatus() {
  try {
    const response = await apiClient.get('/flow/industry-cycle/status')
    return response.data
  } catch (error) {
    console.error('查询行业周期分析状态失败:', error)
    throw error
  }
}

/** 获取最近一次行业周期分析结果 */
export async function getIndustryCycleResult() {
  try {
    const response = await apiClient.get('/flow/industry-cycle/result')
    return response.data
  } catch (error) {
    console.error('获取行业周期分析结果失败:', error)
    throw error
  }
}

// ============================================================
// 行业见顶周期批量诊断（大盘云图）
// ============================================================
/** 发起批量行业周期诊断。body { industries: ['消费电子', '半导体', ...] } */
export async function startIndustryCycleBatch(industries) {
  try {
    const response = await apiClient.post('/flow/industry-cycle/batch-start', { industries })
    return response.data
  } catch (error) {
    console.error('发起批量行业周期诊断失败:', error)
    throw error
  }
}

/** 查询批量行业周期诊断状态 */
export async function getIndustryCycleBatchStatus() {
  try {
    const response = await apiClient.get('/flow/industry-cycle/batch-status')
    return response.data
  } catch (error) {
    console.error('查询批量行业周期诊断状态失败:', error)
    throw error
  }
}

/** 停止批量行业周期诊断 */
export async function stopIndustryCycleBatch() {
  try {
    const response = await apiClient.post('/flow/industry-cycle/batch-stop')
    return response.data
  } catch (error) {
    console.error('停止批量行业周期诊断失败:', error)
    throw error
  }
}

/** 获取所有行业的周期诊断结果（供大盘云图着色） */
export async function getIndustryCycleAllScores() {
  try {
    const response = await apiClient.get('/flow/industry-cycle/all-scores')
    return response.data
  } catch (error) {
    console.error('获取行业周期诊断结果失败:', error)
    throw error
  }
}

/** 获取单个行业的周期诊断结果 */
export async function getIndustryCycleSingleScore(industry) {
  try {
    const response = await apiClient.get('/flow/industry-cycle/single-score', { params: { industry } })
    return response.data
  } catch (error) {
    console.error('获取单个行业周期诊断结果失败:', error)
    throw error
  }
}

/** 手动触发新闻热点总结 */
export async function startNewsSummary() {
  try {
    const response = await apiClient.post('/news/summary/start')
    return response.data
  } catch (error) {
    console.error('触发新闻总结失败:', error)
    throw error
  }
}

/** 查询新闻热点总结状态和结果 */
export async function getNewsSummaryStatus() {
  try {
    const response = await apiClient.get('/news/summary/status')
    return response.data
  } catch (error) {
    console.error('查询新闻总结状态失败:', error)
    throw error
  }
}
