import { formatFlow } from '../utils/formatters'

function getFlowValue(item) {
  if (!item) return null
  if (item.flow !== undefined && item.flow !== null) return item.flow
  if (item.value !== undefined && item.value !== null) return item.value
  return null
}

function analyzeDataDistribution(values) {
  if (!values || values.length === 0) {
    return {
      bins: [],
      binCounts: [],
      maxCount: 0,
      totalRange: [0, 100]
    }
  }

  const minVal = Math.min(...values.filter(v => v !== null && v !== undefined))
  const maxVal = Math.max(...values.filter(v => v !== null && v !== undefined))
  
  if (minVal === maxVal) {
    return {
      bins: [[minVal - 10, minVal + 10]],
      binCounts: [values.length],
      maxCount: values.length,
      totalRange: [minVal - 10, minVal + 10]
    }
  }

  const binCount = Math.min(10, Math.ceil(values.length / 5))
  const binWidth = (maxVal - minVal) / binCount
  
  const bins = []
  for (let i = 0; i < binCount; i++) {
    const start = minVal + i * binWidth
    const end = minVal + (i + 1) * binWidth
    bins.push([start, end])
  }

  const binCounts = bins.map(([start, end]) => {
    return values.filter(v => v !== null && v !== undefined && v >= start && v < end).length
  })

  const maxCount = Math.max(...binCounts)

  return {
    bins,
    binCounts,
    maxCount,
    totalRange: [minVal, maxVal]
  }
}

