"""data_processor 共享基础（从 data_processor._legacy 拆分）。

集中存放跨子模块复用的底层设施：logger、数值/JSON 解析工具、跨组 URL 常量、全球指数缓存路径。
本模块是最底层依赖：只引用 core.config / core.logger / 标准库，
绝不 import _legacy 或其它子模块（避免循环 import）。
"""
import os
import json

from core.logger import get_logger
from core.config import REALTIME_DIR


# ---- loggers（data_summary_logger 供 storage 日报组使用）----
error_logger = get_logger('error')
data_logger = get_logger('data')
system_logger = get_logger('system')
data_summary_logger = get_logger('data_summary')
# 原 cleanup_logger 为死代码（data_collector / news_collector 各自定义自己的同名 logger，
# 无人从本包 import 它），迁移时顺删。


# ---- 跨组 URL 常量（ai_chain 韩股 + market_index 大盘指数共用）----
MARKET_INDEX_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"


# ---- 数值 / JSON 解析工具（无状态，跨组复用）----
def _safe_float(value, default=0):
    try:
        if value is None or value == '-':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_ths_number(value, default=0):
    if isinstance(value, (int, float)):
        return value
    text = (value or '').strip().replace(',', '')
    if not text or text in ('--', '-'):
        return default
    try:
        return float(text)
    except Exception:
        return default


def _parse_ths_int(value, default=0):
    return int(_parse_ths_number(value, default))


def _last_list_value(value):
    if isinstance(value, list) and value:
        last = value[-1]
        if isinstance(last, list) and last:
            return last[-1]
        return last
    return value


def _last_dict_value(data, key):
    if isinstance(data, dict):
        if key in data:
            return data.get(key)
        last_data = data.get('last_zdt')
        if isinstance(last_data, dict) and key in last_data:
            return last_data.get(key)
    return None


def _pick_first_number(data, keys):
    if not isinstance(data, dict):
        return None
    for key in keys:
        value = data.get(key)
        number = _safe_float(value, None)
        if number is not None:
            return number
    for value in data.values():
        if isinstance(value, dict):
            number = _pick_first_number(value, keys)
            if number is not None:
                return number
    return None


def _parse_json_or_jsonp(text):
    if not text:
        return None
    content = text.strip()
    if content.startswith('{') or content.startswith('['):
        return json.loads(content)
    start = content.find('(')
    end = content.rfind(')')
    if start != -1 and end > start:
        return json.loads(content[start + 1:end])
    return None


# ---- 跨组缓存路径（ai_chain KOSPI 兜底读 + market_index 写）----
GLOBAL_INDICES_CACHE_FILE = os.path.join(REALTIME_DIR, 'global_indices_cache.json')
