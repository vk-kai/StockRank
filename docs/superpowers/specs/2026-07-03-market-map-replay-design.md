# 大盘云图复盘（回放）功能设计

日期：2026-07-03
范围：`数据大盘/StockRank`（前端 `frontend/src/MarketMap.vue` + 后端 `backend/`）

## 目标

在大盘云图页面增加"复盘"能力：开盘时段每半小时自动保存一张完整云图快照，用户可点击任一时间点查看那一刻的云图，或一键顺序播放全部快照，直观看出"哪个时间点哪个板块流入多"。

## 两个独立机制（互不干扰）

| 机制 | 频率 | 是否保存 | 用途 |
|---|---|---|---|
| 实时轮询 | 30 秒 | 否 | 始终显示最新行情（现有行为，不变） |
| 复盘快照 | 交易日 9:30/10:00/10:30/11:00/11:30/13:00/13:30/14:00/14:30/15:00 共 10 个整点 | 是（仅当天，次日开盘前清空） | 复盘 + 播放 |

两者是独立的系统：30 秒轮询只取最新、不落盘；半小时快照落盘供回看。实时轮询的代码路径和数据流完全不变。

## 架构概览

- **后端新增独立 daemon 线程** `market_map_snapshot_thread`，与现有 `data_collection_thread` 同模式，职责单一（只抓快照、存盘），互不影响。
- **存储**：JSON 文件 `data/market_map_snapshots/YYYYMMDD.json`（项目其余数据均为 JSON，保持一致）。每天一个文件，跨天覆盖即"清空昨天"。
- **前端**在 `MarketMap.vue` 增加复盘工具条 + 复盘状态机；复用现有 `applyData / buildLayout / render`，渲染层零改动（快照结构与实时 market-map 的 data 完全一致）。

## 后端：快照调度与存储

### 调度
- 线程每 60 秒唤醒一次，判断是否满足抓取条件：
  1. 当前是交易日（复用 `is_trading_day` 逻辑，跳过周末）；
  2. 当前时间命中 10 个半小时整点之一（9:30、10:00、…、15:00），允许 ±90 秒容差；
  3. 今天该时间点尚未抓取（用当天已抓时间点集合去重，避免同一整点重复抓）。
- 满足则调用 `get_market_map_tree()` 取完整 tree，写入当天快照文件。
- 采用"每分钟轮询 + 容差 + 去重"而非精确 `sleep` 到整点，实现简单、不怕漂移、不怕漏唤醒。

### 文件格式
`data/market_map_snapshots/YYYYMMDD.json`：
```json
{
  "date": "2026-07-03",
  "snapshots": [
    { "time": "09:30", "data": { "tree": [...], "total_sectors": 28, "total_stocks": 5200, "cache_time": "..." } },
    { "time": "10:00", "data": { ... } }
  ]
}
```
`data` 结构与现有 `/api/flow/market-map` 返回的 `data` 完全一致，前端可直接 `applyData`。

### 跨天清空
- 写入前读取文件，若文件内 `date != 今天`，则丢弃旧内容、以今天重新起一个文件（等价于"次日开盘前清空昨天"）。
- 因此任意时刻磁盘上最多保留当天这一个文件。

## 后端：新增接口（均受现有 auth 登录保护）

1. `GET /api/flow/market-map-snapshots`
   - 返回今天已抓取的时间点列表：`{ "success": true, "date": "2026-07-03", "points": [ { "time": "09:30", "available": true }, { "time": "10:00", "available": false }, ... ] }`
   - `points` 固定包含全部 10 个时间点，按时间升序；`available` 表示该点今天是否已抓到。
   - 前端据此渲染时间按钮的亮/灰状态。

2. `GET /api/flow/market-map-snapshot?time=10:00`
   - 返回该时间点的完整快照：`{ "success": true, "data": { ... }, "time": "10:00" }`
   - `data` 结构与 market-map 一致；不存在则 `{ "success": false, "message": "该时间点暂无快照" }`。

## 前端：复盘工具条

