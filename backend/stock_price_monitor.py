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
    """取距今最接近 win_min 分钟(及以前)的一个历史采样,作急涨急跌比较点。"""
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
    if not pc or not q.get('high'):
        return None
    peak_pct = (q['high'] - pc) / pc * 100
    if peak_pct < cfg['spike_fade']['peak']:
        return None
    back = (q['high'] - q['price']) / q['high'] * 100
    if back >= cfg['spike_fade']['back']:
        return {'type': 'spike_fade', 'label': f'冲高回落 从高点 -{back:.2f}%'}
    return None


def _dip_rebound(q, cfg):
    if not cfg['dip_rebound']['enabled']:
        return None
    pc = q['prev_close'] or 0
    if not pc or not q.get('low'):
        return None
    trough_pct = (pc - q['low']) / pc * 100
    if trough_pct < cfg['dip_rebound']['trough']:
        return None
    reb = (q['price'] - q['low']) / q['low'] * 100
    if reb >= cfg['dip_rebound']['back']:
        return {'type': 'dip_rebound', 'label': f'探底回升 从低点 +{reb:.2f}%'}
    return None


def _gap_open(q, state, cfg):
    if not cfg['gap_open']['enabled'] or state.get('gap_fired'):
        return None
    pc = q['prev_close'] or 0
    if not pc or not q.get('open'):
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
    if not pc or q.get('high') is None or q.get('low') is None:
        return None
    amp = (q['high'] - q['low']) / pc * 100
    if amp >= cfg['amplitude']['pct']:
        return {'type': 'amplitude', 'label': f'振幅过大 {amp:.2f}%'}
    return None


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


def detect_hits(q, series, state, alerts_cfg, limit, name):
    """对一只票跑全部启用的检测,返回 hits 列表(一次报价可能命中多条)。"""
    hits = []
    if alerts_cfg['limit_up']['enabled'] and q['pct'] >= limit * 0.995:
        hits.append({'type': 'limit_up', 'label': '涨停触及'})
    if alerts_cfg['limit_down']['enabled'] and q['pct'] <= -limit * 0.995:
        hits.append({'type': 'limit_down', 'label': '跌停触及'})

    checkers = (
        lambda: _rapid_move(q, series, alerts_cfg),
        lambda: _cum_move(q, alerts_cfg),
        lambda: _spike_fade(q, alerts_cfg),
        lambda: _dip_rebound(q, alerts_cfg),
        lambda: _amplitude(q, alerts_cfg),
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
    """
    now = now or datetime.now()
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
    """记录一条异动推送(含本次全部联动类型,供去重冷却用)。"""
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


def migrate_legacy_config(raw):
    """旧 {enabled, stocks:[{enabled,name,code,keywords}]} → 新 watchlist schema。

    新 schema(含 watchlist)直接透传;旧 schema 转换:
      - 有 name/code 的当 name 类型 + 默认全开 price_alerts
      - 仅 keywords 的当 keyword 类型(无 price_alerts)
    """
    if not isinstance(raw, dict):
        raw = {}
    if 'watchlist' in raw:
        return {
            'enabled': raw.get('enabled', True),
            'poll_interval_seconds': raw.get('poll_interval_seconds', 25),
            'cooldown_minutes': raw.get('cooldown_minutes', 30),
            'watchlist': raw.get('watchlist', []),
        }

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


def _format_message(name, code, quote, hits):
    pct = quote.get('pct')
    pct_s = f'{round(pct, 2):+.2f}%' if pct is not None else '--'
    lines = [
        f"> 时间:**{quote.get('ts', '')}**",
        f"> 现价:**{quote.get('price')}**  涨跌幅:**{pct_s}**",
        "**触发**",
    ]
    for h in hits:
        lines.append(f"• {h.get('label', h.get('type'))}")
    return f"📈 价格异动 · {name}", "\n".join(lines)


def _default_pusher(title, content):
    try:
        from notification_pusher import send_news_message
        return bool(send_news_message(title, content))
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
        if item.get('resolved_code') == code or item.get('value') == code:
            alerts_cfg = item.get('price_alerts', DEFAULT_ALERTS_CFG)
            break
    if not alerts_cfg:
        return []

    with _state_lock:
        state = _stock_state.setdefault(code, {})
    hits = detect_hits(quote, series, state, alerts_cfg, limit, name)
    if not hits:
        return []

    alerts = _load_alerts()
    cooldown = cfg.get('cooldown_minutes', 30)
    # 本次所有命中类型都还在冷却内 -> 不重复推
    if all(is_in_cooldown(code, h['type'], alerts, cooldown) for h in hits):
        return []

    title, content = _format_message(name, code, quote, hits)
    pushed = pusher(title, content)
    record_alert(code, name, hits[0], hits, quote, pushed)
    return hits
