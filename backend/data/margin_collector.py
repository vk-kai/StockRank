# -*- coding: utf-8 -*-
"""融资融券（融资净买入额）数据采集与缓存。

数据源（主备双路）：
- 主：东方财富数据中心两融明细（RPTA_WEB_RZRQ_GGMX，沪深两市一次拿全，em_request 带 WAF 代理回退）。
  背景：交易所官方接口对服务器 IP 风控时返回空表（akshare 解析空表抛 ValueError），EM 侧长期稳定。
- 备：akshare 的 stock_margin_detail_sse / stock_margin_detail_szse（沪深交易所官方，原逻辑保留）。

每日 09:05 增量更新一次。

融资净买入额口径：统一用 Δ融资余额（当日余额 − 上一交易日余额）在读取时计算，
对两市均成立（余额今 = 余额昨 + 净买入）；融资偿还额 = 融资买入额 − 净买入。

缓存到 REALTIME_DIR/stock_margin.json，按裸 6 位代码建键，每只股票保留最近
KEEP_TRADING_DAYS 个交易日，控制文件体积。
"""
import os
import json
import time
import threading
from datetime import datetime, timedelta

from core.config import REALTIME_DIR, em_request
from core.logger import get_logger
from monitors.thread_monitor import heartbeat, register_thread, set_busy

system_logger = get_logger('system')
error_logger = get_logger('error')

STOCK_MARGIN_CACHE_FILE = os.path.join(REALTIME_DIR, 'stock_margin.json')
MARKET_MARGIN_TOTAL_FILE = os.path.join(REALTIME_DIR, 'market_margin_total.json')  # 全市场融资余额合计(上交所官方,预计算缓存)
MARKET_MARGIN_TOTAL_THS_FILE = os.path.join(REALTIME_DIR, 'market_margin_total_ths.json')  # 同花顺融资融券汇总(主源,含净买入)
BACKFILL_CALENDAR_DAYS = 90      # 首次回填的自然日窗口（≈60 交易日，正好喂满"60日"选项）
KEEP_TRADING_DAYS = 90           # 每只股票保留的最近交易日条数
MARGIN_MIN_STOCKS = 4000         # 单日融资融券标的数下限(低于此值视为单市失败,需重采)
MARGIN_FETCH_RETRIES = 3         # 单日采集标的不足时的重试次数
DAILY_TRIGGER_HOUR = 9
DAILY_TRIGGER_MINUTE = 5
# 每日增量时:超过该自然日数的"缺失/残缺"历史日不再天天重试(更早的缺口交易所/EM接口大多已不提供,
# 天天试只是刷 INFO 日志+浪费请求);首次回填仍按 BACKFILL_CALENDAR_DAYS 全窗口
MARGIN_REPAIR_WINDOW_DAYS = 35

# 东方财富数据中心两融明细(沪深两市一次拿全)
EM_MARGIN_URL = 'https://datacenter-web.eastmoney.com/api/data/v1/get'

# akshare 返回列名（实测稳定）
_SSE_CODE, _SSE_NAME = '标的证券代码', '标的证券简称'
_SSE_RZYE, _SSE_RZMRE, _SSE_RCHE = '融资余额', '融资买入额', '融资偿还额'
_SZ_CODE, _SZ_NAME = '证券代码', '证券简称'
_SZ_RZYE, _SZ_RZMRE = '融资余额', '融资买入额'

# 模块级内存缓存（请求时惰性加载，按 mtime 失效重载）
_MEM = {'mtime': -1, 'data': None, 'lock': threading.Lock()}

# 读-改-写串行锁：定时线程与弹窗按需触发可能并发，避免互相覆盖丢数据
_update_lock = threading.Lock()

_last_margin_run_date = None   # 定时任务每日只跑一次守卫（YYYY-MM-DD）
_last_ondemand_date = None     # 按需触发每日只跑一次守卫（YYYY-MM-DD）
_ondemand_lock = threading.Lock()


def _to_float(v, default=0.0):
    try:
        if v in (None, '', '-', 'None'):
            return default
        # 接口可能返回带千分位的字符串("1,234,567.89")，直接 float 会失败变 0
        if isinstance(v, str):
            return float(v.replace(',', ''))
        return float(v)
    except (TypeError, ValueError):
        return default


def _is_weekday(d):
    return d.weekday() < 5  # 节假日无法精确判断，靠接口返回空兜底


def _normalize_code(c):
    """归一为裸 6 位代码（云图 node.code 可能带 sh/sz 前缀或新浪格式）。"""
    digits = ''.join(ch for ch in str(c) if ch.isdigit())
    return digits[-6:] if len(digits) >= 6 else digits


