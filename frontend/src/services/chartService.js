import { formatFlow } from '../utils/formatters'

function getFlowValue(item) {
  if (!item) return null
  if (item.flow !== undefined && item.flow !== null) return item.flow
  if (item.value !== undefined && item.value !== null) return item.value
  return null
}

function getVisibleTimeData(timeData, replayCursor) {
  if (!Array.isArray(timeData) || timeData.length === 0) return []
  if (replayCursor === null || replayCursor === undefined) return timeData
  return timeData.slice(0, Math.max(1, replayCursor + 1))
}

export function getTopSectorsByLatestSnapshot(timeData, allData, limit = 12, replayCursor = null) {
  const visibleTimeData = getVisibleTimeData(timeData, replayCursor)
  if (visibleTimeData.length === 0) return []

  const latestKey = visibleTimeData[visibleTimeData.length - 1]
  const latestItems = allData[latestKey]?.data || allData[latestKey] || []

  return [...latestItems]
    .filter(item => item && item.name)
    .sort((a, b) => (getFlowValue(b) ?? Number.NEGATIVE_INFINITY) - (getFlowValue(a) ?? Number.NEGATIVE_INFINITY))
    .slice(0, limit)
    .map(item => item.name)
}

export function generateLiveReplayChartOption(timeData, allData, colors, replayCursor = null, limit = 12, fixedTopSectors = null) {
  const visibleTimeData = getVisibleTimeData(timeData, replayCursor)
  const topSectors = Array.isArray(fixedTopSectors) && fixedTopSectors.length > 0
    ? fixedTopSectors
    : getTopSectorsByLatestSnapshot(visibleTimeData, allData, limit)

  if (visibleTimeData.length === 0) {
    return {
      backgroundColor: '#111827',
      title: {
        text: '今日资金流向',
        left: 12,
        top: 10,
        textStyle: {
          color: '#e5eefb',
          fontSize: 16,
          fontWeight: 600
        }
      }
    }
  }

  const series = topSectors.map((sectorName, index) => {
    const color = colors[index % colors.length]
    const data = visibleTimeData.map(timeKey => {
      const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
      const sectorItem = timeDataItem.find(item => item.name === sectorName)

      return {
        value: sectorItem?.flow ?? null,
        change: sectorItem?.change ?? null,
        totalFlow: sectorItem?.total_flow ?? null,
        accumulatedChangePercent: sectorItem?.accumulated_change_percent ?? null,
        appearances: sectorItem?.appearances ?? null,
        time: timeKey,
        name: sectorName
      }
    })

    return {
      name: sectorName,
      type: 'line',
      smooth: true,
      connectNulls: true,
      showSymbol: false,
      symbol: 'circle',
      symbolSize: 5,
      data,
      lineStyle: {
        width: 2.4,
        color
      },
      itemStyle: {
        color
      },
      endLabel: {
        show: true,
        distance: 10,
        formatter: (params) => {
          const value = params?.data?.value ?? params?.value?.value ?? params?.value ?? null
          return `${params.seriesName}  ${formatFlow(value)}`
        }
      },
      labelLayout: {
        moveOverlap: 'shiftY'
      },
      emphasis: {
        focus: 'series',
        scale: 1.1,
        lineStyle: {
          width: 4,
          shadowBlur: 8,
          shadowColor: 'rgba(15, 23, 42, 0.18)'
        },
        itemStyle: {
          borderWidth: 2,
          borderColor: '#fff'
        }
      }
    }
  })

  return {
    backgroundColor: '#111827',
    animation: true,
    animationDuration: 700,
    animationDurationUpdate: 900,
    animationEasing: 'linear',
    animationEasingUpdate: 'linear',
    title: {
      text: replayCursor === null ? '今日资金流向' : `今日走势回放 · ${visibleTimeData[visibleTimeData.length - 1]}`,
      left: 12,
      top: 10,
      textStyle: {
        color: '#e5eefb',
        fontSize: 16,
        fontWeight: 600
      }
    },
    tooltip: {
      trigger: 'axis',
      order: 'valueDesc',
      backgroundColor: 'rgba(17, 24, 39, 0.96)',
      borderColor: 'rgba(148, 163, 184, 0.25)',
      borderWidth: 1,
      textStyle: {
        color: '#fff'
      },
      axisPointer: {
        type: 'line',
        lineStyle: {
          color: 'rgba(84, 112, 198, 0.55)',
          width: 1
        }
      },
      formatter: (params) => {
        const list = Array.isArray(params) ? params.filter(param => param.data && param.data.value !== null) : []
        if (list.length === 0) return ''

        let result = `<div style="font-weight:600;margin-bottom:8px;color:#fff;">${list[0].name || ''}</div>`
        list.forEach(param => {
          const change = param.data?.change
          const value = param.data?.value
          const changeColor = change === null || change === undefined ? '#94a3b8' : (change >= 0 ? '#ff7875' : '#7ec699')
          const changeText = change === null || change === undefined ? '-' : `${(change * 100).toFixed(2)}%`
          result += `
            <div style="display:flex;justify-content:space-between;gap:16px;margin:4px 0;min-width:220px;">
              <span style="color:#cbd5e1;">
                <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${param.color};margin-right:6px;"></span>
                ${param.seriesName}
              </span>
              <span style="color:${changeColor};font-weight:600;">${formatFlow(value)}</span>
              <span style="color:${changeColor};font-weight:600;">${changeText}</span>
            </div>
          `
        })
        return result
      }
    },
    grid: {
      left: 12,
      right: 180,
      top: 56,
      bottom: 26,
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: visibleTimeData,
      axisLine: {
        lineStyle: {
          color: '#d5dbe6'
        }
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        color: '#667085'
      },
      splitLine: {
        show: false
      }
    },
    yAxis: {
      type: 'value',
      name: '资金流入(亿)',
      nameTextStyle: {
        color: '#667085',
        padding: [0, 0, 0, 8]
      },
      axisLine: {
        show: false
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        color: '#667085',
        formatter: (value) => {
          if (Math.abs(value) >= 1) {
            return `${value.toFixed(1)}亿`
          }
          return `${(value * 10000).toFixed(0)}万`
        }
      },
      splitLine: {
        lineStyle: {
          color: '#edf1f7'
        }
      }
    },
    series
  }
}

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
      name: '资金流入(亿)',
      axisLabel: {
        color: '#8ba4c7',
        formatter: (value) => {
          if (Math.abs(value) >= 1) {
            return value.toFixed(1) + '亿'
          }
          return (value * 10000).toFixed(0) + '万'
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
  })
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
