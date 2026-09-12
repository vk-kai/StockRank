from __future__ import annotations

import calendar
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd


BEIJING_TZ = ZoneInfo("Asia/Shanghai")
UTC_TZ = ZoneInfo("UTC")


def now_beijing() -> datetime:
    return datetime.now(BEIJING_TZ)


def _to_timestamp(value) -> Optional[pd.Timestamp]:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return ts


def to_beijing_timestamp(value) -> Optional[pd.Timestamp]:
    ts = _to_timestamp(value)
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.tz_localize(BEIJING_TZ)
    return ts.tz_convert(BEIJING_TZ)


def to_utc_timestamp(value) -> Optional[pd.Timestamp]:
    ts = _to_timestamp(value)
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.tz_localize(BEIJING_TZ).tz_convert(UTC_TZ)
    return ts.tz_convert(UTC_TZ)


def format_beijing_time(value, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    ts = to_beijing_timestamp(value)
    if ts is None:
        return ""
    return ts.strftime(fmt)


def format_beijing_date(value) -> str:
    ts = to_beijing_timestamp(value)
    if ts is None:
        return ""
    return ts.strftime("%Y-%m-%d")


def to_epoch_seconds(value) -> Optional[int]:
    ts = to_utc_timestamp(value)
    if ts is None:
        return None
    return int(ts.timestamp())


def to_chart_seconds(value, *, date_only: bool = False) -> Optional[int]:
    ts = to_beijing_timestamp(value)
    if ts is None:
        return None
    if date_only:
        return calendar.timegm(datetime.strptime(ts.strftime("%Y-%m-%d"), "%Y-%m-%d").timetuple())
    naive_bj = ts.replace(tzinfo=None)
    return calendar.timegm(naive_bj.timetuple())


def chart_seconds_to_beijing_timestamp(value: int) -> pd.Timestamp:
    # chart 秒是"北京墙钟当epoch"的约定:先按 UTC 还原出同一墙钟串,再标成北京时区
    naive_bj = datetime.fromtimestamp(int(value), tz=UTC_TZ).replace(tzinfo=None)
    return pd.Timestamp(naive_bj).tz_localize(BEIJING_TZ)


def chart_seconds_to_utc_timestamp(value: int) -> pd.Timestamp:
    return chart_seconds_to_beijing_timestamp(int(value)).tz_convert(UTC_TZ)


def format_chart_time(value: int, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return chart_seconds_to_beijing_timestamp(int(value)).strftime(fmt)
