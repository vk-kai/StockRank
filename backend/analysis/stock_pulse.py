"""个股异动监控（Stock Pulse）
================================

基于大盘云图数据管道的**个股涨跌幅层面**异动检测（资金层面见 anomaly_detector.py）：
- 盘中每 5 分钟用新浪批量接口采样全 A 涨跌幅（~5000 只，约 13 批请求）
- 与上一轮快照对比，检测三类信号：
  1. 板块聚集异动：同行业（申万一级/二级）多只个股同时拉升 / 集体翻红 / 集体跳水
  2. 个股异动：涨停 / 跌停（自动区分 10%/20%/30%/ST5% 限制；单纯拉升/跳水不推）
  3. 热点汇总：整半点 + 收盘 15:00 推送市场温度（涨跌家数、行业涨幅中位数排行）

防刷屏（参照资金异动三道闸思路）：
- 每轮聚合为**一条**消息；无异动不推（收盘总结除外）
- 同板块+同类型 / 同个股+同类型 冷却去重（cooldown_minutes）
- 单轮板块异动最多推 max_sector_pushes 条；个股摘要每类最多列 stock_summary_top 只

推送：飞书/企微 send_news_message + WebSocket push_event('stock_pulse')。
落盘：
  data/stock_pulse/snapshots_YYYYMMDD.json  当日各轮 {code: pct} 快照（供回放/复盘）
  realtime/stock_pulse_alerts.json          已推送的轮次记录（保留 500 条）
  config/stock_pulse_config.json            阈值配置
"""
import os
import json
import re
import time
import threading
from datetime import datetime
from statistics import median

import requests

from core.config import REALTIME_DIR, CONFIG_DIR, DATA_DIR, get_random_user_agent
from core.logger import get_logger
from monitors.thread_monitor import register_thread, heartbeat
from data.stock_resolver import get_limit_pct
from data.data_collector import is_trading_day

logger = get_logger('pulse')

# --------------------------------------------------------------------------
# 路径与默认配置
# --------------------------------------------------------------------------
PULSE_DIR = os.path.join(DATA_DIR, 'stock_pulse')
ALERTS_FILE = os.path.join(REALTIME_DIR, 'stock_pulse_alerts.json')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'stock_pulse_config.json')

SINA_HQ_URL = "https://hq.sinajs.cn/list={codes}"

DEFAULT_CONFIG = {
    'enabled': True,                  # 总开关
    # ---- 板块聚集（Δpct 为相对上一轮的变化，百分点）----
    'cluster_surge_delta': 1.5,       # 集体拉升：单轮涨幅变化门槛
    'cluster_surge_abs': 8,           #   命中家数绝对门槛
    'cluster_surge_ratio': 0.08,      #   命中家数占板块比例门槛
    'cluster_turn_red_delta': 1.0,    # 集体翻红：单轮涨幅变化门槛（上轮≤0 → 本轮>0）
    'cluster_turn_red_abs': 10,
    'cluster_turn_red_ratio': 0.10,
    'cluster_dump_delta': 1.5,        # 集体跳水：单轮跌幅变化门槛
    'cluster_dump_abs': 8,
    'cluster_dump_ratio': 0.08,
    'cluster_min_hits': 3,            # 小板块最少命中家数（防 3 只小板块误报）
    # ---- 个股 ----
    'limit_tolerance': 0.998,         # pct >= limit*0.998 视为涨停（留浮点余量）
    # ---- 汇总 ----
    'summary_interval_minutes': 30,   # 热点汇总间隔（整半点轮附带）
    'sector_top_n': 3,                # 领涨/领跌行业各取前 N
    'summary_min_sector': 5,          # 行业参与排行最少股票数
    # ---- 推送 ----
    'max_sector_pushes': 3,           # 单轮板块异动最多推送条数（按家数取最显著）
    'stock_summary_top': 5,           # 个股摘要每类最多列几只（超出"等N只"）
    'cooldown_minutes': 40,           # 同板块+同类型 / 同股+同类型 冷却
}

