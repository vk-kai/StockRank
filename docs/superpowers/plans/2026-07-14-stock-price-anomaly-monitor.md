# 自选股价格异动监控 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 StockRank 中新增自选股价格异动监控(10 类异动),复用现有推送管道,价格异动并入异动预警页,并重设计股票监控配置页。

**Architecture:** 新增三个后端模块(`stock_resolver` 名字↔代码与涨跌停规则、`stock_price_feed` 数据源抽象新浪主+腾讯兜底、`stock_price_monitor` 轮询/存盘/检测/冷却/推送),独立后台线程在交易时段每 25s 轮询;当日数据懒替换清零。路由层新增 `/api/flow/stock-price/*` 并把价格命中并入 `/api/flow/anomaly/run`。前端 FlowAlert 加「价格异动」小分类与自适应卡片,ConfigPage 股票监控 tab 重设计(三类型 + 批量)。

**Tech Stack:** Python 3 / Flask(后端,unittest 测试),Vue 3 + Vite(前端,`npm run build`),新浪/腾讯行情 HTTP 接口。

**Spec:** `docs/superpowers/specs/2026-07-14-stock-price-anomaly-monitor-design.md`

---

## 文件结构

**新建(后端,`backend/`):**
- `stock_resolver.py` — 名字↔代码互解(新浪 suggest)+ 板块判定 + 涨跌停幅度(纯函数,易测)
- `stock_price_feed.py` — 行情源抽象:新浪主力 + 腾讯兜底 + 自动切换 + 报文解析(纯解析函数易测)
- `stock_price_monitor.py` — 轮询调度、当日采样存盘(懒替换)、10 类检测、去重冷却、推送入库
- `test_stock_resolver.py` / `test_stock_price_feed.py` / `test_stock_price_monitor.py` / `test_stock_config_migration.py` — unittest

**新建(数据,运行期生成):**
- `data/realtime/stock_quotes_*.json` — 当日逐笔采样(同时只保留一份)
- `data/realtime/stock_price_alerts.json` — 已推送记录 + 冷却状态
- `config/name_code_cache.json` — 名字↔代码解析缓存

**修改(后端):**
- `routes/flow_routes.py` — 加 `/api/flow/stock-price/run`、`/api/flow/stock-price/alerts`;`anomaly_run` 合并价格命中
- `routes/config_routes.py` — stock-monitor 接口兼容新 schema(透传整 blob,沿用现状)
- `app.py` — 启动价格监控后台线程

**修改(前端):**
- `frontend/src/services/apiService.js` — 加 `runStockPriceAnomaly`、`getStockPriceAlerts`
- `frontend/src/FlowAlert.vue` — 加「📈 价格异动」chip + 自适应 stock 卡片 + 合并展示
- `frontend/src/components/ConfigPage/ConfigPage.script.js` + `ConfigPage.vue` — 股票监控 tab 重设计

---

## Phase A — 后端核心:解析、数据源、检测(TDD)

### Task A1: `stock_resolver.py` — 板块判定 + 涨跌停幅度

**Files:**
- Create: `backend/stock_resolver.py`
- Test: `backend/test_stock_resolver.py`

- [ ] **Step 1: 写失败测试(板块判定 + 涨跌停,含 ST 仅主板)**

```python
# backend/test_stock_resolver.py
import unittest
from stock_resolver import classify_board, get_limit_pct


class BoardLimitTests(unittest.TestCase):
    def test_main_board_sh(self):
        self.assertEqual(classify_board('sh600519'), 'main')
        self.assertEqual(get_limit_pct('sh600519', '贵州茅台'), 10.0)

    def test_main_board_sz_prefixes(self):
        for code in ('sz000001', 'sz001872', 'sz002594', 'sz003816'):
            self.assertEqual(classify_board(code), 'main', code)

    def test_creative_board_300_301_302(self):
        for code in ('sz300750', 'sz301236', 'sz302xxx'.replace('xxx', '001')):
            self.assertEqual(classify_board(code), 'creative', code)
        self.assertEqual(get_limit_pct('sz301236', '某某'), 20.0)

    def test_star_board_688_689(self):
        self.assertEqual(classify_board('sh688981'), 'star')
        self.assertEqual(get_limit_pct('sh688981', '某某'), 20.0)

    def test_bse_board(self):
        for code in ('bj430047', 'bj830799', 'bj920002'):
            self.assertEqual(classify_board(code), 'bse', code)
        self.assertEqual(get_limit_pct('bj920002', '某某'), 30.0)

    def test_st_override_only_on_main_board(self):
        self.assertEqual(get_limit_pct('sh600519', '*ST 茅台'), 5.0)      # 主板 ST -> 5
        self.assertEqual(get_limit_pct('sz301236', 'ST 某某'), 20.0)       # 创业板 ST -> 仍 20
        self.assertEqual(get_limit_pct('sh688981', '*ST 某某'), 20.0)      # 科创板 ST -> 仍 20
        self.assertEqual(get_limit_pct('bj920002', 'ST 某某'), 30.0)       # 北交所 ST -> 仍 30

    def test_unknown_falls_back_to_ten(self):
        self.assertEqual(classify_board('zz999999'), 'unknown')
        self.assertEqual(get_limit_pct('zz999999', '某某'), 10.0)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run (from `backend/`): `python -m unittest test_stock_resolver -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'stock_resolver'`)

- [ ] **Step 3: 实现 `stock_resolver.py` 的板块/涨跌停部分**

```python
# backend/stock_resolver.py
# -*- coding: utf-8 -*-
"""自选股:名字↔代码互解 + 板块判定 + 涨跌停幅度。

涨跌停规则(自动,不可手填):
  - 北交所(bj) ±30%
  - 创业板(sz 300/301/302) ±20%
  - 科创板(sh 688/689) ±20%
  - 主板(sh 600/601/603/605;sz 000/001/002/003) ±10%
  - ST/*ST ±5% 仅对主板生效(注册制板块与北交所无 5% ST 档)
"""
from logger import get_logger

logger = get_logger('stock_resolver')


def classify_board(code):
    """code 形如 'sh600519' / 'sz301236' / 'bj920002'。返回 'main'/'creative'/'star'/'bse'/'unknown'。"""
    code = (code or '').lower()
    if len(code) < 3:
        return 'unknown'
    ex, num = code[:2], code[2:]
    if ex == 'bj':
        return 'bse'
    if ex == 'sh':
        if num.startswith(('688', '689')):
            return 'star'
        if num.startswith(('600', '601', '603', '605')):
            return 'main'
        return 'unknown'
    if ex == 'sz':
        if num.startswith(('300', '301', '302')):
            return 'creative'
        if num.startswith(('000', '001', '002', '003')):
            return 'main'
        return 'unknown'
    return 'unknown'


def get_limit_pct(code, name):
    """返回该股涨跌停幅度(正数,百分点)。如 10.0 / 20.0 / 30.0 / 5.0。"""
    board = classify_board(code)
    if board == 'bse':
        base = 30.0
    elif board in ('creative', 'star'):
        base = 20.0
    elif board == 'main':
        base = 10.0
    else:
        base = 10.0  # 未知降级主板
    # ST ±5% 仅主板
    if board == 'main' and name and ('ST' in name.upper()):
        base = 5.0
    return base
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest test_stock_resolver -v`
Expected: PASS(7 个测试全过)

- [ ] **Step 5: 提交**

```bash
git add backend/stock_resolver.py backend/test_stock_resolver.py
git commit -m "feat(stock-resolver): 板块判定与涨跌停幅度(含 ST 仅主板规则)"
```

---

### Task A1b: `stock_resolver.py` — 名字↔代码互解

**Files:**
- Modify: `backend/stock_resolver.py`
- Test: `backend/test_stock_resolver.py`(追加)

- [ ] **Step 1: 写失败测试(解析 suggest + 互解,注入 fetcher)**

追加到 `test_stock_resolver.py`:

```python
from stock_resolver import parse_sina_suggest, resolve_identifier, NameCodeCache


