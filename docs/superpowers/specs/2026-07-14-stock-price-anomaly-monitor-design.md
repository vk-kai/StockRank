# 自选股价格异动监控 — 设计文档

- 日期: 2026-07-14
- 状态: 待审
- 关联代码: `数据大盘/StockRank/`

---

## 1. 背景与目标

用户原话要点:

- **不另做桌面 exe**,把"自选股价格异动"加进 StockRank,复用现有异动预警推送管道(飞书 / 企业微信)。覆盖两种场景:电脑前分心(推送 + 浏览器声音)、不在电脑前(手机推送)。
- 异动类型:涨跌停、急速拉升 / 急速打压、冲高回落、探底回升、累计大涨大跌、大幅高低开、振幅过大、炸板 / 撬板。
- 新增自选股**默认全开**所有价格异动,阈值默认**可改**。
- 涨跌停按板块区分(主板 / 创业板 / 科创板 / 北交所 / ST)。
- 数据源**不用东方财富**(有反爬),用更稳定的源。
- 价格异动作为"异动预警"页的**一个新小分类**;"全部"时与板块异动一起展示。
- 板块与自选股**两套独立去重冷却**。
- 股票监控配置页**重设计**:支持 名字 / 代码 / 关键词 三类型(每条只填一个),易管理、支持批量多选。

### 非目标(YAGNI)

- 不做全市场异动雷达(只做自选股,几只 ~ 几十只)。
- 不做独立桌面 exe。
- 不做 Level-2 / 逐笔大单维度(仅价格 + 盘口快照字段)。
- 不改板块资金异动(`anomaly_detector`)的现有判定与推送逻辑,仅做展示层合并。

---

## 2. 现状分析

| 现有件 | 现状 |
|---|---|
| `anomaly_detector.py` | 板块资金异动(背离 / 巨量 / 突变 / 连续),5 分钟一次,推送走 `notification_pusher.send_news_message`,冷却 30min,记录存 `data/realtime/anomaly_alerts.json` |
| `stock_monitor.py` | **新闻关键词命中**(与价格无关) |
| `FlowAlert.vue` | "🚨 资金异动预警"页,4 维筛选 chip +「全天命中 / 已推送」两视图;已内置浏览器通知 + 声音(测试按钮播 `/assets/sounds/important.mp3`) |
| `config/stock_monitor.json` | `{enabled, stocks:[{enabled,name,code,keywords}]}`;接口 `/api/config/stock-monitor` GET/POST |
| 数据源 | 项目现用东财 push2(反爬维护成本高,见 `ths_cookie_refresh.py` / `diagnose_ths_access.py`) |

结论:价格监控这一层**完全缺失**,但推送管道、预警页骨架、配置/路由模式都现成可复用。

---

## 3. 总体架构

新增模块,**不动板块逻辑**:

| 新增 / 改动 | 职责 |
|---|---|
| `backend/stock_price_feed.py`(新) | 数据源抽象:新浪主力 + 腾讯兜底,自动切换,批量取报价 |
| `backend/stock_resolver.py`(新) | 名字 ↔ 代码互解(新浪 suggest,本地缓存) |
| `backend/stock_price_monitor.py`(新) | 轮询调度 → 存盘 → 检测 → 去重 → 推送 |
| `config/stock_monitor.json`(改) | 配置结构重设计 |
| `data/realtime/stock_quotes_<日期>.json`(新) | 当日逐笔采样(懒替换清零) |
| `data/realtime/stock_price_alerts.json`(新) | 已推送记录 + 冷却状态 |
| `routes/flow_routes.py`(改) | 加 `/api/flow/stock-price/*` |
| `routes/config_routes.py`(改) | stock-monitor 接口兼容新 schema |
| `frontend/src/FlowAlert.vue`(改) | 加「📈 价格异动」小分类 + 自适应卡片 |
| `frontend ConfigPage 股票监控 tab`(重设计) | 三类型录入 + 批量管理 |

轮询为**独立后台线程**(app.py 启动,与板块采集隔离),仅交易时段运行。

---

## 4. 数据源

