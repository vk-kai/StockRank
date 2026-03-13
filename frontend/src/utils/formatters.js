/**
 * 格式化资金流入金额
 * @param {number} value - 资金流入金额（万元）
 * @returns {string} 格式化后的金额
 */
export function formatFlow(value) {
  if (value === null || value === undefined) return '-'
  // 东方财富API返回的资金流入单位是万元
  if (Math.abs(value) >= 10000) {
    return (value / 10000).toFixed(2) + ' 亿'
  } else {
    return value.toFixed(2) + ' 万'
  }
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