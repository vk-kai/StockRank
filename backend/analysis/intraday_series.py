# -*- coding: utf-8 -*-
"""大盘云图悬浮卡迷你分时:当日分钟级价格序列。

数据链沿用两个项目的线上经验(2026-09-08 实测定稿):
  主源  东财 trends2   —— TrendZen 套利分时的主源,返回当日分钟价+昨收;
  兜底  腾讯 minute    —— StockRank 异动修复已在用的腾讯源,同样带昨收。
pytdx(通达信)的 get_minute_time_data 实测默认主机全挂(TrendZen 正是因此
自维护服务器池),不值得为悬浮小图引入 pytdx 依赖。

永不抛异常:任何失败返回 {'success': False, 'error': ...},前端静默不画分时。
"""
from __future__ import annotations

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

_EM_TRENDS_URL = "https://push2his.eastmoney.com/api/qt/stock/trends2/get"
_TX_MINUTE_URL = "https://web.ifzq.gtimg.cn/appstock/app/minute/query"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_TIMEOUT = (3, 6)

# 盘中悬浮高频触发,短缓存防抖;源全挂时允许回吐 5 分钟内的陈旧副本
_CACHE_TTL = 20.0
_STALE_TTL = 300.0
_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


def _market_prefixes(code: str) -> tuple[str, str]:
    """股票代码 → (东财 secid 市场, 腾讯符号前缀)。6 沪 / 4·8 北交 / 其余深。"""
    c = (code or "").strip()
    if c.startswith("6"):
        return "1", "sh"
    if c[:1] in ("4", "8"):
        return "0", "bj"
    return "0", "sz"


def _fetch_eastmoney(code: str) -> tuple[list[dict], float | None]:
    resp = requests.get(
        _EM_TRENDS_URL,
        params={
            "secid": f"{_market_prefixes(code)[0]}.{code}",
            "fields1": "f1,f2,f3,f7,f8",
            "fields2": "f51,f53",
            "iscr": "0",
            "ndays": "1",
        },
        headers=_HEADERS,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or {}
    pre_close = data.get("preClose") or data.get("pre_close")
    points = []
    for line in data.get("trends") or []:
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            price = float(parts[1])
        except (TypeError, ValueError):
            continue
        points.append({"time": parts[0], "price": price})
    if not points:
        raise ValueError("东财 trends2 返回空分时")
    return points, pre_close


def _fetch_tencent(code: str) -> tuple[list[dict], float | None]:
    symbol = f"{_market_prefixes(code)[1]}{code}"
    resp = requests.get(_TX_MINUTE_URL, params={"code": symbol}, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    stock = (resp.json().get("data") or {}).get(symbol) or {}
    qt = stock.get("qt", {}).get(symbol, [])
    pre_close = None
    if len(qt) > 4:
        try:
            pre_close = float(qt[4])
        except (TypeError, ValueError):
            pre_close = None
    points = []
    for line in ((stock.get("data") or {}).get("data")) or []:
        parts = str(line).split(" ")
        if len(parts) < 2:
            continue
        hhmm = parts[0]
        if len(hhmm) == 4:
            hhmm = f"{hhmm[:2]}:{hhmm[2:]}"
        try:
            price = float(parts[1])
        except (TypeError, ValueError):
            continue
        points.append({"time": hhmm, "price": price})
    if not points:
        raise ValueError("腾讯 minute 返回空分时")
    return points, pre_close


def get_stock_intraday_series(code: str) -> dict:
    """取个股当日分时序列:points=[{time,price,pct}],pct 相对昨收。

    主源东财、兜底腾讯;全挂且有未严重过期的缓存时回吐陈旧副本(stale=True)。
    """
    key = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not key:
        return {"success": False, "error": "缺少参数 code"}

    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit["t"] < _CACHE_TTL:
            return {"success": True, "data": hit["data"]}

    last_error = ""
    points = None
    pre_close = None
    source = ""
    for fetcher in (_fetch_eastmoney, _fetch_tencent):
        try:
            points, pre_close = fetcher(key)
            source = "eastmoney" if fetcher is _fetch_eastmoney else "tencent"
            break
        except Exception as e:
            last_error = f"{fetcher.__name__}: {e}"
            logger.debug("分时源失败 code=%s %s", key, last_error)

    if not points:
        with _cache_lock:
            if hit and now - hit["t"] < _STALE_TTL:
                stale = dict(hit["data"], stale=True)
                return {"success": True, "data": stale}
        return {"success": False, "error": f"分时数据不可用({last_error})"}

    for p in points:
        try:
            p["pct"] = round((p["price"] / float(pre_close) - 1) * 100, 3) if pre_close else None
        except (TypeError, ValueError, ZeroDivisionError):
            p["pct"] = None

    data = {
        "code": key,
        "pre_close": pre_close,
        "source": source,
        "last_time": points[-1]["time"],
        "last_price": points[-1]["price"],
        "points": points,
    }
    with _cache_lock:
        if len(_cache) > 800:
            _cache.clear()
        _cache[key] = {"t": now, "data": data}
    return {"success": True, "data": data}
