# -*- coding: utf-8 -*-
"""自选股价格异动监控:轮询、当日采样存盘(懒替换)、10 类检测、去重冷却、推送。

数据保留:不按时间清零,新交易日第一笔数据到来时删旧文件、起新一份(懒替换)。
"""
import os
import json
import glob
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
