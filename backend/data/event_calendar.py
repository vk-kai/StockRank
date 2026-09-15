# -*- coding: utf-8 -*-
"""重大事件日历(加息决议/CPI/非农/PMI 等宏观数据发布)。

归属: 首页 Flask 后端(宏观层面信息,与量化交易项目无关)。

数据源(2026-09-15 调研结论,均实测可用):
- 主源: 百度股市通经济日历(经 akshare.news_economic_baidu),国内直连稳定,
  中文事件名、重要性 1~3、预期/前值/公布齐全;缺点是单日接口、有 403 风控
  (连发多请求会被拒),须逐日取 + 退避重试。
- 备源: ForexFactory 官方周历 JSON(nfs.faireconomy.media),thisweek+nextweek
  一次各一发,impact High/Medium/Low;时间是美东带偏移 ISO,需转北京时间。
  境外 CDN,可能慢或不稳,失败静默降级。

对外只暴露 get_event_calendar(days) → 合并去重、按北京时间升序的事件列表,
进程内 TTL 缓存(半小时);event_calendar_loop 供 app.py 起后台线程,
容器启动即预热,之后每 30 分钟刷新,用户请求永远打到热缓存。
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import requests

from core.logger import get_logger

system_logger = get_logger('system')
error_logger = get_logger('error')

_BEIJING_TZ = timezone(timedelta(hours=8))

# 日历缓存秒(30分钟)/默认取未来几天;可用环境变量覆盖
EVENT_CALENDAR_TTL_SECONDS = int(os.environ.get('EVENT_CALENDAR_TTL_SECONDS', '1800'))
EVENT_CALENDAR_DAYS = int(os.environ.get('EVENT_CALENDAR_DAYS', '7'))
_PREWARM_INTERVAL_SECONDS = 1800

_FF_IMPACT_MAP = {"high": 3, "medium": 2, "low": 1}
_FF_REGION_MAP = {
    "USD": "美国", "EUR": "欧元区", "CNY": "中国", "GBP": "英国", "JPY": "日本",
    "AUD": "澳大利亚", "CAD": "加拿大", "CHF": "瑞士", "NZD": "新西兰", "All": "国际",
}
_FF_URLS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
)
_FF_HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

_cache_lock = threading.Lock()
_cache: dict = {}  # key=(today_str, days) -> (monotonic_ts, items, ttl_seconds)


def _beijing_now() -> datetime:
    return datetime.now(_BEIJING_TZ)


def _clean_val(v) -> Optional[str]:
    """NaN/None → None;其余转字符串(保留 '-14.00' 这类展示口径)。"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s or None


def _fetch_baidu_day(date_yyyymmdd: str) -> list[dict]:
    """百度股市通单日经济事件;403 风控退避重试,失败抛异常由上层跳过该日。"""
    import akshare as ak

    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            df = ak.news_economic_baidu(date=date_yyyymmdd)
            break
        except Exception as exc:
            last_exc = exc
            # 403/限流: 递增退避后再试
            time.sleep(1.5 * (attempt + 1))
    else:
        raise last_exc if last_exc else RuntimeError("baidu calendar fetch failed")

    items: list[dict] = []
    if df is None or df.empty:
        return items
    for row in df.to_dict("records"):
        try:
            imp = int(float(row.get("重要性") or 1))
        except (TypeError, ValueError):
            imp = 1
        items.append({
            "time": f"{row.get('日期')} {row.get('时间')}",
            "region": str(row.get("地区") or "未知"),
            "event": str(row.get("事件") or "").strip(),
            "importance": max(1, min(3, imp)),
            "forecast": _clean_val(row.get("预期")),
            "previous": _clean_val(row.get("前值")),
            "actual": _clean_val(row.get("公布")),
            "source": "baidu",
        })
    return items


