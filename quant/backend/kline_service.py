from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

from backend import db
from backend.config import (
    INTRADAY_KLINE_FRESH_WINDOW_SECONDS,
    KLINE_SOURCE_PRIORITY,
    LOCAL_KLINE_CACHE_RULES,
    REALTIME_SENSITIVE_KLINE_PERIODS,
)
from backend.kline_parquet import (
    get_kline_parquet,
    upsert_kline_parquet,
    get_kline_sync_state,
    update_kline_sync_state,
    delete_kline_parquet,
)
from backend.market import akshare_data, pytdx_data
from backend.time_utils import format_beijing_date, format_beijing_time, now_beijing


def normalize_period(period: str) -> str:
    return {
        "1": "1min",
        "5": "5min",
        "15": "15min",
        "30": "30min",
        "60": "60min",
        "120": "120min",
        "intraday": "1min",
        "quarter": "quarter",
        "year": "year",
    }.get(period, period)


def is_market_session_now(now: Optional[datetime] = None) -> bool:
    # A股时段判断必须锚定北京时间:服务器时区不一定是 Asia/Shanghai,
    # 用本地 datetime.now() 会在 UTC 等环境下把整个交易时段判到深夜,
    # 导致盘中实时逻辑(如日K补充)全天不触发
    current = (now or now_beijing()).time()
    in_morning = time(9, 30) <= current <= time(11, 30)
    in_afternoon = time(13, 0) <= current <= time(15, 0)
    return in_morning or in_afternoon


def is_realtime_sensitive_period(period: str) -> bool:
    return normalize_period(period) in REALTIME_SENSITIVE_KLINE_PERIODS


def get_kline_source_priority(period: str, security_kind: str = "security") -> tuple[str, ...]:
    normalized_period = normalize_period(period)
    source_map = KLINE_SOURCE_PRIORITY.get(security_kind, KLINE_SOURCE_PRIORITY["security"])
    return tuple(source_map.get(normalized_period, ("local", "pytdx")))


def _filter_plausible_kline_times(df: pd.DataFrame, time_col: str, period: str) -> pd.DataFrame:
    if df.empty or time_col not in df.columns:
        return df
    min_time = pd.Timestamp("1990-01-01", tz="UTC")
    # 周/月/季/年线按周期末端(W-FRI/月末/季末/年末)打标，当前未完结周期的标签会
    # 落在未来(最多约1年)，这是 resample 的正常行为，不能当作脏数据丢弃，否则盘中
    # 补充的当天实时数据合成的当周/当月bar会被误删。其余周期保持 now+1天上限。
    if normalize_period(period) in ("weekly", "monthly", "quarter", "year"):
        max_time = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=400)
    else:
        max_time = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)
    mask = df[time_col].between(min_time, max_time)
    if bool(mask.all()):
        return df
    return df[mask].reset_index(drop=True)