_config_cache = None
_config_lock = threading.Lock()
_alerts_lock = threading.Lock()

_limit_cache = {}       # code -> 涨跌停幅度（进程内缓存，get_limit_pct 是纯字符串运算）
_limit_lock = threading.Lock()


def _limit_of(code, name):
    limit = _limit_cache.get(code)
    if limit is None:
        limit = get_limit_pct(code, name)
        with _limit_lock:
            _limit_cache[code] = limit
    return limit


# --------------------------------------------------------------------------
# 配置读写（同 flow_anomaly_config.json 模式）
# --------------------------------------------------------------------------
def load_config():
    global _config_cache
    with _config_lock:
        if _config_cache is not None:
            return _config_cache
        cfg = dict(DEFAULT_CONFIG)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg.update(json.load(f))
            except Exception as e:
                logger.warning(f"读取个股异动配置失败，使用默认值: {e}")
        _config_cache = cfg
        return cfg


def save_config(new_cfg):
    global _config_cache
    cfg = dict(DEFAULT_CONFIG)
    # 仅接受已知字段且可转 float/int/bool 的键，防脏数据
    for k in DEFAULT_CONFIG:
        if k in new_cfg:
            try:
                cfg[k] = (type(DEFAULT_CONFIG[k]))(new_cfg[k])
            except (TypeError, ValueError):
                continue
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    with _config_lock:
        _config_cache = cfg
    return cfg


# --------------------------------------------------------------------------
# 采样：新浪批量涨跌幅（独立实现，不碰大盘云图热路径与缓存）
# --------------------------------------------------------------------------
def _sina_batch_one(batch):
    """新浪批量获取单批涨跌幅（供并行调用）。返回 {sina_code: 涨跌幅%}"""
    headers = {
        'User-Agent': get_random_user_agent(),
        'Referer': 'https://finance.sina.com.cn/'
    }
    result = {}
    try:
        response = requests.get(SINA_HQ_URL.format(codes=','.join(batch)),
                                headers=headers, timeout=10)
        response.encoding = 'gbk'
        for line in response.text.strip().split('\n'):
            m = re.search(r'hq_str_(\w+)="([^"]*)"', line)
            if not m:
                continue
            code = m.group(1)
            fields = m.group(2).split(',')
            if len(fields) >= 4:
                try:
                    pre_close = float(fields[2])
                    price = float(fields[3])
                    # price<=0：盘前/集合竞价未撮合/停牌无成交，跳过避免 -100% 误报
                    if pre_close > 0 and price > 0:
                        result[code] = round((price - pre_close) / pre_close * 100, 2)
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        logger.warning(f"[个股异动] 新浪批量行情获取失败: {e}")
    return result


def fetch_market_pct(codes):
    """并行批量获取全市场涨跌幅。返回 {sina_code: pct%}；数量过少视为失败返回 {}。"""
    if not codes:
        return {}
    from concurrent.futures import ThreadPoolExecutor
    batch_size = 400
    batches = [codes[i:i + batch_size] for i in range(0, len(codes), batch_size)]
    result = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        for batch_result in executor.map(_sina_batch_one, batches):
            result.update(batch_result)
    # 采样覆盖率过低（新浪断连等）视为本轮失败，避免半份数据算出错误Δ
    if len(result) < len(codes) * 0.8:
        logger.warning(f"[个股异动] 采样覆盖率不足 {len(result)}/{len(codes)}，本轮作废")
        return {}
    return result


# --------------------------------------------------------------------------
# 快照落盘（data/stock_pulse/snapshots_YYYYMMDD.json，次日首写自动清空）
# --------------------------------------------------------------------------
_snap_lock = threading.Lock()


def _snap_path(date_str):
    return os.path.join(PULSE_DIR, f'snapshots_{date_str}.json')


