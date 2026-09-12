# -*- coding: utf-8 -*-
"""TrendZen 套利背离告警接入:轮询 feed → 推送 → 本地入库 → ack 回执闭环。

数据流(与价格异动同构,复用异动预警的展示/通知链路):
- 每 poll_interval_seconds 秒 GET {base_url}/api/market/arb/feed(TrendZen 免鉴权投递口),
  返回未投递告警;TrendZen 在响应时即打 delivered 标记 → 天然防重复拉取/重复推微信;
- 每条告警: 格式化 → send_news_message(企业微信/飞书) → 存
  data/realtime/trendzen_arb_alerts.json(kind='arb',cap 500) → WS push_event('arb_alert');
- 微信推送成功 = 闭环 → POST {base_url}/api/market/arb/feed/ack 回执,
  TrendZen 侧该告警变"已读"(只打标签,不清理);
- 推送失败只入本地库、不打回执:delivered 已打过不会重推,TrendZen 保持未读。
"""
import os
import json
import time
from datetime import datetime

import requests

from core.config import REALTIME_DIR, TRENDZEN_ARB_CONFIG_FILE
from core.logger import get_logger
from monitors.thread_monitor import register_thread, heartbeat

logger = get_logger('trendzen_arb')
error_logger = get_logger('error')

ALERTS_FILE = os.path.join(REALTIME_DIR, 'trendzen_arb_alerts.json')

# 轮询窗口:TrendZen 告警产生于 08:50-15:05,两端各留 10 分钟余量;
# 窗口外不请求(夜间零流量),进程白天重启后下一轮即追平未拉取的告警。
_POLL_WINDOW = ('08:40', '15:15')
_SLEEP_OFF_WINDOW = 300  # 窗口外/周末的轮询间隔(秒)

# 与 TrendZen api/arb.py _FEED_DIRECTION_LABELS 对齐;feed 已带 direction_label,这里只是兜底
_DIRECTION_LABELS = {
    'buy': '滞涨买点',
    'sell': '抗跌卖点',
    'preopen_buy': '盘前偏多',
    'preopen_sell': '盘前偏空',
}


def load_config():
    default = {
        'enabled': True,
        # 生产:Flask 容器经 stock-network 直连 quant 容器;本地开发可改成 http://127.0.0.1:8000
        'base_url': 'http://quant:8000',
        'poll_interval_seconds': 60,
    }
    try:
        if os.path.exists(TRENDZEN_ARB_CONFIG_FILE):
            with open(TRENDZEN_ARB_CONFIG_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                default.update({k: raw[k] for k in default if k in raw})
    except Exception as e:
        error_logger.error(f'读取 TrendZen 套利配置失败: {e}')
    return default


# --------------------------------------------------------------------------
# 本地告警库(与 stock_price_alerts.json 同构:cap 500,按时间倒序读)
# --------------------------------------------------------------------------
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
    """供 flow_routes 合并进异动预警流(kind='arb')。"""
    alerts = _load_alerts()
    if date_str:
        alerts = [a for a in alerts if a.get('date') == date_str]
    return sorted(alerts, key=lambda a: a.get('timestamp', ''), reverse=True)[:limit]


# --------------------------------------------------------------------------
# 推送消息格式化(仿 anomaly_detector._format_message 的 markdown 引用体)
# --------------------------------------------------------------------------
def _fmt_pct(v):
    try:
        return f'{float(v):+.2f}%'
    except (TypeError, ValueError):
        return '--'


def _format_message(a):
    """生成微信/飞书 markdown 消息(入参=本地 record,字段与价格异动记录同构)。"""
    direction = str(a.get('direction') or '')
    label = a.get('label') or _DIRECTION_LABELS.get(direction, '套利背离')
    # 买点/偏多 = 看涨机会(红),卖点/偏空 = 绿,与价格异动的红涨绿跌一致
    icon = '🔴' if 'buy' in direction else '🟢'
    name = a.get('name') or ''
    code = a.get('code') or ''

    lines = []
    lines.append(f"> 时间：**{a.get('date', '')} {a.get('time', '')}**")
    lines.append(f"> 个股：**{name}({code})** 涨跌幅：**{_fmt_pct(a.get('stock_pct'))}**")
    lines.append(f"> 基准：**{a.get('bench_label', '')}** 涨跌幅：**{_fmt_pct(a.get('bench_pct'))}**")
    lines.append('')
    lines.append(f"**{label}**")
    if a.get('reason'):
        lines.append(f"> {a['reason']}")
    lines.append('')
    lines.append(f"⏰ {a.get('date', '')} {a.get('time', '')}")

    title = f"{icon} 套利背离 {name}{label}"
    return title, "\n".join(lines)


def _push_one(a):
    """推一条告警,返回 (pushed, title)。无启用通道时视为未推送(不回执,TrendZen 保持未读)。"""
    title, content = _format_message(a)
    try:
        from pushers.notification_pusher import send_news_message, is_push_enabled
        if not is_push_enabled():
            error_logger.warning('TrendZen套利推送跳过: 无已启用的推送通道(飞书/企业微信)')
            return False, title
        pushed = bool(send_news_message(title, content))
        if pushed:
            logger.info(f'TrendZen套利推送成功: {title}')
        else:
            error_logger.warning(f'TrendZen套利推送失败: {title} (推送通道返回False)')
        return pushed, title
    except Exception as e:
        error_logger.error(f'TrendZen套利推送失败: {e}')
        return False, title


def _ack(base_url, tz_ids):
    """回执:推送成功的告警在 TrendZen 侧标已读。失败只记日志,不影响本地已入库数据。"""
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/market/arb/feed/ack",
            params={'ids': ','.join(str(i) for i in tz_ids)},
            timeout=10,
        )
        ok = resp.status_code == 200 and resp.json().get('success')
        if not ok:
            error_logger.warning(f'TrendZen套利回执失败: HTTP {resp.status_code}')
        return bool(ok)
    except Exception as e:
        error_logger.error(f'TrendZen套利回执异常: {e}')
        return False


