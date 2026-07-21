# data_processor.py 模块化拆分设计

- 日期：2026-07-21
- 涉及：backend/data/data_processor.py（2632 行，~60 函数）
- 状态：已完成（2026-07-21，7 步全部落地 + 收尾）
- 前置：backend 目录重构 + config BASE_DIR 修复 + 性能优化（均已完成验证）

## 1. 问题

data_processor.py 是项目核心枢纽（被 15 文件依赖），但 2632 行耦合了 9 个职责区（THS采集/文件IO/日报/大盘指数/AI产业链/大盘云图/市场总览等），难以维护。

## 2. 目标结构（单文件 → 包）

```
data/data_processor/
├── __init__.py      # facade: re-export 全部公共符号 → 15 个依赖文件零改动
├── _common.py       # 5 logger + 解析工具(_safe_float/_parse_json_or_jsonp/_parse_ths_* 等) + 跨组 URL 常量 + GLOBAL_INDICES_CACHE_FILE
├── ths_client.py    # THS: PROXY_POOL/cookie锁/headers/板块资金/板块个股 + latest_data(accessor)
├── storage.py       # 文件IO + 日报聚合 + TOP5对比(G3+G4+G9 强耦合合并)
├── market_index.py  # 大盘指数 + 全球指数 + 大盘摘要(G5+G8, latest_market_data 共享态)
├── ai_chain.py      # AI产业链温度计(G6 自洽)
└── market_map.py    # 大盘云图(G7 自洽)
```

## 3. 设计依据（职责+依赖分析）

- **G5+G8 合并**（market_index）：`latest_market_data` dict 被两组共同 mutate（indices/stats/summary），分开会跨模块共享可变状态。
- **G3+G4+G9 合并**（storage）：G4 的 7/8 函数依赖 G3 文件IO，G9 也依赖 G3。
- **GLOBAL_INDICES_CACHE_FILE 上提 `_common`**：解开 G5(写)↔G6(读 KOSPI 兜底) 的文件耦合。
- **`latest_market_data`** 是 dict mutate（引用不变），跨模块 import 安全。
- **闭包**（get_sector_flow_data 内 3 个嵌套函数）整体迁移，不拆。

## 4. latest_data 修复（accessor）

**已存在 bug**：`flow_routes.py` `from data.data_processor import latest_data` 捕获导入时引用（空 list），而 `get_sector_flow_data` 用 `global latest_data; latest_data = sectors` 重绑，flow_routes 拿到的永远是空 → 非交易时间接口（line 426 `if latest_data:`）总走 fallback，功能降级。

**修复**：ths_client 内用模块级容器 `_state = {'latest_data': []}`，提供 `get_latest_data()` accessor；flow_routes 4 处（426/429/475/478）改用 `get_latest_data()`。facade re-export `get_latest_data`（不再 re-export 裸 latest_data 变量）。

## 5. 渐进式执行策略（legacy 过渡，每步可验证可回退）

一次性拆 2632 行风险高。改为：

1. **步骤1 包转换**：`git mv data_processor.py → data_processor/_legacy.py`，建 `data_processor/__init__.py`（`from ._legacy import *` + 显式 re-export 公共符号）。功能零变化。验证。
2. **步骤2-7 逐子模块抽取**：每个子模块从 `_legacy` 抽出对应函数+全局，`__init__.py` 改 re-export 子模块（去掉对应 `from ._legacy`）。`_legacy` 逐步缩小。每步验证 + commit。
3. **步骤8 收尾**：`_legacy` 清空删除；latest_data accessor + flow_routes 改造；全面验证。

## 6. 验证（每步必做）

1. `python -m compileall` 全过
2. `python -m unittest discover -s tests` 对照基线（53 测试，2 pre-existing 失败不增加）
3. `python -c "import app"` 冒烟
4. 最终：真实启动 `python app.py` + curl /health

## 7. 公共 API（facade 必须 re-export，保 15 文件零改动）

- logger: error_logger, data_logger, system_logger（cleanup_logger 顺删）
- 常量/全局: MARKET_FAST_REFRESH_SECONDS, latest_market_data, get_latest_data（新）
- THS: generate_random_headers, normalize_ths_sector_headers, attach_fresh_ths_cookie, refresh_ths_cookie
- 板块: get_sector_flow_data, get_sector_stocks
- IO: save/load_realtime_data, load_daily_data, cleanup_old_data, is_pushed, update_push_status
- 日报: generate_daily_summary_for_date, load_recent_daily_data, load_recent_realtime_data, load_recent_daily_data_with_accumulation, get_accumulated_top_sectors
- 指数: get_global_market_indices
- ai_chain: get_ai_chain_indicators
- market_map: get_market_map_tree/all/sectors/stocks, get_all_market_map_stocks, refresh_market_map_cache
- 摘要: get_market_overview, refresh/load_market_summary_cache, is_market_summary_complete
- top5: get_top5_comparison_data

## 8. 风险

