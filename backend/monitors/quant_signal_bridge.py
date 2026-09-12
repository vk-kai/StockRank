# -*- coding: utf-8 -*-
"""量化扫描信号桥(StockRank 消息总线接入)。

轮询 quant(合并后的量化后端)的免鉴权增量投递口 /api/market/scan/feed,
把新产生的扫描信号按水位线拉回本地:
  data/realtime/quant_signals.json(kind='tz_signal',cap 500) → WS push_event('tz_signal');

设计要点(与 trendzen_arb_monitor 同风格,但更简单):
- 水位线去重:quant 侧信号表自增 id 做游标,状态存 quant_signal_state.json;
  端点无副作用、不打投递标记,拉取失败/停机不丢(下次从水位线续拉);
- 首跑初始化:状态文件缺失时直接把水位线设为当前 max_id,不回放历史存量;
- 只进统一总线(WS 推送),不发微信/飞书——扫描信号频率高,推送交给作战台事件流,
  避免重蹈"每条都推"的轰炸;
- 轮询窗口与套利监控一致(交易日 08:40-15:15):窗口外休眠,窗口内按配置间隔拉取;
  窗口外产生的信号(如周末手动扫描)由水位线保证下个窗口补拉,不会丢失。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime

from core.config import REALTIME_DIR, CONFIG_DIR
from core.logger import get_logger
from monitors.thread_monitor import register_thread, heartbeat

logger = get_logger('quant_signal')
error_logger = get_logger('error')

ALERTS_FILE = os.path.join(REALTIME_DIR, 'quant_signals.json')
STATE_FILE = os.path.join(REALTIME_DIR, 'quant_signal_state.json')
CONFIG_FILE = os.path.join(CONFIG_DIR, 'quant_signal_bridge.json')

# 轮询窗口:与 trendzen_arb_monitor 一致(信号只会在交易时段批量产生)
_POLL_WINDOW = ('08:40', '15:15')
_SLEEP_OFF_WINDOW = 300  # 窗口外/周末的轮询间隔(秒)


def load_config():
    default = {
        'enabled': True,
        # 生产:Flask 容器经 stock-network 直连 quant 容器;本地开发可改成 http://127.0.0.1:8000
        'base_url': 'http://quant:8000',
        'poll_interval_seconds': 60,
    }
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                default.update({k: raw[k] for k in default if k in raw})
    except Exception as e:
        error_logger.error(f'读取量化信号桥配置失败: {e}')
    return default


# --------------------------------------------------------------------------
# 本地状态与告警库
# --------------------------------------------------------------------------
def _load_state():
    if not os.path.exists(STATE_FILE):
        return None  # None = 首跑
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return int(data.get('last_id', 0) or 0)
    except Exception:
        return None


def _save_state(last_id):
    os.makedirs(REALTIME_DIR, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump({'last_id': int(last_id), 'updated_at': datetime.now().isoformat()}, f)


def _load_alerts():
    if not os.path.exists(ALERTS_FILE):
        return []
    try:
        with open(ALERTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_alerts(alerts):
    os.makedirs(REALTIME_DIR, exist_ok=True)
    with open(ALERTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(alerts[-500:], f, ensure_ascii=False)


def list_alerts(date_str=None, limit=200):
    """供作战台/异动流合并展示(kind='tz_signal')。"""
    alerts = _load_alerts()
    if date_str:
        alerts = [a for a in alerts if a.get('date') == date_str]
    return sorted(alerts, key=lambda a: a.get('timestamp', ''), reverse=True)[:limit]


# --------------------------------------------------------------------------
# 一轮拉取:feed → 逐条入库 → WS 统一总线
# --------------------------------------------------------------------------
def poll_once(cfg=None):
    """拉一轮扫描信号并入库+WS推送。返回本轮新入库条数(测试/手动触发用)。"""
    import requests

    cfg = cfg or load_config()
    base_url = str(cfg.get('base_url') or '').rstrip('/')
    if not base_url:
        return 0

    last_id = _load_state()
    try:
        resp = requests.get(
            f'{base_url}/api/market/scan/feed',
            params={'after_id': last_id or 0, 'limit': 50},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        error_logger.error(f'量化扫描信号feed拉取失败: {e}')
        return 0
    if not payload.get('success'):
        return 0
    items = payload.get('data') or []
    max_id = int(payload.get('max_id') or 0)

    # 首跑:状态文件缺失 → 水位线直接跳到当前 max_id,不回放历史存量
    if last_id is None:
        _save_state(max_id)
        logger.info(f'量化信号桥首跑,水位线初始化为 {max_id}(跳过历史 {max_id} 条存量)')
        return 0

    new_records = []
    now = datetime.now()
    for item in items:
        try:
            sig_id = int(item.get('id'))
        except (TypeError, ValueError):
            continue
        if sig_id <= last_id:
            continue
        direction = str(item.get('direction') or '')
        record = {
            'kind': 'tz_signal',
            'tz_id': sig_id,                      # quant 侧信号ID(水位线对账用)
            'run_id': item.get('run_id'),
            'code': item.get('code', ''),
            'name': item.get('name', ''),
            'direction': direction,
            'label': '买入信号' if 'buy' in direction else ('卖出信号' if 'sell' in direction else '扫描信号'),
            'strategy': item.get('strategy_name', ''),
            'period': item.get('period', ''),
            'price': item.get('price'),
            'time': item.get('signal_time', ''),
            'date': str(item.get('detected_at', ''))[:10],
            'reason': item.get('reason', ''),
            'timestamp': now.isoformat(),
        }
        new_records.append(record)

    if not new_records:
        # 没有新信号也要推进水位线(空表/刚清理等情况)
        if max_id > last_id and not items:
            _save_state(max_id)
        return 0

    alerts = _load_alerts()
    alerts.extend(new_records)
    _save_alerts(alerts)
    new_last = max(int(r['tz_id']) for r in new_records)
    _save_state(max(new_last, last_id))

    logger.info(f'量化扫描信号入库 {len(new_records)} 条(水位线 {last_id} → {new_last})')
    # WebSocket 统一总线推送(作战台事件流/桌面通知)
    try:
        from ws import push_event
        for record in new_records:
            push_event('tz_signal', record)
    except Exception:
        pass
    return len(new_records)


# --------------------------------------------------------------------------
# 后台轮询线程
# --------------------------------------------------------------------------
def _in_poll_window(now):
    if now.weekday() >= 5:
        return False
    hhmm = now.strftime('%H:%M')
    return _POLL_WINDOW[0] <= hhmm <= _POLL_WINDOW[1]


def quant_signal_bridge_loop():
    register_thread('quant_signal_bridge')
    logger.info('量化扫描信号桥线程启动')
    _log_skip_count = 0  # 抑制重复日志
    while True:
        interval = 60
        try:
            heartbeat('quant_signal_bridge')
            cfg = load_config()
            interval = int(cfg.get('poll_interval_seconds', 60) or 60)
            if not cfg.get('enabled'):
                _log_skip_count += 1
                if _log_skip_count <= 3 or _log_skip_count % 120 == 0:
                    logger.info(f'量化信号桥: 开关未启用，等待中({_log_skip_count})')
                time.sleep(interval)
                continue
            if not _in_poll_window(datetime.now()):
                # 窗口外不请求 quant(信号只会在交易时段产生;水位线保证不丢)
                time.sleep(_SLEEP_OFF_WINDOW)
                continue
            _log_skip_count = 0
            poll_once(cfg)
        except Exception as e:
            error_logger.error(f'量化信号桥循环异常: {e}')
        time.sleep(interval)
