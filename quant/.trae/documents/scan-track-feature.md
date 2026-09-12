# 扫描结果跟踪功能实现计划

## Context

用户需要在扫描结果中对股票进行"跟踪"操作，跟踪后自动加入自选股，自选股中显示跟踪标识和收益率，查看已跟踪股票时主图自动显示买点信号，再次点击可取消跟踪并选择是否从自选股移除。

---

## 1. 数据库变更（db.py）

新建 `tracked_signals` 表：

```sql
CREATE TABLE IF NOT EXISTS tracked_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_username TEXT NOT NULL,
    signal_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    direction TEXT NOT NULL,
    signal_price REAL NOT NULL,
    signal_time TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    period TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    tracked_at TEXT NOT NULL,
    UNIQUE(owner_username, signal_id)
)
```

- 冗余存储信号详情，即使 scan_signals 被删除跟踪数据仍独立存活
- `signal_price` 用于计算收益率

新增 db.py 函数：
- `track_signal(signal_id, owner_username)` - 跟踪信号，自动加入自选股
- `untrack_signal(tracked_id, owner_username)` - 取消跟踪，返回被删除记录
- `list_tracked_signals(owner_username)` - 列出所有跟踪信号
- `get_tracked_signals_by_code(code, owner_username)` - 按股票查询跟踪信号

---

## 2. 后端 API 变更（api/market.py）

新增 3 个端点：
- `POST /api/market/scan/track?signal_id=X` - 跟踪信号
- `POST /api/market/scan/untrack?tracked_id=X&remove_from_watchlist=false` - 取消跟踪
- `GET /api/market/tracked-signals?code=XXX` - 获取跟踪信号列表

修改 `GET /api/market/watchlist`，每个 item 增加：
- `tracked_signal_count: number` - 跟踪信号数
- `tracked_return_pct: number | null` - 收益率（当前价 vs 最早买点信号价）

---

## 3. 前端类型变更

`types/scan.ts` 新增：
```typescript
export interface TrackedSignal {
  id: number;
  signal_id: number;
  code: string;
  name: string;
  direction: string;
  signal_price: number;
  signal_time: string;
  strategy_name: string;
  period: string;
  reason: string;
  tracked_at: string;
}
```

`types/market.ts` 修改 `WatchlistSecurityInfo`，增加：
```typescript
tracked_signal_count?: number;
tracked_return_pct?: number | null;
```

---

## 4. 前端 API 变更（api/scan.ts）

新增 3 个函数：`trackSignal`、`untrackSignal`、`fetchTrackedSignals`

---

## 5. App.tsx 变更

- 新增 `trackedSignals` 状态和 `loadTrackedSignals` 函数
- 修改 `handleSelectWatchlistSecurity`：选中已跟踪股票时，自动将跟踪信号转为 `SignalInfo[]` 设置到 `backtestSignals`，图表上显示买点
- 新增 `handleTrackSignal` / `handleUntrackSignal` 事件处理
- 向 Sidebar 传递新 props：`trackedSignals`、`onTrackSignal`、`onUntrackSignal`

---

## 6. Sidebar.tsx 变更

**扫描结果 tab**：
- 每个股票组 header 添加"跟踪"按钮
- 已跟踪的显示"已跟踪"并置灰

**自选股 tab**：
- 有跟踪信号的自选股显示"跟踪"标识（橙色 badge，参考 t0-badge）
- 显示跟踪收益率
- 点击跟踪标识弹出对话框：仅取消跟踪 / 取消跟踪并移出自选 / 返回

---

## 7. 关键文件清单

| 文件 | 改动类型 |
|------|---------|
| `backend/db.py` | 新建表 + 4 个新函数 |
| `backend/api/market.py` | 3 个新端点 + 修改 watchlist 返回 |
| `frontend/src/types/scan.ts` | 新增 TrackedSignal |
| `frontend/src/types/market.ts` | 修改 WatchlistSecurityInfo |
| `frontend/src/api/scan.ts` | 3 个新 API 函数 |
| `frontend/src/App.tsx` | 新增状态 + 事件处理 + 自动加载信号到图表 |
| `frontend/src/components/Sidebar.tsx` | 跟踪按钮 + 跟踪标识 + 取消弹窗 + 收益率显示 |
| `frontend/src/App.css` 或对应样式文件 | 新增样式 |

---

## 8. 验证方法

1. 执行扫描，在扫描结果中点击"跟踪"，确认股票被加入自选股且带跟踪标识
2. 切换到自选股 tab，确认有"跟踪"badge 和收益率显示
3. 点击已跟踪的自选股，确认 K 线图自动显示买点箭头
4. 在自选股中点击跟踪标识，确认弹出取消对话框
5. 选择"取消跟踪并移出自选"，确认股票从自选股列表消失
6. 选择"仅取消跟踪"，确认跟踪标识消失但股票仍在自选股