- **主力:新浪** `hq.sinajs.cn/list=sh600519,sz000001,...` —— 批量,字段全(名称 / 开盘 / 昨收 / 现价 / 最高 / 最低 / 时间戳)。需带 `Referer: https://finance.sina.com.cn`。记忆记录新浪 2026-07-14 实测可用。
- **兜底:腾讯** `qt.gtimg.cn/q=sh600519,...` —— 主力失败自动切,反爬更松。
- 抽象接口:`get_quotes(codes: list[str]) -> dict[code -> {price, pct, open, prev_close, high, low, ts}]`,其中 `pct = (price - prev_close) / prev_close * 100`。上层检测逻辑与数据源解耦,日后换源只动这一层。
- code 带交易所前缀(sh / sz),由 `stock_resolver` 给出。

---

## 5. 配置结构(`stock_monitor.json`)

```jsonc
{
  "enabled": true,
  "poll_interval_seconds": 25,        // 轮询频率
  "cooldown_minutes": 30,             // ★ 自选股专用去重冷却(与板块分开)
  "watchlist": [
    {
      "id": "<uuid>",
      "type": "name",                  // ★ 三选一: name | code | keyword
      "value": "贵州茅台",             // ★ 每条只填一个
      "enabled": true,
      "resolved_name": "贵州茅台",     // name/code 互解后存全(keyword 类型无)
      "resolved_code": "sh600519",     // 价格源用,带交易所前缀
      "price_alerts": {                // 新增自选股 ★ 默认全开,阈值默认可改
        "limit_up":    { "enabled": true },
        "limit_down":  { "enabled": true },
        "rapid_rise":  { "enabled": true, "pct": 3, "win_min": 3 },
        "rapid_drop":  { "enabled": true, "pct": 3, "win_min": 3 },
        "cum_move":    { "enabled": true, "pct": 3 },
        "spike_fade":  { "enabled": true, "peak": 3, "back": 2 },
        "dip_rebound": { "enabled": true, "trough": 3, "back": 2 },
        "gap_open":    { "enabled": true, "pct": 3 },
        "amplitude":   { "enabled": true, "pct": 7 },
        "limit_break": { "enabled": true, "back": 1 }
      }
    }
    // type=keyword 的条目:仅新闻命中(沿用 stock_monitor 逻辑),无 price_alerts
  ]
}
```

字段说明:

- `type` 三选一,`value` 仅一个。**保存时校验只填了一个**,否则报错。
- name / code 类型:resolver 互解后写 `resolved_name` + `resolved_code`(带前缀)。解不到则提示用户改填代码。
- keyword 类型:仅新闻命中,无 `price_alerts`、无价格轮询。
- `price_alerts` 10 类:新增自选股默认全开;每类阈值默认可改。
- `poll_interval_seconds`(默认 25)、`cooldown_minutes`(默认 30,自选股专用)。

### 涨跌停板块规则(自动,不可手填阈值)

按 `resolved_code` 的**交易所前缀(sh / sz / bj)+ 数字前缀**判定(交易所前缀由 resolver 给出):

| 交易所 | 数字前缀 | 板块 | 涨跌停 |
|---|---|---|---|
| sz | **300 / 301 / 302** | 创业板 | ±20% |
| sz | 000 / 001 / 002 / 003 | 深市主板 | ±10% |
| sh | 688 / 689 | 科创板 | ±20% |
| sh | 600 / 601 / 603 / 605 | 沪市主板 | ±10% |
| bj | 任意(43 / 83 / 87 / 88 / 920 等) | 北交所 | ±30% |

**ST 规则(重要)**:`*ST` / `ST` 的 ±5% 限制**只对主板生效**;创业板、科创板(注册制板块)与北交所的 ST 股仍按各自板块 ±20% / ±30%,**无 5% 这档**。故 ST 覆盖**仅当板块判定为「主板」时**才应用,否则会令创业板 ST 票被错判 5%、永远触不到真实 20% 涨停线。

判定顺序:① 交易所前缀 → ② 数字前缀定板块与基线 → ③ **仅主板**且名称含 `ST` / `*ST` 时覆盖为 ±5%。代码无法识别时降级 ±10% 并记日志。

---