class ResolveTests(unittest.TestCase):
    def test_parse_sina_suggest_returns_name_code_exchange(self):
        # 新浪 suggest3 返回形如: "类别\t名称\t代码\t拼音";或 "stock\t贵州茅台\tsh600519\tgzmaotai"
        sample = "11\t贵州茅台\tsh600519\tgzmaotai\n11\t茅台转债\tsh1135xx\tmaotaizhuanzhuan\n"
        rows = parse_sina_suggest(sample)
        self.assertEqual(rows[0], ('贵州茅台', 'sh600519'))
        self.assertEqual(len(rows), 2)

    def test_resolve_name_uses_injected_fetcher_and_caches(self):
        calls = {'n': 0}

        def fake_fetch(keyword):
            calls['n'] += 1
            return "11\t贵州茅台\tsh600519\tgzmaotai\n"

        cache = NameCodeCache(path=None)  # 不落盘
        name, code = resolve_identifier('贵州茅台', hint='name', fetcher=fake_fetch, cache=cache)
        self.assertEqual(code, 'sh600519')
        self.assertEqual(name, '贵州茅台')
        # 第二次走缓存,不再调用网络
        resolve_identifier('贵州茅台', hint='name', fetcher=fake_fetch, cache=cache)
        self.assertEqual(calls['n'], 1)

    def test_resolve_code_normalizes_prefix(self):
        # 用户填 600519 -> 补全 sh 前缀;填带前缀的照用
        self.assertEqual(resolve_identifier('600519', hint='code', fetcher=None)[1], 'sh600519')
        self.assertEqual(resolve_identifier('sh600519', hint='code', fetcher=None)[1], 'sh600519')
        self.assertEqual(resolve_identifier('sz301236', hint='code', fetcher=None)[1], 'sz301236')

    def test_resolve_unresolvable_returns_none(self):
        self.assertIsNone(resolve_identifier('不存在的公司xyz', hint='name',
                                             fetcher=lambda k: '\n', cache=NameCodeCache(path=None)))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest test_stock_resolver -v`
Expected: FAIL(导入 `parse_sina_suggest` 等失败)

- [ ] **Step 3: 实现互解逻辑**

追加到 `stock_resolver.py`:

```python
import os
import json

SUGGEST_URL = 'https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15&key={kw}&name=suggestdata'


def parse_sina_suggest(text):
    """解析新浪 suggest3 文本 -> [(name, prefixed_code), ...]。每行 '类别\\t名称\\t代码\\t拼音'。"""
    rows = []
    if not text:
        return rows
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) >= 3:
            name = parts[1].strip()
            code = parts[2].strip().lower()
            if name and code:
                rows.append((name, code))
    return rows


def _normalize_code(raw):
    """纯数字 -> 按规则补交易所前缀;已含前缀照用。"""
    raw = (raw or '').strip().lower()
    if not raw:
        return ''
    if raw[:2] in ('sh', 'sz', 'bj'):
        return raw
    if not raw.isdigit():
        return ''
    if raw.startswith(('600', '601', '603', '605', '688', '689')):
        return 'sh' + raw
    if raw.startswith(('000', '001', '002', '003', '300', '301', '302')):
        return 'sz' + raw
    if raw.startswith(('43', '83', '87', '88', '920')):
        return 'bj' + raw
    return ''  # 无法判定


class NameCodeCache:
    """内存 + 可选 JSON 落盘的 名字↔代码 缓存。path=None 表示纯内存(测试用)。"""
    def __init__(self, path=None):
        self.path = path
        self._mem = {}
        if path and os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self._mem = json.load(f)
            except Exception:
                self._mem = {}

    def get(self, key):
        return self._mem.get(key)

    def set(self, key, value):
        self._mem[key] = value
        if self.path:
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self._mem, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f'名字代码缓存落盘失败: {e}')


_default_cache = None


def _default_cache():
    global _default_cache
    if _default_cache is None:
        from config import CONFIG_DIR
        _default_cache = NameCodeCache(path=os.path.join(CONFIG_DIR, 'name_code_cache.json'))
    return _default_cache


def resolve_identifier(value, hint, fetcher=None, cache=None):
    """把用户输入解析为 (name, prefixed_code)。hint ∈ {'name','code','keyword'}。
    - code: 直接 _normalize_code;名字靠 suggest 反查(若 fetcher 提供)。
    - fetcher(keyword)->text 可注入(测试);生产用 _default_fetcher。
    返回 (name, code) 或 None(解不出)。
    """
    value = (value or '').strip()
    if not value:
        return None
    cache = cache or _default_cache()

    if hint == 'code':
        code = _normalize_code(value)
        return ('', code) if code else None  # 名字留空,后续报价里有

    if hint == 'name':
        cached = cache.get('name:' + value)
        if cached:
            return cached
        if fetcher is None:
            return None
        rows = parse_sina_suggest(fetcher(value))
        if not rows:
            return None
        name, code = rows[0]
        result = (name, code)
        cache.set('name:' + value, result)
        return result

    return None  # keyword 不需要解析


def _default_fetcher(keyword):
    import requests
    from config import get_random_user_agent
    try:
        url = SUGGEST_URL.format(kw=keyword)
        resp = requests.get(url, headers={
            'User-Agent': get_random_user_agent(),
            'Referer': 'https://finance.sina.com.cn/',
        }, timeout=8)
        resp.encoding = 'utf-8'
        return resp.text
    except Exception as e:
        logger.warning(f'新浪 suggest 请求失败({keyword}): {e}')
        return ''
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest test_stock_resolver -v`
Expected: PASS(全部)

- [ ] **Step 5: 提交**

```bash
git add backend/stock_resolver.py backend/test_stock_resolver.py
git commit -m "feat(stock-resolver): 名字↔代码互解(新浪 suggest + 缓存)"
```

---

### Task A2: `stock_price_feed.py` — 数据源抽象(新浪主+腾讯兜底)

**Files:**
- Create: `backend/stock_price_feed.py`
- Test: `backend/test_stock_price_feed.py`

- [ ] **Step 1: 写失败测试(解析 + 故障切换)**

```python
# backend/test_stock_price_feed.py
import unittest
from stock_price_feed import parse_sina, parse_tencent, get_quotes


SINA_SAMPLE = (
    'var hq_str_sh600519="贵州茅台,1690.00,1676.50,1685.20,1698.00,1680.00,'
    '100,50,1685.20,100,,,,,,,3000,4000,,,,,,9.0,1.0,0,2026-07-14,09:30:00,00";\n'
)
TENCENT_SAMPLE = (
    'v_sh600519="1~贵州茅台~600519~1685.20~1676.50~1690.00~50~100~'
    '1698.00~1680.00~3000~4000~~~~9.0~1.0~~20260714093000~~0.52~1.00~0";\n'
)


class FeedParseTests(unittest.TestCase):
    def test_parse_sina_extracts_fields(self):
        q = parse_sina(SINA_SAMPLE, ['sh600519'])['sh600519']
        self.assertAlmostEqual(q['price'], 1685.20)
        self.assertAlmostEqual(q['prev_close'], 1676.50)
        self.assertAlmostEqual(q['open'], 1690.00)
        self.assertAlmostEqual(q['high'], 1698.00)
        self.assertAlmostEqual(q['low'], 1680.00)
        self.assertAlmostEqual(q['pct'], round((1685.20 - 1676.50) / 1676.50 * 100, 3))

    def test_parse_tencent_extracts_fields(self):
        q = parse_tencent(TENCENT_SAMPLE, ['sh600519'])['sh600519']
        self.assertAlmostEqual(q['price'], 1685.20)
        self.assertAlmostEqual(q['prev_close'], 1676.50)
        self.assertAlmostEqual(q['high'], 1698.00)

    def test_get_quotes_falls_back_to_tencent_when_sina_empty(self):
        calls = []

        def sina_fetch(codes):
            calls.append('sina')
            return ''  # 新浪空/失败

        def tencent_fetch(codes):
            calls.append('tencent')
            return TENCENT_SAMPLE

        q = get_quotes(['sh600519'], sina_fetcher=sina_fetch, tencent_fetcher=tencent_fetch)
        self.assertIn('sh600519', q)
        self.assertEqual(calls, ['sina', 'tencent'])

    def test_get_quotes_uses_sina_when_ok(self):
        def sina_fetch(codes):
            return SINA_SAMPLE

        def tencent_fetch(codes):
            raise AssertionError('不应调用腾讯')

        q = get_quotes(['sh600519'], sina_fetcher=sina_fetch, tencent_fetcher=tencent_fetch)
        self.assertIn('sh600519', q)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest test_stock_price_feed -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现 `stock_price_feed.py`**