def _load_cache():
    if not os.path.exists(STOCK_MARGIN_CACHE_FILE):
        return {'updated_at': '', 'latest_date': '', 'stocks': {}}
    try:
        with open(STOCK_MARGIN_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        error_logger.error(f"读取融资融券缓存失败，重建空缓存: {e}")
        return {'updated_at': '', 'latest_date': '', 'stocks': {}}


def _atomic_write_json(path, obj):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def _fetch_margin_em(date_str):
    """东方财富数据中心两融明细（沪深两市一次拿全）。date_str=YYYYMMDD。

    返回 {code: {'n': name, 'b': 融资余额, 'm': 融资买入额}}；接口失败/无数据返回 {}。
    分页 500/页，页间 0.25s 温和限速；em_request 直连失败自动走代理（防 EM WAF）。
    """
    date_dash = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://data.eastmoney.com/',
    }
    out = {}
    page = 1
    while page <= 40:  # 硬上限防死循环(4445只≈9页,余量充足)
        try:
            resp = em_request(
                EM_MARGIN_URL,
                params={
                    'reportName': 'RPTA_WEB_RZRQ_GGMX', 'columns': 'ALL', 'source': 'WEB',
                    'sortColumns': 'scode', 'sortTypes': '1',
                    'pageSize': 500, 'pageNumber': page,
                    'filter': "(date='%s')" % date_dash,
                },
                headers=headers, timeout=15,
            )
            res = (resp.json().get('result') or {})
            rows = res.get('data') or []
        except Exception as e:
            system_logger.info(f"融资融券[EM] {date_str} 第{page}页抓取失败: {repr(e)[:120]}")
            return out if out else {}
        for row in rows:
            code = _normalize_code(str(row.get('SCODE') or '').strip())
            b = _to_float(row.get('RZYE'), default=None)
            if not code or b is None:
                continue
            out[code] = {
                'n': str(row.get('SECNAME') or ''),
                'b': b,
                'm': _to_float(row.get('RZMRE'), default=None),
            }
        pages = res.get('pages') or 0
        if not rows or page >= pages:
            break
        page += 1
        time.sleep(0.25)
    return out


def _fetch_margin_official(date_str):
    """原 akshare 沪深官方两路采集（备用路：EM 失败时兜底）。"""
    import akshare as ak
    result = {}

    # ---- 上交所 ----
    try:
        df = ak.stock_margin_detail_sse(date=date_str)  # 无数据日会抛 ValueError
        if df is not None and len(df):
            codes = df[_SSE_CODE].astype(str).str.strip().tolist()
            names = df[_SSE_NAME].astype(str).tolist()
            rzye = df[_SSE_RZYE].apply(_to_float).tolist()
            rzmre = df[_SSE_RZMRE].apply(_to_float).tolist()
            for i, raw in enumerate(codes):
                code = _normalize_code(raw)
                if not code:
                    continue
                result[code] = {'n': names[i], 'b': rzye[i], 'm': rzmre[i]}
    except Exception as e:
        system_logger.info(f"融资融券[SSE] {date_str} 无数据或抓取失败: {repr(e)[:120]}")

    # ---- 深交所 ----
    try:
        df = ak.stock_margin_detail_szse(date=date_str)
        if df is not None and len(df):
            codes = df[_SZ_CODE].astype(str).str.strip().tolist()
            names = df[_SZ_NAME].astype(str).tolist()
            rzye = df[_SZ_RZYE].apply(_to_float).tolist()
            rzmre = df[_SZ_RZMRE].apply(_to_float).tolist()
            for i, raw in enumerate(codes):
                code = _normalize_code(raw)
                if not code:
                    continue
                result[code] = {'n': names[i], 'b': rzye[i], 'm': rzmre[i]}
    except Exception as e:
        system_logger.info(f"融资融券[SZSE] {date_str} 无数据或抓取失败: {repr(e)[:120]}")
    return result


def fetch_margin_for_date(date_str):
    """抓取某日（YYYYMMDD）两市融资融券明细，取融资余额 + 融资买入额。

    返回 {code: {'n': name, 'b': 融资余额, 'm': 融资买入额}}。
    融资净买入额统一用 Δ融资余额（当日余额 − 上一交易日余额）在读取时计算，
    对两市均成立（余额今 = 余额昨 + 净买入）；融资偿还额 = 融资买入额 − 净买入。

    主备双路：EM 数据中心优先（单接口两市全量，服务器 IP 被交易所风控时仍可用），
    EM 拿不满/失败时回退沪深官方两路，哪路覆盖多用哪路。
    """
    result_em = _fetch_margin_em(date_str)
    if len(result_em) >= MARGIN_MIN_STOCKS:
        return result_em
    result = _fetch_margin_official(date_str)
    if len(result) > len(result_em):
        return result
    return result_em


def update_margin_cache(max_calendar_days=None, force_dates=None, heartbeat_name=None,
                        repair_window_days=None):
    """串行化包装：定时线程与弹窗按需触发可能并发，加锁避免读-改-写互相覆盖。

    repair_window_days: 每日增量传入 35 —— 超过 35 自然日的缺失/残缺历史日不再天天重试；
    None(首次回填/按需) = 不设限，按 max_calendar_days 全窗口处理。"""
    with _update_lock:
        return _update_margin_cache_impl(max_calendar_days, force_dates, heartbeat_name,
                                         repair_window_days)


