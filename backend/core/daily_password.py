"""动态每日密码：vk666 + 北京时间当天月日(MMDD)。

基准时间通过远程获取北京时间（多源容错），进程内缓存到下一个北京时间自然日零点之后，
约每天刷新一次（跨日凌晨自动失效重取）。所有远程源都失败时，退化为「本地UTC时间+8」
的估算，保证登录仍可用。网络请求仅在缓存失效时发起（单进程每天约一次）。
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8))
PASSWORD_PREFIX = "vk666"
_REQUEST_TIMEOUT = 3.0
# 远程北京时间数据源（按优先级）。每个都解析为 Unix 秒后转北京时间。
_REMOTE_SOURCES = (
    "http://api.m.taobao.com/rest/api3.do?api=mtop.common.getTimestamp",
    "https://worldtimeapi.org/api/timezone/Asia/Shanghai",
    "https://timeapi.io/api/Time/current/zone?timeZone=Asia/Shanghai",
)

_lock = threading.Lock()
_cached_suffix = None     # 形如 "0710"
_cached_expire = 0.0      # epoch 秒，缓存到期时间


def _parse_unix_seconds(raw: str):
    """从各数据源的响应里解析出 Unix 秒；失败返回 None。"""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    # Taobao: {"data": {"t": "1720000000000"}}  (毫秒)
    inner = data.get("data")
    if isinstance(inner, dict) and inner.get("t"):
        try:
            return float(inner["t"]) / 1000.0
        except (ValueError, TypeError):
            pass
    # worldtimeapi: {"unixtime": 1720000000}  (秒)
    if data.get("unixtime") is not None:
        try:
            return float(data["unixtime"])
        except (ValueError, TypeError):
            pass
    # timeapi.io: {"year":..,"month":..,"day":..,"hour":..,"minutes":..,"seconds":..}
    if {"year", "month", "day"} <= set(data.keys()):
        try:
            dt = datetime(
                int(data["year"]), int(data["month"]), int(data["day"]),
                int(data.get("hour", 0)), int(data.get("minutes", 0)),
                int(data.get("seconds", 0)), tzinfo=BEIJING_TZ,
            )
            return dt.timestamp()
        except (ValueError, TypeError):
            pass
    return None


def _fetch_beijing_datetime():
    """逐个尝试远程源，返回北京时间的 aware datetime；全部失败返回 None。"""
    for url in _REMOTE_SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "daily-password/1.0"})
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            ts = _parse_unix_seconds(raw)
            if ts:
                return datetime.fromtimestamp(ts, tz=BEIJING_TZ)
        except Exception:
            continue
    return None


def get_password_suffix() -> str:
    """返回今日北京时间 MMDD（远程获取并缓存到次日凌晨）。"""
    global _cached_suffix, _cached_expire
    now = time.time()
    with _lock:
        if _cached_suffix and now < _cached_expire:
            return _cached_suffix

    bj = _fetch_beijing_datetime()
    if bj is None:
        # 远程不可用：退化为本地 UTC+8，1 小时后重试远程
        bj = datetime.now(BEIJING_TZ)
        ttl = 3600.0
    else:
        # 缓存到下一个北京时间零点之后 60 秒，确保跨日后自动刷新（约每天取一次）
        next_midnight = datetime(bj.year, bj.month, bj.day, tzinfo=BEIJING_TZ) + timedelta(days=1)
        ttl = max(60.0, (next_midnight - bj).total_seconds() + 60.0)

    suffix = bj.strftime("%m%d")
    with _lock:
        _cached_suffix = suffix
        _cached_expire = now + ttl
    return suffix


def get_daily_password() -> str:
    """返回今日动态密码，例如北京时间 07-10 → 'vk6660710'。"""
    return PASSWORD_PREFIX + get_password_suffix()


def verify_password(password) -> bool:
    """校验输入是否等于今日动态密码（None/空串安全）。"""
    if not password:
        return False
    import hmac
    return hmac.compare_digest(str(password), get_daily_password())
