/**
 * API服务封装
 */
import axios from 'axios'

// 创建axios实例
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