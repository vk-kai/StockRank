from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

import pandas as pd

from backend.config import (
    AUTO_SCAN_PERIOD_RULES,
    AUTO_SCAN_TRADING_SESSIONS,
    DOWNLOADABLE_KLINE_PERIODS,
    LOCAL_KLINE_CACHE_RULES,
)


DEFAULT_SCAN_PERIOD = "30min"
SCAN_BASE_REQUIRED_PERIODS = ("daily",)
CHART_TO_LOCAL_PERIOD = {
    "1": "1min",
    "5": "5min",
    "15": "15min",
    "30": "30min",
    "60": "60min",
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
}
LOCAL_TO_CHART_PERIOD = {
    "1min": "1",
    "5min": "5",
    "15min": "15",
    "30min": "30",
    "60min": "60",
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
}
SCAN_PERIOD_LABELS = {
    "1min": "1分钟",
    "5min": "5分钟",
    "15min": "15分钟",
    "30min": "30分钟",
    "60min": "60分钟",
    "daily": "日线",
    "weekly": "周线",
    "monthly": "月线",
}

TRADING_SESSIONS = tuple(
    (
        time.fromisoformat(str(start_text)),
        time.fromisoformat(str(end_text)),
    )
    for start_text, end_text in AUTO_SCAN_TRADING_SESSIONS
)


def normalize_scan_period(period: object) -> str:
    value = str(period or DEFAULT_SCAN_PERIOD).strip()
    normalized = CHART_TO_LOCAL_PERIOD.get(value, value)
    if normalized not in DOWNLOADABLE_KLINE_PERIODS:
        return DEFAULT_SCAN_PERIOD
    return normalized


def scan_period_to_chart_period(period: object) -> str:
    return LOCAL_TO_CHART_PERIOD.get(normalize_scan_period(period), "30")


def get_scan_period_label(period: object) -> str:
    return SCAN_PERIOD_LABELS.get(normalize_scan_period(period), str(period or DEFAULT_SCAN_PERIOD))


def get_required_periods(scan_period: str) -> tuple[str, ...]:
    normalized = normalize_scan_period(scan_period)
    return tuple(dict.fromkeys([*SCAN_BASE_REQUIRED_PERIODS, normalized]))


def get_min_scan_bars(scan_period: str) -> int:
    normalized = normalize_scan_period(scan_period)
    rule_min = int(LOCAL_KLINE_CACHE_RULES.get(normalized, {}).get("min_bars", 180))
    return max(rule_min, 180)


def get_time_col_for_period(scan_period: str) -> str:
    return "date" if normalize_scan_period(scan_period) == "daily" else "datetime"


def get_signal_time_format(scan_period: str) -> str:
    return "%Y-%m-%d" if normalize_scan_period(scan_period) in ("daily", "weekly", "monthly") else "%Y-%m-%d %H:%M"


def is_market_session_time(now: datetime) -> bool:
    current = now.time()
    return any(start <= current <= end for start, end in TRADING_SESSIONS)


def _build_scan_slots(scan_period: str) -> list[time]:
    normalized = normalize_scan_period(scan_period)
    rule = AUTO_SCAN_PERIOD_RULES.get(normalized) or AUTO_SCAN_PERIOD_RULES[DEFAULT_SCAN_PERIOD]
    rule_type = str(rule.get("type") or "intraday_minutes")
    if rule_type == "session_close":
        return [time.fromisoformat(str(slot_text)) for slot_text in rule.get("slots", ("15:00",))]

    step_minutes = max(1, int(rule.get("step_minutes") or 30))
    slots: list[time] = []
    anchor_day = datetime(2000, 1, 1)
    for start, end in TRADING_SESSIONS:
        current_dt = datetime.combine(anchor_day.date(), start) + timedelta(minutes=step_minutes)
        end_dt = datetime.combine(anchor_day.date(), end)
        while current_dt <= end_dt:
            slots.append(current_dt.time())
            current_dt += timedelta(minutes=step_minutes)
    return slots