# --------------------------------------------------------------------------
# 一轮拉取:feed → 逐条(去重→推送→入库→WS)→ 批量回执
# --------------------------------------------------------------------------
def poll_once(cfg=None):
    """拉一轮 feed 并完成推送/入库/回执。返回本轮新入库条数(测试/手动触发用)。"""
    cfg = cfg or load_config()
    base_url = str(cfg.get('base_url') or '').rstrip('/')
    if not base_url:
        return 0
    try:
        resp = requests.get(f'{base_url}/api/market/arb/feed', params={'limit': 50}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        error_logger.error(f'TrendZen套利feed拉取失败: {e}')
        return 0
    items = payload.get('data') or []
    if not items:
        return 0

    now = datetime.now()
    alerts = _load_alerts()
    seen_ids = {a.get('tz_id') for a in alerts}
    new_records = []
    ack_ids = []

    for item in items:
        try:
            tz_id = int(item.get('id'))
        except (TypeError, ValueError):
            continue
        if tz_id in seen_ids:
            # TrendZen delivered 标记理论上已防重;这里兜底本地去重(如人工重放数据)
            continue
        record = {
            'kind': 'arb',
            'tz_id': tz_id,                      # TrendZen 侧告警ID(回执/对账用)
            'pair_id': item.get('pair_id'),
            'code': item.get('stock_code', ''),
            'name': item.get('stock_name', ''),
            'bench_label': item.get('bench_label', ''),
            'direction': item.get('direction', ''),
            'label': item.get('direction_label') or _DIRECTION_LABELS.get(str(item.get('direction')), '套利背离'),
            'time': item.get('signal_time', ''),
            'date': item.get('trade_date', ''),
            'stock_pct': item.get('stock_pct'),
            'bench_pct': item.get('bench_pct'),
            'reason': item.get('reason', ''),
            'pushed': False,
            'acked': False,                      # 回执成功后置 True
            'timestamp': now.isoformat(),
        }
        pushed, _title = _push_one(record)
        record['pushed'] = pushed
        alerts.append(record)
        new_records.append(record)
        seen_ids.add(tz_id)
        if pushed:
            ack_ids.append(tz_id)

    if not new_records:
        return 0

    # 推送成功的批量回执 → TrendZen 侧变已读;成功后本地记录补 acked 标记
    if ack_ids and _ack(base_url, ack_ids):
        acked_set = set(ack_ids)
        for r in alerts:
            if r.get('tz_id') in acked_set:
                r['acked'] = True

    _save_alerts(alerts)
    logger.info(f'TrendZen套利告警入库 {len(new_records)} 条(回执 {len(ack_ids)} 条)')
    # WebSocket 实时推送(前端桌面通知)
    try:
        from ws import push_event
        for record in new_records:
            push_event('arb_alert', record)
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


def trendzen_arb_loop():
    register_thread('trendzen_arb_monitor')
    logger.info('TrendZen套利背离接入线程启动')
    _log_skip_count = 0  # 抑制重复日志
    while True:
        interval = 60
        try:
            heartbeat('trendzen_arb_monitor')
            cfg = load_config()
            interval = int(cfg.get('poll_interval_seconds', 60) or 60)
            if not cfg.get('enabled'):
                _log_skip_count += 1
                if _log_skip_count <= 3 or _log_skip_count % 120 == 0:
                    logger.info(f'TrendZen套利接入: 开关未启用，等待中({_log_skip_count})')
                time.sleep(interval)
                continue
            if not _in_poll_window(datetime.now()):
                # 窗口外不请求 TrendZen(告警只会在交易时段产生)
                time.sleep(_SLEEP_OFF_WINDOW)
                continue
            _log_skip_count = 0
            poll_once(cfg)
        except Exception as e:
            error_logger.error(f'TrendZen套利接入循环异常: {e}')
        time.sleep(interval)