def _today_str(now=None):
    return (now or datetime.now()).strftime('%Y%m%d')


def load_snap_doc(date_str):
    """读取某天快照；不存在或日期不符返回空 doc（跨天即清空昨天）。"""
    path = _snap_path(date_str)
    if not os.path.exists(path):
        return {'date': date_str, 'rounds': []}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            doc = json.load(f)
        if doc.get('date') != date_str or not isinstance(doc.get('rounds'), list):
            return {'date': date_str, 'rounds': []}
        return doc
    except Exception as e:
        logger.error(f"[个股异动] 快照读取失败 {path}: {e}")
        return {'date': date_str, 'rounds': []}


def _write_snap_doc(date_str, doc):
    os.makedirs(PULSE_DIR, exist_ok=True)
    path = _snap_path(date_str)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, path)  # 原子替换


def save_round_pct(date_str, time_str, pct_map):
    """追加/覆盖一轮快照；同一天同一时间点重复则覆盖为最新。"""
    with _snap_lock:
        doc = load_snap_doc(date_str)
        doc['rounds'] = [r for r in doc['rounds'] if r.get('time') != time_str]
        doc['rounds'].append({'time': time_str, 'pct': pct_map})
        doc['rounds'].sort(key=lambda r: r['time'])
        _write_snap_doc(date_str, doc)


def load_prev_round(date_str, time_str):
    """取当日 time_str 之前最近一轮的 (prev_time, pct_map)，没有返回 (None, None)。"""
    doc = load_snap_doc(date_str)
    prev = None
    for r in doc['rounds']:
        if r.get('time', '') >= time_str:
            break
        prev = r
    if prev is None:
        return None, None
    return prev.get('time'), prev.get('pct') or {}


def latest_round(date_str=None):
    """最新一轮 (date_str, time, pct_map)，无数据返回 (None, None, None)。"""
    date_str = date_str or _today_str()
    doc = load_snap_doc(date_str)
    if not doc['rounds']:
        return date_str, None, None
    last = doc['rounds'][-1]
    return date_str, last.get('time'), last.get('pct') or {}


# --------------------------------------------------------------------------
# 股票 → 行业映射
# --------------------------------------------------------------------------
_stocks_map_cache = {'ts': 0.0, 'data': {}}


def _stocks_map():
    """{sina_code: {name, l1, l2}}（复用大盘云图行业缓存，进程内 10 分钟缓存）。"""
    if time.time() - _stocks_map_cache['ts'] < 600 and _stocks_map_cache['data']:
        return _stocks_map_cache['data']
    try:
        from data.data_processor import get_all_market_map_stocks
        raw = get_all_market_map_stocks()
        if raw:
            _stocks_map_cache['ts'] = time.time()
            _stocks_map_cache['data'] = raw
            return raw
    except Exception as e:
        logger.error(f"[个股异动] 行业映射获取失败: {e}")
    return _stocks_map_cache['data']


# --------------------------------------------------------------------------
# 检测：板块聚集
# --------------------------------------------------------------------------
def _cluster_threshold(total, abs_key, ratio_key, cfg):
    """家数门槛 = max(绝对门槛, 板块股票数×比例, 小板块最少命中数)。"""
    return max(int(cfg[abs_key]), int(total * float(cfg[ratio_key])), int(cfg['cluster_min_hits']))


