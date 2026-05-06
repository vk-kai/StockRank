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
    tooltip: {
  trigger: 'item',

  backgroundColor: 'rgba(20,25,45,0.95)',
  borderColor: '#3a4a6b',
  borderWidth: 1,

  formatter: (params) => {
    if (!params.data) return ''
    
    const change = params.data.change
    const totalFlow = params.data.totalFlow
    const accumulatedChange = params.data.accumulatedChangePercent
    const appearances = params.data.appearances

    let changeHtml = '-'
    if (change !== null && change !== undefined) {
      const color = change >= 0 ? '#ee6666' : '#91cc75'
      changeHtml = `<b style="color:${color}">${(change * 100).toFixed(2)}%</b>`
    }

    let tooltipContent = `
      <div style="padding:6px 10px;">
        <div style="font-weight:bold;margin-bottom:6px;color:#fff;">
          ${params.seriesName}
        </div>

        <div style="color:#8ba4c7">
          时间： <b>${params.name}</b>
        </div>

        <div style="color:#8ba4c7">
          资金流入：
          <b style="color:#ee6666">
            ${formatFlow(params.data.value)}
          </b>
        </div>

        <div style="color:#8ba4c7">
          涨跌幅： ${changeHtml}
        </div>
    `

    if (!isToday && totalFlow !== null && totalFlow !== undefined) {
      let accumulatedChangeHtml = '-'
      if (accumulatedChange !== null && accumulatedChange !== undefined) {
        const color = accumulatedChange >= 0 ? '#ee6666' : '#91cc75'
        accumulatedChangeHtml = `<b style="color:${color}">${(accumulatedChange * 100).toFixed(2)}%</b>`
      }

      let totalFlowHtml = '-'
      if (totalFlow !== null && totalFlow !== undefined) {
        totalFlowHtml = `<b style="color:#4fc3f7">${formatFlow(totalFlow)}</b>`
      }

      let appearancesHtml = appearances ? `<b>${appearances}</b>天` : '-'

      tooltipContent += `
        <div style="border-top:1px dashed #3a4a6b;margin:6px 0;"></div>

        <div style="color:#8ba4c7">
          累计流入： ${totalFlowHtml}
        </div>

        <div style="color:#8ba4c7">
          累计涨跌： ${accumulatedChangeHtml}
        </div>

        <div style="color:#8ba4c7">
          出现天数： ${appearancesHtml}
        </div>
      `
    }

    tooltipContent += `</div>`
    return tooltipContent
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
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: 0,
        filterMode: 'none'
      },
      {
        type: 'slider',
        xAxisIndex: 0,
        filterMode: 'none',
        height: 20
      }
    ],
    series: series
  }
}

export function generateSeries(topSectors, timeData, allData, colors, isToday) {
  return topSectors.map((sectorName, index) => {
    const data = timeData.map(timeKey => {
      const timeDataItem = allData[timeKey]?.data || allData[timeKey] || []
      const sectorItem = timeDataItem.find(s => s.name === sectorName)

      if (!sectorItem || sectorItem.flow === undefined || sectorItem.flow === null) {
        return null
      }

      const flow = sectorItem.flow
      const change = sectorItem.change !== undefined && sectorItem.change !== null ? sectorItem.change : null

      if (isToday) {
        return {
          value: flow,
          change: change
        }
      }

      const totalFlow = sectorItem.total_flow !== undefined && sectorItem.total_flow !== null ? sectorItem.total_flow : null
      const accumulatedChangePercent = sectorItem.accumulated_change_percent !== undefined && sectorItem.accumulated_change_percent !== null ? sectorItem.accumulated_change_percent : null
      const appearances = sectorItem.appearances !== undefined && sectorItem.appearances !== null ? sectorItem.appearances : null

      return {
        value: flow,
        change: change,
        totalFlow: totalFlow,
        accumulatedChangePercent: accumulatedChangePercent,
        appearances: appearances
      }
    })

    // Check if there are any valid data points
    const hasValidData = data.some(item => item !== null);
    if (!hasValidData) {
      return null;
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
  }).filter(series => series !== null);
}