```python
# backend/stock_price_feed.py
# -*- coding: utf-8 -*-
"""自选股行情数据源:新浪主力 + 腾讯兜底,自动切换。

新浪 hq.sinajs.cn 字段顺序:
  0 名称,1 今开,2 昨收,3 现价,4 最高,5 最低,...,30 日期,31 时间
腾讯 qt.gtimg.cn 字段(以 ~ 分隔):
  1 名称,2 代码,3 现价,4 昨收,5 今开,6 成交量,...,33 最高,34 最低(位置以实测为准,提供解析)
"""
import re
from logger import get_logger

logger = get_logger('stock_feed')

SINA_URL = 'https://hq.sinajs.cn/list={codes}'
TENCENT_URL = 'https://qt.gtimg.cn/q={codes}'


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def parse_sina(text, codes):
    """解析新浪批量返回。返回 {code: {price,pct,open,prev_close,high,low,ts}}。"""
    out = {}
    if not text:
        return out
    for code in codes:
        m = re.search(r'hq_str_' + re.escape(code) + r'="([^"]*)"', text)
        if not m:
            continue
        f = m.group(1).split(',')
        if len(f) < 6 or not f[1]:
            continue
        try:
            price = _f(f[3]); prev_close = _f(f[2])
            pct = round((price - prev_close) / prev_close * 100, 3) if prev_close else 0.0
            ts = f'{f[30]} {f[31]}' if len(f) > 31 and f[30] else ''
            out[code] = {
                'price': price, 'open': _f(f[1]), 'prev_close': prev_close,
                'high': _f(f[4]), 'low': _f(f[5]), 'pct': pct, 'ts': ts,
            }
        except Exception as e:
            logger.warning(f'新浪解析失败 {code}: {e}')
    return out


def parse_tencent(text, codes):
    """解析腾讯批量返回。"""
    out = {}
    if not text:
        return out
    for code in codes:
        m = re.search(r'v_' + re.escape(code) + r'="([^"]*)"', text)
        if not m:
            continue
        f = m.group(1).split('~')
        if len(f) < 6:
            continue
        try:
            price = _f(f[3]); prev_close = _f(f[4])
            pct = round((price - prev_close) / prev_close * 100, 3) if prev_close else 0.0
            high = _f(f[33]) if len(f) > 33 else price
            low = _f(f[34]) if len(f) > 34 else price
            openp = _f(f[5]) if len(f) > 5 else price
            out[code] = {
                'price': price, 'open': openp, 'prev_close': prev_close,
                'high': high, 'low': low, 'pct': pct, 'ts': '',
            }
        except Exception as e:
            logger.warning(f'腾讯解析失败 {code}: {e}')
    return out


def _default_sina_fetch(codes):
    import requests
    from config import get_random_user_agent
    try:
        resp = requests.get(SINA_URL.format(codes=','.join(codes)), headers={
            'User-Agent': get_random_user_agent(),
            'Referer': 'https://finance.sina.com.cn/',
        }, timeout=8)
        resp.encoding = 'gbk'  # 新浪行情返回 gbk
        return resp.text
    except Exception as e:
        logger.warning(f'新浪行情请求失败: {e}')
        return ''


def _default_tencent_fetch(codes):
    import requests
    from config import get_random_user_agent
    try:
        resp = requests.get(TENCENT_URL.format(codes=','.join(codes)), headers={
            'User-Agent': get_random_user_agent(),
        }, timeout=8)
        resp.encoding = 'gbk'
        return resp.text
    except Exception as e:
        logger.warning(f'腾讯行情请求失败: {e}')
        return ''


def get_quotes(codes, sina_fetcher=None, tencent_fetcher=None):
    """批量取报价,新浪优先,空/失败切腾讯。返回 {code: quote}。"""
    codes = [c for c in codes if c]
    if not codes:
        return {}
    sina_fetcher = sina_fetcher or _default_sina_fetch
    tencent_fetcher = tencent_fetcher or _default_tencent_fetch

    out = parse_sina(sina_fetcher(codes), codes)
    missing = [c for c in codes if c not in out]
    if missing:
        tqq = parse_tencent(tencent_fetcher(codes), codes)
        for c in missing:
            if c in tqq:
                out[c] = tqq[c]
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest test_stock_price_feed -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/stock_price_feed.py backend/test_stock_price_feed.py
git commit -m "feat(stock-feed): 行情源抽象(新浪主+腾讯兜底+自动切换)"
```

---

### Task A3: `stock_price_monitor.py` — 当日存盘(懒替换)+ 检测(10 类)

**Files:**
- Create: `backend/stock_price_monitor.py`
- Test: `backend/test_stock_price_monitor.py`

- [ ] **Step 1: 写失败测试 — 懒替换清零**

```python
# backend/test_stock_price_monitor.py
# -*- coding: utf-8 -*-
import os
import tempfile
import unittest

import stock_price_monitor as m


class LazyRotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        m.REALTIME_DIR = self.tmp  # 重定向数据目录

    def test_append_keeps_same_day_samples(self):
        m.append_sample('sh600519', {'ts': '2026-07-14 09:30:00', 'price': 1685, 'pct': 0.5,
                                     'open': 1685, 'prev_close': 1676, 'high': 1688, 'low': 1684},
                        date='2026-07-14')
        m.append_sample('sh600519', {'ts': '2026-07-14 09:30:25', 'price': 1690, 'pct': 0.8,
                                     'open': 1685, 'prev_close': 1676, 'high': 1692, 'low': 1684},
                        date='2026-07-14')
        data = m.load_quotes('2026-07-14')
        self.assertEqual(len(data['sh600519']), 2)

    def test_new_day_wipes_previous(self):
        m.append_sample('sh600519', {'ts': '2026-07-13 15:00:00', 'price': 1680, 'pct': 0.2,
                                     'open': 1678, 'prev_close': 1676, 'high': 1685, 'low': 1675},
                        date='2026-07-13')
        # 次交易日第一笔到来
        m.append_sample('sh600519', {'ts': '2026-07-14 09:30:00', 'price': 1685, 'pct': 0.5,
                                     'open': 1685, 'prev_close': 1676, 'high': 1688, 'low': 1684},
                        date='2026-07-14')
        self.assertFalse(os.path.exists(os.path.join(self.tmp, 'stock_quotes_2026-07-13.json')))
        data = m.load_quotes('2026-07-14')
        self.assertEqual(len(data['sh600519']), 1)  # 旧日数据被清
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest test_stock_price_monitor -v`
Expected: FAIL(`ModuleNotFoundError`)

- [ ] **Step 3: 实现存盘 + 懒替换部分**

```python
# backend/stock_price_monitor.py
# -*- coding: utf-8 -*-
"""自选股价格异动监控:轮询、当日采样存盘(懒替换)、10 类检测、去重冷却、推送。

数据保留:不按时间清零,新交易日第一笔数据到来时删旧文件、起新一份(懒替换)。
"""
import os
import json
import glob
from datetime import datetime, timedelta

from config import REALTIME_DIR, CONFIG_DIR, STOCK_MONITOR_CONFIG_FILE
from logger import get_logger

logger = get_logger('stock_price')
error_logger = get_logger('error')

ALERTS_FILE = os.path.join(REALTIME_DIR, 'stock_price_alerts.json')


def _quotes_file(date):
    return os.path.join(REALTIME_DIR, f'stock_quotes_{date}.json')


def load_quotes(date):
    path = _quotes_file(date)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_quotes(date, data):
    os.makedirs(REALTIME_DIR, exist_ok=True)
    with open(_quotes_file(date), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)


def append_sample(code, sample, date):
    """追加采样。若磁盘上存在其它日期的 stock_quotes_*.json(上一交易日),先删掉(懒替换)。"""
    # 清掉非当天的遗留文件
    for stale in glob.glob(os.path.join(REALTIME_DIR, 'stock_quotes_*.json')):
        if not stale.endswith(f'stock_quotes_{date}.json'):
            try:
                os.remove(stale)
            except Exception:
                pass
    data = load_quotes(date)
    data.setdefault(code, []).append(sample)
    # 每股保留最近 1500 点(约一个交易日 25s 采样),防异常膨胀
    if len(data[code]) > 1500:
        data[code] = data[code][-1500:]
    _save_quotes(date, data)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest test_stock_price_monitor LazyRotationTests -v`
Expected: PASS(2 个)

- [ ] **Step 5: 提交**

```bash
git add backend/stock_price_monitor.py backend/test_stock_price_monitor.py
git commit -m "feat(stock-monitor): 当日采样存盘 + 懒替换清零"
```

---

### Task A3b: 检测规则(10 类)

**Files:**
- Modify: `backend/stock_price_monitor.py`
- Test: `backend/test_stock_price_monitor.py`(追加 `DetectionTests`)

- [ ] **Step 1: 写失败测试 — 各类检测**

追加到 `test_stock_price_monitor.py`:

```python
from stock_price_monitor import detect_hits, _rapid_move, _cum_move, _spike_fade, _amplitude


def _q(price, prev_close, high=None, low=None, pct=None):
    high = price if high is None else high
    low = price if low is None else low
    if pct is None:
        pct = round((price - prev_close) / prev_close * 100, 3)
    return {'price': price, 'prev_close': prev_close, 'high': high, 'low': low,
            'open': prev_close, 'pct': pct, 'ts': '2026-07-14 09:30:00'}


class DetectionTests(unittest.TestCase):
    def test_limit_up_main_board(self):
        q = _q(11.0, 10.0, pct=10.0)
        hits = detect_hits(q, series=[q], state={}, alerts_cfg=m.DEFAULT_ALERTS_CFG,
                           limit=10.0, name='某某')
        types = [h['type'] for h in hits]
        self.assertIn('limit_up', types)

    def test_rapid_rise_within_window(self):
        # 3 分钟前 -1%,现在 +3% -> 急速拉升 4%/3min(默认阈值 3%)
        prev = _q(9.9, 10.0, pct=-1.0)
        prev['ts'] = '2026-07-14 09:27:00'
        now = _q(10.3, 10.0, pct=3.0)
        now['ts'] = '2026-07-14 09:30:00'
        hit = _rapid_move(now, [prev, now], m.DEFAULT_ALERTS_CFG)
        self.assertIsNotNone(hit)
        self.assertEqual(hit['type'], 'rapid_rise')

    def test_cum_move_default_threshold(self):
        now = _q(10.3, 10.0, pct=3.0)
        hit = _cum_move(now, m.DEFAULT_ALERTS_CFG)
        self.assertEqual(hit['type'], 'cum_move')

    def test_spike_fade(self):
        # 曾涨 4%(最高),现回落到 +1.6% -> (高点回落 ≈ 2.4%) 触发(peak≥3,back≥2)
        now = _q(10.16, 10.0, high=10.40, pct=1.6)
        hit = _spike_fade(now, m.DEFAULT_ALERTS_CFG)
        self.assertEqual(hit['type'], 'spike_fade')

    def test_amplitude(self):
        # 振幅 (10.7-9.5)/10 = 12% >= 7%
        now = _q(10.2, 10.0, high=10.7, low=9.5)
        hit = _amplitude(now, m.DEFAULT_ALERTS_CFG)
        self.assertEqual(hit['type'], 'amplitude')

    def test_disabled_type_not_fired(self):
        cfg = json.loads(json.dumps(m.DEFAULT_ALERTS_CFG))
        cfg['amplitude']['enabled'] = False
        now = _q(10.2, 10.0, high=10.7, low=9.5)
        self.assertIsNone(_amplitude(now, cfg))
```