def _sector_findings(cur, prev, stocks, cfg, time_str):
    """板块聚集检测。cur/prev: {code: pct}。返回板块异动列表（一级+二级各算）。"""
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
    findings = []
    for level_key, level_label in (('l1', '一级'), ('l2', '二级')):
        buckets = {}  # sector -> [(code, name, l1, pct, prev_pct, delta)]
        for code, pct in cur.items():
            info = stocks.get(code)
            if not info:
                continue
            prev_pct = prev.get(code)
            if prev_pct is None:
                continue
            sec = info.get(level_key)
            if not sec:
                continue
            l1 = info.get('l1', '')
            buckets.setdefault(sec, []).append(
                (code, info.get('name', ''), l1, pct, prev_pct, pct - prev_pct))

        for sec, items in buckets.items():
            total = len(items)
            if total < 5:  # 板块太小无统计意义
                continue
            hits = []
            surge = [it for it in items if it[5] >= float(cfg['cluster_surge_delta'])]
            if len(surge) >= _cluster_threshold(total, 'cluster_surge_abs', 'cluster_surge_ratio', cfg):
                hits.append({'type': 'cluster_surge', 'label': '集体拉升', 'count': len(surge)})
            turn_red = [it for it in items
                        if it[4] <= 0 and it[3] > 0 and it[5] >= float(cfg['cluster_turn_red_delta'])]
            if len(turn_red) >= _cluster_threshold(total, 'cluster_turn_red_abs',
                                                   'cluster_turn_red_ratio', cfg):
                hits.append({'type': 'cluster_turn_red', 'label': '集体翻红', 'count': len(turn_red)})
            dump = [it for it in items if it[5] <= -float(cfg['cluster_dump_delta'])]
            if len(dump) >= _cluster_threshold(total, 'cluster_dump_abs', 'cluster_dump_ratio', cfg):
                hits.append({'type': 'cluster_dump', 'label': '集体跳水', 'count': len(dump)})
            if not hits:
                continue

            leaders = sorted(items, key=lambda x: -x[3])[:3]
            losers = sorted(items, key=lambda x: x[3])[:3]
            findings.append({
                'kind': 'pulse_sector',
                'level': level_key,
                'level_label': level_label,
                'l1': items[0][2],
                'sector': sec,
                'total': total,
                'median_pct': round(median([it[3] for it in items]), 2),
                'median_delta': round(median([it[5] for it in items]), 2),
                'leaders': [{'name': n, 'code': c, 'pct': round(p, 2), 'delta': round(d, 2)}
                            for c, n, _l1, p, _pp, d in leaders],
                'losers': [{'name': n, 'code': c, 'pct': round(p, 2), 'delta': round(d, 2)}
                           for c, n, _l1, p, _pp, d in losers],
                'hits': hits,
                'time': time_str,
                'date': _today_str(),
            })
    # 家数最多的排前（更显著）
    findings.sort(key=lambda f: -max(h['count'] for h in f['hits']))
    return findings


# --------------------------------------------------------------------------
# 检测：个股
# --------------------------------------------------------------------------
def _stock_findings(cur, prev, stocks, cfg, time_str):
    """个股检测：仅涨停/跌停（仅状态翻转时触发，封板期间不重复报）。
    单纯拉升/跳水不推送（用户只关心涨跌停），由板块聚集覆盖整体异动。"""
    cfg = {**DEFAULT_CONFIG, **(cfg or {})}
    out = []
    tol = float(cfg['limit_tolerance'])
    for code, pct in cur.items():
        info = stocks.get(code)
        if not info:
            continue
        name = info.get('name', '')
        prev_pct = prev.get(code)
        if prev_pct is None:
            continue  # 涨停/跌停需对比上一轮，首轮无对比不触发
        limit = _limit_of(code, name)
        hit = None
        if pct >= limit * tol and prev_pct < limit * tol:
            hit = {'type': 'limit_up', 'label': '涨停'}
        elif pct <= -limit * tol and prev_pct > -limit * tol:
            hit = {'type': 'limit_down', 'label': '跌停'}
        if hit:
            hit.update({'code': code, 'name': name, 'sector': info.get('l1', ''),
                        'pct': pct, 'kind': 'pulse_stock', 'time': time_str, 'date': _today_str()})
            out.append(hit)
    return out