def _normalize_remote_kline_df(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    normalized_period = normalize_period(period)
    work_df = df.copy()
    time_col = "datetime" if "datetime" in work_df.columns else "date" if "date" in work_df.columns else None
    if time_col is None:
        return pd.DataFrame()

    sample_val = work_df[time_col].iloc[0] if len(work_df) > 0 else None
    if isinstance(sample_val, str):
        work_df[time_col] = pd.to_datetime(work_df[time_col], format="mixed", errors="coerce")
    else:
        work_df[time_col] = pd.to_datetime(work_df[time_col], errors="coerce")

    if not _is_date_based_period(normalized_period):
        if not pd.api.types.is_datetime64tz_dtype(work_df[time_col]):
            try:
                work_df[time_col] = work_df[time_col].dt.tz_localize("Asia/Shanghai", ambiguous="infer", nonexistent="shift_forward").dt.tz_convert("UTC")
            except Exception:
                pass
        else:
            work_df[time_col] = work_df[time_col].dt.tz_convert("UTC")
    else:
        if not pd.api.types.is_datetime64tz_dtype(work_df[time_col]):
            work_df[time_col] = work_df[time_col].dt.tz_localize("UTC")
        else:
            work_df[time_col] = work_df[time_col].dt.tz_convert("UTC")

    work_df = work_df.dropna(subset=[time_col])
    work_df = _filter_plausible_kline_times(work_df, time_col, normalized_period)
    work_df = work_df.drop_duplicates(subset=[time_col], keep="last")
    work_df = work_df.sort_values(time_col).reset_index(drop=True)

    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in work_df.columns:
            work_df[col] = pd.to_numeric(work_df[col], errors="coerce")

    if _is_date_based_period(normalized_period) and "date" not in work_df.columns:
        work_df["date"] = work_df[time_col].dt.normalize()
    if not _is_date_based_period(normalized_period) and "datetime" not in work_df.columns:
        work_df["datetime"] = work_df[time_col]
    return work_df


def _kline_df_to_records(df: pd.DataFrame, period: str) -> list[dict]:
    normalized_period = normalize_period(period)
    normalized_df = _normalize_remote_kline_df(df, normalized_period)
    if normalized_df.empty:
        return []

    time_col = "date" if _is_date_based_period(normalized_period) else "datetime"
    records = []
    for _, row in normalized_df.iterrows():
        bar_time = row[time_col]
        if pd.isna(bar_time):
            continue
        ts = pd.Timestamp(bar_time)
        if _is_date_based_period(normalized_period):
            time_str = ts.strftime("%Y-%m-%d")
        elif ts.tzinfo is not None:
            time_str = ts.isoformat()
        else:
            time_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        records.append(
            {
                "bar_time": time_str,
                "open": row.get("open", 0),
                "high": row.get("high", 0),
                "low": row.get("low", 0),
                "close": row.get("close", 0),
                "volume": row.get("volume", 0),
                "amount": row.get("amount"),
            }
        )
    return records


def _is_date_based_period(period: str) -> bool:
    return normalize_period(period) in ("daily", "weekly", "monthly", "quarter", "year")


def _get_df_time_col(period: str) -> str:
    return "date" if _is_date_based_period(period) else "datetime"


def _format_sync_bar_time(value, period: str) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    if _is_date_based_period(period):
        return format_beijing_date(value)
    return format_beijing_time(value, "%Y-%m-%d %H:%M:%S")


def _slice_df_before(df: pd.DataFrame, period: str, before_ts: Optional[str | int | float]) -> pd.DataFrame:
    if df is None or df.empty or before_ts in (None, ""):
        return df if df is not None else pd.DataFrame()
    time_col = _get_df_time_col(period)
    if time_col not in df.columns:
        return df
    before_dt = pd.to_datetime(before_ts, errors="coerce", utc=True)
    if pd.isna(before_dt):
        return pd.DataFrame()
    return df[df[time_col] < before_dt].reset_index(drop=True)


def _read_local_kline_slice(code: str, period: str, count: int, before_ts: Optional[str | int | float] = None) -> pd.DataFrame:
    normalized_period = normalize_period(period)
    return get_kline_parquet(code, normalized_period, limit=count, before_ts=before_ts)


def _build_kline_page_result(df: pd.DataFrame, period: str, requested_count: int, source: str) -> dict:
    normalized_period = normalize_period(period)
    work_df = _normalize_remote_kline_df(df, normalized_period)
    data = work_df.tail(int(requested_count)).reset_index(drop=True) if not work_df.empty else pd.DataFrame()
    time_col = _get_df_time_col(normalized_period)
    next_before_ts = None
    if not data.empty and time_col in data.columns:
        next_before_ts = pd.Timestamp(data.iloc[0][time_col]).isoformat()
    has_more = len(work_df) > len(data)
    return {
        "data": data,
        "has_more": has_more,
        "next_before_ts": next_before_ts,
        "source": source,
    }


def _period_minutes(period: str) -> Optional[int]:
    normalized = normalize_period(period)
    if not normalized.endswith("min"):
        return None
    try:
        return int(normalized[:-3])
    except ValueError:
        return None


def _aggregate_consecutive_minute_bars(
    df: pd.DataFrame,
    source_period: str,
    target_period: str,
) -> pd.DataFrame:
    source_minutes = _period_minutes(source_period)
    target_minutes = _period_minutes(target_period)
    if not source_minutes or not target_minutes:
        return pd.DataFrame()
    if target_minutes <= source_minutes or target_minutes % source_minutes != 0:
        return pd.DataFrame()

    work_df = _normalize_remote_kline_df(df, source_period)
    if work_df.empty or "datetime" not in work_df.columns:
        return pd.DataFrame()

    group_size = max(target_minutes // source_minutes, 1)
    work_df = work_df.sort_values("datetime").reset_index(drop=True)
    work_df["_group"] = work_df.index // group_size

    agg_map = {
        "datetime": "last",
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    if "amount" in work_df.columns:
        agg_map["amount"] = "sum"

    result = work_df.groupby("_group", as_index=False).agg(agg_map)
    result = result.drop(columns=["_group"], errors="ignore")
    return _normalize_remote_kline_df(result, target_period)


def _aggregate_monthly_to_period(
    df: pd.DataFrame,
    target_period: str,
) -> pd.DataFrame:
    """从月线数据聚合为季线或年线"""
    normalized_target = normalize_period(target_period)
    if normalized_target not in ("quarter", "year"):
        return pd.DataFrame()

    work_df = _normalize_remote_kline_df(df, "monthly")
    if work_df.empty or "date" not in work_df.columns:
        return pd.DataFrame()

    work_df = work_df.sort_values("date").reset_index(drop=True)

    if normalized_target == "quarter":
        work_df["_group"] = work_df["date"].dt.year.astype(str) + "-Q" + ((work_df["date"].dt.month - 1) // 3 + 1).astype(str)
    else:  # year
        work_df["_group"] = work_df["date"].dt.year.astype(str)

    agg_map = {
        "date": "last",
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    if "amount" in work_df.columns:
        agg_map["amount"] = "sum"

    result = work_df.groupby("_group", as_index=False).agg(agg_map)
    result = result.drop(columns=["_group"], errors="ignore")
    return _normalize_remote_kline_df(result, normalized_target)


def _aggregate_daily_to_period(
    df: pd.DataFrame,
    target_period: str,
) -> pd.DataFrame:
    """从日线数据聚合为周/月/季/年线。

    与 akshare `_resample_hist_df` 一致采用 resample：周线锚周五(W-FRI)，
    月/季/年线锚自然月末。聚合结果含 `date` 列，可被 _build_kline_page_result、
    kline_to_chart_data、signal_diagnosis、backtest/runtime 等下游直接消费。
    """
    normalized_target = normalize_period(target_period)
    if normalized_target not in ("weekly", "monthly", "quarter", "year"):
        return pd.DataFrame()

    work_df = _normalize_remote_kline_df(df, "daily")
    if work_df.empty or "date" not in work_df.columns:
        return pd.DataFrame()

    work_df = work_df.sort_values("date").reset_index(drop=True)

    freq_map = {
        "weekly": "W-FRI",
        "monthly": "ME",
        "quarter": "QE",
        "year": "YE",
    }
    freq = freq_map[normalized_target]

    agg_map = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    if "amount" in work_df.columns:
        agg_map["amount"] = "sum"

    indexed = work_df.set_index("date")
    result = (
        indexed.resample(freq)
        .agg(agg_map)
        .dropna(subset=["open", "high", "low", "close"], how="any")
        .reset_index()
    )
    return _normalize_remote_kline_df(result, normalized_target)


def _fetch_remote_kline_for_cache(
    code: str,
    period: str,
    fetch_count: int,
    security_kind: str,
    before_ts: Optional[str | int | float] = None,
) -> pd.DataFrame:
    normalized_period = normalize_period(period)

    # 指数:pytdx(指数无需复权)
    if security_kind == "index":
        try:
            pytdx_df = _normalize_remote_kline_df(
                pytdx_data.get_index_kline(code, normalized_period, fetch_count, before_ts=before_ts),
                normalized_period,
            )
            if not pytdx_df.empty:
                return pytdx_df.tail(fetch_count).reset_index(drop=True)
        except Exception:
            pass
        return pd.DataFrame()

    # 日/周/月:优先 akshare 前复权(qfq,最新价==真实价),pytdx(不复权)仅作 fallback
    if normalized_period in ("daily", "weekly", "monthly"):
        try:
            hist_fetcher = akshare_data.get_etf_hist_daily if security_kind == "etf" else akshare_data.get_stock_hist_daily
            akshare_df = _normalize_remote_kline_df(hist_fetcher(code, period=normalized_period), normalized_period)
            sliced = _slice_df_before(akshare_df, normalized_period, before_ts)
            if sliced is not None and not sliced.empty:
                return sliced.tail(fetch_count).reset_index(drop=True)
        except Exception:
            pass
        try:
            pytdx_df = _normalize_remote_kline_df(
                pytdx_data.get_kline(code, normalized_period, fetch_count, before_ts=before_ts),
                normalized_period,
            )
            if not pytdx_df.empty:
                return pytdx_df.tail(fetch_count).reset_index(drop=True)
        except Exception:
            pass
        return pd.DataFrame()

    # 分钟:pytdx 优先 + akshare ETF 分钟(均不复权)
    try:
        pytdx_df = _normalize_remote_kline_df(
            pytdx_data.get_kline(code, normalized_period, fetch_count, before_ts=before_ts),
            normalized_period,
        )
        if not pytdx_df.empty:
            return pytdx_df.tail(fetch_count).reset_index(drop=True)
    except Exception:
        pytdx_df = pd.DataFrame()

    minute_period = _period_minutes(normalized_period)
    if security_kind == "etf" and minute_period in {1, 5, 15, 30, 60}:
        try:
            akshare_df = _normalize_remote_kline_df(
                akshare_data.get_etf_minute_data(code, period=str(minute_period)),
                normalized_period,
            )
            return _slice_df_before(akshare_df, normalized_period, before_ts).tail(fetch_count).reset_index(drop=True)
        except Exception:
            return pd.DataFrame()

    return pd.DataFrame()


def _fetch_kline_df_from_sources(
    code: str,
    period: str,
    count: int,
    security_kind: str,
    before_ts: Optional[str | int | float] = None,
) -> tuple[pd.DataFrame, str]:
    normalized_period = normalize_period(period)
    source_priority = get_kline_source_priority(normalized_period, security_kind)

    for source in source_priority:
        try:
            if source == "local" and security_kind != "index":
                df = ensure_local_kline_cache(
                    code,
                    normalized_period,
                    limit=count + max(count, 200),
                    security_kind=security_kind,
                    before_ts=before_ts,
                )
            elif source == "pytdx":
                min_bars = int(LOCAL_KLINE_CACHE_RULES.get(normalized_period, {}).get("min_bars", count))
                fetch_count = max(count + max(count, 200), min_bars)
                df = (
                    pytdx_data.get_index_kline(code, normalized_period, fetch_count, before_ts=before_ts)
                    if security_kind == "index"
                    else pytdx_data.get_kline(code, normalized_period, fetch_count, before_ts=before_ts)
                )
                df = _normalize_remote_kline_df(df, normalized_period)
            elif source == "akshare" and security_kind != "index":
                if normalized_period not in ("daily", "weekly", "monthly"):
                    continue
                hist_fetcher = akshare_data.get_etf_hist_daily if security_kind == "etf" else akshare_data.get_stock_hist_daily
                df = hist_fetcher(code, period=normalized_period)
                df = _normalize_remote_kline_df(df, normalized_period)
                df = _slice_df_before(df, normalized_period, before_ts)
            else:
                continue
        except Exception:
            continue

        if df is not None and not df.empty:
            return df, source

    return pd.DataFrame(), "none"


def _is_after_close_stale(sync_state: Optional[dict], period: str) -> bool:
    normalized_period = normalize_period(period)
    if normalized_period not in REALTIME_SENSITIVE_KLINE_PERIODS:
        return False
    now = now_beijing()
    if now.weekday() >= 5 or now.hour < 15:
        return False
    today = now.strftime("%Y-%m-%d")
    last_bar_time = str((sync_state or {}).get("last_bar_time") or "")
    return not last_bar_time.startswith(today)


def _is_sync_due(
    sync_state: Optional[dict],
    min_bars: int,
    refresh_interval_seconds: int,
    period: str = "",
) -> bool:
    if not sync_state or int(sync_state.get("bar_count") or 0) < int(min_bars):
        return True

    if period and _is_after_close_stale(sync_state, period):
        return True

    last_synced_at = sync_state.get("last_synced_at")
    if not last_synced_at:
        return True

    try:
        last_synced = pd.Timestamp(last_synced_at).to_pydatetime()
    except Exception:
        return True
    # last_synced_at 由 kline_parquet 以北京墙钟写入,这里用北京 naive now 对齐(勿用 datetime.now())
    return now_beijing().replace(tzinfo=None) - last_synced >= timedelta(seconds=int(refresh_interval_seconds))


def ensure_local_kline_cache(
    code: str,
    period: str,
    limit: Optional[int] = None,
    force_refresh: bool = False,
    security_kind: str = "security",
    before_ts: Optional[str | int | float] = None,
    fresh_window_seconds: Optional[int] = None,
) -> pd.DataFrame:
    normalized_period = normalize_period(period)
    rule = LOCAL_KLINE_CACHE_RULES.get(normalized_period)
    if not rule:
        return pd.DataFrame()

    min_bars = int(rule["min_bars"])
    fetch_limit = int(limit or min_bars)
    sync_state = get_kline_sync_state(code, normalized_period)
    if force_refresh:
        delete_kline_parquet(code, normalized_period)
        sync_state = None
    sync_due = _is_sync_due(sync_state, min_bars, int(rule["refresh_interval_seconds"]), normalized_period)
    if fresh_window_seconds and not force_refresh:
        # 盘中场景叠加更短的新鲜度窗口:本地缓存最多滞后 fresh_window_seconds,
        # 保证实时行情源不可用时仍能从历史接口拿到近实时(含当天未收盘)的bar
        sync_due = sync_due or _is_sync_due(sync_state, min_bars, int(fresh_window_seconds), normalized_period)
    local_bar_count = int(sync_state.get("bar_count") or 0) if sync_state else 0
    needs_more_history = fetch_limit > local_bar_count

    if not force_refresh:
        local_df = _read_local_kline_slice(code, normalized_period, fetch_limit, before_ts=before_ts)
        if not local_df.empty and len(local_df) >= min(min_bars, fetch_limit):
            if before_ts not in (None, "") or (not sync_due and not needs_more_history and len(local_df) >= fetch_limit):
                return local_df

    remote_df = pd.DataFrame()

    if force_refresh or sync_due or needs_more_history:
        if force_refresh:
            fetch_count = max(fetch_limit, min_bars)
        elif not sync_state or int(sync_state.get("bar_count") or 0) < min_bars:
            fetch_count = max(fetch_limit, int(rule["full_fetch_bars"]))
        elif needs_more_history:
            fetch_count = max(fetch_limit, int(rule["full_fetch_bars"]))
        else:
            fetch_count = int(rule["refresh_fetch_bars"])
        remote_df = _fetch_remote_kline_for_cache(
            code,
            normalized_period,
            fetch_count,
            security_kind,
        )
        records = _kline_df_to_records(remote_df, normalized_period)
        if records:
            keep_latest = max(int(rule["keep_latest"]), fetch_count)
            saved = upsert_kline_parquet(
                code,
                normalized_period,
                records,
                keep_latest=keep_latest,
                replace_existing=force_refresh,
            )
            if saved:
                merged_df = _read_local_kline_slice(code, normalized_period, keep_latest)
                if not merged_df.empty:
                    time_col = _get_df_time_col(normalized_period)
                    first_bar = merged_df[time_col].iloc[0]
                    last_bar = merged_df[time_col].iloc[-1]
                    update_kline_sync_state(
                        code,
                        normalized_period,
                        len(merged_df),
                        _format_sync_bar_time(first_bar, normalized_period),
                        _format_sync_bar_time(last_bar, normalized_period),
                    )
                elif not remote_df.empty:
                    time_col = _get_df_time_col(normalized_period)
                    first_bar = remote_df[time_col].iloc[0] if len(remote_df) > 0 else None
                    last_bar = remote_df[time_col].iloc[-1] if len(remote_df) > 0 else None
                    update_kline_sync_state(
                        code,
                        normalized_period,
                        len(remote_df),
                        _format_sync_bar_time(first_bar, normalized_period),
                        _format_sync_bar_time(last_bar, normalized_period),
                    )

    local_df = _read_local_kline_slice(code, normalized_period, fetch_limit, before_ts=before_ts)
    if not local_df.empty:
        return local_df

    if not remote_df.empty:
        return remote_df.tail(fetch_limit).reset_index(drop=True)

    fallback_df = _fetch_remote_kline_for_cache(
        code,
        normalized_period,
        max(fetch_limit, min_bars),
        security_kind,
        before_ts=before_ts,
    )
    if not fallback_df.empty:
        records = _kline_df_to_records(fallback_df, normalized_period)
        if records:
            fallback_keep_latest = max(int(rule["keep_latest"]), max(fetch_limit, min_bars))
            saved = upsert_kline_parquet(
                code,
                normalized_period,
                records,
                keep_latest=fallback_keep_latest,
                replace_existing=force_refresh,
            )
            if saved:
                merged_df = _read_local_kline_slice(code, normalized_period, fallback_keep_latest)
                if not merged_df.empty:
                    time_col = _get_df_time_col(normalized_period)
                    first_bar = merged_df[time_col].iloc[0]
                    last_bar = merged_df[time_col].iloc[-1]
                    update_kline_sync_state(
                        code,
                        normalized_period,
                        len(merged_df),
                        _format_sync_bar_time(first_bar, normalized_period),
                        _format_sync_bar_time(last_bar, normalized_period),
                    )
                elif not fallback_df.empty:
                    time_col = _get_df_time_col(normalized_period)
                    first_bar = fallback_df[time_col].iloc[0] if len(fallback_df) > 0 else None
                    last_bar = fallback_df[time_col].iloc[-1] if len(fallback_df) > 0 else None
                    update_kline_sync_state(
                        code,
                        normalized_period,
                        len(fallback_df),
                        _format_sync_bar_time(first_bar, normalized_period),
                        _format_sync_bar_time(last_bar, normalized_period),
                )
    return fallback_df.tail(fetch_limit).reset_index(drop=True) if not fallback_df.empty else pd.DataFrame()


def get_local_history_ready(code: str, period: str, require_fresh: bool = False) -> bool:
    normalized_period = normalize_period(period)
    rule = LOCAL_KLINE_CACHE_RULES.get(normalized_period)
    if not rule:
        return False
    sync_state = get_kline_sync_state(code, normalized_period)
    ready = bool(sync_state and int(sync_state.get("bar_count") or 0) >= int(rule["min_bars"]))
    if not ready:
        return False
    if require_fresh:
        return not _is_sync_due(sync_state, int(rule["min_bars"]), int(rule["refresh_interval_seconds"]), normalized_period)
    return True


def ensure_local_history_bundle(
    code: str,
    limit_overrides: Optional[dict[str, int]] = None,
    force_refresh: bool = False,
    security_kind: str = "security",
):
    limit_overrides = limit_overrides or {}
    results = {}
    for period in LOCAL_KLINE_CACHE_RULES:
        results[period] = ensure_local_kline_cache(
            code,
            period,
            limit=limit_overrides.get(period),
            force_refresh=force_refresh,
            security_kind=security_kind,
        )
    return results


def _is_intraday_for_daily_kline(now: Optional[datetime] = None) -> bool:
    """检查是否是盘中时间，用于判断日K线是否需要补充当天实时数据。

    锚定北京时间:bar 的时间轴、today 字符串、历史下载窗口都以北京日期为准,
    服务器本地时区(UTC 等)下用本地时钟会让日K盘中补充在真实交易时段
    永远不触发,表现为"分钟线实时、唯独日K只有历史"。
    """
    current = (now or now_beijing()).time()
    # 9:30-11:30 和 13:00-15:00 是A股交易时间
    in_morning = time(9, 30) <= current <= time(11, 30)
    in_afternoon = time(13, 0) <= current <= time(15, 0)
    # 盘前（9:15-9:30）也算，因为可能有集合竞价数据
    in_pre_open = time(9, 15) <= current < time(9, 30)
    return in_morning or in_afternoon or in_pre_open


def _is_etf_like_code(code: str) -> bool:
    """通过代码前缀判断是否为 ETF/LOF（与 security_service.infer_t0_flag 一致）。"""
    code = str(code).strip().zfill(6)
    return code.startswith(("15", "50", "51", "52", "56", "58"))


def _synthesize_today_bar_from_minute_df(code: str, prev_close: float, today_str: str, security_kind: str = "security") -> pd.DataFrame:
    """实时报价源全部不可用时的最后兜底:用 pytdx 当天30分钟线聚合成当天日K。

    TDX 分钟bars(get_security_bars)与实时报价(get_security_quotes)是不同接口,
    报价接口被机房网络风控/拦截时分钟接口往往仍可用;东财日线历史接口同样被拦时,
    这是唯一能盘中合成当天bar的来源。分钟价为不复权口径,用昨天分钟末根收盘
    对齐本地hfq昨收得到换算因子,与报价兜底链的处理一致。
    """
    try:
        if security_kind == "index":
            minute_df = pytdx_data.get_index_kline(code, "30min", 24)
        else:
            minute_df = pytdx_data.get_kline(code, "30min", 24)
    except Exception as e:
        logger.info(f"[盘中补充] {code} 分钟线兜底获取异常: {e}")
        return pd.DataFrame()
    if minute_df is None or minute_df.empty or "datetime" not in minute_df.columns:
        return pd.DataFrame()

    normalized = _normalize_remote_kline_df(minute_df, "30min")
    if normalized.empty:
        return pd.DataFrame()

    today_start = pd.Timestamp(today_str, tz="UTC")
    today_bars = normalized[normalized["datetime"] >= today_start]
    if today_bars.empty:
        logger.info(f"[盘中补充] {code} 分钟线兜底: 当天无分钟bar(未开盘/停牌)")
        return pd.DataFrame()

    prev_bars = normalized[normalized["datetime"] < today_start]
    raw_prev_close = float(prev_bars.iloc[-1]["close"]) if not prev_bars.empty else 0.0
    hfq_factor = (prev_close / raw_prev_close) if (prev_close > 0 and raw_prev_close > 0) else 1.0
    # 因子合理性校验(与报价合成同口径):qfq 基线下因子必须≈1,超界说明分钟源
    # 昨收口径异常(除权日未调整/错标的),丢弃降级纯历史。
    if prev_close > 0 and raw_prev_close > 0 and not (0.85 <= hfq_factor <= 1.15):
        logger.info(
            f"[盘中补充] {code} 分钟线兜底因子异常丢弃: 本地昨收{prev_close}/分钟昨收{raw_prev_close}"
            f"=因子{hfq_factor:.3f}超[0.85,1.15]"
        )
        return pd.DataFrame()

    close = float(today_bars.iloc[-1]["close"]) * hfq_factor
    if close <= 0:
        return pd.DataFrame()
    if prev_close and prev_close > 0:
        ratio = close / prev_close
        if ratio < 0.6 or ratio > 1.6:
            logger.info(f"[盘中补充] {code} 分钟线兜底校验丢弃: 比值{ratio:.2f}超[0.6,1.6]")
            return pd.DataFrame()

    amount = float(today_bars["amount"].sum()) if "amount" in today_bars.columns else 0.0
    logger.info(f"[盘中补充] {code} 分钟线兜底成功合成当天bar close={close} bars={len(today_bars)}")
    return pd.DataFrame([{
        "date": today_start,
        "open": float(today_bars.iloc[0]["open"]) * hfq_factor,
        "high": float(today_bars["high"].max()) * hfq_factor,
        "low": float(today_bars["low"].min()) * hfq_factor,
        "close": close,
        "volume": float(today_bars["volume"].sum()),
        "amount": amount,
    }])


# 盘中「当天实时bar」微缓存：日K盘中每请求都绕过响应缓存去远程取实时报价
# （腾讯/pytdx，几百毫秒），快速切换个股时明显拖慢。日K单根bar 15 秒新鲜度足够。
# 只缓存成功结果（空结果不缓存，失败下轮重试）。
_today_bar_cache: dict = {}
_TODAY_BAR_CACHE_TTL = 15.0


def _fetch_today_realtime_bar_df(code: str, security_kind: str, today_str: str, prev_close: float = 0.0) -> pd.DataFrame:
    """_fetch_today_realtime_bar_df_uncached 的微缓存包装（TTL 15s，仅缓存成功结果）。"""
    import time as _time
    key = (str(code).strip().zfill(6), str(security_kind), str(today_str), round(float(prev_close or 0), 4))
    hit = _today_bar_cache.get(key)
    if hit is not None and _time.time() - hit[0] < _TODAY_BAR_CACHE_TTL:
        return hit[1].copy()
    df = _fetch_today_realtime_bar_df_uncached(code, security_kind, today_str, prev_close)
    if df is not None and not df.empty:
        _today_bar_cache[key] = (_time.time(), df.copy())
    return df


def _fetch_today_realtime_bar_df_uncached(code: str, security_kind: str, today_str: str, prev_close: float = 0.0) -> pd.DataFrame:
    """盘中取当天实时日K（单根 bar），用于补充到历史日线末尾。

    用实时行情报价合成当天的 OHLCV，而不是用 pytdx 日线历史接口——
    通达信日线(category=4)是收盘结算后的历史数据，盘中不返回当天未收盘的K线，
    这是之前盘中补充逻辑失效的根因。

    数据源兜底链（复用项目现成的实时行情函数，不改动既有数据源）：
      - 个股/ETF 主源 akshare_data.get_tencent_realtime_quote（qt.gtimg.cn 单点）：
        对 ETF 报价准确。pytdx 对 ETF/基金存在已知 10 倍放大 bug（price/昨收整体
        ×10），若用作 ETF 主源会被下方合理性校验丢弃，导致盘中日K补不上当天实时K线。
      - 指数主源 pytdx_data.get_realtime_quotes：指数实时点位准确（腾讯前缀对 000001
        等上证指数存在 sh/sz 歧义，故指数仍走 pytdx）。
      - 兜底 akshare：ETF 用 get_etf_realtime_quote，个股用 get_stock_spot_detail；
        指数无 akshare 单点兜底，pytdx 失败则返回空，由调用方退回纯历史。

    返回：单行 DataFrame，含 date(UTC tz)/open/high/low/close/volume/amount；
          取不到或异常时返回空 DataFrame，调用方会降级为纯历史数据。
    """
    code_str = str(code).strip().zfill(6)
    quote: Optional[dict] = None

    logger.info(f"[盘中补充] {code} 开始 kind={security_kind} today={today_str} prev_close={prev_close}")

    # 个股/ETF：腾讯主源（对 ETF 报价准确，规避 pytdx 的 10 倍放大 bug）
    if security_kind != "index":
        try:
            quote = akshare_data.get_tencent_realtime_quote(code_str)
            if quote and quote.get("price"):
                logger.info(f"[盘中补充] {code} 腾讯命中 price={quote.get('price')} open={quote.get('open')} high={quote.get('high')} low={quote.get('low')} vol={quote.get('volume')}")
        except Exception as e:
            logger.info(f"[盘中补充] {code} 腾讯异常: {e}")

    # 指数主源 / 个股ETF兜底：pytdx（指数点位准确；ETF 即便 10 倍失真也会被下方校验丢弃）
    if not quote or not quote.get("price"):
        try:
            quotes = pytdx_data.get_realtime_quotes([code_str])
            if quotes:
                quote = quotes[0]
                logger.info(f"[盘中补充] {code} pytdx命中 price={quote.get('price')} open={quote.get('open')} high={quote.get('high')} low={quote.get('low')} vol={quote.get('volume')}")
        except Exception as e:
            logger.info(f"[盘中补充] {code} pytdx异常: {e}")

    if not quote or not quote.get("price"):
        logger.info(f"[盘中补充] {code} 腾讯/pytdx均无可用数据，尝试akshare兜底")
        try:
            if _is_etf_like_code(code_str):
                quote = akshare_data.get_etf_realtime_quote(code_str) or None
            elif security_kind != "index":
                quote = akshare_data.get_stock_spot_detail(code_str) or None
        except Exception as e:
            logger.info(f"[盘中补充] {code} akshare兜底异常: {e}")
        if quote:
            logger.info(f"[盘中补充] {code} akshare命中 price={quote.get('price')}")

    if not quote:
        logger.info(f"[盘中补充] {code} 所有报价源均无实时数据，尝试分钟线聚合兜底")
        return _synthesize_today_bar_from_minute_df(code_str, prev_close, today_str, security_kind)

    try:
        # 本地日线/周月线基准是前复权(qfq),而实时报价是不复权(raw)。用"昨收"对齐
        # 两种口径得到换算因子 = 本地qfq昨收 / 实时raw昨收,把当天实时 OHLC 换算到
        # qfq 口径。qfq 最新价==真实价,因子日常≈1;除权除息当日会有微小偏差(≈股息率),
        # 次日历史同步后自愈。指数不复权,本地昨收==raw昨收,因子自然退化为1。
        quote_prev_close = float(quote.get("pre_close") or quote.get("prev_close") or 0)
        hfq_factor = (prev_close / quote_prev_close) if (prev_close > 0 and quote_prev_close > 0) else 1.0
        # 因子合理性校验:qfq 基线下因子必须≈1(除权日偏差仅股息级,±15%容错)。
        # 部分源在除权日返回"未除权调整的原始昨收"(如10转3.7除权日昨收差3.7倍),
        # 因子会飙到 3~5,直接乘会把当天bar放大数倍(实测长电科技 66→251),必须丢弃。
        if prev_close > 0 and quote_prev_close > 0 and not (0.85 <= hfq_factor <= 1.15):
            logger.info(
                f"[盘中补充] {code} 因子异常丢弃: 本地昨收{prev_close}/实时昨收{quote_prev_close}"
                f"=因子{hfq_factor:.3f}超[0.85,1.15](疑似除权日未调整昨收或错标的),降级纯历史"
            )
            return pd.DataFrame()
        if abs(hfq_factor - 1.0) > 1e-4:
            logger.info(f"[盘中补充] {code} raw→qfq换算因子={hfq_factor:.5f} (本地昨收{prev_close}/实时昨收{quote_prev_close})")
        bar = {
            "date": pd.Timestamp(today_str, tz="UTC"),
            "open": float(quote.get("open") or 0) * hfq_factor,
            "high": float(quote.get("high") or 0) * hfq_factor,
            "low": float(quote.get("low") or 0) * hfq_factor,
            "close": float(quote.get("price") or 0) * hfq_factor,
            "volume": float(quote.get("volume") or 0),
            "amount": float(quote.get("amount") or 0),
        }
    except Exception as e:
        logger.info(f"[盘中补充] {code} 合成bar异常: {e}")
        return pd.DataFrame()

    # 当天尚未开盘（close 为 0）时不应追加，否则会盖掉昨天那根
    if bar["close"] <= 0:
        logger.info(f"[盘中补充] {code} close={bar['close']}<=0(未开盘/停牌)，不追加")
        return pd.DataFrame()

    # 合理性校验(第二道防线):qfq 基线下当天bar与昨收的比值应在 [0.6,1.6]
    # (A股涨跌停±10/20/30%全覆盖);因子校验漏网的可疑数据在此兜底丢弃。
    if prev_close and prev_close > 0:
        ratio = bar["close"] / prev_close
        if ratio < 0.6 or ratio > 1.6:
            logger.info(
                f"[盘中补充] {code} 校验丢弃: 实时{bar['close']}/昨收{prev_close}=比值{ratio:.2f}超[0.6,1.6]"
            )
            return pd.DataFrame()

    logger.info(f"[盘中补充] {code} 成功合成当天bar close={bar['close']} vol={bar['volume']} amount={bar['amount']}")
    return pd.DataFrame([bar])


def get_security_kline(
    code: str,
    period: str,
    count: int,
    security_kind: str = "security",
    before_ts: Optional[str | int | float] = None,
) -> dict:
    normalized_period = normalize_period(period)
    requested_count = max(1, int(count))
    logger.info(f"[K线请求] {code} period={normalized_period} kind={security_kind} before_ts={before_ts} 盘中={_is_intraday_for_daily_kline()}")

    # 日K线盘中实时数据补充：历史数据 + 当天实时K线
    if normalized_period == "daily" and not before_ts and _is_intraday_for_daily_kline():
        # 历史部分走 ensure_local_kline_cache(带盘中新鲜度窗口),而不是直接读 parquet:
        # 直接读的旧方案在本地历史过期(服务器数日未同步/下载任务未跑)时,
        # ① 图中历史与当天之间出现缺口;② prev_close 过旧会让实时bar被合理性校验
        # 误杀,最终退化成"只有已下载的旧历史"。ensure 内部有节流,本地新鲜时
        # 等价于一次 parquet 读;过期则从 akshare 日线接口补齐——该接口盘中本身
        # 返回当天未收盘K线,即使下方实时行情源全部不可用也有兜底。
        history_df = ensure_local_kline_cache(
            code,
            "daily",
            limit=requested_count,
            security_kind=security_kind,
            fresh_window_seconds=INTRADAY_KLINE_FRESH_WINDOW_SECONDS,
        )
        source = "local"

        # 如果本地无数据，从远程获取
        if history_df is None or history_df.empty:
            history_df, source = _fetch_kline_df_from_sources(
                code, "daily", requested_count, security_kind, before_ts=None
            )

        if history_df is not None and not history_df.empty:
            today = now_beijing().strftime("%Y-%m-%d")
            time_col = "date" if "date" in history_df.columns else "datetime"
            today_start = pd.Timestamp(today, tz="UTC")

            # 历史里 < 今天 的部分：用昨天的真实收盘做 prev_close 校验实时价；
            # 盘中要排除本地今天的脏数据，统一用远程实时覆盖（按需求：当天本地有也不用）。
            history_before_today = history_df[history_df[time_col] < today_start].reset_index(drop=True) if time_col in history_df.columns else history_df
            prev_close = float(history_before_today.iloc[-1].get("close") or 0) if not history_before_today.empty else 0.0

            last_bar_date = None
            if time_col in history_df.columns and len(history_df) > 0:
                last_bar_time = history_df.iloc[-1][time_col]
                if pd.notna(last_bar_time):
                    last_bar_date = pd.Timestamp(last_bar_time).strftime("%Y-%m-%d")
            logger.info(f"[盘中补充] {code} 日K盘中: 历史末根={last_bar_date} today={today} prev_close={prev_close}")

            # 盘中始终用远程实时覆盖当天（即使本地已有今天的脏数据也不用）
            try:
                realtime_df = _fetch_today_realtime_bar_df(code, security_kind, today, prev_close=prev_close)
                if realtime_df is not None and not realtime_df.empty:
                    today_bar = realtime_df[realtime_df[time_col] >= today_start]
                    if not today_bar.empty:
                        logger.info(f"[盘中补充] {code} 用实时覆盖当天: close={float(today_bar.iloc[-1].get('close') or 0)} vol={float(today_bar.iloc[-1].get('volume') or 0)}")
                        merged_df = pd.concat([history_before_today, today_bar], ignore_index=True)
                        merged_df = merged_df.drop_duplicates(subset=[time_col], keep="last")
                        merged_df = merged_df.sort_values(time_col).reset_index(drop=True)
                        return _build_kline_page_result(merged_df, "daily", requested_count, f"{source}+realtime")
            except Exception as e:
                logger.info(f"[盘中补充] {code} 日K补充异常(降级纯历史): {e}")
                return _build_kline_page_result(history_df, "daily", requested_count, source)

            # 实时取不到，降级返回历史（ensure 已带盘中新鲜度窗口，通常含
            # akshare 日线接口返回的当天bar快照，仅滞后数分钟）
            logger.info(f"[盘中补充] {code} 实时取不到，降级返回本地缓存历史")
            return _build_kline_page_result(history_df, "daily", requested_count, source)

    if normalized_period == "120min":
        base_period = "60min"
        base_count = max(requested_count * 2 + 20, int(LOCAL_KLINE_CACHE_RULES.get(base_period, {}).get("min_bars", requested_count * 2)))
        base_df, source = _fetch_kline_df_from_sources(code, base_period, base_count, security_kind)
        aggregated_df = _aggregate_consecutive_minute_bars(base_df, base_period, normalized_period)
        aggregated_df = _slice_df_before(aggregated_df, normalized_period, before_ts)
        if not aggregated_df.empty:
            return _build_kline_page_result(aggregated_df, normalized_period, requested_count, f"{source}+120min")

    if normalized_period in ("weekly", "monthly", "quarter", "year"):
        # 周/月/季/年线统一从日线聚合
        # 盘中时需要包含当天实时数据，与日线同源一致
        days_per_bar = {"weekly": 7, "monthly": 31, "quarter": 95, "year": 366}[normalized_period]
        base_period = "daily"
        base_count = max(requested_count * days_per_bar + 30, 160)

        # 盘中时使用带实时补充的日线获取逻辑
        if not before_ts and _is_intraday_for_daily_kline():
            # 与日K盘中分支同理:走 ensure 带盘中新鲜度窗口,本地过期时先补齐历史
            base_df = ensure_local_kline_cache(
                code,
                base_period,
                limit=base_count,
                security_kind=security_kind,
                fresh_window_seconds=INTRADAY_KLINE_FRESH_WINDOW_SECONDS,
            )
            source = "local"
            if base_df is None or base_df.empty:
                base_df, source = _fetch_kline_df_from_sources(code, base_period, base_count, security_kind)

            if base_df is not None and not base_df.empty:
                # 盘中始终用远程实时覆盖当天（本地有今天的脏数据也不用）
                today = now_beijing().strftime("%Y-%m-%d")
                time_col = "date" if "date" in base_df.columns else "datetime"
                today_start = pd.Timestamp(today, tz="UTC")

                base_before_today = base_df[base_df[time_col] < today_start].reset_index(drop=True) if time_col in base_df.columns else base_df
                prev_close = float(base_before_today.iloc[-1].get("close") or 0) if not base_before_today.empty else 0.0

                try:
                    realtime_df = _fetch_today_realtime_bar_df(code, security_kind, today, prev_close=prev_close)
                    if realtime_df is not None and not realtime_df.empty:
                        today_bar = realtime_df[realtime_df[time_col] >= today_start]
                        if not today_bar.empty:
                            base_df = pd.concat([base_before_today, today_bar], ignore_index=True)
                            base_df = base_df.drop_duplicates(subset=[time_col], keep="last")
                            base_df = base_df.sort_values(time_col).reset_index(drop=True)
                            source = f"{source}+realtime"
                except Exception as e:
                    logger.info(f"[盘中补充] {code} 周月线聚合前实时补充失败: {e}")
        else:
            # 非盘中或历史查询，直接读取本地数据
            base_df = get_kline_parquet(code, base_period, limit=base_count)
            source = "local"
            if base_df is None or base_df.empty:
                base_df, source = _fetch_kline_df_from_sources(code, base_period, base_count, security_kind)

        aggregated_df = _aggregate_daily_to_period(base_df, normalized_period)
        aggregated_df = _slice_df_before(aggregated_df, normalized_period, before_ts)
        if not aggregated_df.empty:
            return _build_kline_page_result(aggregated_df, normalized_period, requested_count, f"{source}+{normalized_period}")

    df, source = _fetch_kline_df_from_sources(
        code,
        normalized_period,
        requested_count,
        security_kind,
        before_ts=before_ts,
    )
    if df is not None and not df.empty:
        return _build_kline_page_result(df, normalized_period, requested_count, source)

    return {
        "data": pd.DataFrame(),
        "has_more": False,
        "next_before_ts": None,
        "source": "none",
    }