def _update_margin_cache_impl(max_calendar_days, force_dates, heartbeat_name,
                              repair_window_days=None):
    """抓取尚未缓存的最近交易日并合并写回。

    - force_dates: 显式指定要抓的日期（YYYYMMDD 列表），仅抓其中未缓存的
    - max_calendar_days: 从今天往回看的自然日窗口（默认 BACKFILL_CALENDAR_DAYS）
    - heartbeat_name: 传入线程名则在逐日抓取间发心跳，避免长回填被判死
    - repair_window_days: 残缺日/陈旧缺失日的重采窗口（自然日），None=不限
    返回更新到的最新日期；无更新返回原 latest_date。
    """
    max_cal = max_calendar_days if max_calendar_days is not None else BACKFILL_CALENDAR_DAYS
    cache = _load_cache()
    stocks = cache.get('stocks', {})

    cached_dates = set()
    for rec in stocks.values():
        for row in rec.get('s', []):
            cached_dates.add(row[0])

    if force_dates:
        target_dates = sorted(d for d in force_dates if d not in cached_dates)
    else:
        today = datetime.now()
        target_dates = []
        for back in range(0, max_cal):
            d = today - timedelta(days=back)
            if not _is_weekday(d):
                continue
            # 每日增量模式(repair_window_days 有值):太老的历史缺失日不再天天重试,
            # 交易所/EM 接口对老日期基本不再提供,重试只是刷日志+浪费请求
            if repair_window_days is not None and back > repair_window_days:
                break
            ds = d.strftime('%Y%m%d')
            if ds not in cached_dates:
                target_dates.append(ds)
        # 残缺日自动重采:历史某日并入时只有单市数据(标的数 < 下限,如交易所接口风控期间),
        # 重新纳入抓取目标;重抓后"同日取最后一次"去重,残缺记录自动被完整记录覆盖
        if repair_window_days is not None:
            day_counts = {}
            for rec in stocks.values():
                for row in rec.get('s', []):
                    day_counts[row[0]] = day_counts.get(row[0], 0) + 1
            for d, cnt in day_counts.items():
                if cnt >= MARGIN_MIN_STOCKS or d in target_dates:
                    continue
                try:
                    age_days = (today - datetime.strptime(d, '%Y%m%d')).days
                except ValueError:
                    continue
                if age_days <= repair_window_days:
                    target_dates.append(d)
        target_dates.sort()  # 远→近，便于做 SZSE Δ余额

    if not target_dates:
        system_logger.info("融资融券缓存已是最新，无需更新")
        return cache.get('latest_date', '')

    system_logger.info(f"融资融券开始抓取 {len(target_dates)} 个交易日: {target_dates[0]}~{target_dates[-1]}")

    new_latest = cache.get('latest_date', '')
    for ds in target_dates:
        if heartbeat_name:
            heartbeat(heartbeat_name)
        day = fetch_margin_for_date(ds)
        if not day:
            continue  # 非交易日 / 尚未公布 → 不计为已缓存，下次再试
        # 校验+重试:标的数 < 4000 视为单市采集失败(约一半缺失,如 SSE/SZSE 某接口断连),重采取最多
        retries = 0
        while len(day) < MARGIN_MIN_STOCKS and retries < MARGIN_FETCH_RETRIES:
            retries += 1
            system_logger.warning(f"融资融券 {ds} 仅 {len(day)} 只(<{MARGIN_MIN_STOCKS},疑似单市失败),重试 {retries}/{MARGIN_FETCH_RETRIES}")
            time.sleep(2)
            day2 = fetch_margin_for_date(ds)
            if day2 and len(day2) > len(day):
                day = day2
            if len(day) >= MARGIN_MIN_STOCKS:
                break
        for code, info in day.items():
            rec = stocks.get(code)
            if rec is None:
                rec = {'n': info['n'], 's': []}
                stocks[code] = rec
            if info.get('n'):
                rec['n'] = info['n']
            # 仅存 [日期, 融资余额, 融资买入额]；净买入/偿还额在 get_stock_margin_series 读取时算
            rec['s'].append([ds, info['b'], info['m']])
        new_latest = max(new_latest, ds)
        system_logger.info(f"融资融券 {ds} 已合并（{len(day)} 只）")

    # 每只股票：按日期升序排序、同日去重(留后)、仅保留最近 KEEP_TRADING_DAYS 个交易日
    for rec in stocks.values():
        s = rec.get('s')
        if not s:
            continue
        s.sort(key=lambda r: r[0])
        dedup = {}
        for row in s:
            dedup[row[0]] = row  # 同日取最后一次
        s_sorted = [dedup[k] for k in sorted(dedup)]
        if len(s_sorted) > KEEP_TRADING_DAYS:
            s_sorted = s_sorted[-KEEP_TRADING_DAYS:]
        rec['s'] = s_sorted

    cache['stocks'] = stocks
    cache['latest_date'] = new_latest
    cache['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    _atomic_write_json(STOCK_MARGIN_CACHE_FILE, cache)
    with _MEM['lock']:
        _MEM['mtime'] = -1
        _MEM['data'] = None  # 失效内存缓存
    system_logger.info(f"融资融券缓存已写入: latest={new_latest}, 股票数={len(stocks)}")
    return new_latest


def _ensure_mem():
    """惰性加载缓存到内存，文件 mtime 变化时重载。"""
    with _MEM['lock']:
        try:
            mt = os.path.getmtime(STOCK_MARGIN_CACHE_FILE)
        except OSError:
            mt = -1
        if _MEM['data'] is None or mt != _MEM['mtime']:
            _MEM['data'] = _load_cache()
            _MEM['mtime'] = mt
        return _MEM['data']


def get_stock_margin_series(code):
    """返回单只股票的融资净买入额时间序列（供弹窗柱状图）。"""
    code = _normalize_code(code)
    if not code:
        return {'name': '', 'latest_date': '', 'latest_balance': None, 'latest_balance_date': '', 'series': []}
    data = _ensure_mem()
    rec = data.get('stocks', {}).get(code)
    latest = data.get('latest_date', '')
    if not rec:
        return {'name': '', 'latest_date': latest, 'latest_balance': None, 'latest_balance_date': '', 'series': []}
    raw = rec.get('s', [])  # [[date, 融资余额, 融资买入额], ...] 已升序（兼容旧2元组）
    series = []
    prev_b = None
    latest_balance = None
    latest_balance_date = ''
    for r in raw:
        d, b = r[0], r[1]
        buy = r[2] if len(r) > 2 else None        # 融资买入额（旧缓存无此列→None）
        j = (b - prev_b) if prev_b is not None else None   # Δ融资余额 = 融资净买入额；首日→None
        repay = (buy - j) if (buy is not None and j is not None) else None  # 融资偿还额 = 买入额 − 净买入
        series.append({'d': d, 'j': j, 'buy': buy, 'repay': repay, 'b': b})
        if b is not None:
            latest_balance = b
            latest_balance_date = d
        prev_b = b
    return {
        'name': rec.get('n', ''),
        'latest_date': latest,
        'latest_balance': latest_balance,
        'latest_balance_date': latest_balance_date,
        'series': series,
    }


def get_all_latest_margin_net_inflow():
    """全市场每只融资融券标的的「最新一日融资净买入额」(= Δ融资余额)。

    只读现有 stock_margin.json 缓存，不发起任何抓取（缓存由每日 09:05 线程维护）。
    返回 {'latest_date': 'YYYYMMDD', 'map': {裸6位code: {'net':净流入额(元), 'rate':净流入/昨日余额}}}。
    仅 1 个交易日记录的标的无法算 Δ，不计入；净流入=0 的也计入（用于区分"无数据"）。"""
    data = _ensure_mem()
    stocks = data.get('stocks', {})
    latest_date = data.get('latest_date', '')
    result = {}
    for code, rec in stocks.items():
        raw = rec.get('s') if isinstance(rec, dict) else None
        if not raw or len(raw) < 2:
            continue
        try:
            prev_b = raw[-2][1]
            cur_b = raw[-1][1]
        except (IndexError, TypeError):
            continue
        if prev_b is None or cur_b is None:
            continue
        net = cur_b - prev_b
        # rate = 净流入/昨日余额(相对增速)：前端按它排名，避免大市值股绝对额垄断深色(亮的永远是左上角大盘)
        rate = (net / prev_b) if prev_b else 0.0
        result[code] = {'net': net, 'rate': rate}
    return {'latest_date': latest_date, 'map': result}


def get_all_latest_margin_balance():
    """全市场每只融资融券标的的「最新一日融资余额」(大盘云图"按融资余额"布局用)。

    只读现有 stock_margin.json 缓存,不发起任何抓取(缓存由每日 09:05 线程维护)。
    返回 {'latest_date': 'YYYYMMDD', 'map': {裸6位code: 融资余额(元)}}。
    至少 1 条记录即计入(无需 Δ,与净买入接口不同)。"""
    data = _ensure_mem()
    stocks = data.get('stocks', {})
    latest_date = data.get('latest_date', '')
    result = {}
    for code, rec in stocks.items():
        raw = rec.get('s') if isinstance(rec, dict) else None
        if not raw:
            continue
        try:
            cur_b = raw[-1][1]
        except (IndexError, TypeError):
            continue
        if cur_b is None:
            continue
        result[code] = cur_b
    return {'latest_date': latest_date, 'map': result}


MAX_SMOOTH_FILL_STREAK = 3   # 连续平滑上限:超过后采信真实水平,避免把后续每天钉死在前值画成假横线


def _aggregate_market_margin_total():
    """聚合 stock_margin.json 所有个股的融资余额(b),按日求和(用户自有维度)。
    异常日平滑:当日采集覆盖不全(有数据股票数 < 中位 85%)或合计跳变 >15% 时用前值填充,
    消除"某日采集覆盖突变导致的断崖式跳变"(7月那种 30000→15000亿 的假跳变)。
    连续平滑不超过 MAX_SMOOTH_FILL_STREAK 天:异常若持续存在(某交易所接口长期失败/口径变化),
    说明水平已真实变化,采信真实值继续画走势,而不是每天都被钉回旧前值变成一条假横线。
    返回 {'history': [...], 'filled_days': 被平滑的天数}。"""
    data = _ensure_mem()
    stocks = data.get('stocks', {})
    daily = {}
    counts = {}
    for rec in stocks.values():
        raw = rec.get('s') if isinstance(rec, dict) else None
        if not raw:
            continue
        for r in raw:
            try:
                d, b = r[0], r[1]
            except (IndexError, TypeError):
                continue
            if b is None:
                continue
            daily[d] = daily.get(d, 0.0) + float(b)
            counts[d] = counts.get(d, 0) + 1
    if not daily:
        return {'history': [], 'filled_days': 0}
    sorted_dates = sorted(daily.keys())
    median_count = sorted(counts.values())[len(counts) // 2]
    threshold = median_count * 0.85
    history = []
    prev_total = None
    prev_shown = None   # 上一"展示日"的融资余额(用于逐日净买入差分,与同花顺口径一致)
    filled_days = 0
    fill_streak = 0
    for d in sorted_dates:
        raw_total = daily[d]
        cnt = counts[d]
        if prev_total is not None and prev_total > 0:
            is_anomaly = (
                cnt < threshold
                or raw_total <= 0
                or abs(raw_total - prev_total) / prev_total > 0.15
            )
        else:
            is_anomaly = False
        if is_anomaly and fill_streak < MAX_SMOOTH_FILL_STREAK:
            # 瞬时异常(单日覆盖突变/跳变) → 用前值平滑
            total = prev_total
            fill_streak += 1
            filled_days += 1
        else:
            # 正常日,或异常已连续多日(口径/覆盖发生真实变化) → 采信真实值
            total = raw_total
            fill_streak = 0
            if total <= 0:
                # 数据中断(当日全部为0/缺失),不再有可信基线,后续按真实值展示
                prev_total = None
        net_buy = None if prev_shown is None else round(total - prev_shown, 2)
        history.append({'date': d, 'total': round(total, 2), 'net_buy': net_buy})
        if total > 0:
            prev_total = total
            prev_shown = total
    # 裁掉开头连续无效日(采集回填不全时前缀 total=0,画图贴底突跳,如 04-07~06-08 全 0 段)
    while history and not history[0].get('total'):
        history.pop(0)
    return {'history': history, 'filled_days': filled_days}


def refresh_market_margin_total():
    """刷新全市场融资余额合计缓存(聚合个股融资余额 b,用户自有维度)。每日 09:05 调一次。"""
    try:
        agg = _aggregate_market_margin_total()
        history = agg['history']
        if not history:
            return False
        latest = history[-1]
        prev = history[-2] if len(history) >= 2 else None
        change_pct = None
        if prev and prev['total']:
            change_pct = round((latest['total'] - prev['total']) / prev['total'] * 100, 2)
        data = {
            'latest_date': latest['date'],
            'latest_total': latest['total'],
            'prev_total': prev['total'] if prev else None,
            'change_pct': change_pct,
            'latest_net_buy': latest.get('net_buy'),
            'history': history,
            'filled_days': agg['filled_days'],
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source': '自有维度(聚合个股融资余额)',
        }
        tmp = MARKET_MARGIN_TOTAL_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, MARKET_MARGIN_TOTAL_FILE)
        return True
    except Exception as e:
        error_logger.error(f"刷新全市场融资余额合计失败: {e}")
        return False


def _load_ths_total():
    """读同花顺汇总缓存;不存在/落后超 6 自然日/字段缺失 → None(走回退)。

    6天而非4天:融资数据 T+1 发布+周末+当日半截被防抖丢弃,最新日可能是 T-2,
    周一上午距上周四已超 4 天但数据其实是新的,4 天阈值会误判过期走回退。"""
    if not os.path.exists(MARKET_MARGIN_TOTAL_THS_FILE):
        return None
    try:
        with open(MARKET_MARGIN_TOTAL_THS_FILE, 'r', encoding='utf-8') as f:
            cached = json.load(f)
    except Exception:
        return None
    if not cached or not cached.get('latest_date') or not cached.get('history'):
        return None
    try:
        if (datetime.now() - datetime.strptime(cached['latest_date'], '%Y%m%d')) > timedelta(days=6):
            return None
    except ValueError:
        return None
    return cached


def _fetch_em_margin_history(size=500):
    """东财数据中心两融历史汇总(RPTA_RZRQ_LSHJ,沪深合计日级)。

    用途:①补长历史(同花顺分页上限约4页≈40交易日,超页返回第一页重复数据,更早的拿不到)
    ②THS 失效时的兜底主源。系统已有 em_request 带 WAF 代理回退。
    返回升序 [{date,total,buy,rzrq,close}](单位元;close=上证收盘,供弹窗指数线兜底);失败返回 []。
    """
    try:
        resp = em_request(
            EM_MARGIN_URL,
            params={'reportName': 'RPTA_RZRQ_LSHJ', 'columns': 'ALL', 'source': 'WEB',
                    'sortColumns': 'dim_date', 'sortTypes': '-1',
                    'pageSize': str(size), 'pageNumber': '1'},
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                     'Referer': 'https://data.eastmoney.com/'},
            timeout=15)
        rows = ((resp.json().get('result') or {}).get('data')) or []
    except Exception as e:
        error_logger.error(f"两融历史汇总[EM]抓取失败: {repr(e)[:120]}")
        return []
    out = []
    for row in rows:
        d = str(row.get('DIM_DATE') or '')[:10].replace('-', '')
        total = _to_float(row.get('RZYE'), default=None)
        if len(d) != 8 or total is None:
            continue
        buy = _to_float(row.get('RZMRE'), default=None)
        rzrq = _to_float(row.get('RZRQYE'), default=None)
        close = _to_float(row.get('NEW'), default=None)
        out.append({'date': d, 'total': round(total, 0),
                    'buy': round(buy, 0) if buy is not None else None,
                    'rzrq': round(rzrq, 0) if rzrq is not None else None,
                    'close': round(close, 2) if close is not None else None})
    out.sort(key=lambda x: x['date'])
    return out


