"""AI 产业链外部环境温度计。

7 个对 AI 产业链（封测/先进封装/AI 硬件，如长电科技）影响显著的领先指标。
依赖 _common 的 _safe_float/error_logger/MARKET_INDEX_URL/GLOBAL_INDICES_CACHE_FILE。
"""
import os
import json
import re
import time
import random
from datetime import datetime

import requests

from core.config import REALTIME_DIR, get_random_user_agent, get_eastmoney_headers, em_request
from ._common import _safe_float, error_logger, MARKET_INDEX_URL, GLOBAL_INDICES_CACHE_FILE


# 7个对AI产业链（封测/先进封装/AI硬件，如长电科技）影响显著的领先指标。
# 上色按"对AI链利好/利空"判定而非单纯涨跌：需求链涨=利好，宏观链涨=利空。
# 数据源：美股3 + 美元指数 + 韩国KOSPI → 新浪；韩股2(SK海力士/三星) → 腾讯财经(kr代码)；
#         KOSPI 东财/全球指数缓存兜底；美债10年 → 美国财政部日线CSV(无key, 国内可访问)。
AI_CHAIN_CONFIG = [
    # (key, 展示名, 链(demand/macro), 新浪代码, 腾讯代码, 东财secid(仅兜底), 区域)
    ('nvda',    '英伟达',     'demand', 'gb_nvda', None,         None,         '美股'),
    ('soxx',    '费城半导体', 'demand', 'gb_soxx', None,         None,         '美股'),   # SOXX ETF 代理 SOX 指数
    ('tsm',     '台积电',     'demand', 'gb_tsm',  None,         None,         '美股'),
    ('skhynix', 'SK海力士',   'demand', None,     'kr000660',   '177.000660', '韩股'),
    ('samsung', '三星电子',   'demand', None,     'kr005930',   '177.005930', '韩股'),
    ('kospi',   '韩国综合',   'demand', 'b_KOSPI', None,        '100.KS11',   '韩国'),   # KOSPI(新浪优先, 东财兜底)
    ('dxy',     '美元指数',   'macro',  'DINIW',   None,        None,         '外汇'),
    ('us10y',   '美债10年',   'macro',  None,      None,        None,         '美债'),
]
AI_CHAIN_CACHE_FILE = os.path.join(REALTIME_DIR, 'ai_chain_cache.json')
AI_CHAIN_NEUTRAL_THRESHOLD = 0.0005  # |change|(分数) < 0.05% 视为中性


def _ai_chain_impact(chain, change_fraction):
    """单项对AI链的影响方向。change 为分数(如 -0.0352)。"""
    if change_fraction is None or abs(change_fraction) < AI_CHAIN_NEUTRAL_THRESHOLD:
        return '中性'
    if chain == 'demand':
        return '利好' if change_fraction > 0 else '利空'
    return '利空' if change_fraction > 0 else '利好'  # macro：美元/美债涨=利空


def _ai_chain_summary(indicators):
    """综合环境灯：按总量多数表决（全市场利好总数 vs 利空总数）。

    需求链/宏观链仍分别给出 signal 供展示，但 overall 直接看利好 vs 利空的总数——
    避免“宏观链 1 个利空就否决需求链 6 个利好”的过度敏感（原宏观一票否决逻辑已弃用）。
    例：6 利好 / 1 利空 → 偏多（不再因宏观 1 利空而判偏空）。
    """
    def signal(items):
        bull = sum(1 for i in items if i.get('impact') == '利好')
        bear = sum(1 for i in items if i.get('impact') == '利空')
        if bull > bear:
            return '偏多', bull, bear
        if bear > bull:
            return '偏空', bull, bear
        return '中性', bull, bear

    demand = [i for i in indicators if i.get('chain') == 'demand']
    macro = [i for i in indicators if i.get('chain') == 'macro']
    d_sig, d_bull, d_bear = signal(demand)
    m_sig, m_bull, m_bear = signal(macro)
    total_bull = d_bull + m_bull
    total_bear = d_bear + m_bear
    if total_bull > total_bear:
        overall = '偏多'
    elif total_bear > total_bull:
        overall = '偏空'
    else:
        overall = '中性'
    return {
        'overall': overall,
        'demand_signal': d_sig,
        'macro_signal': m_sig,
        'bull_count': total_bull,
        'bear_count': total_bear,
    }


