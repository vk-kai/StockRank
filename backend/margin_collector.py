# -*- coding: utf-8 -*-
"""融资融券（融资净买入额）数据采集与缓存。

数据源：akshare 的 stock_margin_detail_sse / stock_margin_detail_szse，
分别取自**上交所 / 深交所官方**（不涉及东方财富，规避其反爬）。
每个交易日两市各一次调用即可拿到当日全部标的，每日 09:05 增量更新一次。

融资净买入额口径：
- SSE：融资买入额 − 融资偿还额（接口直出两列）
- SZSE：接口无"融资偿还额"，用 Δ融资余额（当日余额 − 上一交易日余额）等价得到

缓存到 REALTIME_DIR/stock_margin.json，按裸 6 位代码建键，每只股票保留最近
KEEP_TRADING_DAYS 个交易日，控制文件体积。
"""
import os
import json
import time
import threading
from datetime import datetime, timedelta

from config import REALTIME_DIR
from logger import get_logger
from thread_monitor import heartbeat, register_thread, set_busy

system_logger = get_logger('system')
error_logger = get_logger('error')

STOCK_MARGIN_CACHE_FILE = os.path.join(REALTIME_DIR, 'stock_margin.json')
BACKFILL_CALENDAR_DAYS = 90      # 首次回填的自然日窗口（≈60 交易日，正好喂满"60日"选项）
KEEP_TRADING_DAYS = 90           # 每只股票保留的最近交易日条数
DAILY_TRIGGER_HOUR = 9
DAILY_TRIGGER_MINUTE = 5

# akshare 返回列名（实测稳定）
_SSE_CODE, _SSE_NAME = '标的证券代码', '标的证券简称'
_SSE_RZYE, _SSE_RZMRE, _SSE_RCHE = '融资余额', '融资买入额', '融资偿还额'
_SZ_CODE, _SZ_NAME = '证券代码', '证券简称'
_SZ_RZYE = '融资余额'

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


def fetch_margin_for_date(date_str):
    """抓取某日（YYYYMMDD）两市融资融券明细，仅取融资余额。

    返回 {code: {'n': name, 'b': 融资余额}}。
    融资净买入额统一用 Δ融资余额（当日余额 − 上一交易日余额）在读取时计算，
    对两市均成立（余额今 = 余额昨 + 净买入），无需区分数据源、也不受抓取顺序影响。
    """
    import akshare as ak
    result = {}

    # ---- 上交所 ----
    try:
        df = ak.stock_margin_detail_sse(date=date_str)  # 无数据日会抛 ValueError
        if df is not None and len(df):
            codes = df[_SSE_CODE].astype(str).str.strip().tolist()
            names = df[_SSE_NAME].astype(str).tolist()
            rzye = df[_SSE_RZYE].apply(_to_float).tolist()
            for i, raw in enumerate(codes):
                code = _normalize_code(raw)
                if not code:
                    continue
                result[code] = {'n': names[i], 'b': rzye[i]}
    except Exception as e:
        system_logger.info(f"融资融券[SSE] {date_str} 无数据或抓取失败: {repr(e)[:120]}")

    # ---- 深交所 ----
    try:
        df = ak.stock_margin_detail_szse(date=date_str)
        if df is not None and len(df):
            codes = df[_SZ_CODE].astype(str).str.strip().tolist()
            names = df[_SZ_NAME].astype(str).tolist()
            rzye = df[_SZ_RZYE].apply(_to_float).tolist()
            for i, raw in enumerate(codes):
                code = _normalize_code(raw)
                if not code:
                    continue
                result[code] = {'n': names[i], 'b': rzye[i]}
    except Exception as e:
        system_logger.info(f"融资融券[SZSE] {date_str} 无数据或抓取失败: {repr(e)[:120]}")
    return result


def update_margin_cache(max_calendar_days=None, force_dates=None, heartbeat_name=None):
    """串行化包装：定时线程与弹窗按需触发可能并发，加锁避免读-改-写互相覆盖。"""
    with _update_lock:
        return _update_margin_cache_impl(max_calendar_days, force_dates, heartbeat_name)


def _update_margin_cache_impl(max_calendar_days, force_dates, heartbeat_name):
    """抓取尚未缓存的最近交易日并合并写回。

    - force_dates: 显式指定要抓的日期（YYYYMMDD 列表），仅抓其中未缓存的
    - max_calendar_days: 从今天往回看的自然日窗口（默认 BACKFILL_CALENDAR_DAYS）
    - heartbeat_name: 传入线程名则在逐日抓取间发心跳，避免长回填被判死
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
            ds = d.strftime('%Y%m%d')
            if ds not in cached_dates:
                target_dates.append(ds)
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
        for code, info in day.items():
            rec = stocks.get(code)
            if rec is None:
                rec = {'n': info['n'], 's': []}
                stocks[code] = rec
            if info.get('n'):
                rec['n'] = info['n']
            # 仅存 [日期, 融资余额]；净买入额在 get_stock_margin_series 按 Δ余额算
            rec['s'].append([ds, info['b']])
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
        return {'name': '', 'latest_date': '', 'series': []}
    data = _ensure_mem()
    rec = data.get('stocks', {}).get(code)
    latest = data.get('latest_date', '')
    if not rec:
        return {'name': '', 'latest_date': latest, 'series': []}
    raw = rec.get('s', [])  # [[date, 融资余额], ...] 已升序
    series = []
    prev_b = None
    for r in raw:
        d, b = r[0], r[1]
        j = (b - prev_b) if prev_b is not None else None  # Δ融资余额 = 融资净买入额；首日无前值→null
        series.append({'d': d, 'j': j, 'b': b})
        prev_b = b
    return {'name': rec.get('n', ''), 'latest_date': latest, 'series': series}


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
                    update_margin_cache(heartbeat_name='margin_collector')
                    _last_margin_run_date = today
                except Exception as e:
                    error_logger.error(f"融资融券每日更新异常: {e}")
                finally:
                    set_busy('margin_collector', False)
        except Exception as e:
            error_logger.error(f"融资融券采集线程异常: {e}")
        time.sleep(60)