def _fill_net_buy(history):
    """对升序 history 按 Δ融资余额 统一重算 net_buy(与逐股/THS 口径一致)。"""
    prev = None
    for x in history:
        t = x.get('total')
        x['net_buy'] = round(t - prev, 0) if (t is not None and prev is not None) else None
        if t is not None:
            prev = t
    return history


_EM_HIST_CACHE = {'ts': 0.0, 'payload': None}
_EM_HIST_TTL = 600  # EM 兜底 payload 进程内缓存10分钟


def _em_history_payload():
    """EM 两融历史汇总 → 与 THS 同构的完整 payload(约500交易日,含净买入)。失败/不足返回 None。"""
    now = time.time()
    if _EM_HIST_CACHE['payload'] and now - _EM_HIST_CACHE['ts'] < _EM_HIST_TTL:
        return _EM_HIST_CACHE['payload']
    rows = _fetch_em_margin_history(500)
    if len(rows) < 3:
        return None
    history = _fill_net_buy(rows)
    valid = [x for x in history if x['total']]
    latest = valid[-1]
    prev_item = valid[-2] if len(valid) >= 2 else None
    change_pct = None
    if prev_item and prev_item['total']:
        change_pct = round((latest['total'] / prev_item['total'] - 1) * 100, 2)
    payload = {'latest_date': latest['date'], 'latest_total': latest['total'],
               'prev_total': prev_item['total'] if prev_item else None,
               'change_pct': change_pct, 'latest_net_buy': latest['net_buy'],
               'latest_buy': latest.get('buy'), 'latest_rzrq': latest.get('rzrq'),
               'history': history, 'source': 'em_lshj'}
    _EM_HIST_CACHE['ts'] = now
    _EM_HIST_CACHE['payload'] = payload
    return payload