# --------------------------------------------------------------------------
# 汇总：市场温度
# --------------------------------------------------------------------------
def build_market_summary(pct_map, stocks, cfg=None):
    """全市场涨跌家数 + 申万一级行业涨幅中位数排行。"""
    cfg = cfg or load_config()
    top_n = int(cfg.get('sector_top_n', 3))
    min_sector = int(cfg.get('summary_min_sector', 5))
    ups = downs = flats = limit_ups = limit_downs = 0
    sector_stats = {}
    for code, pct in pct_map.items():
        if pct > 0:
            ups += 1
        elif pct < 0:
            downs += 1
        else:
            flats += 1
        info = stocks.get(code)
        name = info.get('name', '') if info else ''
        limit = _limit_of(code, name)
        if pct >= limit * 0.998:
            limit_ups += 1
        elif pct <= -limit * 0.998:
            limit_downs += 1
        l1 = info.get('l1') if info else None
        if l1:
            st = sector_stats.setdefault(l1, {'pcts': [], 'up': 0, 'total': 0})
            st['pcts'].append(pct)
            st['total'] += 1
            if pct > 0:
                st['up'] += 1
    ranked = []
    for name, st in sector_stats.items():
        if st['total'] < min_sector:
            continue
        ranked.append({'sector': name, 'median_pct': round(median(st['pcts']), 2),
                       'up_ratio': round(st['up'] / st['total'] * 100), 'count': st['total']})
    ranked.sort(key=lambda x: -x['median_pct'])
    return {
        'advance': ups, 'decline': downs, 'flat': flats,
        'limit_up': limit_ups, 'limit_down': limit_downs,
        'sectors_top': ranked[:top_n],
        'sectors_bottom': list(reversed(ranked[-top_n:])),
    }


def get_latest_summary():
    """最新一轮概览（供 API /summary；不发起网络请求，读当日快照）。
    除市场温度外，附带板块聚集活动：最新一轮有多少板块在集体拉升/跳水及各自中位涨幅。"""
    date_str, time_str, pct_map = latest_round()
    if not pct_map:
        return None
    stocks = _stocks_map()
    summary = {'date': date_str, 'time': time_str,
               **build_market_summary(pct_map, stocks)}
    # 板块聚集活动概览（基于最新两轮对比，与实时检测同一套阈值）
    rising, falling = [], []
    try:
        prev_time, prev = load_prev_round(date_str, time_str)
        if prev:
            cfg = load_config()
            for f in _sector_findings(pct_map, prev, stocks, cfg, time_str):
                types = {h['type'] for h in f['hits']}
                item = {'sector': f['sector'], 'l1': f['l1'], 'level': f['level'],
                        'median_pct': f['median_pct'], 'total': f['total'],
                        'hits': [{'type': h['type'], 'label': h['label'], 'count': h['count']}
                                 for h in f['hits']]}
                if 'cluster_dump' in types:
                    falling.append(item)
                elif types & {'cluster_surge', 'cluster_turn_red'}:
                    rising.append(item)
    except Exception as e:
        logger.warning(f"[个股异动] 板块活动概览计算失败: {e}")
    summary['rising_count'] = len(rising)
    summary['falling_count'] = len(falling)
    summary['sectors_rising'] = rising[:8]
    summary['sectors_falling'] = falling[:8]
    return summary


# --------------------------------------------------------------------------
# 轮次编排：检测 → 冷却 → 聚合推送 → 入库
# --------------------------------------------------------------------------
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
        json.dump(alerts, f, ensure_ascii=False, indent=2)


def _cooldown_keys(alerts, cooldown_sec, now_ts):
    """收集冷却期内出现过的去重键集合（记录按时间追加，倒序遇到过期即停）。"""
    keys = set()
    for a in reversed(alerts):
        try:
            t = datetime.fromisoformat(a['timestamp']).timestamp()
        except Exception:
            continue
        if now_ts - t >= cooldown_sec:
            break
        keys.update(a.get('keys') or [])
    return keys