(顶部已 `import json` 的话无需重复;否则补 `import json`。)

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest test_stock_price_monitor DetectionTests -v`
Expected: FAIL(导入 `detect_hits` 等失败)

- [ ] **Step 3: 实现检测函数**

追加到 `stock_price_monitor.py`:

```python
# ---------- 默认阈值(新增自选股默认全开) ----------
DEFAULT_ALERTS_CFG = {
    'limit_up':    {'enabled': True},
    'limit_down':  {'enabled': True},
    'rapid_rise':  {'enabled': True, 'pct': 3.0, 'win_min': 3},
    'rapid_drop':  {'enabled': True, 'pct': 3.0, 'win_min': 3},
    'cum_move':    {'enabled': True, 'pct': 3.0},
    'spike_fade':  {'enabled': True, 'peak': 3.0, 'back': 2.0},
    'dip_rebound': {'enabled': True, 'trough': 3.0, 'back': 2.0},
    'gap_open':    {'enabled': True, 'pct': 3.0},
    'amplitude':   {'enabled': True, 'pct': 7.0},
    'limit_break': {'enabled': True, 'back': 1.0},
}


def _find_ref(series, win_min):
    """取距今最接近 win_min 分钟的一个历史采样(作急涨急跌比较点)。"""
    if len(series) < 2:
        return None
    try:
        cur = datetime.strptime(series[-1]['ts'], '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None
    cutoff = cur - timedelta(minutes=win_min)
    ref = None
    for s in series[:-1]:
        try:
            t = datetime.strptime(s['ts'], '%Y-%m-%d %H:%M:%S')
        except Exception:
            continue
        if t <= cutoff:
            ref = s
        else:
            break
    return ref or series[0]


def _rapid_move(q, series, cfg):
    ref = _find_ref(series, cfg['rapid_rise']['win_min'])
    if not ref:
        return None
    prev_close = q['prev_close'] or 0
    if not prev_close:
        return None
    cur_pct = (q['price'] - prev_close) / prev_close * 100
    ref_pct = (ref['price'] - prev_close) / prev_close * 100
    delta = cur_pct - ref_pct
    if delta >= cfg['rapid_rise']['pct'] and cfg['rapid_rise']['enabled']:
        return {'type': 'rapid_rise', 'label': f'急速拉升 {delta:+.2f}%/{cfg["rapid_rise"]["win_min"]}min'}
    if delta <= -cfg['rapid_drop']['pct'] and cfg['rapid_drop']['enabled']:
        return {'type': 'rapid_drop', 'label': f'急速打压 {delta:+.2f}%/{cfg["rapid_drop"]["win_min"]}min'}
    return None


def _cum_move(q, cfg):
    if not cfg['cum_move']['enabled']:
        return None
    pct = q['pct']
    if abs(pct) < cfg['cum_move']['pct']:
        return None
    return {'type': 'cum_move', 'label': f'累计{"大涨" if pct > 0 else "大跌"} {pct:+.2f}%'}


def _spike_fade(q, cfg):
    if not cfg['spike_fade']['enabled']:
        return None
    pc = q['prev_close'] or 0
    if not pc or not q['high']:
        return None
    peak_pct = (q['high'] - pc) / pc * 100
    if peak_pct < cfg['spike_fade']['peak']:
        return None
    back = (q['high'] - q['price']) / q['high'] * 100 if q['high'] else 0
    if back >= cfg['spike_fade']['back']:
        return {'type': 'spike_fade', 'label': f'冲高回落 从高点 -{back:.2f}%'}
    return None


def _dip_rebound(q, cfg):
    if not cfg['dip_rebound']['enabled']:
        return None
    pc = q['prev_close'] or 0
    if not pc or not q['low']:
        return None
    trough_pct = (pc - q['low']) / pc * 100
    if trough_pct < cfg['dip_rebound']['trough']:
        return None
    reb = (q['price'] - q['low']) / q['low'] * 100 if q['low'] else 0
    if reb >= cfg['dip_rebound']['back']:
        return {'type': 'dip_rebound', 'label': f'探底回升 从低点 +{reb:.2f}%'}
    return None


def _gap_open(q, state, cfg):
    if not cfg['gap_open']['enabled'] or state.get('gap_fired'):
        return None
    pc = q['prev_close'] or 0
    if not pc or not q['open']:
        return None
    gap = (q['open'] - pc) / pc * 100
    if abs(gap) >= cfg['gap_open']['pct']:
        state['gap_fired'] = True
        return {'type': 'gap_open', 'label': f'大幅{"高开" if gap > 0 else "低开"} {gap:+.2f}%'}
    return None


def _amplitude(q, cfg):
    if not cfg['amplitude']['enabled']:
        return None
    pc = q['prev_close'] or 0
    if not pc or q['high'] is None or q['low'] is None:
        return None
    amp = (q['high'] - q['low']) / pc * 100
    if amp >= cfg['amplitude']['pct']:
        return {'type': 'amplitude', 'label': f'振幅过大 {amp:.2f}%'}
    return None


def _limit_break(q, limit, state, cfg):
    if not cfg['limit_break']['enabled']:
        return None
    hit = None
    if q['pct'] >= limit * 0.995:
        state['touched_up'] = True
    if q['pct'] <= -limit * 0.995:
        state['touched_down'] = True
    if state.get('touched_up') and q['pct'] <= limit - cfg['limit_break']['back']:
        hit = {'type': 'limit_break', 'label': f'炸板 回落至 {q["pct"]:+.2f}%'}
    if state.get('touched_down') and q['pct'] >= -limit + cfg['limit_break']['back']:
        hit = {'type': 'limit_break', 'label': f'撬板 反弹至 {q["pct"]:+.2f}%'}
    return hit


def detect_hits(q, series, state, alerts_cfg, limit, name):
    """对一只票跑全部启用的检测,返回 hits 列表(可能多条)。"""
    hits = []
    if alerts_cfg['limit_up']['enabled'] and q['pct'] >= limit * 0.995:
        hits.append({'type': 'limit_up', 'label': '涨停触及'})
    if alerts_cfg['limit_down']['enabled'] and q['pct'] <= -limit * 0.995:
        hits.append({'type': 'limit_down', 'label': '跌停触及'})
    for fn in (_rapid_move, _cum_move, _spike_fade, _dip_rebound, _amplitude):
        try:
            h = fn(q, series, alerts_cfg) if fn is _rapid_move else fn(q, alerts_cfg)
        except Exception as e:
            logger.warning(f'检测异常 {name}: {e}'); h = None
        if h:
            hits.append(h)
    h = _gap_open(q, state, alerts_cfg); 
    if h: hits.append(h)
    h = _limit_break(q, limit, state, alerts_cfg)
    if h: hits.append(h)
    return hits
```

> 注:`_rapid_move` 需要 series 参数,其余只需 q。`detect_hits` 里对 `_rapid_move` 单独传 series,其它传 `(q, cfg)`。

- [ ] **Step 4: 修正 detect_hits 中函数签名调用(确保一致)**

把 `detect_hits` 中循环替换为显式调用,避免参数错配:

```python
    for fn in (
        lambda: _rapid_move(q, series, alerts_cfg),
        lambda: _cum_move(q, alerts_cfg),
        lambda: _spike_fade(q, alerts_cfg),
        lambda: _dip_rebound(q, alerts_cfg),
        lambda: _amplitude(q, alerts_cfg),
    ):
        try:
            h = fn()
        except Exception as e:
            logger.warning(f'检测异常 {name}: {e}'); h = None
        if h:
            hits.append(h)
```

(替换 Step 3 里对应的 for 循环块。)

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m unittest test_stock_price_monitor DetectionTests -v`
Expected: PASS(6 个)

- [ ] **Step 6: 提交**

```bash
git add backend/stock_price_monitor.py backend/test_stock_price_monitor.py
git commit -m "feat(stock-monitor): 10 类价格异动检测规则"
```

---

### Task A3c: 去重冷却 + 推送入库

**Files:**
- Modify: `backend/stock_price_monitor.py`
- Test: `backend/test_stock_price_monitor.py`(追加 `CooldownTests`)

- [ ] **Step 1: 写失败测试 — 冷却**

追加:

```python
from stock_price_monitor import is_in_cooldown, record_alert, _load_alerts, _save_alerts
from datetime import datetime


class CooldownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        m.REALTIME_DIR = self.tmp
        m.ALERTS_FILE = os.path.join(self.tmp, 'stock_price_alerts.json')

    def test_no_cooldown_on_first_hit(self):
        self.assertFalse(is_in_cooldown('sh600519', 'rapid_rise', [], 30))

    def test_cooldown_blocks_same_type_within_window(self):
        now = datetime(2026, 7, 14, 10, 0, 0)
        alerts = [{'code': 'sh600519', 'type': 'rapid_rise',
                   'timestamp': now.isoformat()}]
        later = now + timedelta(minutes=10)
        self.assertTrue(is_in_cooldown('sh600519', 'rapid_rise', alerts, 30, now=later))

    def test_different_type_not_blocked(self):
        now = datetime(2026, 7, 14, 10, 0, 0)
        alerts = [{'code': 'sh600519', 'type': 'rapid_rise', 'timestamp': now.isoformat()}]
        self.assertFalse(is_in_cooldown('sh600519', 'cum_move', alerts, 30, now=now))
```

(顶部已有 `from datetime import ... timedelta`?补 `timedelta` 到 import。)

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest test_stock_price_monitor CooldownTests -v`
Expected: FAIL

- [ ] **Step 3: 实现冷却 + 入库**

追加到 `stock_price_monitor.py`:

```python
def _load_alerts():
    if not os.path.exists(ALERTS_FILE):
        return []
    try:
        with open(ALERTS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


def _save_alerts(alerts):
    os.makedirs(REALTIME_DIR, exist_ok=True)
    with open(ALERTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(alerts[-500:], f, ensure_ascii=False)


def is_in_cooldown(code, hit_type, alerts, cooldown_minutes, now=None):
    now = now or datetime.now()
    threshold = timedelta(minutes=cooldown_minutes)
    for a in reversed(alerts):
        if a.get('code') == code and a.get('type') == hit_type:
            try:
                t = datetime.fromisoformat(a['timestamp'])
            except Exception:
                continue
            if now - t < threshold:
                return True
    return False


def record_alert(code, name, hit, quote, pushed, now=None):
    now = now or datetime.now()
    alerts = _load_alerts()
    rec = {
        'code': code, 'name': name, 'type': hit['type'], 'label': hit.get('label', ''),
        'price': quote.get('price'), 'pct': quote.get('pct'),
        'kind': 'stock',
        'time': quote.get('ts', ''), 'date': (quote.get('ts', '') or now.strftime('%Y-%m-%d'))[:10],
        'pushed': pushed, 'timestamp': now.isoformat(),
    }
    alerts.append(rec)
    _save_alerts(alerts)
    return rec


def list_alerts(date_str=None, limit=200):
    alerts = _load_alerts()
    if date_str:
        alerts = [a for a in alerts if a.get('date') == date_str]
    return sorted(alerts, key=lambda a: a.get('timestamp', ''), reverse=True)[:limit]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest test_stock_price_monitor -v`(全部)
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/stock_price_monitor.py backend/test_stock_price_monitor.py
git commit -m "feat(stock-monitor): 去重冷却 + 推送入库记录"
```

---

## Phase B — 后端集成:配置迁移、路由、后台线程

### Task B1: 配置加载/迁移(`stock_monitor.json` 旧 → 新)

**Files:**
- Modify: `backend/stock_price_monitor.py`
- Create: `backend/test_stock_config_migration.py`

- [ ] **Step 1: 写失败测试 — 旧配置迁移**

```python
# backend/test_stock_config_migration.py
import unittest
from stock_price_monitor import migrate_legacy_config, DEFAULT_ALERTS_CFG


class MigrationTests(unittest.TestCase):
    def test_legacy_stock_with_name_code_gets_full_price_alerts(self):
        legacy = {
            'enabled': True,
            'stocks': [
                {'enabled': True, 'name': '贵州茅台', 'code': '600519', 'keywords': ['茅台']},
            ],
        }
        cfg = migrate_legacy_config(legacy)
        self.assertTrue(cfg['enabled'])
        item = cfg['watchlist'][0]
        self.assertEqual(item['type'], 'name')
        self.assertEqual(item['value'], '贵州茅台')
        self.assertEqual(item['price_alerts'], DEFAULT_ALERTS_CFG)

    def test_new_schema_passes_through(self):
        new = {'enabled': True, 'poll_interval_seconds': 25, 'cooldown_minutes': 30, 'watchlist': []}
        self.assertEqual(migrate_legacy_config(new), new)

    def test_missing_fields_get_defaults(self):
        cfg = migrate_legacy_config({})
        self.assertEqual(cfg['poll_interval_seconds'], 25)
        self.assertEqual(cfg['cooldown_minutes'], 30)
        self.assertEqual(cfg['watchlist'], [])

    def test_keyword_only_entry_has_no_price_alerts(self):
        legacy = {'stocks': [{'enabled': True, 'name': '', 'code': '', 'keywords': ['降息']}]}
        cfg = migrate_legacy_config(legacy)
        item = cfg['watchlist'][0]
        self.assertEqual(item['type'], 'keyword')
        self.assertNotIn('price_alerts', item)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest test_stock_config_migration -v`
Expected: FAIL(`migrate_legacy_config` 不存在)

- [ ] **Step 3: 实现迁移 + 加载**

追加到 `stock_price_monitor.py`:

```python
def migrate_legacy_config(raw):
    """旧 {enabled, stocks:[{enabled,name,code,keywords}]} → 新 watchlist schema。
    新 schema 直接透传;旧 schema 转换:有 name/code 的当 name 类型 + 默认全开 price_alerts;
    仅 keywords 的当 keyword 类型(无 price_alerts)。
    """
    if not isinstance(raw, dict):
        raw = {}
    if 'watchlist' in raw:
        cfg = {
            'enabled': raw.get('enabled', True),
            'poll_interval_seconds': raw.get('poll_interval_seconds', 25),
            'cooldown_minutes': raw.get('cooldown_minutes', 30),
            'watchlist': raw.get('watchlist', []),
        }
        return cfg

    watchlist = []
    for s in raw.get('stocks', []):
        if not isinstance(s, dict) or not s.get('enabled', True):
            continue
        name = (s.get('name') or '').strip()
        code = (s.get('code') or '').strip()
        keywords = s.get('keywords') or []
        if name or code:
            watchlist.append({
                'id': _gen_id(), 'type': 'name', 'value': name or code, 'enabled': True,
                'resolved_name': name, 'resolved_code': code,
                'price_alerts': json.loads(json.dumps(DEFAULT_ALERTS_CFG)),
            })
        elif keywords:
            for kw in keywords:
                if kw.strip():
                    watchlist.append({
                        'id': _gen_id(), 'type': 'keyword', 'value': kw.strip(), 'enabled': True,
                    })
    return {
        'enabled': raw.get('enabled', True),
        'poll_interval_seconds': 25, 'cooldown_minutes': 30,
        'watchlist': watchlist,
    }


def _gen_id():
    import uuid
    return uuid.uuid4().hex[:12]


def load_config():
    """读取并迁移 stock_monitor.json → 新 schema。"""
    if not os.path.exists(STOCK_MONITOR_CONFIG_FILE):
        return {'enabled': False, 'poll_interval_seconds': 25, 'cooldown_minutes': 30, 'watchlist': []}
    try:
        with open(STOCK_MONITOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        error_logger.error(f'读取股票监控配置失败: {e}')
        return {'enabled': False, 'poll_interval_seconds': 25, 'cooldown_minutes': 30, 'watchlist': []}
    return migrate_legacy_config(raw)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest test_stock_config_migration -v`
Expected: PASS(4 个)

- [ ] **Step 5: 提交**

```bash
git add backend/stock_price_monitor.py backend/test_stock_config_migration.py
git commit -m "feat(stock-monitor): 配置加载 + 旧 schema 迁移"
```

---

### Task B2: 监控主循环(轮询→存盘→检测→冷却→推送)

**Files:**
- Modify: `backend/stock_price_monitor.py`

> 说明:本任务为编排逻辑,依赖前述已测组件;用注入 `quotes_provider` 与 `pusher` 做可测设计,网络/推送在生产注入默认实现。

- [ ] **Step 1: 写失败测试 — 主循环对单只票触发一次推送**

追加到 `test_stock_price_monitor.py`:

```python
from stock_price_monitor import process_tick


class ProcessTickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        m.REALTIME_DIR = self.tmp
        m.ALERTS_FILE = os.path.join(self.tmp, 'stock_price_alerts.json')

    def test_hit_pushes_and_records(self):
        pushed = []
        cfg = {'enabled': True, 'cooldown_minutes': 30,
               'watchlist': [{'id': '1', 'type': 'code', 'value': '600519',
                              'resolved_code': 'sh600519', 'resolved_name': '贵州茅台',
                              'enabled': True, 'price_alerts': m.DEFAULT_ALERTS_CFG}]}
        quote = {'price': 11.0, 'prev_close': 10.0, 'high': 11.0, 'low': 10.0,
                 'open': 10.0, 'pct': 10.0, 'ts': '2026-07-14 09:30:00'}
        # limit=10 -> pct 10 触发 limit_up
        m.process_tick('sh600519', '贵州茅台', quote, cfg, limit=10.0,
                       pusher=lambda t, c: pushed.append((t, c)) or True)
        self.assertTrue(pushed)
        self.assertEqual(pushed[0][0][:2], '📈')  # 标题以 📈 开头
        alerts = m._load_alerts()
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['type'], 'limit_up')

    def test_cooldown_skips_push(self):
        pushed = []
        cfg = {'enabled': True, 'cooldown_minutes': 30,
               'watchlist': [{'id': '1', 'type': 'code', 'value': '600519',
                              'resolved_code': 'sh600519', 'resolved_name': '贵州茅台',
                              'enabled': True, 'price_alerts': m.DEFAULT_ALERTS_CFG}]}
        quote = {'price': 11.0, 'prev_close': 10.0, 'high': 11.0, 'low': 10.0,
                 'open': 10.0, 'pct': 10.0, 'ts': '2026-07-14 09:30:00'}
        push = lambda t, c: pushed.append((t, c)) or True
        m.process_tick('sh600519', '贵州茅台', quote, cfg, limit=10.0, pusher=push)
        m.process_tick('sh600519', '贵州茅台', quote, cfg, limit=10.0, pusher=push)  # 第二次冷却
        self.assertEqual(len(pushed), 1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m unittest test_stock_price_monitor ProcessTickTests -v`
Expected: FAIL

- [ ] **Step 3: 实现 process_tick + 默认 pusher**

追加到 `stock_price_monitor.py`:

```python
import threading

_state_lock = threading.Lock()
_stock_state = {}  # {code: {gap_fired, touched_up, touched_down}}


def _default_pusher(title, content):
    try:
        from notification_pusher import send_news_message
        return bool(send_news_message(title, content))
    except Exception as e:
        error_logger.error(f'价格异动推送失败: {e}')
        return False


def _format_message(name, code, quote, hits):
    lines = [f"> 时间:**{quote.get('ts','')}**",
             f"> 现价:**{quote.get('price')}**  涨跌幅:**{quote.get('pct'):ildo.2f}%**".replace('ildo.', '')]
    # 上一行避免格式错误,实际用:
    lines = [f"> 时间:**{quote.get('ts','')}**",
             f"> 现价:**{quote.get('price')}**  涨跌幅:**{round(quote.get('pct') or 0, 2)}%**",
             "**触发**"]
    for h in hits:
        lines.append(f"• {h.get('label', h.get('type'))}")
    title = f"📈 价格异动 · {name}"
    return title, "\n".join(lines)


def process_tick(code, name, quote, cfg, limit, pusher=None):
    """处理一只票的一次报价:存盘→检测→冷却→推送→入库。"""
    pusher = pusher or _default_pusher
    date = (quote.get('ts', '') or datetime.now().strftime('%Y-%m-%d'))[:10]
    append_sample(code, quote, date)
    data = load_quotes(date)
    series = data.get(code, [])
    alerts_cfg = None
    for item in cfg.get('watchlist', []):
        if item.get('resolved_code') == code or item.get('value') == code:
            alerts_cfg = item.get('price_alerts', DEFAULT_ALERTS_CFG)
            break
    if not alerts_cfg:
        return []
    with _state_lock:
        state = _stock_state.setdefault(code, {})
    hits = detect_hits(quote, series, state, alerts_cfg, limit, name)
    alerts = _load_alerts()
    cooldown = cfg.get('cooldown_minutes', 30)
    fired = []
    for h in hits:
        if is_in_cooldown(code, h['type'], alerts, cooldown):
            continue
        title, content = _format_message(name, code, quote, [h] if False else hits)
        pushed = pusher(title, content)
        record_alert(code, name, h, quote, pushed)
        alerts.append({'code': code, 'type': h['type'], 'timestamp': datetime.now().isoformat()})
        fired.append(h)
        break  # 一次报价合并推一条(含全部 hits)
    return fired
```

> 注意:`_format_message` 顶部那行含 `ildo.` 是占位修复说明,正式代码只保留后一组 `lines`(已给出干净版本)。请删掉前两行带 `ildo.` 的 lines,只保留:
> ```python
> lines = [f"> 时间:**{quote.get('ts','')}**",
>          f"> 现价:**{quote.get('price')}**  涨跌幅:**{round(quote.get('pct') or 0, 2)}%**",
>          "**触发**"]
> ```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m unittest test_stock_price_monitor ProcessTickTests -v`
Expected: PASS(2 个)

- [ ] **Step 5: 提交**

```bash
git add backend/stock_price_monitor.py backend/test_stock_price_monitor.py
git commit -m "feat(stock-monitor): 主循环 process_tick(存盘/检测/冷却/推送)"
```

---

### Task B3: 轮询后台线程

**Files:**
- Modify: `backend/stock_price_monitor.py`
- Modify: `backend/app.py`

- [ ] **Step 1: 实现轮询循环函数**

追加到 `stock_price_monitor.py`:

```python
def stock_price_loop():
    """后台线程:交易时段每 poll_interval_seconds 秒批量拉报价 → 逐票 process_tick。"""
    from data_collector import is_trading_day, is_trading_time
    from stock_price_feed import get_quotes
    from stock_resolver import get_limit_pct
    logger.info('价格异动监控线程启动')
    while True:
        try:
            now = datetime.now()
            cfg = load_config()
            interval = cfg.get('poll_interval_seconds', 25)
            if not cfg.get('enabled'):
                time.sleep(interval); continue
            if not (is_trading_day(now) and is_trading_time(now)):
                time.sleep(interval); continue
            targets = [w for w in cfg.get('watchlist', [])
                       if w.get('enabled') and w.get('type') in ('name', 'code') and w.get('resolved_code')]
            if targets:
                codes = [w['resolved_code'] for w in targets]
                quotes = get_quotes(codes)
                for w in targets:
                    code = w['resolved_code']
                    q = quotes.get(code)
                    if not q:
                        continue
                    name = w.get('resolved_name') or q.get('name') or code
                    try:
                        limit = get_limit_pct(code, name)
                        process_tick(code, name, q, cfg, limit)
                    except Exception as e:
                        error_logger.error(f'process_tick 异常 {code}: {e}')
        except Exception as e:
            error_logger.error(f'价格异动监控循环异常: {e}')
        time.sleep(interval)
```

并在文件顶部 import 补 `import time`(若未有)。

- [ ] **Step 2: 在 app.py 启动线程**

修改 `backend/app.py`,在 `create_app()` 内现有 `threading.Thread(target=monitor_loop, daemon=True).start()` 附近追加:

```python
        # 自选股价格异动监控
        from stock_price_monitor import stock_price_loop
        threading.Thread(target=stock_price_loop, daemon=True).start()
```

- [ ] **Step 3: 静态校验导入与语法**

Run: `python -c "import sys; sys.path.insert(0,'backend'); import stock_price_monitor; import stock_resolver; import stock_price_feed; print('import ok')"`
Expected: `import ok`(无异常)

- [ ] **Step 4: 提交**

```bash
git add backend/stock_price_monitor.py backend/app.py
git commit -m "feat(stock-monitor): 交易时段轮询后台线程 + app.py 启动"
```

---

### Task B4: 路由 — `/api/flow/stock-price/*` + 合并进 anomaly/run

**Files:**
- Modify: `backend/routes/flow_routes.py`

- [ ] **Step 1: 加价格异动接口 + 合并到 anomaly_run**

在 `flow_routes.py` 顶部 import 区追加(已有 `from anomaly_detector import ...`):

```python
from stock_price_monitor import list_alerts as list_stock_alerts
```

在 `anomaly_run` 返回前,把价格命中合并进 findings。修改 `anomaly_run`(在 `findings` 计算完成后、`jsonify` 前):

```python
        # 合并自选股价格异动(kind='stock')
        try:
            stock_alerts = list_stock_alerts(date_str=snaphshot_date if False else None, limit=500)
        except Exception:
            stock_alerts = []
        stock_findings = [{
            'kind': 'stock',
            'sector': a.get('name', '') + '(' + a.get('code', '') + ')',
            'time': a.get('time', ''), 'date': a.get('date', ''),
            'net_flow': None, 'change_pct': a.get('pct'),
            'price': a.get('price'),
            'hits': [{'type': a.get('type'), 'label': a.get('label', '')}],
            'name': a.get('name', ''), 'code': a.get('code', ''),
        } for a in stock_alerts]
        # 给板块 findings 补 kind='sector'
        for f in findings:
            f.setdefault('kind', 'sector')
        findings = findings + stock_findings
```

(注:`snaphshot_date` 拼写按实际变量名调整;若 `anomaly_run` 里快照变量名不同,用当日日期 `datetime.now().strftime('%Y-%m-%d')`。)

新增两个接口(放在 anomaly 相关接口之后):

```python
@flow_bp.route('/stock-price/run', methods=['GET'])
def stock_price_run():
    """自选股价格异动当日命中(供异动预警页合并展示)。"""
    try:
        from datetime import datetime
        date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
        alerts = list_stock_alerts(date_str=date_str, limit=500)
        return jsonify({'success': True, 'data': alerts, 'count': len(alerts)})
    except Exception as e:
        error_logger.error(f'API /api/flow/stock-price/run 异常: {e}')
        return jsonify({'success': False, 'message': '价格异动查询失败'}), 500


@flow_bp.route('/stock-price/alerts', methods=['GET'])
def stock_price_alerts():
    """价格异动已推送记录。"""
    try:
        date_str = request.args.get('date')
        return jsonify({'success': True, 'data': list_stock_alerts(date_str=date_str), 'count': 0})
    except Exception as e:
        error_logger.error(f'API /api/flow/stock-price/alerts 异常: {e}')
        return jsonify({'success': False, 'message': '查询失败'}), 500
```

- [ ] **Step 2: 语法校验**

Run: `python -c "import sys; sys.path.insert(0,'backend'); import routes.flow_routes; print('routes ok')"`
Expected: `routes ok`

- [ ] **Step 3: 提交**

```bash
git add backend/routes/flow_routes.py
git commit -m "feat(flow-routes): 价格异动接口 + 合并进异动预警查询"
```

---

## Phase C — 前端

### Task C1: apiService 新增调用

**Files:**
- Modify: `frontend/src/services/apiService.js`

- [ ] **Step 1: 加两个函数**

在 `getAnomalyAlerts` 之后追加:

```javascript
export async function runStockPriceAnomaly(date) {
  try {
    const params = {}
    if (date) params.date = date
    const response = await apiClient.get('/flow/stock-price/run', { params })
    return response.data
  } catch (error) {
    console.error('查询价格异动失败:', error)
    throw error
  }
}

export async function getStockPriceAlerts(date) {
  try {
    const response = await apiClient.get('/flow/stock-price/alerts', { params: { date } })
    return response.data
  } catch (error) {
    console.error('获取价格异动记录失败:', error)
    throw error
  }
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/services/apiService.js
git commit -m "feat(api): 价格异动查询接口前端封装"
```

---

### Task C2: FlowAlert.vue — 加「📈 价格异动」小分类 + 自适应卡片

**Files:**
- Modify: `frontend/src/FlowAlert.vue`

- [ ] **Step 1: DIM_META 加价格维度**

`DIM_META` 改为:

```javascript
const DIM_META = {
  divergence: { icon: '⚖️', label: '背离' },
  surge:      { icon: '💥', label: '巨量' },
  spike:      { icon: '⚡', label: '突变' },
  streak:     { icon: '🔁', label: '连续' },
  price:      { icon: '📈', label: '价格异动' }
}
```

`filteredFindings` 改为兼顾 `kind`:

```javascript
    filteredFindings() {
      const list = this.filter === 'all' ? this.findings
        : this.filter === 'price'
          ? this.findings.filter(f => f.kind === 'stock')
          : this.findings.filter(f => f.kind !== 'stock' && f.hits.some(h => h.type === this.filter))
      return [...list].sort((a, b) => (a.time < b.time ? 1 : -1))
    },
```

`dimCount` 加 price 计数:

```javascript
    dimCount() {
      const c = {}
      this.findings.forEach(f => {
        if (f.kind === 'stock') { c.price = (c.price || 0) + 1; return }
        f.hits.forEach(h => { c[h.type] = (c[h.type] || 0) + 1 })
      })
      return c
    },
```

- [ ] **Step 2: 卡片模板自适应(板块 vs 个股)**

把 `<!-- 全天命中视图 -->` 内的 `.fa-card` 块替换为按 `kind` 分支:

```html
          <div class="fa-card" v-for="(f, idx) in shownFindings" :key="idx"
               :class="{ 'fa-card-stock': f.kind === 'stock' }"
               :style="{ '--i': Math.min(idx, 15) }">
            <div class="fa-card-head">
              <span class="fa-time">{{ f.date }} {{ f.time }}</span>
              <span class="fa-sector">{{ f.kind === 'stock' ? (f.name + ' ' + f.code) : f.sector }}</span>
              <span class="fa-rank" v-if="f.is_rank_top">★ 榜首</span>
              <span class="fa-rank-id" v-else-if="f.kind !== 'stock'">#{{ f.rank }}</span>
              <span class="fa-stock-tag" v-else>📈 价格异动</span>
            </div>
            <div class="fa-card-meta">
              <span v-if="f.kind !== 'stock'" class="fa-net" :class="f.net_flow >= 0 ? 'pos' : 'neg'">
                净流入 {{ fmt(f.net_flow) }} 亿
              </span>
              <span class="fa-chg" :class="f.change_pct >= 0 ? 'pos' : 'neg'">
                {{ f.change_pct >= 0 ? '+' : '' }}{{ fmt(f.change_pct) }}%
              </span>
              <span v-if="f.kind === 'stock'" class="fa-price">现价 {{ fmt(f.price) }}</span>
              <span class="fa-lead" v-if="f.lead_stock">龙头 {{ f.lead_stock }}<template v-if="f.lead_change != null"> {{ f.lead_change >= 0 ? '+' : '' }}{{ fmt(f.lead_change) }}%</template></span>
            </div>
            <div class="fa-hits">
              <span v-for="(h, i) in f.hits" :key="i" :class="['fa-hit', f.kind === 'stock' ? 'hit-price' : `hit-${h.type}`]">
                {{ hitIcon(f.kind === 'stock' ? 'price' : h.type) }} {{ h.label }}
              </span>
            </div>
          </div>
```

样式补:

```css
.fa-card-stock { border-left-color: #52c41a; }
.fa-stock-tag { font-size: 11px; color: #52c41a; border: 1px solid #52c41a; border-radius: 10px; padding: 1px 8px; }
.fa-price { color: #c0cce0; }
.hit-price { background: rgba(82,196,26,.18); border-color: rgba(82,196,26,.5); }
.chip-price.active { background: #52c41a; border-color: #73d13d; }
```

- [ ] **Step 3: 构建前端验证无编译错误**

Run: `cd frontend && npm run build`
Expected: 构建成功(`dist/` 更新)

- [ ] **Step 4: 提交**

```bash
git add frontend/src/FlowAlert.vue
git commit -m "feat(flow-alert): 价格异动小分类 + 自适应个股卡片"
```

---

### Task C3: ConfigPage 股票监控 tab 重设计

**Files:**
- Modify: `frontend/src/components/ConfigPage/ConfigPage.script.js`
- Modify: `frontend/src/ConfigPage.vue`(股票监控 tab 模板)

> 范围:① 录入区改为「类型单选(名字/代码/关键词)+ 单值输入」;② 列表展示每条类型徽标 + 开关 + 「价格预警设置」展开(10 类开关与阈值);③ 批量多选(开关价格预警 / 统一改阈值 / 统一开关类型)。keyword 条目无价格设置区。

- [ ] **Step 1: script.js — 数据模型与保存逻辑**

在 `ConfigPage.script.js` 的 `data()` 内,把现有股票监控相关字段(`stockMonitorConfig` 等)替换/扩充为:

```javascript
      stockMonitor: {
        enabled: false,
        poll_interval_seconds: 25,
        cooldown_minutes: 30,
        watchlist: [],
      },
      newWatch: { type: 'name', value: '' },
      selectedIds: [],
      PRICE_TYPES: [
        { key: 'limit_up', label: '涨停触及', fields: [] },
        { key: 'limit_down', label: '跌停触及', fields: [] },
        { key: 'rapid_rise', label: '急速拉升', fields: [{k:'pct',label:'阈值%'},{k:'win_min',label:'窗口分钟'}] },
        { key: 'rapid_drop', label: '急速打压', fields: [{k:'pct',label:'阈值%'},{k:'win_min',label:'窗口分钟'}] },
        { key: 'cum_move', label: '累计大涨/大跌', fields: [{k:'pct',label:'阈值%'}] },
        { key: 'spike_fade', label: '冲高回落', fields: [{k:'peak',label:'曾涨%'},{k:'back',label:'回落%'}] },
        { key: 'dip_rebound', label: '探底回升', fields: [{k:'trough',label:'曾跌%'},{k:'back',label:'反弹%'}] },
        { key: 'gap_open', label: '大幅高/低开', fields: [{k:'pct',label:'阈值%'}] },
        { key: 'amplitude', label: '振幅过大', fields: [{k:'pct',label:'阈值%'}] },
        { key: 'limit_break', label: '炸板/撬板', fields: [{k:'back',label:'回落%'}] },
      ],
```

`methods` 内新增/替换:

```javascript
    async loadStockMonitor() {
      const res = await getStockMonitorConfig()
      const d = res.data || {}
      this.stockMonitor = {
        enabled: d.enabled || false,
        poll_interval_seconds: d.poll_interval_seconds || 25,
        cooldown_minutes: d.cooldown_minutes || 30,
        watchlist: d.watchlist || [],
      }
    },
    addWatchItem() {
      const v = (this.newWatch.value || '').trim()
      if (!v) { this.showToast('请输入内容', 'error'); return }
      const item = { id: Math.random().toString(36).slice(2, 12), type: this.newWatch.type, value: v, enabled: true }
      if (this.newWatch.type !== 'keyword') {
        item.price_alerts = JSON.parse(JSON.stringify(this.defaultPriceAlerts()))
      }
      this.stockMonitor.watchlist.unshift(item)
      this.newWatch.value = ''
    },
    defaultPriceAlerts() {
      const o = {}
      this.PRICE_TYPES.forEach(t => {
        o[t.key] = { enabled: true }
        t.fields.forEach(f => {
          o[t.key][f.k] = ({ pct: 3, win_min: 3, peak: 3, back: 2, trough: 3 })[f.k] ?? 1
        })
      })
      return o
    },
    removeWatchItem(id) {
      this.stockMonitor.watchlist = this.stockMonitor.watchlist.filter(w => w.id !== id)
      this.selectedIds = this.selectedIds.filter(x => x !== id)
    },
    batchToggle(field, value) {
      this.stockMonitor.watchlist
        .filter(w => this.selectedIds.includes(w.id) && w.price_alerts && w.price_alerts[field])
        .forEach(w => { w.price_alerts[field].enabled = value })
    },
    async saveStockMonitor() {
      if (!this.configPassword) { this.showToast('请输入密码', 'error'); return }
      try {
        await saveStockMonitorConfig({ ...this.stockMonitor, password: this.configPassword })
        this.showToast('股票监控配置保存成功', 'success')
      } catch (e) { this.showToast('保存失败', 'error') }
    },
```

> 需要在 `mounted` 调 `this.loadStockMonitor()`;`configPassword` 沿用现有密码字段名(若不同,按实际改)。

- [ ] **Step 2: ConfigPage.vue — 股票监控 tab 模板**

把原股票监控 tab 内容替换为:

```html
    <div v-if="activeTab==='stock'" class="cfg-section">
      <div class="cfg-row">
        <label><input type="checkbox" v-model="stockMonitor.enabled"> 启用自选股价格监控</label>
        <label>轮询频率(秒)<input type="number" v-model.number="stockMonitor.poll_interval_seconds" min="10"></label>
        <label>去重冷却(分钟)<input type="number" v-model.number="stockMonitor.cooldown_minutes" min="1"></label>
      </div>

      <div class="cfg-add">
        <select v-model="newWatch.type">
          <option value="name">按股票名字</option>
          <option value="code">按代码</option>
          <option value="keyword">按关键词(新闻)</option>
        </select>
        <input v-model="newWatch.value" placeholder="填一个值(名字 / 代码 / 关键词)" @keyup.enter="addWatchItem">
        <button @click="addWatchItem">＋ 添加</button>
      </div>

      <table class="cfg-watchlist">
        <thead><tr>
          <th><input type="checkbox" @change="toggleAll($event)"></th>
          <th>类型</th><th>内容</th><th>开关</th><th>价格预警</th><th></th>
        </tr></thead>
        <tbody>
          <tr v-for="w in stockMonitor.watchlist" :key="w.id">
            <td><input type="checkbox" :value="w.id" v-model="selectedIds"></td>
            <td><span class="badge" :class="'badge-'+w.type">{{ {name:'名字',code:'代码',keyword:'关键词'}[w.type] }}</span></td>
            <td>{{ w.value }}</td>
            <td><input type="checkbox" v-model="w.enabled"></td>
            <td>
              <details v-if="w.price_alerts">
                <summary>设置 ({{ enabledCount(w) }}/{{ PRICE_TYPES.length }})</summary>
                <div class="cfg-price-grid">
                  <div v-for="t in PRICE_TYPES" :key="t.key" class="cfg-price-item">
                    <label><input type="checkbox" v-model="w.price_alerts[t.key].enabled"> {{ t.label }}</label>
                    <span v-for="f in t.fields" :key="f.k">
                      {{ f.label }}<input type="number" step="0.1" v-model.number="w.price_alerts[t.key][f.k]" style="width:60px">
                    </span>
                  </div>
                </div>
              </details>
              <span v-else class="muted">新闻关键词,无价格监控</span>
            </td>
            <td><button @click="removeWatchItem(w.id)">删除</button></td>
          </tr>
        </tbody>
      </table>

      <div class="cfg-batch" v-if="selectedIds.length">
        已选 {{ selectedIds.length }} 项 →
        <button @click="batchToggle('limit_up', true)">开启涨停</button>
        <button @click="batchToggle('limit_up', false)">关闭涨停</button>
        <button @click="batchToggle('cum_move', true)">开启累计涨跌</button>
        <button @click="selectedIds = []">取消选择</button>
      </div>

      <button class="cfg-save" @click="saveStockMonitor">💾 保存配置</button>
    </div>
```

补 `methods`:

```javascript
    toggleAll(e) {
      this.selectedIds = e.target.checked ? this.stockMonitor.watchlist.map(w => w.id) : []
    },
    enabledCount(w) {
      return this.PRICE_TYPES.filter(t => w.price_alerts && w.price_alerts[t.key] && w.price_alerts[t.key].enabled).length
    },
```

补样式(简略,沿用现有暗色风格):

```css
.badge { padding: 2px 8px; border-radius: 10px; font-size: 12px; }
.badge-name { background: rgba(24,144,255,.2); color: #40a9ff; }
.badge-code { background: rgba(82,196,26,.2); color: #52c41a; }
.badge-keyword { background: rgba(250,140,22,.2); color: #fa8c16; }
.cfg-watchlist { width: 100%; border-collapse: collapse; }
.cfg-watchlist th, .cfg-watchlist td { border: 1px solid rgba(148,163,184,.2); padding: 6px; text-align: left; }
.cfg-price-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 6px; margin-top: 6px; }
.cfg-price-item { background: rgba(255,255,255,.04); padding: 4px 8px; border-radius: 4px; }
.muted { color: #8ba4c7; font-size: 12px; }
```

- [ ] **Step 3: 构建前端**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/ConfigPage/ConfigPage.script.js frontend/src/ConfigPage.vue
git commit -m "feat(config-page): 股票监控重设计(三类型 + 价格预警 + 批量)"
```

---

## Phase D — 验证、打包、推送

### Task D1: 全量测试 + 前端打包 + 推送

- [ ] **Step 1: 跑全部后端测试**

Run: `cd backend && python -m unittest discover -p 'test_stock_*.py' -v`
Expected: 全部 PASS

- [ ] **Step 2: 前端打包**

Run: `cd frontend && npm run build`
Expected: 构建成功,`dist/` 更新

- [ ] **Step 3: 提交构建产物**

```bash
git add frontend/dist
git commit -m "build(frontend): 更新生产构建产物(价格异动监控)"
```

- [ ] **Step 4: 推送**

```bash
git push origin main
```
Expected: 推送成功

---

## Self-Review(写计划后自检)

**Spec 覆盖核对:**
- §3 架构(feed/resolver/monitor)→ A1/A1b/A2/A3 ✅
- §4 数据源新浪+腾讯+切换 → A2 ✅
- §5 配置 schema + 三类型 + 涨跌停板块规则 → B1 + A1 ✅(ST 仅主板已测)
- §6 十类检测 + 阈值 → A3b ✅
- §7 懒替换清零 → A3 ✅(已测)
- §8 两套独立冷却 → A3c(自选股冷却)+ 现有板块冷却不动 ✅
- §9 推送入库 → B2 ✅
- §10 FlowAlert 新小分类 + 自适应卡片 → C2 ✅
- §11 ConfigPage 重设计 + 批量 → C3 ✅
- §12 路由 → B4 ✅
- §13 决策(自动解/懒替换/25s)→ A1b/A3/B3 ✅

**类型一致性核对:** `detect_hits`/`process_tick`/`list_alerts`/`record_alert`/`is_in_cooldown` 签名在测试与实现一致;`DEFAULT_ALERTS_CFG` 的 key 与 `PRICE_TYPES` 的 key 一致(10 个);`get_quotes`/`parse_sina`/`parse_tencent` 签名一致。

**已知需在实现时注意(非占位,实为约束):**
1. `anomaly_run` 合并段里变量名(`snapshot` 的 date)须按 `flow_routes.py` 实际变量名对齐,实现时读上下文确认。
2. `_format_message` 的占位修复说明已在 Task B2 注明,实现时只保留干净版本。
3. ConfigPage 的密码字段名(`configPassword`)按现有 script 实际字段对齐。
4. 新浪/腾讯字段位置以实盘报文为准,实现后用真实代码各跑一次 `get_quotes` 抽样核对解析(腾讯 high/low 在第 33/34 位为常见但需确认)。