def refresh_market_margin_total_ths():
    """同花顺融资融券市场汇总(主源):融资余额合计+融资净买入+两融余额,4页≈40交易日。

    同花顺分页上限约4页(超页返回第一页重复数据),更早历史由东财两融历史汇总补齐。
    净买入口径:Δ融资余额(当日合计−上一交易日合计),与逐股口径一致。
    半截数据防抖:最新一日融资余额较前日跌幅>15%(交易所当日数据未出全的中间态,
    如 2026-10-30 同花顺提前展示沪市半截 11989 亿 vs 前日 23567 亿)→丢弃最新日;
    只防尾部,历史中间日不判(真实单日暴跌<15%极罕见,不误杀)。
    """
    try:
        from data.data_processor.ths_margin import fetch_ths_margin_summary
        rows = fetch_ths_margin_summary(pages=4)
        if len(rows) < 3:
            error_logger.error(f"同花顺融资汇总数据不足({len(rows)}条),保留旧缓存")
            return False
        while len(rows) >= 2 and rows[-1].get('rzye') and rows[-2].get('rzye') \
                and rows[-1]['rzye'] < rows[-2]['rzye'] * 0.85:
            dropped = rows.pop()
            error_logger.warning(
                f"丢弃疑似未出全的半截数据: {dropped['date']} 融资余额{dropped['rzye']}亿"
                f"(前日{rows[-1]['rzye']}亿)")
        history = []
        prev = None
        for r in rows:
            rzye = r.get('rzye')
            # 同花顺单位"亿元" → 统一转"元"(与旧接口契约一致:前端除以1e8展示亿)
            total_yuan = round(rzye * 1e8, 0) if rzye is not None else None
            net_buy = round((rzye - prev) * 1e8, 0) if (prev is not None and rzye is not None) else None
            history.append({'date': r['date'],
                            'total': total_yuan,
                            'net_buy': net_buy,
                            'buy': round(r['buy'] * 1e8, 0) if r.get('buy') is not None else None,
                            'rzrq': round(r['rzrq'] * 1e8, 0) if r.get('rzrq') is not None else None})
            prev = rzye
        # 补长历史:同花顺分页上限约4页,更早的用东财两融历史汇总(约500交易日)按日期合并;
        # 旧缓存也参与合并,防个别页失败/接口异常时丢历史。优先级:THS(主源) > EM(长历史) > 旧缓存
        try:
            if os.path.exists(MARKET_MARGIN_TOTAL_THS_FILE):
                with open(MARKET_MARGIN_TOTAL_THS_FILE, 'r', encoding='utf-8') as f:
                    old_hist = (json.load(f) or {}).get('history') or []
            else:
                old_hist = []
        except Exception:
            old_hist = []
        merged = {x['date']: x for x in old_hist}
        for x in _fetch_em_margin_history(500):
            merged[x['date']] = x
        for x in history:
            old_item = merged.get(x['date'])
            if old_item and x.get('close') is None:
                x['close'] = old_item.get('close')  # THS 行无指数,继承已合并的 EM 上证收盘
            merged[x['date']] = x
        history = _fill_net_buy([merged[d] for d in sorted(merged.keys())])[-600:]  # 上限600日≈两年半
        valid = [x for x in history if x['total']]
        if not valid:
            error_logger.error("同花顺融资汇总无有效数据,保留旧缓存")
            return False
        latest = valid[-1]
        prev_item = valid[-2] if len(valid) >= 2 else None
        change_pct = None
        if prev_item and prev_item['total']:
            change_pct = round((latest['total'] / prev_item['total'] - 1) * 100, 2)
        payload = {'latest_date': latest['date'], 'latest_total': latest['total'],
                   'prev_total': prev_item['total'] if prev_item else None,
                   'change_pct': change_pct,
                   'latest_net_buy': latest['net_buy'],
                   'latest_buy': latest.get('buy'), 'latest_rzrq': latest.get('rzrq'),
                   'history': history, 'source': 'ths_rzrq'}
        tmp = MARKET_MARGIN_TOTAL_THS_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, MARKET_MARGIN_TOTAL_THS_FILE)
        system_logger.info(
            f"同花顺融资汇总已缓存: {latest['date']} 融资余额{latest['total'] / 1e8:.1f}亿 "
            f"净买入{(latest['net_buy'] or 0) / 1e8:+.1f}亿 两融{(latest.get('rzrq') or 0) / 1e8:.1f}亿")
        return True
    except Exception as e:
        error_logger.error(f"刷新同花顺融资汇总失败: {e}")
        return False


