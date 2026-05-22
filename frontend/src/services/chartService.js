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

export function getTopSectorsByLatestSnapshot(timeData, allData, limit = 10, replayCursor = null) {
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

export function buildReplaySectorOrder(timeData, allData, limit = 10) {
  const sectorStats = new Map()

  timeData.forEach((timeKey, timeIndex) => {
    const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
    timeDataItem.forEach((item) => {
      if (!item || !item.name) return

      const flow = getFlowValue(item)
      if (!sectorStats.has(item.name)) {
        sectorStats.set(item.name, {
          name: item.name,
          firstSeen: timeIndex,
          lastSeen: timeIndex,
          peakFlow: flow ?? 0,
          appearances: 0
        })
      }

      const stats = sectorStats.get(item.name)
      stats.lastSeen = timeIndex
      stats.appearances += 1
      if (flow !== null && flow !== undefined) {
        stats.peakFlow = Math.max(stats.peakFlow, flow)
      }
    })
  })

  return Array.from(sectorStats.values())
    .sort((a, b) => {
      if (b.peakFlow !== a.peakFlow) return b.peakFlow - a.peakFlow
      if (a.firstSeen !== b.firstSeen) return a.firstSeen - b.firstSeen
      if (b.appearances !== a.appearances) return b.appearances - a.appearances
      return b.lastSeen - a.lastSeen
    })
    .slice(0, limit)
    .map(item => item.name)
}

export function generateLiveReplayChartOption(timeData, allData, colors, replayCursor = null, limit = 10, fixedTopSectors = null, isReplayMode = false) {
  const fullTimeData = Array.isArray(timeData) ? timeData : []
  
  const topSectors = Array.isArray(fixedTopSectors) && fixedTopSectors.length > 0
    ? fixedTopSectors
    : buildReplaySectorOrder(fullTimeData, allData, limit)

  if (fullTimeData.length === 0) {
    return {
      backgroundColor: '#111827',
      title: { show: false },
      xAxis: { type: 'category', data: [] },
      yAxis: { type: 'value', name: '资金流入(亿)' },
      series: []
    }
  }

  const sectorAvgFlows = topSectors.map(sectorName => {
    let totalFlow = 0
    let count = 0
    fullTimeData.forEach(timeKey => {
      const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
      const sectorItem = timeDataItem.find(item => item.name === sectorName)
      const flow = sectorItem ? getFlowValue(sectorItem) : null
      if (flow !== null && flow !== undefined) {
        totalFlow += Math.abs(flow)
        count++
      }
    })
    return {
      name: sectorName,
      avgFlow: count > 0 ? totalFlow / count : 0
    }
  })

  sectorAvgFlows.sort((a, b) => b.avgFlow - a.avgFlow)
  const largeScaleSectors = new Set(
    sectorAvgFlows.slice(0, Math.ceil(sectorAvgFlows.length * 0.2)).map(s => s.name)
  )

  const visibleDataCount = isReplayMode && replayCursor !== null
    ? Math.min(replayCursor + 1, fullTimeData.length)
    : fullTimeData.length
    
  const displayTimeData = fullTimeData.slice(0, visibleDataCount)

  const series = topSectors.map((sectorName, index) => {
    const color = colors[index % colors.length]
    let seen = false
    const useRightAxis = largeScaleSectors.has(sectorName)

    const data = displayTimeData.map((timeKey, idx) => {
      const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
      const sectorItem = timeDataItem.find(item => item.name === sectorName)
      const flow = sectorItem ? getFlowValue(sectorItem) : null

      if (flow !== null && flow !== undefined) {
        seen = true
      }

      if (!seen) return null

      return {
        value: flow,
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
      connectNulls: false,
      showSymbol: false,
      symbol: 'circle',
      symbolSize: 5,
      yAxisIndex: useRightAxis ? 1 : 0,
      data,
      lineStyle: {
        width: 1.5,
        color
      },
      itemStyle: {
        color
      },
      endLabel: {
        show: !isReplayMode && (visibleDataCount >= fullTimeData.length),
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
          width: 2.5,
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
    animationDuration: isReplayMode ? 300 : 700,
    animationDurationUpdate: isReplayMode ? 300 : 900,
    animationEasing: 'linear',
    animationEasingUpdate: 'linear',
    title: { show: false },
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
      left: 18,
      right: 176,
      top: 18,
      bottom: 26,
      containLabel: true
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: displayTimeData,
      axisLine: {
        lineStyle: {
          color: 'rgba(148, 163, 184, 0.35)'
        }
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        color: '#cbd5e1'
      },
      splitLine: {
        show: false
      }
    },
    yAxis: [
      {
        type: 'value',
        name: '资金流入(亿)',
        nameTextStyle: {
          color: '#cbd5e1',
          padding: [0, 0, 0, 8]
        },
        axisLine: {
          show: false
        },
        axisTick: {
          show: false
        },
        axisLabel: {
          color: '#cbd5e1',
          formatter: (value) => {
            if (Math.abs(value) >= 1) {
              return `${value.toFixed(1)}亿`
            }
            return `${(value * 10000).toFixed(0)}万`
          }
        },
        splitLine: {
          lineStyle: {
            color: 'rgba(148, 163, 184, 0.14)'
          }
        }
      },
      {
        type: 'value',
        name: '大额流入(亿)',
        nameTextStyle: {
          color: '#fbbf24',
          padding: [0, 0, 0, 8]
        },
        axisLine: {
          show: false
        },
        axisTick: {
          show: false
        },
        axisLabel: {
          color: '#fbbf24',
          formatter: (value) => {
            if (Math.abs(value) >= 1) {
              return `${value.toFixed(1)}亿`
            }
            return `${(value * 10000).toFixed(0)}万`
          }
        },
        splitLine: {
          show: false
        }
      }
    ],
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
    backgroundColor: '#111827',
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

            const appearancesHtml = appearances ? `<b>${appearances}</b>次` : '-'

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
            return `${value.toFixed(1)}亿`
          }
          return `${(value * 10000).toFixed(0)}万`
        }
      }
    },
    series
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
          change
        }
      }

      return {
        value: flow,
        change,
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
      data,
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

export function collectAllSectors(timeData, allData, isToday) {
  const sectorStats = new Map()

  timeData.forEach(timeKey => {
    const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
    timeDataItem.forEach((item) => {
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

  return Array.from(sectorStats.values())
    .sort((a, b) => {
      if (b.latestFlow !== a.latestFlow) {
        return b.latestFlow - a.latestFlow
      }
      return b.count - a.count
    })
    .map(s => s.name)
}