- 函数 import 头重建（子模块要 import 依赖）——靠 compileall + import app 捕获。
- 模块级副作用 `if USE_PROXY: load_proxy_pool()`（line 54-55）随 ths_client 迁移，触发时机不变（facade import 链触发）。
- deferred import（函数内 from data.data_collector import 等）路径不变，无影响。
- 每步一个 git commit，出错 revert。

## 9. 执行进度（新窗口接续指引）

**全部完成（2026-07-21）**：

| 步骤 | 子模块 | commit |
|---|---|---|
| 1 | 单文件→包转换 + facade | `14ee8a1` |
| 2 | `ai_chain.py`（G6） | `f29aa1a` |
| 3 | `market_map.py`（G7，11 函数 + SW_L2_TO_L1） | `2c4eea2` |
| 4 | `_common.py`（4 logger + 解析工具 + MARKET_INDEX_URL/GLOBAL_INDICES_CACHE_FILE；删死代码 cleanup_logger） | `2c4eea2` |
| 5 | `ths_client.py`（THS 全套 + **latest_data accessor 修复** + flow_routes 4 处改造） | `987bdf0` |
| 6 | `storage.py`（G3 文件IO + G4 日报 + G9 TOP5，16 公共函数） | `3ab5af3` |
| 7 | `market_index.py`（G5 大盘指数 + G8 摘要 + get_stock_statistics；latest_market_data 共享态） | `c6a7b5b` |
| 收尾 | 删 `_legacy.py` + facade 去 `from ._legacy import *` | `bc817ad` |

**最终结构**（原 2632 行单文件 → 7 文件）：
`__init__.py`(facade) / `_common` / `ths_client` / `storage` / `market_index` / `ai_chain` / `market_map`

**额外修复**（步骤3 commit `2c4eea2`）：发现 `.gitignore` 的 `backend/data/*/` 规则在 data_processor 由单文件改为包后被误忽略，
导致步骤1/2 的 `__init__.py`/`ai_chain.py` 从未入库（origin/main 实际不可用）。改为 `backend/data/*/*` + `!backend/data/data_processor/*.py`，
已 `git check-ignore` 验证代码包放行、运行时数据/jarvis/health/daily/realtime 仍忽略。

**latest_data bug 修复**（步骤5）：原 `get_sector_flow_data` 用 `global latest_data; latest_data = sectors` 重绑定，
flow_routes 导入时捕获的空 list 永不更新 → 非交易时间接口总走 fallback。改为 ths_client 内 `_state={'latest_data':[]}` + `get_latest_data()` accessor，
flow_routes 4 处改用 accessor，facade 不再暴露裸变量。

**全验证**：每步 `compileall` + `import app` + 公共 API 溯源；最终 `import app` + 全部 consumer 模块
(routes/analysis/monitors/pushers/data) + `unittest` 53 测试（2 预存失败 test_auth_guard/test_stock_price_monitor，与拆分无关）
+ 真实启动 `python app.py` + `curl /health` → **200**。

**部署提醒**：线上 docker 跑旧镜像，需服务器重新构建部署才生效（见 [[stockrank-deployed-on-server]]）。
步骤1/2 的 broken 中间 commit 已留在历史，但 origin/main 末端（本次推送后）完整可用。

**抽取范式（以已完成的 ai_chain.py 为标准模板）**：
1. `grep -n "^def \|^# ===\|^[A-Z_]* ="` _legacy.py 定位目标区行号（注意：每删一个子模块，后续行号前移，每步重新 grep）
2. Read _legacy 对应区，Write 子模块（顶部 import 头：标准库 + `from core.config import ...` + `from ._legacy import 依赖的工具/_safe_float 等`；然后注释+全局+函数原样复制）
3. Python 脚本按行号删 _legacy 对应区（**带 assert 边界校验**：起止行内容匹配预期，避免删错；例 `assert 'AI产业链' in lines[1395]`）
4. `__init__.py` 追加 `from .子模块 import 公共函数`（显式，避免 import * 污染）
5. 验证：`python -m compileall -q data/data_processor/` + `python -m unittest discover -t . -s tests -p "test_*.py"`（基线 53 测试 / 2 pre-existing 失败：test_auth_guard 401 + test_stock_price_monitor emoji）+ `python -c "import app"` + 公共 API 可达抽查
6. commit（message: `refactor(data_processor): 步骤N 抽出 X 子模块`）

**关键约束**：
- 无循环 import：`__init__.py` 先 `from ._legacy import *`，子模块 `from ._legacy import 工具`（_legacy 总是先加载完）
- _common 抽出前，子模块过渡期从 _legacy import 工具；_common 抽出后，统一改 from ._common
- deferred import（函数内 `from data.data_collector import ...` 等）路径不变
- 模块级副作用 `if USE_PROXY: load_proxy_pool()` 随 ths_client 迁移，触发时机不变（facade import 链）
- 基线测试 2 个 pre-existing 失败（test_auth_guard / test_stock_price_monitor）与本拆分无关，不要试图修复

