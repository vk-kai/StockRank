from __future__ import annotations

from typing import Optional

import pandas as pd

from backend.backtest.runtime import filter_dataframe_by_time_range, load_backtest_dataframe
from backend.backtest.strategies import get_backtest_strategy
from backend.kline_parquet import get_kline_parquet
from backend.live_scan.data_loader import merge_scan_realtime_tail
from backend.live_scan.periods import get_min_scan_bars, normalize_scan_period
from backend.live_scan.strategies import get_strategy as get_scan_strategy
from backend.market import akshare_data
from backend.strategy_diagnosis import diagnose_strategy_bar, build_out_of_range_evaluations
from backend.time_utils import (
    chart_seconds_to_utc_timestamp,
    format_chart_time,
    format_beijing_date,
    to_chart_seconds,
    to_epoch_seconds,
)

SCAN_DIAGNOSIS_LIMIT = 1200
DATE_BASED_PERIODS = {"daily", "weekly", "monthly", "quarter", "year"}


def _to_timestamp(value) -> Optional[int]:
    return to_epoch_seconds(value)


def _to_chart_timestamp(value, *, date_only: bool = False) -> Optional[int]:
    return to_chart_seconds(value, date_only=date_only)


def _timestamp_to_label(timestamp: int, period: str) -> str:
    if period in DATE_BASED_PERIODS:
        return format_chart_time(timestamp, "%Y-%m-%d")
    return format_chart_time(timestamp, "%Y-%m-%d %H:%M")


def _find_bar_timestamp(df: pd.DataFrame, period: str, target_timestamp: int) -> Optional[int]:
    if df is None or df.empty:
        return None
    time_col = "date" if period in DATE_BASED_PERIODS else "datetime"
    if time_col not in df.columns:
        return None

    date_only = period in DATE_BASED_PERIODS
    for value in df[time_col].tolist():
        chart_ts = _to_chart_timestamp(value, date_only=date_only)
        actual_ts = _to_timestamp(value)
        if chart_ts == int(target_timestamp):
            return chart_ts
        if actual_ts == int(target_timestamp):
            return chart_ts if chart_ts is not None else actual_ts
    return None


def _build_out_of_range_reason(range_start: str, range_end: str) -> str:
    return f"当前K线超出本次回测时间范围，回测只覆盖 {range_start} 至 {range_end}。"


def _load_scan_history_until_target(code: str, period: str, target_timestamp: int) -> pd.DataFrame:
    normalized_period = normalize_scan_period(period)
    limit = max(get_min_scan_bars(normalized_period), SCAN_DIAGNOSIS_LIMIT)
    target_utc = chart_seconds_to_utc_timestamp(target_timestamp)
    before_ts = target_utc + pd.Timedelta(seconds=1)
    df = get_kline_parquet(code, normalized_period, limit=limit, before_ts=before_ts.isoformat())
    if df is None or df.empty:
        return pd.DataFrame()

    if normalized_period in DATE_BASED_PERIODS:
        time_col = "date"
    else:
        time_col = "datetime"
    if time_col not in df.columns:
        return pd.DataFrame()

    if normalized_period not in DATE_BASED_PERIODS and akshare_data.is_trading_date():
        merged_df = merge_scan_realtime_tail(df, code, normalized_period, limit)
        if merged_df is not None and not merged_df.empty:
            df = merged_df

    cutoff = target_utc
    df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
    df = df.dropna(subset=[time_col])
    df = df[df[time_col] <= cutoff].reset_index(drop=True)
    return df


def diagnose_signal_bar(
    *,
    source: str,
    code: str,
    name: str,
    period: str,
    strategy_name: str,
    target_timestamp: int,
    range_start: Optional[str] = None,
    range_end: Optional[str] = None,
) -> dict:
    target_timestamp = int(target_timestamp)
    normalized_source = str(source or "").strip().lower()

    if normalized_source == "backtest":
        if not strategy_name:
            raise ValueError("回测诊断缺少策略名称")
        if not range_start or not range_end:
            raise ValueError("回测诊断缺少回测时间范围")

        date_only = period in DATE_BASED_PERIODS
        range_start_ts = to_chart_seconds(range_start, date_only=date_only)
        range_end_ts = to_chart_seconds(range_end, date_only=date_only)
        if range_start_ts is None or range_end_ts is None:
            raise ValueError("回测时间范围格式无效")

        if target_timestamp < range_start_ts or target_timestamp > range_end_ts:
            return {
                "bar_time": _timestamp_to_label(target_timestamp, period),
                "strategy_name": strategy_name,
                "source": normalized_source,
                "evaluations": build_out_of_range_evaluations(
                    strategy_name,
                    _build_out_of_range_reason(range_start, range_end),
                ),
            }

        start_date = format_beijing_date(range_start).replace("-", "")
        end_date = format_beijing_date(range_end).replace("-", "")
        raw_df = load_backtest_dataframe(code, name, period, start_date, end_date)
        raw_df = filter_dataframe_by_time_range(raw_df, range_start, range_end)
        if raw_df.empty:
            raise ValueError("回测诊断未获取到有效K线数据")

        target_bar_ts = _find_bar_timestamp(raw_df, period, target_timestamp) or target_timestamp
        evaluations = diagnose_strategy_bar(strategy_name, raw_df.copy(), target_bar_ts, code=code, name=name)
        return {
            "bar_time": _timestamp_to_label(target_bar_ts, period),
            "strategy_name": strategy_name,
            "source": normalized_source,
            "evaluations": evaluations,
        }

    if normalized_source == "scan":
        if not strategy_name:
            raise ValueError("扫描诊断缺少策略名称")

        scan_period = normalize_scan_period(period)
        raw_df = _load_scan_history_until_target(code, scan_period, target_timestamp)
        if raw_df.empty:
            raise ValueError("扫描诊断未获取到有效K线数据")

        target_bar_ts = _find_bar_timestamp(raw_df, scan_period, target_timestamp) or target_timestamp
        evaluations = diagnose_strategy_bar(strategy_name, raw_df.copy(), target_bar_ts, code=code, name=name)
        return {
            "bar_time": _timestamp_to_label(target_bar_ts, period),
            "strategy_name": strategy_name,
            "source": normalized_source,
            "evaluations": evaluations,
        }

    raise ValueError(f"不支持的诊断场景: {source}")