def _fetch_ai_chain_sina():
    """新浪批量：美股(gb_)3个 + 美元指数(DINIW)。返回 {key: {price, change, change_amount}}"""
    out = {}
    targets = [c for c in AI_CHAIN_CONFIG if c[3]]
    if not targets:
        return out
    headers = {'User-Agent': get_random_user_agent(), 'Referer': 'https://finance.sina.com.cn/'}
    try:
        resp = requests.get('https://hq.sinajs.cn/list=' + ','.join(c[3] for c in targets),
                            headers=headers, timeout=6)
        resp.encoding = 'gbk'
        code_to_key = {c[3]: c[0] for c in targets}
        for line in resp.text.strip().split('\n'):
            m = re.search(r'hq_str_(\w+)="([^"]*)"', line)
            if not m:
                continue
            code, key = m.group(1), code_to_key.get(m.group(1))
            if not key:
                continue
            fields = m.group(2).split(',')
            try:
                if code.startswith('gb_'):
                    # 美股: [1]=现价 [2]=涨跌幅% [4]=涨跌额
                    if len(fields) > 4 and fields[1]:
                        price = float(fields[1])
                        cp = _safe_float(fields[2], None)
                        amt = _safe_float(fields[4], None)
                        if cp is None and amt is not None:
                            prev = price - amt
                            cp = ((price - prev) / prev * 100) if prev else None
                        out[key] = {
                            'price': price,
                            'change': (cp / 100) if cp is not None else None,
                            'change_amount': amt,
                        }
                elif code == 'DINIW':
                    # 美元指数: [1]=现价, [3]=昨结(推导涨跌)
                    if len(fields) > 3 and fields[1]:
                        price = float(fields[1])
                        prev = _safe_float(fields[3], None)
                        if prev and prev > 0:
                            out[key] = {'price': price,
                                        'change': (price - prev) / prev,
                                        'change_amount': price - prev}
                        else:
                            out[key] = {'price': price, 'change': None, 'change_amount': None}
                elif code.startswith('b_'):
                    # 国际指数(如 b_KOSPI 韩国综合): [1]=现价 [2]=涨跌额 [3]=涨跌幅%
                    if len(fields) > 3 and fields[1]:
                        price = float(fields[1])
                        cp = _safe_float(fields[3], None)
                        if cp is not None:
                            out[key] = {'price': price,
                                        'change': cp / 100,
                                        'change_amount': price * cp / 100}
            except (ValueError, IndexError):
                continue
    except Exception as e:
        error_logger.warning(f"新浪AI链指标获取失败: {e}")
    return out


def _fetch_ai_chain_tencent():
    """腾讯财经批量：韩股(SK海力士 kr000660 + 三星电子 kr005930)。
    返回 {key: {price, change, change_amount}}

    腾讯港股/韩股格式(352字段)：
    [3]=昨收 [5]=现价 [31]=涨跌额 [32]=涨跌幅%
    """
    out = {}
    targets = [c for c in AI_CHAIN_CONFIG if c[4]]
    if not targets:
        return out
    try:
        codes = ','.join(c[4] for c in targets)
        resp = requests.get(f'https://qt.gtimg.cn/q={codes}', timeout=6)
        resp.encoding = 'utf-8'
        code_to_key = {c[4]: c[0] for c in targets}
        for line in resp.text.strip().split(';'):
            line = line.strip()
            if '="' not in line:
                continue
            prefix = line.split('="', 1)[0].split('.')[-1]  # e.g. v_kr000660 -> kr000660
            # 也可能是 v_kr000660 格式
            if prefix.startswith('v_'):
                prefix = prefix[2:]
            key = code_to_key.get(prefix)
            if not key:
                continue
            content = line.split('="', 1)[1].rstrip('"')
            fields = content.split('~')
            if len(fields) < 33:
                continue
            try:
                prev_close = _safe_float(fields[3], None)
                price = _safe_float(fields[5], None)
                change_pct = _safe_float(fields[32], None)
                change_amt = _safe_float(fields[31], None)
                if price is not None and change_pct is not None:
                    out[key] = {
                        'price': price,
                        'change': change_pct / 100,
                        'change_amount': change_amt,
                    }
            except (ValueError, IndexError):
                continue
    except Exception as e:
        error_logger.warning(f"腾讯财经AI链指标(韩股)获取失败: {e}")
    return out


