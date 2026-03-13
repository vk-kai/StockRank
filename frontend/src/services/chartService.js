/**
 * 图表配置封装
 */
import { formatFlow } from '../utils/formatters'

/**
 * 生成图表配置
 * @param {Array} timeData - 时间数据
 * @param {Array} series - 系列数据
 * @param {Array} topSectors - 板块列表
 * @param {Object} oldSelected - 旧的选中状态
 * @param {Array} colors - 颜色列表
 * @returns {Object} ECharts配置
 */
export function generateChartOption(timeData, series, topSectors, oldSelected, colors) {
  return {
    tooltip: {
  trigger: 'item',

  backgroundColor: 'rgba(20,25,45,0.95)',
  borderColor: '#3a4a6b',
  borderWidth: 1,

  formatter: (params) => {

    const change = params.data?.change

    let changeHtml = '-'

    if (change !== null && change !== undefined) {

      const color = change >= 0 ? '#ee6666' : '#91cc75'

      changeHtml = `
        <b style="color:${color}">
          ${(change * 100).toFixed(2)}%
        </b>
      `
    }

    return `
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
            ${formatFlow(params.data?.value)}
          </b>
        </div>

        <div style="color:#8ba4c7">
          涨跌幅： ${changeHtml}
        </div>
      </div>
    `
  }
},   
    legend: {
      data: topSectors,
      textStyle: {
        color: '#8ba4c7'
      },
      type: 'scroll',
      selectedMode: true,
      selected: topSectors.reduce((acc, name, index) => {
        acc[name] = oldSelected[name] !== undefined ? oldSelected[name] : (index < 5)
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

/**
 * 生成系列数据
 * @param {Array} topSectors - 板块列表
 * @param {Array} timeData - 时间数据
 * @param {Object} allData - 所有数据
 * @param {Array} colors - 颜色列表
 * @returns {Array} 系列数据
 */
export function generateSeries(topSectors, timeData, allData, colors) {
  return topSectors.map((sectorName, index) => {
    const data = timeData.map(timeKey => {
      const timeDataItem = allData[timeKey]?.data || []
      const sectorItem = timeDataItem.find(s => s.name === sectorName)

      if (!sectorItem) {
        return { value: null, change: null }
      }

      return {
        value: sectorItem.flow,
        change: sectorItem.change
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