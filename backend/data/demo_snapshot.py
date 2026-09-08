# -*- coding: utf-8 -*-
"""演示模式快照:每个交易日收盘后把首页+大盘云图数据固化一份到 data/demo/。

给未登录访客演示用——/api/demo/* 免鉴权接口永远只读这份快照,不含任何实时数据。
- 快照只从本地数据文件读取(零上游请求),捕获失败不影响线上;
- 每个交易日 capture_time(默认 15:35)后重捕一次覆盖;进程启动时若无快照立即补
  (此时可能是半天的部分数据,当天收盘后仍会被覆盖成全天);
- 首页: 分钟级板块资金(折线图+top榜单) + 新闻 + 大盘摘要;
- 云图: market_map_snapshots 里最后一个整点快照(自带真实涨跌幅)。
"""
import os
import re
import json
import glob
import time
from datetime import datetime

from core.config import DATA_DIR, REALTIME_DIR, DEMO_CONFIG_FILE
from core.logger import get_logger

logger = get_logger('demo_snapshot')
error_logger = get_logger('error')

DEMO_DIR = os.path.join(DATA_DIR, 'demo')
SNAPSHOT_FILE = os.path.join(DEMO_DIR, 'demo_snapshot.json')
MARKET_MAP_SNAPSHOT_DIR = os.path.join(DATA_DIR, 'market_map_snapshots')

_REALTIME_FILE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})\.json$')
_MAP_SNAPSHOT_FILE_RE = re.compile(r'^(\d{8})\.json$')


def load_config():
    default = {'enabled': True, 'capture_time': '15:35'}
    try:
        if os.path.exists(DEMO_CONFIG_FILE):
            with open(DEMO_CONFIG_FILE, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                default.update({k: raw[k] for k in default if k in raw})
    except Exception as e:
        error_logger.error(f'读取演示模式配置失败: {e}')
    return default


def _read_json(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _latest_realtime_file():
    """最新的分钟级资金文件 data/realtime/YYYY-MM-DD.json(=最近一个有数据的交易日)。"""
    candidates = []
    for path in glob.glob(os.path.join(REALTIME_DIR, '*.json')):
        m = _REALTIME_FILE_RE.match(os.path.basename(path))
        if m:
            candidates.append((m.group(1), path))
    if not candidates:
        return None, None
    date, path = max(candidates)
    return date, path


def _latest_map_snapshot():
    """云图整点快照的最后一个时间点(通常是 15:00 收盘态,自带真实涨跌幅)。"""
    candidates = []
    for path in glob.glob(os.path.join(MARKET_MAP_SNAPSHOT_DIR, '*.json')):
        m = _MAP_SNAPSHOT_FILE_RE.match(os.path.basename(path))
        if m:
            candidates.append((m.group(1), path))
    if not candidates:
        return None
    data = _read_json(max(candidates)[1])
    if not data or not isinstance(data.get('snapshots'), list) or not data['snapshots']:
        return None
    snap = data['snapshots'][-1]
    return {
        'date': data.get('date', ''),
        'time': snap.get('time', ''),
        'data': snap.get('data') or {},
    }


def capture_demo_snapshot():
    """从本地文件固化一份演示快照,返回快照 dict(失败也返回 available=False 的骨架)。"""
    payload = {'available': False, 'captured_at': datetime.now().isoformat()}

    date, minute_path = _latest_realtime_file()
    if date and minute_path:
        minute = _read_json(minute_path)
        if isinstance(minute, dict) and minute:
            payload['date'] = date
            payload['minute'] = minute
            payload['available'] = True

    try:
        from data.news_processor import get_recent_news
        result = get_recent_news(1, 20)
        news = result.get('news') if isinstance(result, dict) else result
        payload['news'] = (news or [])[:20]
    except Exception as e:
        error_logger.error(f'演示快照抓取新闻失败: {e}')
        payload['news'] = []

    summary = _read_json(os.path.join(REALTIME_DIR, 'market_summary.json'))
    if isinstance(summary, dict):
        payload['market_summary'] = summary

    try:
        map_snap = _latest_map_snapshot()
        if map_snap:
            payload['market_map'] = map_snap
    except Exception as e:
        error_logger.error(f'演示快照抓取云图失败: {e}')

    try:
        os.makedirs(DEMO_DIR, exist_ok=True)
        tmp = SNAPSHOT_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, SNAPSHOT_FILE)
        logger.info(f"演示快照已更新 date={payload.get('date')} available={payload.get('available')}")
    except Exception as e:
        error_logger.error(f'演示快照落盘失败: {e}')
    return payload


def load_demo_snapshot():
    """读快照;文件缺失/损坏返回 {'available': False}。"""
    data = _read_json(SNAPSHOT_FILE)
    if isinstance(data, dict):
        return data
    return {'available': False}


def demo_snapshot_loop():
    from monitors.thread_monitor import register_thread, heartbeat
    register_thread('demo_snapshot')
    logger.info('演示快照线程启动')
    while True:
        try:
            heartbeat('demo_snapshot')
            cfg = load_config()
            if cfg.get('enabled'):
                now = datetime.now()
                today = now.strftime('%Y-%m-%d')
                snap = load_demo_snapshot()
                captured_today = str(snap.get('captured_at', ''))[:10] == today
                due = str(cfg.get('capture_time', '15:35')) <= now.strftime('%H:%M')
                # 重捕条件:过了 capture_time 且今天还没捕过(收盘后的全天数据),
                # 或进程刚启动还没有任何快照(宁可半天数据也不空白演示页)
                if (due and not captured_today) or not snap.get('available'):
                    capture_demo_snapshot()
        except Exception as e:
            error_logger.error(f'演示快照循环异常: {e}')
        time.sleep(60)
