# -*- coding: utf-8 -*-
"""自选股价格异动监控:轮询、当日采样存盘(懒替换)、10 类检测、去重冷却、推送。

数据保留:不按时间清零,新交易日第一笔数据到来时删旧文件、起新一份(懒替换)。
"""
import os
import json
import glob
import time
import threading
from datetime import datetime, timedelta

from config import REALTIME_DIR, STOCK_MONITOR_CONFIG_FILE
from logger import get_logger

logger = get_logger('stock_price')
error_logger = get_logger('error')

ALERTS_FILE = os.path.join(REALTIME_DIR, 'stock_price_alerts.json')


# --------------------------------------------------------------------------
# 当日采样存盘(懒替换:新交易日首笔数据到来时清掉旧文件)
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# 默认阈值(新增自选股默认全开)
# --------------------------------------------------------------------------
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
    """取距今最接近 win_min 分钟(及以前)的一个历史采样,作急涨急跌比较点。

    Returns:
        dict or None: 返回参考采样点，如果数据不足则返回 None

    注意：必须返回一个时间 <= cutoff 的采样点，避免开盘初期误用第一个点。
    """
    if len(series) < 2:
        return None
    try:
        cur = datetime.strptime(series[-1]['ts'], '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None
    cutoff = cur - timedelta(minutes=win_min)
    ref = None
    # 从旧到新遍历，找到 cutoff 时间前最近的一个采样点
    for s in series[:-1]:
        try:
            t = datetime.strptime(s['ts'], '%Y-%m-%d %H:%M:%S')
        except Exception:
            continue
        if t <= cutoff:
            ref = s  # 持续更新，直到遇到第一个 > cutoff 的点
        else:
            break  # 遇到 > cutoff 的点，停止
    # 必须有一个时间 <= cutoff 的采样点，否则返回 None（数据不足）
    return ref


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


# --------------------------------------------------------------------------
# 辅助函数：获取上次推送的参考值（用于递进检测）
# --------------------------------------------------------------------------
def _get_last_ref_value(code, hit_type, alerts, today):
    """获取上次推送的参考值，用于递进检测。

    返回：(ref_value, should_check)
    - ref_value: 上次推送时的参考值（低点/高点/涨跌幅/振幅），无记录时返回 None
    - should_check: 是否需要继续检测（如果当天没有记录或冷却期已过，返回 True）
    """
    if not alerts:
        return None, True
    # 从最新记录开始查找
    for a in reversed(alerts):
        if a.get('code') != code or a.get('type') != hit_type:
            continue
        # 只看当天的记录
        if a.get('date') != today:
            return None, True
        # 找到最近一条同类型记录
        if hit_type == 'dip_rebound':
            return a.get('ref_low'), True
        elif hit_type == 'spike_fade':
            return a.get('ref_high'), True
        elif hit_type == 'cum_move':
            return a.get('ref_pct'), True
        elif hit_type == 'amplitude':
            return a.get('ref_amp'), True
    return None, True


def _cum_move(q, cfg, alerts=None, today=None):
    """累计涨跌检测（递进）。

    只有涨跌幅比上次推送时更极端（涨得更多或跌得更多），才会触发。
    避免持续涨跌时反复推送。
    """
    if not cfg['cum_move']['enabled']:
        return None
    pct = q['pct']
    if abs(pct) < cfg['cum_move']['pct']:
        return None

    # 递进检测：只有涨跌幅更极端才触发
    if alerts and today:
        last_pct, _ = _get_last_ref_value(q.get('_code', ''), 'cum_move', alerts, today)
        if last_pct is not None:
            # 判断方向是否一致
            same_direction = (pct > 0 and last_pct > 0) or (pct < 0 and last_pct < 0)
            if same_direction:
                # 如果是同向，只有更极端才触发（涨得更多或跌得更多）
                if abs(pct) <= abs(last_pct):
                    return None
            # 如果方向相反（从涨到跌或从跌到涨），允许触发

    return {'type': 'cum_move', 'label': f'累计{"大涨" if pct > 0 else "大跌"} {pct:+.2f}%', 'direction': 1 if pct > 0 else -1}


def _spike_fade(q, cfg, alerts=None, today=None):
    """冲高回落检测（递进）。

    只有出现比上次推送时更高的新高点并回落，才会触发。
    避免重复上报同一高点的回落。
    """
    if not cfg['spike_fade']['enabled']:
        return None
    pc = q['prev_close'] or 0
    if not pc or not q.get('high'):
        return None

    peak_pct = (q['high'] - pc) / pc * 100
    if peak_pct < cfg['spike_fade']['peak']:
        return None

    back = (q['high'] - q['price']) / q['high'] * 100
    if back < cfg['spike_fade']['back']:
        return None

    # 递进检测：只有出现新高点才触发
    if alerts and today:
        last_high, _ = _get_last_ref_value(q.get('_code', ''), 'spike_fade', alerts, today)
        if last_high is not None:
            # 如果当前高点没有创新高（即当前高点 <= 上次推送时的高点），不触发
            if q['high'] <= last_high:
                return None

    return {'type': 'spike_fade', 'label': f'冲高回落 从高点 -{back:.2f}%'}


def _dip_rebound(q, cfg, alerts=None, today=None):
    """探底回升检测（递进）。

    只有出现比上次推送时更低的新低点并反弹，才会触发。
    避免重复上报同一低点的反弹。

    逻辑：
    1. 首先检测是否满足基本条件（跌超过阈值+反弹超过阈值）
    2. 如果当天已推送过，检查是否出现新低点
    3. 只有新低点比上次推送时的低点更低，才触发
    """
    if not cfg['dip_rebound']['enabled']:
        return None
    pc = q['prev_close'] or 0
    if not pc or not q.get('low'):
        return None

    trough_pct = (pc - q['low']) / pc * 100
    if trough_pct < cfg['dip_rebound']['trough']:
        return None

    reb = (q['price'] - q['low']) / q['low'] * 100
    if reb < cfg['dip_rebound']['back']:
        return None

    # 递进检测：只有出现新低点才触发
    if alerts and today:
        last_low, _ = _get_last_ref_value(q.get('_code', ''), 'dip_rebound', alerts, today)
        if last_low is not None:
            # 如果当前低点没有创新低（即当前低点 >= 上次推送时的低点），不触发
            if q['low'] >= last_low:
                return None

    return {'type': 'dip_rebound', 'label': f'探底回升 从低点 +{reb:.2f}%'}


def _gap_open(q, state, cfg):
    """检测大幅低开/高开。
    
    只在开盘后30分钟内检测，且每天只提醒一次。
    通过 alerts 记录判断是否当天已触发，避免状态丢失后重复提醒。
    """
    if not cfg['gap_open']['enabled']:
        return None
    
    # 时间窗口检查：只在开盘后30分钟内检测（9:30-10:00 或 13:00-13:30）
    try:
        ts = q.get('ts', '')
        if ts:
            t = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            hour, minute = t.hour, t.minute
            # 只在早盘开盘后30分钟内检测（9:30-10:00）
            if not (hour == 9 and minute >= 30 or hour == 10 and minute == 0):
                return None
    except Exception:
        pass
    
    # 检查是否当天已触发过（通过 alerts 记录）
    if state.get('gap_fired'):
        return None
    
    pc = q['prev_close'] or 0
    if not pc or not q.get('open'):
        return None
    gap = (q['open'] - pc) / pc * 100
    if abs(gap) >= cfg['gap_open']['pct']:
        state['gap_fired'] = True
        return {'type': 'gap_open', 'label': f'大幅{"高开" if gap > 0 else "低开"} {gap:+.2f}%'}
    return None


def _amplitude(q, cfg, alerts=None, today=None):
    """振幅过大检测（递进）。

    只有振幅比上次推送时更大，才会触发。
    避免振幅持续增大时反复推送。
    """
    if not cfg['amplitude']['enabled']:
        return None
    pc = q['prev_close'] or 0
    if not pc or q.get('high') is None or q.get('low') is None:
        return None

    amp = (q['high'] - q['low']) / pc * 100
    if amp < cfg['amplitude']['pct']:
        return None

    # 递进检测：只有振幅更大才触发
    if alerts and today:
        last_amp, _ = _get_last_ref_value(q.get('_code', ''), 'amplitude', alerts, today)
        if last_amp is not None:
            # 如果振幅没有扩大，不触发
            if amp <= last_amp:
                return None

    return {'type': 'amplitude', 'label': f'振幅过大 {amp:.2f}%'}


def _limit_break(q, limit, state, cfg):
    if not cfg['limit_break']['enabled']:
        return None
    if q['pct'] >= limit * 0.995:
        state['touched_up'] = True
    if q['pct'] <= -limit * 0.995:
        state['touched_down'] = True
    if state.get('touched_up') and q['pct'] <= limit - cfg['limit_break']['back']:
        return {'type': 'limit_break', 'label': f'炸板 回落至 {q["pct"]:+.2f}%'}
    if state.get('touched_down') and q['pct'] >= -limit + cfg['limit_break']['back']:
        return {'type': 'limit_break', 'label': f'撬板 反弹至 {q["pct"]:+.2f}%'}
    return None


def detect_hits(q, series, state, alerts_cfg, limit, name, alerts=None, today=None):
    """对一只票跑全部启用的检测,返回 hits 列表(一次报价可能命中多条)。

    Args:
        alerts: 历史告警记录，用于递进检测
        today: 当前日期字符串，用于查询当天记录
    """
    hits = []
    if alerts_cfg['limit_up']['enabled'] and q['pct'] >= limit * 0.995:
        hits.append({'type': 'limit_up', 'label': '触及涨停'})
    if alerts_cfg['limit_down']['enabled'] and q['pct'] <= -limit * 0.995:
        hits.append({'type': 'limit_down', 'label': '触及跌停'})

    checkers = (
        lambda: _rapid_move(q, series, alerts_cfg),
        lambda: _cum_move(q, alerts_cfg, alerts, today),
        lambda: _spike_fade(q, alerts_cfg, alerts, today),
        lambda: _dip_rebound(q, alerts_cfg, alerts, today),
        lambda: _amplitude(q, alerts_cfg, alerts, today),
    )
    for fn in checkers:
        try:
            h = fn()
        except Exception as e:
            logger.warning(f'检测异常 {name}: {e}')
            h = None
        if h:
            hits.append(h)

    h = _gap_open(q, state, alerts_cfg)
    if h:
        hits.append(h)
    h = _limit_break(q, limit, state, alerts_cfg)
    if h:
        hits.append(h)
    return hits


# --------------------------------------------------------------------------
# 去重冷却 + 推送入库
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
        json.dump(alerts[-500:], f, ensure_ascii=False)


def is_in_cooldown(code, hit_type, alerts, cooldown_minutes, now=None):
    """同 (股票,类型) 在 cooldown_minutes 内是否已推过。

    一条推送记录可含多个联动类型(types);命中任一即视为该类型冷却中。
    
    特殊处理：
    - gap_open（低开/高开）类型：当天只提醒一次，不看冷却时间
    """
    now = now or datetime.now()
    today = now.strftime('%Y-%m-%d')
    
    # gap_open 类型：当天只提醒一次
    if hit_type == 'gap_open':
        for a in reversed(alerts):
            if a.get('code') != code:
                continue
            types = a.get('types') or [a.get('type')]
            if hit_type in types:
                # 只要当天有记录，就认为已触发
                if a.get('date') == today:
                    return True
        return False
    
    # 其他类型：按冷却时间判断
    threshold = timedelta(minutes=cooldown_minutes)
    for a in reversed(alerts):
        if a.get('code') != code:
            continue
        types = a.get('types') or [a.get('type')]
        if hit_type in types:
            try:
                t = datetime.fromisoformat(a['timestamp'])
            except Exception:
                continue
            if now - t < threshold:
                return True
    return False


def record_alert(code, name, primary_hit, all_hits, quote, pushed, now=None):
    """记录一条异动推送(含本次全部联动类型,供去重冷却用)。

    同时记录关键数据用于递进检测：
    - dip_rebound: 记录低点价格
    - spike_fade: 记录高点价格
    - cum_move: 记录涨跌幅
    - amplitude: 记录振幅
    """
    now = now or datetime.now()
    alerts = _load_alerts()
    rec = {
        'code': code, 'name': name, 'kind': 'stock',
        'type': primary_hit['type'],
        'types': [h['type'] for h in all_hits],
        'labels': [h.get('label', '') for h in all_hits],
        'label': primary_hit.get('label', ''),
        'price': quote.get('price'), 'pct': quote.get('pct'),
        'time': quote.get('ts', ''),
        'date': (quote.get('ts', '') or now.strftime('%Y-%m-%d'))[:10],
        'pushed': pushed, 'timestamp': now.isoformat(),
    }
    # 记录关键数据用于递进检测
    if primary_hit['type'] == 'dip_rebound':
        rec['ref_low'] = quote.get('low')  # 记录低点
    elif primary_hit['type'] == 'spike_fade':
        rec['ref_high'] = quote.get('high')  # 记录高点
    elif primary_hit['type'] == 'cum_move':
        rec['ref_pct'] = quote.get('pct')  # 记录涨跌幅
    elif primary_hit['type'] == 'amplitude':
        # 记录振幅
        pc = quote.get('prev_close') or 0
        if pc and quote.get('high') is not None and quote.get('low') is not None:
            rec['ref_amp'] = (quote['high'] - quote['low']) / pc * 100
    alerts.append(rec)
    _save_alerts(alerts)
    return rec


def list_alerts(date_str=None, limit=200):
    alerts = _load_alerts()
    if date_str:
        alerts = [a for a in alerts if a.get('date') == date_str]
    return sorted(alerts, key=lambda a: a.get('timestamp', ''), reverse=True)[:limit]


# --------------------------------------------------------------------------
# 配置:旧 schema 迁移 + 加载
# --------------------------------------------------------------------------
def _gen_id():
    import uuid
    return uuid.uuid4().hex[:12]


def _normalize_watch_item(it):
    """确保单个 watchlist item 同时带 price_alerts(name/code 适用)与 news_alerts。

    每个 item 最终都有 news_alerts:{enabled, keywords};name/code 类型补 price_alerts。
    这样既能兼容旧 watchlist(无 news_alerts),也让新闻匹配链路读到统一结构。
    """
    if not isinstance(it, dict):
        return it
    it = dict(it)
    typ = it.get('type', 'name')
    # 价格告警:name/code 类型补默认(若缺);keyword 类型不挂(沿用旧行为,loop 会过滤)
    if typ in ('name', 'code'):
        if not it.get('price_alerts'):
            it['price_alerts'] = json.loads(json.dumps(DEFAULT_ALERTS_CFG))
        it.setdefault('price_monitor', True)  # 价格监控总开关
    # 新闻告警:所有类型都补全结构
    na = it.get('news_alerts')
    if not isinstance(na, dict):
        name = (it.get('resolved_name') or (it.get('value', '') if typ != 'keyword' else '') or '').strip()
        code = (it.get('resolved_code') or '').strip()
        if typ == 'keyword':
            base_kw = [it.get('value', '')] if it.get('value') else []
            enabled = True
        else:
            base_kw = [k for k in [name, code] if k]
            enabled = False
        it['news_alerts'] = {'enabled': enabled, 'keywords': base_kw}
    else:
        na.setdefault('enabled', False)
        if not isinstance(na.get('keywords'), list):
            na['keywords'] = []
    return it


def migrate_legacy_config(raw):
    """旧 {enabled, stocks:[{enabled,name,code,keywords}]} → 新 watchlist schema。

    新 schema(含 watchlist)透传并补全 news_alerts;旧 schema 转换:
      - 有 name/code 的当 name 类型 + 默认全开 price_alerts + news_alerts(继承旧 keywords)
      - 仅 keywords 的当 keyword 类型(无 price_alerts,news_alerts 用 keywords)
    每个 watchlist item 最终都带 news_alerts,部分带 price_alerts。
    """
    if not isinstance(raw, dict):
        raw = {}
    if 'watchlist' in raw:
        watchlist = [_normalize_watch_item(it) for it in raw.get('watchlist', [])]
        return {
            'enabled': raw.get('enabled', True),
            'poll_interval_seconds': raw.get('poll_interval_seconds', 25),
            'cooldown_minutes': raw.get('cooldown_minutes', 30),
            'watchlist': watchlist,
        }

    watchlist = []
    for s in raw.get('stocks', []):
        if not isinstance(s, dict) or not s.get('enabled', True):
            continue
        name = (s.get('name') or '').strip()
        code = (s.get('code') or '').strip()
        keywords = [k.strip() for k in (s.get('keywords') or []) if k and k.strip()]
        if name or code:
            kws = []
            for k in [name, code] + keywords:
                if k and k not in kws:
                    kws.append(k)
            watchlist.append({
                'id': _gen_id(), 'type': 'name', 'value': name or code, 'enabled': True,
                'resolved_name': name, 'resolved_code': code,
                'price_monitor': True,
                'price_alerts': json.loads(json.dumps(DEFAULT_ALERTS_CFG)),
                'news_alerts': {'enabled': bool(keywords), 'keywords': kws},
            })
        elif keywords:
            for kw in keywords:
                watchlist.append({
                    'id': _gen_id(), 'type': 'keyword', 'value': kw, 'enabled': True,
                    'news_alerts': {'enabled': True, 'keywords': [kw]},
                })
    return {
        'enabled': raw.get('enabled', True),
        'poll_interval_seconds': 25,
        'cooldown_minutes': 30,
        'watchlist': watchlist,
    }


def load_config():
    """读取 stock_monitor.json 并迁移为新 schema。"""
    default = {'enabled': False, 'poll_interval_seconds': 25, 'cooldown_minutes': 30, 'watchlist': []}
    if not os.path.exists(STOCK_MONITOR_CONFIG_FILE):
        return default
    try:
        with open(STOCK_MONITOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except Exception as e:
        error_logger.error(f'读取股票监控配置失败: {e}')
        return default
    return migrate_legacy_config(raw)


# --------------------------------------------------------------------------
# 主循环:处理一只票的一次报价(存盘→检测→冷却→推送→入库)
# --------------------------------------------------------------------------
_state_lock = threading.Lock()
_stock_state = {}  # {code: {gap_fired, touched_up, touched_down}}


def _format_message(name, code, quote, primary_hit):
    """格式化推送消息：只推一条最重要的异动原因。

    红色=利好(涨), 绿色=利空(跌), 与资金异动一致。
    """
    pct = quote.get('pct')
    pct_s = f'{round(pct, 2):+.2f}%' if pct is not None else '--'
    hit_type = primary_hit.get('type', '')
    label = primary_hit.get('label', hit_type)

    # 判断异动方向:利好(涨)→红, 利空(跌)→绿
    bullish_types = {'rapid_rise', 'limit_up', 'gap_open_high', 'limit_break_up'}
    bearish_types = {'rapid_drop', 'limit_down', 'gap_open_low', 'limit_break_down'}
    # 混合型按label关键字判断
    if hit_type in bullish_types or '大涨' in label or '拉升' in label or '高开' in label or '涨停' in label:
        direction = 'bullish'  # 利好
    elif hit_type in bearish_types or '大跌' in label or '打压' in label or '低开' in label or '跌停' in label:
        direction = 'bearish'  # 利空
    elif '回升' in label or '反弹' in label or '撬板' in label:
        direction = 'bullish'  # 回升是利好
    elif '回落' in label or '炸板' in label:
        direction = 'bearish'  # 回落是利空
    else:
        # 振幅/缺口等中性，看当前涨跌方向
        direction = 'bullish' if (pct or 0) >= 0 else 'bearish'

    # 标题符号: 🔴利好(红) / 🟢利空(绿)，与资金异动保持一致
    icon = '🔴' if direction == 'bullish' else '🟢'

    content = (
        f"> 时间:**{quote.get('ts', '')}**\n"
        f"> 现价:**{quote.get('price')}**  涨跌幅:**{pct_s}**\n"
        f"**{label}**"
    )
    # 标题直接写关键信息，不加"价格异动"前缀，方便手机横幅一眼看到
    title = f"{icon} {name}{label}"
    return title, content


def _select_primary_hit(code, hits, alerts, cooldown):
    """从命中列表中选出最重要的一条新触发原因(不在冷却中+优先级最高)。"""
    PRIORITY = {
        'limit_up': 1, 'limit_down': 1,
        'rapid_rise': 2, 'rapid_drop': 2,
        'cum_move': 3,
        'spike_fade': 4, 'dip_rebound': 4,
        'limit_break': 5,
        'amplitude': 6,
        'gap_open': 7,
    }
    # 先筛选不在冷却中的新触发项
    new_hits = [h for h in hits if not is_in_cooldown(code, h['type'], alerts, cooldown)]
    if not new_hits:
        # 全部在冷却中但整体不是(all在冷却)说明有部分刚过冷却，取优先级最高的
        new_hits = hits
    # 按优先级排序取第一个
    new_hits.sort(key=lambda h: PRIORITY.get(h['type'], 99))
    return new_hits[0]


def _default_pusher(title, content):
    try:
        from notification_pusher import send_news_message, is_push_enabled
        if not is_push_enabled():
            error_logger.warning(f'价格异动推送跳过: 无已启用的推送通道(飞书/企业微信)')
            return False
        result = send_news_message(title, content)
        if result:
            logger.info(f'价格异动推送成功: {title}')
        else:
            error_logger.warning(f'价格异动推送失败: {title} (推送通道返回False)')
        return bool(result)
    except Exception as e:
        error_logger.error(f'价格异动推送失败: {e}')
        return False


def process_tick(code, name, quote, cfg, limit, pusher=None):
    """处理一只票的一次报价:存盘→检测→冷却→推送→入库。返回本次命中的 hits。"""
    pusher = pusher or _default_pusher
    date = (quote.get('ts', '') or datetime.now().strftime('%Y-%m-%d'))[:10]
    append_sample(code, quote, date)
    series = load_quotes(date).get(code, [])

    alerts_cfg = None
    for item in cfg.get('watchlist', []):
        rc = (item.get('resolved_code') or '').strip()
        val = (item.get('value') or '').strip()
        # 匹配逻辑：resolved_code精确匹配 或 value精确匹配code 或 value匹配不含交易所前缀的代码
        if rc == code or val == code or (code and val == code[2:]):
            alerts_cfg = item.get('price_alerts', DEFAULT_ALERTS_CFG)
            break
    if not alerts_cfg:
        return []

    with _state_lock:
        state = _stock_state.setdefault(code, {})

    # 在quote中添加code，用于递进检测
    quote_with_code = dict(quote)
    quote_with_code['_code'] = code

    alerts = _load_alerts()
    hits = detect_hits(quote_with_code, series, state, alerts_cfg, limit, name, alerts, date)
    if not hits:
        return []

    cooldown = cfg.get('cooldown_minutes', 30)
    # 本次所有命中类型都还在冷却内 -> 不重复推
    if all(is_in_cooldown(code, h['type'], alerts, cooldown) for h in hits):
        return []

    # 选出最重要的新触发原因(只推一条)
    primary = _select_primary_hit(code, hits, alerts, cooldown)
    title, content = _format_message(name, code, quote, primary)
    pushed = pusher(title, content)
    record_alert(code, name, primary, hits, quote, pushed)
    # WebSocket实时推送价格异动到前端
    try:
        from app import push_event
        push_event('price_alert', {
            'code': code, 'name': name, 'type': primary['type'],
            'label': primary['label'], 'price': quote.get('price'),
            'pct': quote.get('pct'), 'timestamp': _now_iso(),
            'pushed': pushed
        })
    except Exception:
        pass
    return hits


# --------------------------------------------------------------------------
# 后台轮询线程:交易时段每 poll_interval_seconds 秒批量拉报价 → 逐票 process_tick
# --------------------------------------------------------------------------
def stock_price_loop():
    from data_collector import is_trading_day, is_trading_time
    from stock_price_feed import get_quotes
    from stock_resolver import resolve_identifier, get_limit_pct
    logger.info('价格异动监控线程启动')
    _log_skip_count = 0  # 抑制重复日志
    while True:
        try:
            now = datetime.now()
            cfg = load_config()
            interval = cfg.get('poll_interval_seconds', 25)
            if not cfg.get('enabled'):
                _log_skip_count += 1
                if _log_skip_count <= 3 or _log_skip_count % 120 == 0:
                    logger.info(f'价格异动监控: 全局开关未启用，等待中({_log_skip_count})')
                time.sleep(interval); continue
            if not (is_trading_day(now) and is_trading_time(now)):
                time.sleep(interval); continue
            _log_skip_count = 0
            targets = []  # [(code, name), ...]
            for w in cfg.get('watchlist', []):
                if not (w.get('enabled') and w.get('type') in ('name', 'code')
                        and w.get('price_monitor', True)):
                    continue
                code = (w.get('resolved_code') or '').strip()
                name = w.get('resolved_name') or ''
                if not code:
                    # 现场解析:名字 -> 代码;纯代码 -> 补交易所前缀
                    resolved = resolve_identifier(w.get('value', ''), hint=w.get('type'))
                    if not resolved:
                        error_logger.warning(f'价格异动监控: 无法解析 {w.get("value")}，跳过')
                        continue
                    name, code = resolved
                targets.append((code, name or w.get('value', '')))
            if not targets:
                time.sleep(interval); continue
            codes = [t[0] for t in targets]
            quotes = get_quotes(codes)
            for code, name in targets:
                q = quotes.get(code)
                if not q:
                    continue
                try:
                    limit = get_limit_pct(code, name)
                    hits = process_tick(code, name, q, cfg, limit)
                    if hits:
                        logger.info(f'价格异动 {name}({code}): {[h["type"] for h in hits]}')
                except Exception as e:
                    error_logger.error(f'process_tick 异常 {code}: {e}')
        except Exception as e:
            error_logger.error(f'价格异动监控循环异常: {e}')
        time.sleep(interval)