def _format_round_message(record):
    """飞书/企微 markdown：标题即最重要异动，正文紧凑分节，一眼可扫。
    - 标题：时间 + 最显著的板块/涨跌停信号（通知栏不点开就知道发生了什么）
    - 板块聚集：一行一板块，跳水显领跌、拉升显领涨
    - 个股：涨跌停只列名字（幅度恒近涨停价，重复无信息量）
    - 市场温度：一行家数 + 领涨领跌行业
    """
    t = record.get('time', '')
    closing = record.get('closing')
    cfg = load_config()
    sectors = record.get('sectors') or []
    stocks = record.get('stocks') or []
    summary = record.get('summary')

    # ---- 标题：最多 3 个信号片段 ----
    title_bits = []
    for f in sectors[:2]:
        h = max(f['hits'], key=lambda x: x['count'])
        title_bits.append(f"{f['sector']}{h['count']}只{h['label']}")
    lu = sum(1 for s in stocks if s['type'] == 'limit_up')
    ld = sum(1 for s in stocks if s['type'] == 'limit_down')
    if lu:
        title_bits.append(f"涨停{lu}只")
    if ld:
        title_bits.append(f"跌停{ld}只")
    if not title_bits:
        title_bits.append(f"上涨{summary['advance']} 涨停{summary['limit_up']}"
                          if summary else "市场温度")
    title = f"{'📊 收盘' if closing else '📈'} {t}｜{' · '.join(title_bits[:3])}"

    # ---- 正文 ----
    lines = []
    # 对比基准非 5 分钟（跨午休/补采样）时注明，避免 Δ 误读
    prev_time = record.get('prev_time')
    if prev_time:
        try:
            hh, mm = map(int, t.split(':'))
            ph, pm = map(int, prev_time.split(':'))
            if (hh * 60 + mm) - (ph * 60 + pm) != 5:
                lines.append(f"> ⏱ 对比基准 {prev_time}（间隔非5分钟）")
        except Exception:
            pass

    if sectors:
        lines.append("> **🧲 板块聚集**")
        for f in sectors:
            sec_label = f"{f['l1']}·{f['sector']}" if f.get('level') == 'l2' and f.get('l1') != f['sector'] else f['sector']
            for h in f['hits']:
                icon = '🔴' if h['type'] in ('cluster_surge', 'cluster_turn_red') else '🟢'
                lead = ''
                if h['type'] == 'cluster_dump' and f.get('losers'):
                    worst = f['losers'][0]
                    lead = f"，领跌 {worst['name']} {worst['pct']:+.2f}%"
                elif f.get('leaders'):
                    best = f['leaders'][0]
                    lead = f"，领涨 {best['name']} {best['pct']:+.2f}%"
                lines.append(
                    f"> {icon} **{sec_label}**：{h['count']}/{f['total']} 只{h['label']}"
                    f"（中位 {f['median_pct']:+.2f}%）{lead}")

    if stocks:
        groups = {}
        for s in stocks:
            groups.setdefault(s['type'], []).append(s)
        lines.append("> **🚨 个股涨跌停**")
        top = int(cfg.get('stock_summary_top', 5))
        for typ, label, icon in (('limit_up', '涨停', '🔴'), ('limit_down', '跌停', '🟢')):
            items = groups.get(typ)
            if not items:
                continue
            shown = items[:top]
            names = '、'.join(s['name'] for s in shown)
            more = " 等" if len(items) > len(shown) else ""
            lines.append(f"> {icon} {label} {len(items)} 只：{names}{more}")

    if summary:
        lines.append("> **🌡 市场温度**")
        lines.append(f"> 上涨 {summary['advance']} / 下跌 {summary['decline']}"
                     f" ｜ 涨停 {summary['limit_up']} / 跌停 {summary['limit_down']}")
        if summary.get('sectors_top'):
            tops = '、'.join(f"{s['sector']} {s['median_pct']:+.2f}%"
                             for s in summary['sectors_top'])
            lines.append(f"> 🔴 {tops}")
        if summary.get('sectors_bottom'):
            bots = '、'.join(f"{s['sector']} {s['median_pct']:+.2f}%"
                             for s in summary['sectors_bottom'])
            lines.append(f"> 🟢 {bots}")

    return title, "\n".join(lines)


