# backend 目录工程化重构（分层 + 绝对包导入）

- 日期：2026-07-21
- 涉及项目：数据大盘 / StockRank（backend）
- 状态：待审查
- 前置任务：利好利空总分聚合优化（已完成并验证）
- 后续任务：data_processor.py 拆分为功能模块（本任务验证通过后独立进行）

## 1. 背景与动机

backend 根目录平铺 40 个源码 `.py` 文件，无分层、无职责边界，"想起啥弄啥"。已有两个分层先例（`routes/` 路由、`Jarvis/` 安全），但其余模块全堆在根。目标是按依赖层次与职责划分到子包，统一为绝对包导入，提升可维护性，**且不拆分任何大文件、不改业务逻辑**。

### 1.1 范围（已与用户确认）

- 只做目录结构调整（移动文件 + 改 import），**不拆任何大文件**。
- **渐进分批**迁移，每批可独立验证、可回退。
- import 统一改为**绝对包导入**（`from 包.模块 import`）。

## 2. 测试基线（重构安全网）

`cd backend && python -m unittest discover -p "test_*.py"`：**49 测试，47 通过，2 失败**。

两个失败均为 **pre-existing**（与本次重构无关）：
- `test_auth_guard`：登录认证 401（依赖 session 环境）
- `test_stock_price_monitor.test_hit_pushes_and_records`：推送标题 emoji 断言

**重构验收标准**：上述 2 个已知失败不增加、47 个通过不退化 + 全部 `py_compile` 通过 + `python -c "import app"` 冒烟通过。

## 3. 目标包结构

```
backend/
├── app.py  ws.py             # 入口留根（启动方式不变）
├── core/       config, logger, daily_password
├── data/       data_processor, news_processor, stock_price_feed, stock_resolver,
│               data_collector, news_collector, margin_collector, ths_cookie_refresh,
│               market_map_snapshot, market_map_push_store
├── analysis/   ai_analyzer, stock_scorer, industry_cycle, anomaly_detector,
│               intraday_timeline, news_score_thresholds
├── pushers/    notification_pusher, feishu_pusher, wechat_pusher
├── monitors/   health_checker, monitor, thread_monitor, stock_monitor, stock_price_monitor
├── routes/     （已存在，不动）
├── Jarvis/     （已存在，保留命名）
├── scripts/    run_scoring_local, diagnose_ths_access
└── tests/      test_*.py（8个）
```

## 4. 依赖矩阵（迁移顺序依据）

> 来源：backend 根目录 `^from <本地模块>` 扫描。`routes/`、`Jarvis/` 内部 import 同样需要随目标模块迁移而更新。

