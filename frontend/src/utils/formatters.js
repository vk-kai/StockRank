/**
 * 格式化资金流入金额
 * @param {number} value - 资金流入金额（亿元）
 * @returns {string} 格式化后的金额
 */
export function formatFlow(value) {
  if (value === null || value === undefined) return '-'
  // 同花顺API返回的资金流入单位是亿元
  if (Math.abs(value) >= 1) {
    return value.toFixed(2) + ' 亿'
  } else {
    return (value * 10000).toFixed(2) + ' 万'
  }
}

/**
 * 格式化净流入金额（统一使用亿为单位）
 * @param {number} value - 净流入金额（亿元）
 * @returns {string} 格式化后的金额
 */
export function formatNetFlow(value) {
  if (value === null || value === undefined) return '-'
  // 统一使用亿为单位
  return value.toFixed(2) + ' 亿'
}

/**
 * 格式化涨跌幅
 * @param {number} value - 涨跌幅（小数）
 * @returns {string} 格式化后的涨跌幅
 */
export function formatChange(value) {
  if (value === null || value === undefined) return '-'
  const sign = value >= 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(2)}%`
}