def _fetch_ai_chain_eastmoney():
    """东方财富兜底：韩股(SK海力士 + 三星)。仅在腾讯财经失败时调用。
    返回 {key: {price, change, change_amount}}"""
    out = {}
    targets = [c for c in AI_CHAIN_CONFIG if c[5]]
    if not targets:
        return out
    params = {
        'fltt': 2, 'invt': 2,
        'fields': 'f2,f3,f4,f12,f14',
        'secids': ','.join(c[5] for c in targets)
    }
    data = None
    max_retries = 2
    for attempt in range(max_retries):
        headers = get_eastmoney_headers()
        try:
            resp = em_request(MARKET_INDEX_URL, params=params, headers=headers, timeout=8)
            if resp is not None:
                resp.raise_for_status()
                data = resp.json()
                break
        except Exception as e:
            if attempt < max_retries - 1:
                backoff = 0.5 * (2 ** attempt) + random.uniform(0, 0.5)
                time.sleep(backoff)
            else:
                error_logger.warning(f"东方财富AI链指标(韩股)兜底获取失败(重试{max_retries}次): {e}")
    if data:
        diff = data.get('data', {}).get('diff', []) if data.get('data') else []
        em_map = {item.get('f12'): item for item in diff}
        for c in targets:
            key = c[0]
            secid = c[5]
            item = em_map.get(secid.split('.')[-1])
            if item and item.get('f2') not in ('-', None):
                out[key] = {
                    'price': float(item.get('f2', 0) or 0),
                    'change': float(item.get('f3', 0) or 0) / 100,
                    'change_amount': float(item.get('f4', 0) or 0),
                }

    # KOSPI 复用"全球股市地图"已缓存的实时值(同源 100.KS11，change 为分数)
    if 'kospi' not in out:
        try:
            if os.path.exists(GLOBAL_INDICES_CACHE_FILE):
                with open(GLOBAL_INDICES_CACHE_FILE, 'r', encoding='utf-8') as f:
                    gcache = json.load(f)
                v = gcache.get('100.KS11')
                if v and v.get('price') is not None and v.get('change') is not None:
                    out['kospi'] = {
                        'price': float(v['price']),
                        'change': v['change'],
                        'change_amount': v.get('change_amount'),
                    }
        except Exception as e:
            error_logger.warning(f"KOSPI复用全球指数缓存失败: {e}")
    return out


def _fetch_ai_chain_us10y():
    """美国财政部日线美债10年收益率。CSV 新日期在前，取首行=最新。返回 {price, change, change_amount, date} 或 {}"""
    try:
        year = datetime.now().year
        url = (f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
               f"&field_tdr_date_value={year}&page&_format=csv")
        resp = requests.get(url, headers={'User-Agent': get_random_user_agent()}, timeout=8)
        resp.raise_for_status()
        lines = [ln for ln in resp.text.splitlines() if ln.strip()]
        col = None
        hidx = None
        for i, ln in enumerate(lines):
            if '10 yr' in ln.lower():
                header = ln.split(',')
                for j, h in enumerate(header):
                    if h.strip().strip('"').lower() == '10 yr':
                        col, hidx = j, i
                        break
                if col is not None:
                    break
        if col is None or hidx is None or hidx + 2 >= len(lines):
            return {}
        latest = lines[hidx + 1].split(',')
        prev = lines[hidx + 2].split(',')
        price = _safe_float(latest[col], None) if len(latest) > col else None
        prev_price = _safe_float(prev[col], None) if len(prev) > col else None
        if price is None:
            return {}
        change = ((price - prev_price) / prev_price) if prev_price else None
        return {
            'price': price,
            'change': change,
            'change_amount': (price - prev_price) if prev_price is not None else None,
            'date': latest[0].strip(),
        }
    except Exception as e:
        error_logger.warning(f"美债10年(财政部CSV)获取失败: {e}")
        return {}