| 模块 | 依赖的本地模块 | 目标包 |
|---|---|---|
| config | — | core |
| logger | config | core |
| daily_password | — | core |
| data_processor | config, logger | data |
| news_processor | config, logger | data |
| stock_price_feed | logger | data |
| stock_resolver | logger | data |
| data_collector | data_processor, thread_monitor, logger | data |
| news_collector | news_processor, ai_analyzer, notification_pusher, stock_monitor, logger, thread_monitor | data |
| margin_collector | config, logger, thread_monitor | data |
| ths_cookie_refresh | —（仅标准库 + websocket） | data |
| market_map_snapshot | config, data_processor, data_collector | data |
| market_map_push_store | config | data |
| ai_analyzer | config, logger, news_score_thresholds | analysis |
| stock_scorer | config, ai_analyzer, data_processor, logger | analysis |
| industry_cycle | config, ai_analyzer, data_processor, logger | analysis |
| anomaly_detector | config, data_processor, logger | analysis |
| intraday_timeline | data_processor, margin_collector, news_processor | analysis |
| news_score_thresholds | — | analysis |
| feishu_pusher | config, logger | pushers |
| wechat_pusher | config, feishu_pusher, logger | pushers |
| notification_pusher | feishu_pusher, wechat_pusher, logger | pushers |
| health_checker | logger, config | monitors |
| monitor | logger, config, daily_password | monitors |
| thread_monitor | logger | monitors |
| stock_monitor | config, logger | monitors |
| stock_price_monitor | config, logger | monitors |
| app | config, data_processor, data_collector, news_collector, margin_collector, health_checker, routes, thread_monitor, monitor, market_map_snapshot, Jarvis, ws | 根 |
| routes/* | data_processor, data_collector, ai_analyzer, anomaly_detector, margin_collector, industry_cycle, intraday_timeline, market_map_snapshot, market_map_push_store, news_processor, config, logger, daily_password | routes |
| Jarvis/* | daily_password | Jarvis |
| run_scoring_local | data_processor | scripts |
| diagnose_ths_access | config, data_processor | scripts |

## 5. 包根与启动方式

- **backend/ 仍是 sys.path 根**：启动方式 `cd backend && python app.py` 不变，docker / start_dev.bat 不改。
- 子包内一律绝对导入：`from core.config import X`、`from data.data_processor import X`。
- 每个子包加空 `__init__.py`（让 Python 识别为包）。

## 6. 迁移单元与规则

**迁移单元 = 目标包**：每批把一个目标包的所有模块从根移入子目录，然后**全局更新所有引用这些模块的 import** 为绝对路径。

关键规则（避免迁移中状态混乱）：
- 迁移包 A 时，包 A 内模块**互相引用**全部改为 `from A.xxx import`（绝对）。
- 迁移包 A 时，包 A 内模块**引用尚未迁移的模块**（属其他包、还在根）暂时保持原样 `from xxx import`；待那些模块所属批次迁移时，再回头更新。
- 每移一个包，全局 `grep "from <该包内模块> import"` 找到所有引用点，统一改成 `from 包.<模块> import`。

## 7. 迁移批次

按依赖层次，被依赖最多的底层先迁：

| 批次 | 目标包 | 模块 | 全局需更新的引用来源 |
|---|---|---|---|
| **批1** | core/ | config, logger, daily_password | 几乎所有文件 |
| **批2** | data/ | data_processor, news_processor, stock_price_feed, stock_resolver, data_collector, news_collector, margin_collector, ths_cookie_refresh, market_map_snapshot, market_map_push_store | analysis, routes, app, scripts, Jarvis(经daily_password间接) |
| **批3a** | analysis/ | ai_analyzer, stock_scorer, industry_cycle, anomaly_detector, intraday_timeline, news_score_thresholds | data/news_collector, routes, app |
| **批3b** | pushers/ | feishu_pusher, wechat_pusher, notification_pusher | data/news_collector, routes |
| **批3c** | monitors/ | health_checker, monitor, thread_monitor, stock_monitor, stock_price_monitor | data/data_collector, data/news_collector, data/margin_collector, app |
| **批4** | scripts/ + tests/ | run_scoring_local, diagnose_ths_access, test_*.py | 仅自身 |

**每批收尾三重验证**：
1. `python -m compileall backend`（或对改动文件 `py_compile`）全过；
2. `python -m unittest discover -p "test_*.py"` 对照基线（47 通过 / 2 已知失败）；
3. `python -c "import app"` 冒烟通过（不启动线程，仅验证 import 链）。

## 8. 导入改写示例

```
from config import DATA_DIR            → from core.config import DATA_DIR
from logger import get_logger          → from core.logger import get_logger
from data_processor import error_logger→ from data.data_processor import error_logger
from ai_analyzer import analyze_news   → from analysis.ai_analyzer import analyze_news
from feishu_pusher import ...          → from pushers.feishu_pusher import ...
from health_checker import ...         → from monitors.health_checker import ...
```

`routes/`、`Jarvis/` 内部已有的包内 import 保持；它们对根模块的引用随对应批次更新。

## 9. 不动的部分

- **不拆任何大文件**：data_processor（2632行）、ai_analyzer（1035行）等只移动 + 改 import，业务逻辑零改动。
- Jarvis 命名保留、`app.py`/`ws.py` 留根。
- `routes/`、`Jarvis/` 目录结构与命名不动。

## 10. 风险与回退

- **主要风险**：漏改 import → ImportError。缓解：每批三重验证 + 全局 grep 校验无残留旧路径 import。
- **回退**：每批一个 git commit，出错 `git revert` 该批，精准回退。
- **部署**：本地三重验证通过后，服务器 docker 重新构建生效。

## 11. 后续任务（本 spec 不含）

`data_processor.py`（2632 行，职责混杂：数据IO + 板块流 + 市场地图 + THS + 东财请求 + 推送状态）拆分为多个功能模块。**在本目录重构验证通过后**，作为独立任务走 brainstorming → spec → TDD 拆分。

## 12. 交付物

- 重构后的目录结构（按第 3 节）。
- 全部 import 改为绝对包导入。
- 每批 git commit（便于回退）。
- 验证记录：三重验证输出（测试 47/2、compileall、import 冒烟）。
