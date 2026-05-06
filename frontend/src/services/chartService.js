import { formatFlow } from '../utils/formatters'

export function generateChartOption(timeData, series, topSectors, oldSelected, colors, isToday) {
  const validSelected = {}
  const topSectorsSet = new Set(topSectors)
  for (const [name, selected] of Object.entries(oldSelected)) {
    if (topSectorsSet.has(name)) {
      validSelected[name] = selected
    }
  }

  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'cross'
      },
      backgroundColor: 'rgba(20,25,45,0.95)',
      borderColor: '#3a4a6b',
      borderWidth: 1,
      formatter: (params) => {
        let result = `<div style="font-weight:bold;margin-bottom:6px;color:#fff;">${params[0]?.name || ''}</div>`
        
        params.forEach(param => {
          if (!param.data || param.data === null) return
          
          const change = param.data.change
          const totalFlow = param.data.totalFlow
          const accumulatedChangePercent = param.data.accumulatedChangePercent
          const appearances = param.data.appearances

          let changeHtml = '-'
          if (change !== null && change !== undefined) {
            const color = change >= 0 ? '#ee6666' : '#91cc75'
            changeHtml = `<b style="color:${color}">${(change * 100).toFixed(2)}%</b>`
          }

          result += `
            <div style="display:flex;justify-content:space-between;gap:20px;margin:4px 0;">
              <span style="color:#8ba4a7;">
                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${param.color};margin-right:6px;"></span>
                ${param.seriesName}
              </span>
              <span style="color:#ee6666;font-weight:bold;">
                ${formatFlow(param.data.value)}
              </span>
              <span style="color:#8ba4a7;">
                ${changeHtml}
              </span>
            </div>
          `

          if (!isToday && totalFlow !== null && totalFlow !== undefined) {
            let accumulatedChangeHtml = '-'
            if (accumulatedChangePercent !== null && accumulatedChangePercent !== undefined) {
              const color = accumulatedChangePercent >= 0 ? '#ee6666' : '#91cc75'
              accumulatedChangeHtml = `<b style="color:${color}">${(accumulatedChangePercent * 100).toFixed(2)}%</b>`
            }

            let totalFlowHtml = '-'
            if (totalFlow !== null && totalFlow !== undefined) {
              totalFlowHtml = `<b style="color:#4fc3f7">${formatFlow(totalFlow)}</b>`
            }

            let appearancesHtml = appearances ? `<b>${appearances}</b>天` : '-'

            result += `
              <div style="border-top:1px dashed #3a4a6b;margin:6px 0;padding-top:6px;">
                <div style="color:#8ba4a7;">累计流入: ${totalFlowHtml}</div>
                <div style="color:#8ba4a7;">累计涨跌: ${accumulatedChangeHtml}</div>
                <div style="color:#8ba4a7;">出现天数: ${appearancesHtml}</div>
              </div>
            `
          }
        })
        
        return result
      }
    },
    legend: {
      data: topSectors,
      textStyle: {
        color: '#8ba4c7'
      },
      selectedMode: true,
      selected: topSectors.reduce((acc, name, index) => {
        acc[name] = validSelected[name] !== undefined ? validSelected[name] : (index < 5)
        return acc
      }, {})
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '15%',
      top: '15%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: timeData,
      axisLabel: {
        color: '#8ba4c7'
      }
    },
    yAxis: {
      type: 'value',
      name: '资金流入',
      axisLabel: {
        color: '#8ba4c7',
        formatter: (value) => {
          if (value >= 100000000) {
            return (value / 100000000).toFixed(1) + '亿'
          }
          if (value >= 10000) {
            return (value / 10000).toFixed(0) + '万'
          }
          return value
        }
      }
    },

    series: series
  }
}

export function generateSeries(topSectors, timeData, allData, colors, isToday) {
  return topSectors.map((sectorName, index) => {
    const data = timeData.map(timeKey => {
        const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
        const sectorItem = timeDataItem.find(item => item.name === sectorName)
        const flow = sectorItem?.flow || null
        const change = sectorItem?.change !== undefined && sectorItem?.change !== null ? sectorItem.change : 0

        if (isToday) {
          return {
            value: flow,
            change: change
          }
        }

        return {
          value: flow,
          change: change,
          totalFlow: sectorItem?.total_flow ?? 0,
          accumulatedChangePercent: sectorItem?.accumulated_change_percent ?? 0,
          appearances: sectorItem?.appearances ?? 0
        }
      })

    // 检查该板块是否在至少一个时间点有数据
    const hasValidData = data.some(d => d !== null)
    if (!hasValidData) {
      return null
    }

    return {
      name: sectorName,
      type: 'line',
      smooth: true,
      connectNulls: true,
      showSymbol: true,
      symbol: 'circle',
      symbolSize: 6,
      data: data,
      lineStyle: {
        width: 2,
        color: colors[index % colors.length]
      },
      itemStyle: {
        color: colors[index % colors.length]
      },
      emphasis: {
        focus: 'series',
        scale: 1.5,
        lineStyle: {
          width: 4,
          shadowBlur: 10,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        },
        itemStyle: {
          borderWidth: 3,
          borderColor: '#fff',
          shadowBlur: 10,
          shadowColor: 'rgba(0, 0, 0, 0.5)'
        }
      }
    }
  }).filter(series => series !== null)
}

/**
 * 从所有时间点数据中收集出现过的板块，并按出现频率和资金流入排序
 */
export function collectAllSectors(timeData, allData, isToday) {
  const sectorStats = new Map()
  
  // 收集所有时间点的板块数据
  timeData.forEach(timeKey => {
    const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
    timeDataItem.forEach((item, index) => {
      const name = item.name
      if (!name) return
      
      if (!sectorStats.has(name)) {
        sectorStats.set(name, {
          name,
          count: 0,
          totalFlow: 0,
          latestFlow: 0,
          latestChange: 0
        })
      }
      
      const stats = sectorStats.get(name)
      stats.count++
      
      if (item.flow !== undefined && item.flow !== null) {
        stats.totalFlow += item.flow
        stats.latestFlow = item.flow
      }
      
      if (item.change !== undefined && item.change !== null) {
        stats.latestChange = item.change
      }
    })
  })
  
  // 转换为数组并排序
  return Array.from(sectorStats.values())
    .sort((a, b) => {
      // 优先按最新资金流入排序
      if (b.latestFlow !== a.latestFlow) {
        return b.latestFlow - a.latestFlow
      }
      // 再按出现次数排序
      return b.count - a.count
    })
    .map(s => s.name)
}