位置：`.mm-footer` 内、页脚说明文字（`.mm-footer-text`）的**右侧**。

```
[9:30][10:00][10:30][11:00][11:30][13:00][13:30][14:00][14:30][15:00]   ▶播放   🔴实时
```

- **10 个时间按钮**：未到/未抓取 → 置灰禁用；当前选中 → 高亮。
- **▶播放 / ⏸暂停**：自动顺序播放全部已抓快照。**没有**上一帧/下一帧手动步进按钮（明确不做）。
- **🔴 实时**：退出复盘、回实时模式。

## 前端：复盘状态机（MarketMap.vue）

### 状态
新增：`replayMode`（bool）、`replayTime`（当前复盘的时间点，如 "10:00"）、`replayPlaying`（bool）、`replayPoints`（可用时间点数组）、`replayTimer`（播放定时器）。

### 行为
- 进入页面/实时模式：照常 30 秒轮询（`fetchData`），并顺带拉一次 `market-map-snapshots` 刷新时间按钮的可用状态（可挂在轮询里低频更新，如每 5 分钟一次）。
- 点时间按钮 `enterReplay(time)`：
  1. `clearInterval(timer)` 暂停 30 秒轮询；
  2. 拉取该时间点快照 → `applyData` → 渲染；
  3. `replayMode=true`、`replayTime=time`、该按钮高亮；
  4. 画布顶部显示水印"🕐 复盘 10:00"以区别于实时。
- ▶播放：从当前 `replayTime`（或第一个可用点）开始，每 **1.5 秒**推进到下一个已抓快照，到 15:00（最后一个）**自动停止**（不循环）；按钮变 ⏸，再点暂停。
- 🔴实时 `exitReplay()`：`replayMode=false`、清水印、`clearInterval(replayTimer)`、恢复 30 秒轮询、拉实时数据。
- 复盘态下，hover / 单击 / 双击 / 缩放 / 拖动 / 融资弹窗等交互**全部保留**（基于快照 tree，行为与实时一致）。
- 非交易日 / 盘前：时间按钮全灰，工具条提示"开盘后自动记录"。

### 关键约束
- 复盘期间必须暂停 30 秒轮询，否则快照画面会被实时数据覆盖。
- 实时轮询永远只显示最新、不落盘——复盘机制完全独立。

## 边界情况

- **盘中进入复盘**：只能看到"已抓到的"时间点（如 10:30 时可见 9:30/10:00/10:30），后续按钮置灰；点"实时"回实时继续看盘。
- **盘后复盘**：10 个点全可用，可完整回放全天。
- **非交易日**：线程不抓取，按钮全灰。
- **服务重启**：当天已抓的快照在磁盘上，重启后仍在；线程继续补抓后续整点。
- **`get_market_map_tree()` 失败**（网络异常）：该整点跳过、下一分钟重试，记日志，不影响其它点。

## 文件改动清单

**后端**
- 新建 `backend/market_map_snapshot.py`：调度线程 + 存取函数（`load_today_snapshots` / `save_snapshot` / `get_points_status` / `get_snapshot`）。
- `backend/routes/flow_routes.py`：新增 2 个路由（`market-map-snapshots`、`market-map-snapshot`）。
- `backend/app.py`：启动 `market_map_snapshot_thread`。

**前端**
- `frontend/src/MarketMap.vue`：复盘工具条 UI + 复盘状态机 + 水印 + 样式。
- `frontend/src/services/apiService.js`：新增 `getMarketMapSnapshots()`、`getMarketMapSnapshot(time)` 封装。

## 默认决策（已与用户确认）

- 播放速度：**1.5 秒/帧**（固定，不做可调）。
- 播放结束：到 15:00 自动停止，**不循环**。
- **不做**上一帧/下一帧按钮。
- 快照存**完整 tree**（含个股涨跌幅/市值/市盈率），保证渲染与实时一致。
- 跨天清空策略：写快照时按 `date` 判断覆盖，等价于次日开盘前清空。
