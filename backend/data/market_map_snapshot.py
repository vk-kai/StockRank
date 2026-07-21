"""大盘云图复盘快照

交易日 9:30~15:00 每半小时整点抓取一次完整云图并落盘，供前端复盘 / 播放。
次日（写新一天首张快照时）自动覆盖旧文件，等价于"次日开盘前清空"。
独立 daemon 线程，与首页 30 秒实时轮询互不影响、互不落盘。

文件：data/market_map_snapshots/YYYYMMDD.json
结构：{"date": "2026-07-03", "snapshots": [{"time": "09:30", "data": {...同 market-map...}}, ...]}
"""
import os
import json
import time
import threading
from datetime import datetime

from core.config import DATA_DIR
from data.data_processor import get_market_map_tree, error_logger, system_logger
from data.data_collector import is_trading_day

# 10 个半小时整点（升序）
SNAPSHOT_TIMES = ['09:30', '10:00', '10:30', '11:00', '11:30',
                  '13:00', '13:30', '14:00', '14:30', '15:00']

SNAPSHOT_DIR = os.path.join(DATA_DIR, 'market_map_snapshots')
POLL_INTERVAL = 60          # 线程每 60 秒检查一次
TOLERANCE_SECONDS = 90      # 距整点 ±90 秒内视为命中（60 秒轮询必能覆盖，最大偏差 30 秒）

_write_lock = threading.Lock()


def _file_path(date_str):
    return os.path.join(SNAPSHOT_DIR, f'{date_str}.json')


def _today_str(now=None):
    return (now or datetime.now()).strftime('%Y%m%d')


def _empty_doc(date_str):
    return {'date': date_str, 'snapshots': []}


def load_doc(date_str):
    """读取某天快照文件；文件不存在或日期不符返回空 doc（跨天即清空昨天）。"""
    path = _file_path(date_str)
    if not os.path.exists(path):
        return _empty_doc(date_str)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            doc = json.load(f)
        if doc.get('date') != date_str:
            # 文件是前几天的：视作空，首次 save_snapshot 会整体覆盖
            return _empty_doc(date_str)
        if not isinstance(doc.get('snapshots'), list):
            doc['snapshots'] = []
        return doc
    except Exception as e:
        error_logger.error(f"[大盘云图快照] 读取失败 {path}: {e}")
        return _empty_doc(date_str)


def _write_doc(date_str, doc):
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    path = _file_path(date_str)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    os.replace(tmp, path)  # 原子替换，避免并发读到半截文件


def captured_times(date_str):
    """今天已抓取的时间点集合。"""
    doc = load_doc(date_str)
    return {s['time'] for s in doc['snapshots'] if isinstance(s, dict) and 'time' in s}


def save_snapshot(time_str, data, date_str=None):
    """追加一张快照；同一天同一时间点重复抓取则覆盖为最新；文件日期非当天则先清空。"""
    date_str = date_str or _today_str()
    with _write_lock:
        doc = load_doc(date_str)
        doc['snapshots'] = [s for s in doc['snapshots'] if s.get('time') != time_str]
        doc['snapshots'].append({'time': time_str, 'data': data})
        doc['snapshots'].sort(key=lambda s: s['time'])
        _write_doc(date_str, doc)


def get_points_status(date_str=None):
    """返回 (date_str, [{time, available}, ...])：全部 10 个点的今天抓取状态。"""
    date_str = date_str or _today_str()
    have = captured_times(date_str)
    return date_str, [{'time': t, 'available': t in have} for t in SNAPSHOT_TIMES]


def get_snapshot(time_str, date_str=None):
    """取今天某时间点的快照 data，不存在返回 None。"""
    date_str = date_str or _today_str()
    if time_str not in SNAPSHOT_TIMES:
        return None
    doc = load_doc(date_str)
    for s in doc['snapshots']:
        if s.get('time') == time_str:
            return s.get('data')
    return None


def _match_mark(now, captured):
    """若 now 落在某"未抓取整点"的 ±TOLERANCE 内，返回该时间点字符串，否则 None。"""
    now_secs = now.hour * 3600 + now.minute * 60 + now.second
    for t in SNAPSHOT_TIMES:
        h, m = t.split(':')
        mark_secs = (int(h) * 60 + int(m)) * 60
        if abs(now_secs - mark_secs) <= TOLERANCE_SECONDS and t not in captured:
            return t
    return None


def market_map_snapshot_thread():
    """每分钟检查：交易日 + 命中未抓取整点 → 抓取完整云图并存盘。"""
    system_logger.info("大盘云图快照线程已启动")
    while True:
        try:
            now = datetime.now()
            if is_trading_day(now):
                date_str = _today_str(now)
                target = _match_mark(now, captured_times(date_str))
                if target:
                    data = get_market_map_tree()
                    if data:
                        save_snapshot(target, data, date_str)
                        system_logger.info(f"[大盘云图快照] 已保存 {date_str} {target}")
                    else:
                        error_logger.warning(f"[大盘云图快照] {target} 取数据为空，跳过（下个轮询周期重试）")
        except Exception as e:
            error_logger.error(f"[大盘云图快照] 线程异常: {e}")
        time.sleep(POLL_INTERVAL)