def get_ai_chain_indicators():
    """AI产业链外部环境温度计：7个领先指标，多源并发+缓存兜底，预算 impact 与综合环境灯。
    数据源优先级：新浪(美股+KOSPI+美元) > 腾讯财经(韩股) > 东方财富(兜底) > 缓存。
    返回 {indicators:[...], summary:{...}, update_time, source}，失败返回 None。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from concurrent.futures import TimeoutError as _FutTimeout
    ex = ThreadPoolExecutor(max_workers=4)
    fut_map = {
        ex.submit(_fetch_ai_chain_sina): 'sina',        # 美股3 + KOSPI + 美元指数
        ex.submit(_fetch_ai_chain_tencent): 'tencent',   # 韩股2(主源)
        ex.submit(_fetch_ai_chain_eastmoney): 'em',      # 韩股2(兜底)
        ex.submit(_fetch_ai_chain_us10y): 'us10y',       # 美债10年(日线)
    }
    results = {'sina': {}, 'tencent': {}, 'em': {}, 'us10y': None}
    try:
        for fut in as_completed(fut_map, timeout=10):
            kind = fut_map[fut]
            try:
                results[kind] = fut.result()
            except Exception as e:
                error_logger.warning(f"AI链数据源({kind})异常: {e}")
    except _FutTimeout:
        error_logger.warning("AI链部分数据源超时,使用已得数据 + 缓存兜底")
    ex.shutdown(wait=False)
    sina_data = results['sina'] or {}
    tencent_data = results['tencent'] or {}
    em_data = results['em'] or {}
    us10y = results['us10y']

    raw_map = {}
    for k, v in em_data.items():
        raw_map[k] = (v, 'eastmoney')     # 东财最低优先级
    for k, v in tencent_data.items():
        raw_map[k] = (v, 'tencent')       # 腾讯覆盖东财
    for k, v in sina_data.items():
        raw_map[k] = (v, 'sina')          # 新浪最高优先级
    if us10y:
        raw_map['us10y'] = (us10y, 'treasury')

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    result = {}
    for cfg in AI_CHAIN_CONFIG:
        key, name, chain = cfg[0], cfg[1], cfg[2]
        region = cfg[6]
        pair = raw_map.get(key)
        if not pair:
            continue
        raw, source = pair
        change = raw.get('change')
        item = {
            'key': key, 'name': name, 'chain': chain, 'region': region,
            'price': round(raw['price'], 4) if raw.get('price') is not None else None,
            'change': change,
            'change_amount': raw.get('change_amount'),
            'impact': _ai_chain_impact(chain, change),
            'source': source,
            'update_time': now,
        }
        if key == 'us10y' and raw.get('date'):
            item['date'] = raw['date']
        result[key] = item

    # 缓存兜底：任一源偶发缺失时用上次成功值补齐(标 stale)
    try:
        cache = {}
        if os.path.exists(AI_CHAIN_CACHE_FILE):
            with open(AI_CHAIN_CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
        for cfg in AI_CHAIN_CONFIG:
            key = cfg[0]
            if key not in result and key in cache:
                v = dict(cache[key])
                v['stale'] = True
                result[key] = v
        fresh = {k: v for k, v in result.items() if not v.get('stale')}
        if fresh:
            cache.update(fresh)
            with open(AI_CHAIN_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        error_logger.warning(f"AI链指标缓存读写失败: {e}")

    indicators = [result[c[0]] for c in AI_CHAIN_CONFIG if c[0] in result]
    if not indicators:
        error_logger.error("AI链指标全部获取失败：所有数据源均不可用")
        return None

    sources = []
    if sina_data:
        sources.append('sina')
    if tencent_data:
        sources.append('tencent')
    if em_data:
        sources.append('eastmoney')
    source_label = '+'.join(sources) if sources else 'cache'
    return {
        'indicators': indicators,
        'summary': _ai_chain_summary(indicators),
        'update_time': now,
        'source': source_label,
    }