function buildDynamicAxisMapping(distribution) {
  const { bins, binCounts, maxCount, totalRange } = distribution
  
  if (bins.length === 0 || maxCount === 0) {
    return {
      segments: [],
      mapValueToAxis: (value) => value,
      getAxisLabel: (value) => `${value.toFixed(1)}亿`
    }
  }

  const totalPoints = binCounts.reduce((sum, count) => sum + count, 0)
  const segments = []
  let accumulatedSpace = 0

  bins.forEach(([start, end], index) => {
    const count = binCounts[index]
    const proportion = count / totalPoints
    const spaceAllocation = proportion * 0.8 + 0.2 / bins.length
    
    segments.push({
      range: [start, end],
      axisRange: [accumulatedSpace, accumulatedSpace + spaceAllocation],
      count,
      proportion
    })
    
    accumulatedSpace += spaceAllocation
  })

  const mapValueToAxis = (value) => {
    if (value === null || value === undefined) return null
    
    for (const segment of segments) {
      const [start, end] = segment.range
      const [axisStart, axisEnd] = segment.axisRange
      
      if (value >= start && value < end) {
        const positionInRange = (value - start) / (end - start)
        return axisStart + positionInRange * (axisEnd - axisStart)
      }
    }
    
    if (value >= totalRange[1]) {
      return 1.0
    }
    if (value < totalRange[0]) {
      return 0.0
    }
    
    return null
  }

  const getAxisLabel = (axisValue) => {
    for (const segment of segments) {
      const [axisStart, axisEnd] = segment.axisRange
      const [start, end] = segment.range
      
      if (axisValue >= axisStart && axisValue < axisEnd) {
        const positionInRange = (axisValue - axisStart) / (axisEnd - axisStart)
        const realValue = start + positionInRange * (end - start)
        
        if (realValue >= 1000) {
          return `${(realValue / 1000).toFixed(1)}k亿`
        } else if (realValue >= 10) {
          return `${realValue.toFixed(0)}亿`
        } else if (realValue >= 1) {
          return `${realValue.toFixed(1)}亿`
        } else {
          return `${(realValue * 10000).toFixed(0)}万`
        }
      }
    }
    
    return `${axisValue.toFixed(2)}`
  }

  return {
    segments,
    mapValueToAxis,
    getAxisLabel
  }
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
      yAxis: { type: 'value' },
      series: []
    }
  }

  const visibleDataCount = isReplayMode && replayCursor !== null
    ? Math.min(replayCursor + 1, fullTimeData.length)
    : fullTimeData.length
    
  const displayTimeData = fullTimeData.slice(0, visibleDataCount)

  const allFlowValues = []
  topSectors.forEach(sectorName => {
    displayTimeData.forEach(timeKey => {
      const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
      const sectorItem = timeDataItem.find(item => item.name === sectorName)
      const flow = sectorItem ? getFlowValue(sectorItem) : null
      if (flow !== null && flow !== undefined) {
        allFlowValues.push(flow)
      }
    })
  })

  const maxFlow = allFlowValues.length > 0 ? Math.max(5, ...allFlowValues) : 5

  const useBrokenAxis = maxFlow > 15

  let axisMapping = null
  if (useBrokenAxis) {
    const distribution = analyzeDataDistribution(allFlowValues)
    axisMapping = buildDynamicAxisMapping(distribution)
  }

  function mapValueToAxis(value) {
    if (value === null || value === undefined) return null
    if (!useBrokenAxis) return value
    if (axisMapping) {
      return axisMapping.mapValueToAxis(value)
    }
    if (value <= 100) {
      return value * 0.15 / 100
    } else if (value <= 400) {
      return 0.15 + (value - 100) * 0.6 / 300
    } else {
      const extra = value - 400
      const maxExtra = maxFlow - 400
      return 0.75 + (extra / maxExtra) * 0.25
    }
  }

  function getLabelColor(index, total) {
    if (total <= 1) return '#ffffff'
    const ratio = index / (total - 1)
    const brightness = Math.round(255 - ratio * 100)
    return `rgb(${brightness}, ${brightness}, ${brightness + Math.round((255 - brightness) * 0.3)})`
  }

  const series = topSectors.map((sectorName, index) => {
    const color = colors[index % colors.length]
    const labelColor = getLabelColor(index, topSectors.length)
    let seen = false

    const data = displayTimeData.map((timeKey, idx) => {
      const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
      const sectorItem = timeDataItem.find(item => item.name === sectorName)
      const flow = sectorItem ? getFlowValue(sectorItem) : null

      if (flow !== null && flow !== undefined) {
        seen = true
      }

      if (!seen) return null

      return {
        value: mapValueToAxis(flow),
        realValue: flow,
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
      smooth: 0.3,
      connectNulls: false,
      showSymbol: false,
      symbol: 'circle',
      symbolSize: 5,
      data,
      lineStyle: {
        width: 1.8,
        color
      },
      itemStyle: {
        color
      },
      endLabel: {
        show: true,
        distance: 10,
        color: labelColor,
        formatter: (params) => {
          const realValue = params?.data?.realValue ?? params?.value ?? null
          return `${params.seriesName}  ${formatFlow(realValue)}`
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

  let yAxisConfig
  if (useBrokenAxis) {
    let tickValues = []
    
    if (axisMapping && axisMapping.segments.length > 0) {
      axisMapping.segments.forEach(segment => {
        const [start, end] = segment.range
        const [axisStart, axisEnd] = segment.axisRange
        const midValue = (start + end) / 2
        const midAxis = (axisStart + axisEnd) / 2
        
        tickValues.push({ axisValue: axisStart, realValue: start })
        tickValues.push({ axisValue: midAxis, realValue: midValue })
      })
      
      const lastSegment = axisMapping.segments[axisMapping.segments.length - 1]
      tickValues.push({ 
        axisValue: lastSegment.axisRange[1], 
        realValue: lastSegment.range[1] 
      })
    } else {
      tickValues = [0, 50, 100, 150, 200, 250, 300, 350, 400]
      if (maxFlow > 400) {
        const step = Math.ceil((maxFlow - 400) / 3 / 100) * 100
        for (let v = 400 + step; v <= maxFlow; v += step) {
          tickValues.push(v)
        }
      }
    }
    
    yAxisConfig = {
      type: 'value',
      min: 0,
      max: 1,
      interval: 0.1,
      axisLine: {
        show: false
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        color: '#cbd5e1',
        formatter: (value) => {
          if (axisMapping) {
            return axisMapping.getAxisLabel(value)
          }
          
          let realValue
          if (value <= 0.15) {
            realValue = value * 100 / 0.15
          } else if (value <= 0.75) {
            realValue = 100 + (value - 0.15) * 300 / 0.6
          } else {
            const extra = (value - 0.75) * (maxFlow - 400) / 0.25
            realValue = 400 + extra
          }
          
          if (realValue >= 1000) {
            return `${(realValue / 1000).toFixed(1)}k亿`
          } else if (realValue >= 10) {
            return `${realValue.toFixed(0)}亿`
          } else if (realValue >= 1) {
            return `${realValue.toFixed(1)}亿`
          } else {
            return `${(realValue * 10000).toFixed(0)}万`
          }
        }
      },
      splitLine: {
        lineStyle: {
          color: 'rgba(148, 163, 184, 0.14)'
        }
      }
    }
  } else {
    yAxisConfig = {
      type: 'value',
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
    }
  }

  const animationDuration = isReplayMode ? 8000 : 700
  
  return {
    backgroundColor: '#111827',
    animation: true,
    animationDuration: animationDuration,
    animationDurationUpdate: animationDuration,
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
      left: 80,
      right: 140,
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
    yAxis: yAxisConfig,
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

  let maxFlow = 5
  const allFlowValues = []
  series.forEach(s => {
    if (s.data && Array.isArray(s.data)) {
      s.data.forEach(item => {
        if (item && item.value !== null && item.value !== undefined) {
          maxFlow = Math.max(maxFlow, item.value)
          allFlowValues.push(item.value)
        }
      })
    }
  })

  const useBrokenAxis = maxFlow > 15

  let axisMapping = null
  if (useBrokenAxis) {
    const distribution = analyzeDataDistribution(allFlowValues)
    axisMapping = buildDynamicAxisMapping(distribution)
  }

  function mapValueToAxis(value) {
    if (value === null || value === undefined) return null
    if (!useBrokenAxis) return value
    if (axisMapping) {
      return axisMapping.mapValueToAxis(value)
    }
    if (value <= 100) {
      return value * 0.15 / 100
    } else if (value <= 400) {
      return 0.15 + (value - 100) * 0.6 / 300
    } else {
      const extra = value - 400
      const maxExtra = maxFlow - 400
      return 0.75 + (extra / maxExtra) * 0.25
    }
  }

  const mappedSeries = series.map(s => {
    if (!useBrokenAxis) return s
    
    return {
      ...s,
      data: s.data.map(item => {
        if (!item) return item
        return {
          ...item,
          value: mapValueToAxis(item.value),
          realValue: item.value
        }
      })
    }
  })

  let yAxisConfig
  if (useBrokenAxis) {
    let tickValues = []
    
    if (axisMapping && axisMapping.segments.length > 0) {
      axisMapping.segments.forEach(segment => {
        const [start, end] = segment.range
        const [axisStart, axisEnd] = segment.axisRange
        const midValue = (start + end) / 2
        const midAxis = (axisStart + axisEnd) / 2
        
        tickValues.push({ axisValue: axisStart, realValue: start })
        tickValues.push({ axisValue: midAxis, realValue: midValue })
      })
      
      const lastSegment = axisMapping.segments[axisMapping.segments.length - 1]
      tickValues.push({ 
        axisValue: lastSegment.axisRange[1], 
        realValue: lastSegment.range[1] 
      })
    } else {
      tickValues = [0, 50, 100, 150, 200, 250, 300, 350, 400]
      if (maxFlow > 400) {
        const step = Math.ceil((maxFlow - 400) / 3 / 100) * 100
        for (let v = 400 + step; v <= maxFlow; v += step) {
          tickValues.push(v)
        }
      }
    }

    yAxisConfig = {
      type: 'value',
      min: 0,
      max: 1,
      interval: 0.1,
      axisLabel: {
        color: '#8ba4c7',
        formatter: (value) => {
          if (axisMapping) {
            return axisMapping.getAxisLabel(value)
          }
          
          let realValue
          if (value <= 0.15) {
            realValue = value * 100 / 0.15
          } else if (value <= 0.75) {
            realValue = 100 + (value - 0.15) * 300 / 0.6
          } else {
            const extra = (value - 0.75) * (maxFlow - 400) / 0.25
            realValue = 400 + extra
          }
          
          if (realValue >= 1000) {
            return `${(realValue / 1000).toFixed(1)}k亿`
          } else if (realValue >= 10) {
            return `${realValue.toFixed(0)}亿`
          } else if (realValue >= 1) {
            return `${realValue.toFixed(1)}亿`
          } else {
            return `${(realValue * 10000).toFixed(0)}万`
          }
        }
      }
    }
  } else {
    yAxisConfig = {
      type: 'value',
      axisLabel: {
        color: '#8ba4c7',
        formatter: (value) => {
          if (Math.abs(value) >= 1) {
            return `${value.toFixed(1)}亿`
          }
          return `${(value * 10000).toFixed(0)}万`
        }
      }
    }
  }

  return {
    backgroundColor: '#111827',
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'line',
        lineStyle: {
          color: 'rgba(84, 112, 198, 0.55)',
          width: 1
        }
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
          const displayValue = useBrokenAxis ? (param.data.realValue ?? param.data.value) : param.data.value

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
                ${formatFlow(displayValue)}
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
      axisLine: {
        lineStyle: {
          color: 'rgba(148, 163, 184, 0.35)'
        }
      },
      axisTick: {
        show: false
      },
      axisLabel: {
        color: '#8ba4c7'
      },
      splitLine: {
        show: false
      }
    },
    yAxis: yAxisConfig,
    series: mappedSeries
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