## 6. 价格异动类型与检测规则

每次采样落盘后,对每只启用的 name/code 票逐一跑下表。命中的类型汇集为一次「价格异动事件」,统一去重 + 推送。

| 类型 | key | 判定逻辑 | 依赖数据 | 默认阈值 |
|---|---|---|---|---|
| 涨停触及 | `limit_up` | `pct >= +limit*0.995` | 单点 | 板块自动 |
| 跌停触及 | `limit_down` | `pct <= -limit*0.995` | 单点 | 板块自动 |
| 急速拉升 | `rapid_rise` | 现价相对 `win_min` 分钟前的价涨 `>= pct` | 滚动窗口 | 3% / 3min |
| 急速打压 | `rapid_drop` | 现价相对 `win_min` 分钟前的价跌 `>= pct` | 滚动窗口 | 3% / 3min |
| 累计大涨/大跌 | `cum_move` | 当日 `abs(pct) >= pct`(涨/跌方向区分推送文案) | 单点 | ±3% |
| 冲高回落 | `spike_fade` | 当日最高涨幅 `>= peak` 且 `(最高-现价)/最高*100 >= back` | 盘中最高 | peak 3 / back 2 |
| 探底回升 | `dip_rebound` | 当日最低跌幅 `>= trough` 且 `(现价-最低)/最低*100 >= back` | 盘中最低 | trough 3 / back 2 |
| 大幅高/低开 | `gap_open` | `(开盘-昨收)/昨收` 越过 ±pct,开盘后 10 分钟内仅触发一次 | 开盘价 | 3% |
| 振幅过大 | `amplitude` | `(最高-最低)/昨收*100 >= pct` | 最高 / 最低 | 7% |
| 炸板 / 撬板 | `limit_break` | 曾触涨停后现 pct 跌破涨停线 `>= back`(炸板);曾触跌停后反弹 `>= back`(撬板) | 状态记忆 | back 1 |

实现要点:

- **滚动窗口**:`rapid_rise/drop` 取距今最接近 `win_min` 分钟的一个历史采样作比较点;25s 采样下 3min ≈ 7 个点,够用。
- **盘中最高 / 最低**:随采样实时更新当日 running max/min(亦可用报价字段 high/low,双重取值)。
- **状态记忆**:`limit_break` 需每只票维护当日布尔标志 `touched_up` / `touched_down`,跨日复位(随懒替换清零一并重置)。
- **去重粒度**:按 `(resolved_code, 类型key)` 组合,在 `cooldown_minutes` 内只推一次。

---

## 7. 数据采集与存储

- **轮询**:交易时段(工作日 9:25–11:30、13:00–15:00)每 `poll_interval_seconds`(默认 25)秒,批量拉全部 name/code 条目报价(一次请求)。非交易时段线程睡眠不请求。
- **存盘**:`data/realtime/stock_quotes_<YYYY-MM-DD>.json`,结构:
  ```jsonc
  { "sh600519": [ {"ts":"2026-07-14 09:25:00","price":1680.0,"pct":0.21,"open":1680.0,"prev_close":1676.5,"high":1688.0,"low":1679.0}, ... ] }
  ```
- **★ 懒替换清零(关键,非时间驱动)**:每次写入前比较本次 `ts` 的日期与当前文件日期,不同 → 删旧文件、起新的一份。同一交易日只追加。周末 / 节假日保留上一交易日的数据,直到**下一交易日第一笔报价到来**才整份顶替。
- 容量:25s × ~4.5h ≈ 650 点/票;几只 ~ 几十只自选,单文件可控。

---

## 8. 去重冷却(两套独立)

- **板块资金异动**:沿用 `anomaly_detector` 的 `cooldown_minutes`(默认 30),不动。
- **自选股价格异动**:`stock_monitor.json` 新 `cooldown_minutes`(默认 30);按 `(resolved_code + 类型key)` 去重;状态存 `data/realtime/stock_price_alerts.json`。

两套互不影响。

---

## 9. 推送与归类