def _fetch_forex_factory() -> list[dict]:
    """ForexFactory 本周+下周日历;失败返回空列表(主源独立可用)。"""
    items: list[dict] = []
    for url in _FF_URLS:
        try:
            resp = requests.get(url, headers=_FF_HEADERS, timeout=6)
            if resp.status_code != 200:
                system_logger.debug("forexfactory %s http %s", url.rsplit("/", 1)[-1], resp.status_code)
                continue
            for it in resp.json():
                impact = str(it.get("impact") or "Low").lower()
                raw_date = str(it.get("date") or "")
                try:
                    dt = datetime.fromisoformat(raw_date).astimezone(_BEIJING_TZ)
                except ValueError:
                    continue
                items.append({
                    "time": dt.strftime("%Y-%m-%d %H:%M"),
                    "region": _FF_REGION_MAP.get(str(it.get("country") or ""), str(it.get("country") or "国际")),
                    "event": str(it.get("title") or "").strip(),
                    "importance": _FF_IMPACT_MAP.get(impact, 1),
                    "forecast": _clean_val(it.get("forecast")),
                    "previous": _clean_val(it.get("previous")),
                    "actual": _clean_val(it.get("actual")),
                    "source": "ff",
                })
        except Exception as exc:
            system_logger.debug("forexfactory 拉取失败: %s", exc)
    return items


def _dedup(items: list[dict]) -> list[dict]:
    """同 日期+时刻+地区+重要度 视为同一事件(百度中文名优先,信息更全)。"""
    seen: dict[tuple, dict] = {}
    for it in items:
        key = (it["time"], it["region"], it["importance"])
        cur = seen.get(key)
        if cur is None or (cur["source"] != "baidu" and it["source"] == "baidu"):
            seen[key] = it
    return sorted(seen.values(), key=lambda x: x["time"])


def _build_calendar(days: int) -> list[dict]:
    now = _beijing_now()
    dates = [(now + timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]
    today_str = now.strftime("%Y-%m-%d")

    merged: list[dict] = []
    ok_days = 0
    for ds in dates:
        try:
            day_items = _fetch_baidu_day(ds)
            merged.extend(day_items)
            if day_items:
                ok_days += 1
        except Exception as exc:
            system_logger.debug("百度日历 %s 拉取失败: %s", ds, exc)
        time.sleep(0.4)  # 风控节流: 逐日请求间留间隔

    if ok_days == 0:
        # 主源全挂: 至少把备源顶上,保证面板不空
        system_logger.info("百度经济日历全部日期失败,降级 ForexFactory")
    else:
        system_logger.info("事件日历: 百度源命中 %d/%d 天", ok_days, days)

    merged.extend(_fetch_forex_factory())
    items = _dedup(merged)

    # 裁掉窗口外(FF nextweek 可能超出 days)与无事件名的脏行
    horizon = (now + timedelta(days=days)).strftime("%Y-%m-%d")
    items = [it for it in items if today_str <= it["time"][:10] <= horizon and it["event"]]
    return items


def get_event_calendar(days: Optional[int] = None) -> list[dict]:
    """未来 days 天的重大事件列表(TTL 缓存,北京时间升序)。"""
    days = max(1, min(int(days or EVENT_CALENDAR_DAYS), 30))
    today_str = _beijing_now().strftime("%Y-%m-%d")
    key = (today_str, days)
    now_s = time.monotonic()

    with _cache_lock:
        hit = _cache.get(key)
        if hit and now_s - hit[0] < hit[2]:
            return hit[1]
        items = _build_calendar(days)
        # 正常结果 30 分钟;全空(双源都挂/风控)只短缓存 60s,尽快重试别空一整天
        ttl = EVENT_CALENDAR_TTL_SECONDS if items else 60
        _cache[key] = (now_s, items, ttl)
        # 顺手清掉跨日的陈旧缓存
        for k in [k for k in _cache if k[0] != today_str]:
            _cache.pop(k, None)
        return items


def event_calendar_loop() -> None:
    """后台预热循环: 启动即拉一次,之后每 30 分钟刷新(配合 app.py 守护线程)。"""
    while True:
        try:
            get_event_calendar(EVENT_CALENDAR_DAYS)
        except Exception as exc:
            error_logger.error(f"事件日历预热失败: {exc}")
        time.sleep(_PREWARM_INTERVAL_SECONDS)