def resolve_run_slot(now: datetime, scan_period: str, *, is_trading_date: bool) -> Optional[str]:
    if not is_trading_date:
        return None

    rule = AUTO_SCAN_PERIOD_RULES.get(normalize_scan_period(scan_period)) or AUTO_SCAN_PERIOD_RULES[DEFAULT_SCAN_PERIOD]
    if str(rule.get("type") or "intraday_minutes") == "session_close":
        # 日/周/月线：收盘 slot。15:00 收盘后自动下载会占用一段时间，期间 readiness
        # 会挡住扫描且不消耗 slot（20 秒轮询持续重试），所以给收盘后一段缓冲窗口，
        # 等下载完成后扫描仍能触发。注意不能用 is_market_session_time 判断——场次
        # 上界 15:00:00 精确到微秒，一旦过了 15:00 整就永远出不了 slot。
        buffer_minutes = max(1, int(rule.get("after_close_buffer_minutes") or 90))
        current = now.time()
        slot_key = None
        for slot in _build_scan_slots(scan_period):
            slot_end = (datetime.combine(now.date(), slot) + timedelta(minutes=buffer_minutes)).time()
            if slot <= current <= slot_end:
                slot_key = f"{now.strftime('%Y%m%d')}-{slot.strftime('%H%M')}"
        return slot_key

    if not is_market_session_time(now):
        # 分钟级收盘后短缓冲：当日最后一根完整K线（如 30min 的 15:00 bar）只有过了
        # 收盘时刻才真正完成，而场次上界精确到 15:00:00，稍过即出不了 slot。给一段
        # 短缓冲让收盘 bar 也能被扫到（午间 11:30 同理，覆盖 11:30-11:35）。
        buffer_minutes = max(1, int(rule.get("after_close_buffer_minutes") or 5))
        current = now.time()
        for start, end in TRADING_SESSIONS:
            end_with_buffer = (datetime.combine(now.date(), end) + timedelta(minutes=buffer_minutes)).time()
            if not (end <= current <= end_with_buffer):
                continue
            session_slots = [slot for slot in _build_scan_slots(scan_period) if start < slot <= end]
            if session_slots:
                last_slot = session_slots[-1]
                return f"{now.strftime('%Y%m%d')}-{last_slot.strftime('%H%M')}"
        return None

    slot_key = None
    for slot in _build_scan_slots(scan_period):
        if now.time() >= slot:
            slot_key = f"{now.strftime('%Y%m%d')}-{slot.strftime('%H%M')}"
    return slot_key


def resolve_next_run_slot(now: datetime, scan_period: str, *, is_trading_date: bool) -> Optional[datetime]:
    """下一次自动扫描的预计触发时刻(当日)。

    非交易日、或当日全部槽位已过(收盘后) → None，前端显示"待下一交易日"。
    分钟级槽位由 _build_scan_slots 按交易场次生成；日/周/月线为收盘 15:00 单槽位。
    """
    if not is_trading_date:
        return None
    for slot in _build_scan_slots(scan_period):
        # 带上 now 的 tzinfo(调用方传 now_beijing() 是 aware 的)，避免 naive/aware 比较抛 TypeError
        slot_dt = datetime.combine(now.date(), slot, tzinfo=getattr(now, "tzinfo", None))
        if slot_dt > now:
            return slot_dt
    return None


def resolve_latest_completed_slot(now: datetime, scan_period: str, *, is_trading_date: bool) -> Optional[pd.Timestamp]:
    slot_key = resolve_run_slot(now, scan_period, is_trading_date=is_trading_date)
    if not slot_key:
        return None
    _, slot_text = slot_key.split("-", 1)
    return pd.Timestamp(f"{now.strftime('%Y-%m-%d')} {slot_text[:2]}:{slot_text[2:]}", tz="UTC")


def is_completed_scan_bar(bar_time: pd.Timestamp, now: datetime, scan_period: str, *, is_trading_date: bool) -> bool:
    """判断 bar 数据是否已跟上最新完成槽位（覆盖性判断，>=）。

    pytdx 分钟尾巴里带未完成 forming bar（以周期结束时间戳标记），用
    "最后一根 == 期望槽位" 做等值判断在盘中恒为 False。这里改为
    candidate >= expected_slot：数据只要覆盖到期望槽位即可，forming bar
    由调用方（executor）在跑策略前剔除。
    """
    expected_slot = resolve_latest_completed_slot(now, scan_period, is_trading_date=is_trading_date)
    if expected_slot is None:
        return False
    candidate = pd.Timestamp(bar_time)
    if candidate.tzinfo is None:
        candidate = candidate.tz_localize("UTC")
    else:
        candidate = candidate.tz_convert("UTC")
    return candidate >= expected_slot