def _push_round(date_str, time_str, sector_fs, stock_fs, summary, cfg,
                closing=False, prev_time=None):
    """合并冷却 → 聚合一条记录 → 飞书推送 → 入库 → WebSocket。返回是否推送。"""
    now = datetime.now()
    now_ts = now.timestamp()
    cooldown = float(cfg.get('cooldown_minutes', 40)) * 60

    alerts = _load_alerts()
    recent = _cooldown_keys(alerts, cooldown, now_ts)

    # 板块异动：同板块+同类型冷却；按家数取最显著 N 条
    kept_sectors, keys = [], []
    for f in sector_fs:
        f_keys = [f"{f['sector']}|{h['type']}" for h in f['hits']]
        if any(k in recent for k in f_keys):
            continue
        kept_sectors.append(f)
        keys.extend(f_keys)
    kept_sectors = kept_sectors[:int(cfg.get('max_sector_pushes', 3))]

    # 个股异动：同股+同类型冷却
    kept_stocks = []
    for s in stock_fs:
        s_key = f"stock:{s['code']}|{s['type']}"
        if s_key in recent:
            continue
        kept_stocks.append(s)
        keys.append(s_key)

    # 是否推送：有板块/个股异动；或整半点汇总轮；或收盘轮必推
    minute_ok = summary is not None and (
        closing or int(time_str.split(':')[1]) % int(cfg.get('summary_interval_minutes', 30)) == 0)
    if not kept_sectors and not kept_stocks and not minute_ok:
        return False

    record = {
        'kind': 'pulse_round', 'date': date_str, 'time': time_str,
        'timestamp': now.isoformat(), 'closing': closing,
        'prev_time': prev_time, 'sectors': kept_sectors, 'stocks': kept_stocks,
        'summary': summary, 'keys': keys, 'pushed': False,
    }

    pushed = False
    try:
        from pushers.notification_pusher import send_news_message
        title, content = _format_round_message(record)
        pushed = bool(send_news_message(title, content))
    except Exception as e:
        logger.error(f"[个股异动] 推送失败: {e}")
    record['pushed'] = pushed

    with _alerts_lock:
        alerts = _load_alerts()
        alerts.append(record)
        _save_alerts(alerts[-500:])  # 防膨胀

    try:
        from ws import push_event
        push_event('stock_pulse', record)
    except Exception:
        pass
    return True


def detect_round(date_str, time_str, cur, prev=None, prev_time=None, push=False,
                 stocks=None, cfg=None, closing=False):
    """对单轮快照跑个股异动检测。

    cur/prev: {code: pct}。返回 (板块异动列表, 个股异动列表, 市场温度或 None)。
    push=True 时走冷却 + 聚合推送（实时轮用）。
    """
    cfg = cfg or load_config()
    stocks = stocks or _stocks_map()
    if not cur or not stocks:
        return [], [], None

    sector_fs = _sector_findings(cur, prev or {}, stocks, cfg, time_str) if prev else []
    stock_fs = _stock_findings(cur, prev or {}, stocks, cfg, time_str)

    # 汇总：整半点轮 / 收盘轮附带
    summary = None
    try:
        minute = int(time_str.split(':')[1])
    except Exception:
        minute = -1
    if closing or minute % int(cfg.get('summary_interval_minutes', 30)) == 0:
        summary = build_market_summary(cur, stocks, cfg)

    if push:
        _push_round(date_str, time_str, sector_fs, stock_fs, summary, cfg,
                    closing=closing, prev_time=prev_time)
    return sector_fs, stock_fs, summary