- 命中 → 去重 → `notification_pusher.send_news_message(title, content)`(同板块异动通道:飞书 + 企业微信)→ 记录入 `stock_price_alerts.json`。
- 消息格式:标题 `📈 价格异动 · <股票名>`;正文含 时间 / 现价 / 涨跌幅 / 触发类型与数值(如「急速拉升 +3.2%(3min)」「冲高回落 从高点 -2.1%」)。
- 浏览器声音 / 弹窗(可选增强):FlowAlert 已有通知 + 声音基础设施;初版前端在「刷新」时呈现新异动,后续可加 SSE / 前端轮询做实时响铃(非本期必需)。

---

## 10. 异动预警页(FlowAlert)改造

- 筛选条新增 `📈 价格异动` chip,与现有 4 维(背离 / 巨量 / 突变 / 连续)并列;`DIM_META` 增 price 维度。
- **"全部"展示全部**(板块 + 价格混排,按时间倒序)。
- 后端 `/api/flow/anomaly/run` 改为合并返回:板块全天命中(`detect_full_day`) + 价格当日命中(读 `stock_price_alerts.json`),每条带 `kind: sector | stock`。
- **卡片自适应**:
  - sector 卡片(现状):板块 / 净流入 / 龙头 + 维度 chip。
  - stock 卡片(新):时间 · 股票名(代码) · 现价 · 涨跌幅 + 命中类型彩色 chip(复用 hit-chip 样式,新增 `price-*` 配色)。
- 统计区 / `dimCount` 计入价格类。
- 「已推送记录」视图合并板块 + 价格已推送。

---

## 11. 配置页(ConfigPage · 股票监控 tab)重设计

- **监控列表**:每行 = 类型徽标(名字 / 代码 / 关键词)+ 内容 + 开关 +「价格预警设置」(展开看 / 改 10 类开关与阈值)。keyword 行无价格设置区。
- **新增条目**:先选类型(单选)→ 填一个值 → 保存时 resolver 互解 → 新增默认 10 项全开。
- **批量多选**:勾选多只 → 一键 开 / 关价格预警、统一改某类阈值、统一开关某异动类型。
- 目标:不用再纠结 name / code / keywords 三框怎么填,一眼看清每只票开了哪些预警。

---

## 12. 后端接口

新增(挂 `flow_bp`,受全局登录拦截保护):

- `GET /api/flow/stock-price/run` —— 返回当日价格异动命中(供 FlowAlert 合并)。
- `GET /api/flow/stock-price/alerts` —— 已推送记录。

改动:

- `config_routes.py` 的 stock-monitor GET/POST:接受新 schema(沿用现状「整 blob 透传 + POST 校验密码」),无需新结构。

---

## 13. 关键决策记录

1. **名字 ↔ 代码**:自动解 + 兜底手填(解不到则提示改填代码)。
2. **数据保留**:**懒替换** —— 新交易日第一笔数据到来才清旧,非时间驱动;周末 / 节假日保留上一交易日数据。
3. **轮询频率**:25 秒。

---

## 14. 落地步骤概览

1. 后端:`stock_price_feed`(含 `stock_resolver`)→ `stock_price_monitor`(检测 + 存盘 + 懒替换 + 冷却)→ 推送接入 → `flow_routes` 接口。
2. 配置:新 schema + **旧 `stock_monitor.json` 迁移**(原 `stocks[]` → 新 `watchlist[]`:name/code 补全互解 + 默认全开 price_alerts;含 keywords 的按需转 keyword 条目)。
3. 前端:ConfigPage 股票监控重设计 → FlowAlert「价格异动」小分类与自适应卡片。
4. 自测:单只票模拟各类型命中;阈值可改;冷却生效;懒替换跨日;涨跌停板块规则;新浪 Referer + 腾讯兜底切换。

---

## 15. 风险与备注

- 新浪 `hq.sinajs.cn` 需 Referer,偶发限频 → 腾讯兜底 + 失败计数自动切源。
- 急速拉升 / 打压 精度受 25s 采样限制(可接受;加密会增源限频风险)。
- 旧 `stock_monitor.json` 迁移需保证不丢既有 keyword 监控。
- 交易时段判定需处理节假日(可先用固定时段 + 工作日,节假日熔断后续再细化)。
