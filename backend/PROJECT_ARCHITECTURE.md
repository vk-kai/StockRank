# StockRank 项目架构与运行逻辑

## 项目概述

StockRank 是一个股票板块资金流向监控系统，主要功能：
1. 实时采集A股板块资金流向数据
2. 采集财经新闻并推送
3. 前端可视化展示资金流向图表
4. 支持查看板块个股详情

## 目录结构

```
StockRank/
├── backend/                    # 后端服务 (Flask)
│   ├── app.py                 # 主入口，创建Flask应用
│   ├── config.py              # 配置文件路径定义
│   ├── data_processor.py      # 数据处理核心模块
│   ├── data_collector.py      # 数据采集线程
│   ├── news_collector.py      # 新闻采集线程
│   ├── news_processor.py      # 新闻处理
│   ├── ai_analyzer.py         # AI分析模块
│   ├── feishu_pusher.py       # 飞书推送
│   ├── monitor.py             # 系统监控
│   ├── thread_monitor.py      # 线程监控
│   ├── logger.py              # 日志模块
│   ├── stock_monitor.py       # 股票监控
│   ├── routes/                # API路由
│   │   ├── flow_routes.py     # 资金流向API
│   │   ├── news_routes.py     # 新闻API
│   │   ├── config_routes.py   # 配置API
│   │   ├── log_routes.py      # 日志API
│   │   ├── house_routes.py    # 房价API
│   │   └── auth_routes.py     # 认证API
│   ├── Jarvis/                # 安全中间件
│   │   ├── middleware.py      # IP封禁、请求限流
│   │   ├── security.py        # 安全检测
│   │   └── config.py          # 安全配置
│   └── data/                  # 数据目录(运行时生成)
│       ├── daily/             # 每日汇总数据
│       ├── realtime/          # 实时数据
│       └── news/              # 新闻数据
├── frontend/                   # 前端 (Vue 3)
│   └── src/
│       ├── components/        # Vue组件
│       ├── services/          # API服务
│       └── utils/             # 工具函数
├── config/                     # 配置目录
│   ├── monitor_config.json    # 监控配置
│   └── ai_prompt.txt          # AI提示词
└── test/                       # 测试脚本
```

## 核心模块说明

### 1. data_processor.py - 数据处理核心

**全局变量:**
- `latest_data`: 最新板块资金数据列表
- `latest_market_data`: 最新大盘指数数据

**核心函数:**
```python
get_sector_flow_data()      # 从东方财富获取板块资金数据
get_market_index_data()     # 获取大盘指数
load_daily_data(date)       # 加载指定日期的每日数据
load_recent_daily_data(days) # 加载最近N天数据
load_realtime_data(date)    # 加载实时数据
save_daily_data(date, data) # 保存每日数据
generate_daily_summary()    # 生成每日汇总
get_top5_comparison_data()  # 获取TOP5对比数据
```

**数据结构 (latest_data):**
```python
[
    {
        'rank': 1,
        'name': '电池',      # 板块名称
        'flow': 152463.67,   # 资金净流入(万元)
        'change': 0.04,      # 涨跌幅(小数)
        'code': 'BK1033'     # 板块代码
    },
    ...
]
```

### 2. data_collector.py - 数据采集线程

**核心逻辑:**
- 每5分钟采集一次数据
- 仅在交易时间采集
- 上午收盘(11:30)和下午收盘(15:00)生成每日汇总

**交易时间判断函数:**
```python
is_trading_day(now)      # 是否交易日
is_trading_time(now)     # 是否交易时间
is_morning_close(now)    # 是否上午收盘
is_afternoon_close(now)  # 是否下午收盘
```

### 3. flow_routes.py - 资金流向API

**主要接口:**

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/flow/current` | GET | 获取当前资金流向 |
| `/api/flow/history` | GET | 获取历史数据 |
| `/api/flow/minute` | GET | 获取分钟数据 |
| `/api/flow/sector-stocks` | GET | 获取板块个股 |
| `/api/flow/daily-report` | GET | 获取每日报告 |

**sector-stocks 接口逻辑:**
```
请求: /api/flow/sector-stocks?sector=电池

1. 从 latest_data 查找板块代码
2. 如果 latest_data 为空，调用 get_sector_flow_data()
3. 如果仍找不到，从历史数据中查找
4. 用板块代码请求东方财富API获取个股数据
```

### 4. news_collector.py - 新闻采集

- 从东方财富获取财经新闻
- 支持AI分析新闻情感
- 支持飞书推送

## 数据流

```
东方财富API
    │
    ▼
data_collector.py (采集线程)
    │
    ├── 实时数据 → backend/data/realtime/YYYY-MM-DD.json
    │
    └── 每日汇总 → backend/data/daily/YYYY-MM-DD.json
                    │
                    ▼
              flow_routes.py (API)
                    │
                    ▼
              frontend (展示)
```

## 数据文件格式

### realtime/YYYY-MM-DD.json
```json
{
    "09:35": {
        "timestamp": "2024-01-15T09:35:00+08:00",
        "data": [
            {"name": "电池", "flow": 10000, "change": 0.02, "code": "BK1033"},
            ...
        ]
    },
    "09:40": {...}
}
```

### daily/YYYY-MM-DD.json
```json
{
    "timestamp": "2024-01-15T15:00:00+08:00",
    "data": [
        {"rank": 1, "name": "电池", "flow": 152463, "change": 0.04, "code": "BK1033"},
        ...
    ]
}
```

## 外部API

### 东方财富板块资金
```
URL: https://push2.eastmoney.com/api/qt/clist/get
参数:
  fs: m:90+s:4     # 板块
  fid: f62         # 排序字段(主力净流入)
  fields: f12,f14,f62,f3,...  # 返回字段
```

**字段说明:**
- f12: 板块代码
- f14: 板块名称
- f62: 主力净流入(元)
- f3: 涨跌幅(百分比*100)

### 东方财富板块个股
```
URL: https://push2.eastmoney.com/api/qt/clist/get
参数:
  fs: b:{板块代码}  # 如 b:BK1033
  fid: f62
```

## 前端关键文件

### apiService.js - API调用
```javascript
getCurrentFlow()           // 获取当前资金流向
getHistoryData(days)       // 获取历史数据
getMinuteData(hours)       // 获取分钟数据
getSectorStocks(sector)    // 获取板块个股
```

### chartService.js - 图表配置
```javascript
generateChartOption()      // 生成ECharts配置
generateSeries()           // 生成图表系列数据
```

## 运行方式

### 后端启动
```bash
cd backend
python app.py
# 默认端口: 5001
```

### 前端启动
```bash
cd frontend
npm install
npm run dev
# 默认端口: 5173
```

### 生产环境
```bash
cd frontend
npm run build
# 静态文件输出到 frontend/dist
```

## 注意事项

1. **数据采集时机**: 仅在交易时间采集数据，非交易时间 `latest_data` 可能为空
2. **板块代码查找**: `/sector-stocks` 接口会依次从 `latest_data`、历史数据中查找板块代码
3. **历史数据**: 每日收盘后自动生成汇总，保存在 `data/daily/` 目录
4. **安全中间件**: Jarvis 模块提供 IP 封禁和请求限流功能
5. **日志位置**: `backend/logs/` 目录

## 常见问题

### Q: 非交易时间获取不到板块代码?
A: 系统会自动调用 `get_sector_flow_data()` 获取数据，东方财富API在非交易时间也能返回数据

### Q: 历史数据中没有code字段?
A: 已修复，新保存的数据会包含 `code` 字段

### Q: 前端图表点击板块获取个股失败?
A: 检查后端日志，确认板块名称是否正确匹配