def get_market_margin_total():
    """读全市场融资余额合计。主源:同花顺市场汇总(官方口径,含净买入);
    同花顺不可用时回退 EM 两融历史汇总;再不可用回退旧路径(聚合个股融资余额 b)。"""
    ths = _load_ths_total()
    if ths:
        return ths
    # 回退1:EM 两融历史汇总(约500交易日+完整净买入,比逐股自算更权威且免聚合)
    em = _em_history_payload()
    if em:
        return em
    # 回退2:旧自算路径(个股聚合)
    if os.path.exists(MARKET_MARGIN_TOTAL_FILE):
        try:
            with open(MARKET_MARGIN_TOTAL_FILE, 'r', encoding='utf-8') as f:
                cached = json.load(f)
        except Exception:
            cached = None
        if cached:
            hist0 = (cached.get('history') or [{}])[0]
            # 个股缓存没有更新的交易日 且 已是新格式(含逐日 net_buy) → 直接返回
            # 旧格式缓存(无 net_buy/带 0 值前缀)不复用,落到下面重算一次升级
            if 'net_buy' in hist0 and str(cached.get('latest_date', '')) >= str(_ensure_mem().get('latest_date', '')):
                return cached
    # 首次/已落后:立即计算 + 存
    try:
        if refresh_market_margin_total():
            with open(MARKET_MARGIN_TOTAL_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        error_logger.error(f"计算融资余额合计失败: {e}")
    return {'latest_date': '', 'latest_total': None, 'prev_total': None,
            'change_pct': None, 'history': []}


_SSE_CACHE = {'ts': 0.0, 'data': []}
_SSE_CACHE_TTL = 1800  # 进程内缓存30分钟(新浪日线一天只变一次,弹窗连开不重复请求)


def fetch_sse_daily(lmt=60):
    """上证指数日线收盘(新浪源 akshare,与经济周期模块同源,公开接口无反爬)。
    供融资余额弹窗融合展示"上证指数 vs 融资余额"走势。
    返回 [{'date':'YYYYMMDD','close':float}](升序),失败返回 [](不阻塞融资主数据)。"""
    now = time.time()
    if now - _SSE_CACHE['ts'] < _SSE_CACHE_TTL and _SSE_CACHE['data']:
        return _SSE_CACHE['data'][-lmt:] if lmt else _SSE_CACHE['data']
    try:
        import akshare as ak
        df = ak.stock_zh_index_daily(symbol='sh000001')
        if df is None or df.empty or 'close' not in df.columns:
            return []
        out = []
        for _, r in df.iterrows():
            try:
                d = str(r['date']).replace('-', '').replace('/', '')[:8]
                out.append({'date': d, 'close': round(float(r['close']), 2)})
            except (ValueError, TypeError):
                continue
        if out:
            _SSE_CACHE['ts'] = now
            _SSE_CACHE['data'] = out
        return out[-lmt:] if lmt else out
    except Exception as e:
        error_logger.error(f"获取上证指数日线失败: {e}")
        return []


def trigger_ondemand_update_async():
    """弹窗检测到无数据时调用：后台触发一次当日更新（每天最多一次）。

    返回 True 表示本次刚触发；False 表示今天已触发过（不再重复）。
    用于满足"打开发现没数据时，不论几点都把当天数据更新一次"的需求。
    """
    global _last_ondemand_date
    today = datetime.now().strftime('%Y-%m-%d')
    with _ondemand_lock:
        if _last_ondemand_date == today:
            return False
        _last_ondemand_date = today  # 占位，防止并发/连点重复触发
    t = threading.Thread(target=_ondemand_update_worker, daemon=True)
    t.start()
    return True


def _ondemand_update_worker():
    global _last_ondemand_date
    try:
        set_busy('margin_collector', True)
        system_logger.info("融资融券：弹窗检测到无数据，触发按需更新…")
        update_margin_cache(heartbeat_name='margin_collector')
        try:
            if not refresh_market_margin_total_ths():
                refresh_market_margin_total()
        except Exception as e:
            error_logger.warning(f"按需刷新全市场融资余额合计失败: {e}")
    except Exception as e:
        error_logger.error(f"融资融券按需更新失败，放开当日占位允许重试: {e}")
        with _ondemand_lock:
            _last_ondemand_date = None
    finally:
        set_busy('margin_collector', False)


def margin_collection_thread():
    """每日 09:05 增量更新融资融券缓存；首次启动若缓存缺失则后台回填。"""
    global _last_margin_run_date
    register_thread('margin_collector')
    system_logger.info("启动融资融券采集线程，每日 09:05 增量更新一次…")

    # 首次回填（缓存不存在时）
    if not os.path.exists(STOCK_MARGIN_CACHE_FILE):
        try:
            set_busy('margin_collector', True)
            system_logger.info("融资融券缓存不存在，开始首次回填（约 60 交易日）…")
            update_margin_cache(heartbeat_name='margin_collector')
        except Exception as e:
            error_logger.error(f"融资融券首次回填失败: {e}")
        finally:
            set_busy('margin_collector', False)
        _last_margin_run_date = datetime.now().strftime('%Y-%m-%d')

    while True:
        try:
            heartbeat('margin_collector')
            now = datetime.now()
            today = now.strftime('%Y-%m-%d')
            # 当天 09:05 之后首次进入 → 跑一次（错过点也能补跑，每日只跑一次）
            after_trigger = now.hour > DAILY_TRIGGER_HOUR or (
                now.hour == DAILY_TRIGGER_HOUR and now.minute >= DAILY_TRIGGER_MINUTE
            )
            if after_trigger and _last_margin_run_date != today:
                system_logger.info(f"融资融券每日更新触发（{today}）…")
                try:
                    set_busy('margin_collector', True)
                    # 每日增量:35 天外的历史缺失/残缺日不再天天重试(见 MARGIN_REPAIR_WINDOW_DAYS)
                    update_margin_cache(heartbeat_name='margin_collector',
                                        repair_window_days=MARGIN_REPAIR_WINDOW_DAYS)
                    _last_margin_run_date = today
                    # 同步刷新全市场融资余额合计缓存(主:同花顺汇总;备:个股聚合)
                    try:
                        if not refresh_market_margin_total_ths():
                            refresh_market_margin_total()
                    except Exception as e:
                        error_logger.warning(f"全市场融资余额合计刷新失败: {e}")
                except Exception as e:
                    error_logger.error(f"融资融券每日更新异常: {e}")
                finally:
                    set_busy('margin_collector', False)
        except Exception as e:
            error_logger.error(f"融资融券采集线程异常: {e}")
        time.sleep(60)