def detect_full_day(date_str=None, push=False):
    """回放某天全部轮次（复盘/手动扫描用）。返回 (findings, latest_summary, round_count)。"""
    if not date_str:
        date_str = _today_str()
    doc = load_snap_doc(date_str)
    rounds = doc.get('rounds') or []
    all_findings = []
    latest_summary = None
    for i, r in enumerate(rounds):
        try:
            prev = rounds[i - 1]['pct'] if i > 0 else None
            sfs, stkfs, summ = detect_round(date_str, r['time'], r.get('pct') or {},
                                            prev=prev, push=push)
            all_findings.extend(sfs)
            all_findings.extend(stkfs)
            if summ:
                latest_summary = {'date': date_str, 'time': r['time'], **summ}
        except Exception as e:
            logger.warning(f"[个股异动] 回放异常 {r.get('time')}: {e}")
    all_findings.sort(key=lambda f: (f.get('time', ''), 0 if f.get('kind') == 'pulse_sector' else 1),
                      reverse=True)
    return all_findings, latest_summary, len(rounds)


def list_alerts(date_str=None, limit=200):
    """已推送的轮次记录（倒序）。"""
    alerts = _load_alerts()
    if date_str:
        alerts = [a for a in alerts if a.get('date') == date_str]
    alerts = sorted(alerts, key=lambda a: a.get('timestamp', ''), reverse=True)
    return alerts[:limit]


# --------------------------------------------------------------------------
# 后台线程：交易时段每 5 分钟对齐采样
# --------------------------------------------------------------------------
_last_round_key = ''  # 'YYYYMMDDHH:MM'，同一 5 分钟窗口内防重复采样


def _run_round(time_str, cfg, closing=False):
    """执行一轮：采样 → 取上一轮 → 检测 → 推送 → 落盘。"""
    stocks = _stocks_map()
    if not stocks:
        logger.warning("[个股异动] 行业映射为空，跳过本轮")
        return
    cur = fetch_market_pct(list(stocks.keys()))
    if not cur:
        return
    date_str = _today_str()
    prev_time, prev = load_prev_round(date_str, time_str)
    save_round_pct(date_str, time_str, cur)
    sector_fs, stock_fs, _ = detect_round(date_str, time_str, cur, prev=prev,
                                          prev_time=prev_time, push=True,
                                          stocks=stocks, cfg=cfg, closing=closing)
    logger.info(f"[个股异动] {date_str} {time_str} 采样{len(cur)}只 "
                f"板块命中{len(sector_fs)} 个股命中{len(stock_fs)}"
                f"{'（收盘总结）' if closing else ''}")


def stock_pulse_loop():
    """个股异动监控主循环：20 秒轮询，命中 5 分钟整点（分钟%5==0）即采样一轮。"""
    global _last_round_key
    register_thread('stock_pulse', heartbeat_timeout=900)  # 采样周期5分钟，需放宽超时
    logger.info('个股异动监控线程启动')
    while True:
        try:
            heartbeat('stock_pulse')
            now = datetime.now()
            cfg = load_config()
            if not cfg.get('enabled', True):
                time.sleep(60)
                continue
            if not is_trading_day(now):
                time.sleep(60)
                continue

            closing_catchup = False
            if now.hour == 15 and 1 <= now.minute <= 40:
                # 收盘兜底：15:01~15:40 之间若当日还没有 15:00 轮（如后端中途重启），补一次收盘总结
                doc = load_snap_doc(_today_str(now))
                if not any(r.get('time') == '15:00' for r in doc['rounds']):
                    closing_catchup = True

            if closing_catchup:
                _run_round('15:00', cfg, closing=True)
                _last_round_key = _today_str(now) + '15:00'
            elif now.minute % 5 == 0:
                key = _today_str(now) + now.strftime('%H:%M')
                if key != _last_round_key:
                    _last_round_key = key
                    _run_round(now.strftime('%H:%M'), cfg, closing=(now.hour == 15))
        except Exception as e:
            logger.error(f"[个股异动] 线程循环异常: {e}")
        time.sleep(20)
