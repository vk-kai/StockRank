from __future__ import annotations

from typing import Optional

import pandas as pd

from backend import db
from backend.kline_parquet import get_kline_parquet
from backend.market import pytdx_data
from backend.scan_universe_service import load_download_universe_snapshot

from .periods import normalize_scan_period


def load_local_kline_df(code: str, period: str, limit: int) -> pd.DataFrame:
    return get_kline_parquet(code, period, limit=limit)


def merge_scan_realtime_tail(local_df: pd.DataFrame, code: str, scan_period: str, min_scan_bars: int) -> pd.DataFrame:
    if local_df is None or local_df.empty:
        return pd.DataFrame()

    normalized_period = normalize_scan_period(scan_period)
    if normalized_period not in ("1min", "5min", "15min", "30min", "60min", "daily", "weekly", "monthly"):
        return local_df.tail(min_scan_bars).reset_index(drop=True)

    remote_tail = pytdx_data.get_kline(code, normalized_period, min(max(min_scan_bars, 8), 64))
    if remote_tail is None or remote_tail.empty:
        return local_df.tail(min_scan_bars).reset_index(drop=True)

    work_df = remote_tail.copy()
    time_col = "date" if normalized_period in ("daily", "weekly", "monthly") else "datetime"
    if time_col not in work_df.columns:
        return local_df.tail(min_scan_bars).reset_index(drop=True)

    work_df[time_col] = pd.to_datetime(work_df[time_col], errors="coerce", utc=True, format="mixed")
    work_df = work_df.dropna(subset=[time_col]).sort_values(time_col).reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in work_df.columns:
            work_df[col] = pd.to_numeric(work_df[col], errors="coerce")

    # 比例对齐:local(前复权 qfq)与 pytdx 实时尾巴(不复权)在除权日有股息级微差,
    # 用 local 末根 close / 尾巴首根 close 把尾巴价格缩放到 local 口径。
    # qfq 基线下两者日常≈1,除权日偏差也仅股息级(±3%内),区间收紧到 [0.8,1.25]
    # ——显著偏离 1 只可能是错标的或滞后数据,此时不缩放(宁可比对偏差也别放大错价)。
    if not local_df.empty and not work_df.empty:
        try:
            local_last_close = float(pd.to_numeric(local_df["close"], errors="coerce").iloc[-1])
            remote_first_close = float(pd.to_numeric(work_df["close"], errors="coerce").iloc[0])
            if local_last_close > 0 and remote_first_close > 0:
                scale = local_last_close / remote_first_close
                if 0.8 < scale < 1.25 and abs(scale - 1.0) > 0.03:
                    for col in ("open", "high", "low", "close"):
                        if col in work_df.columns:
                            work_df[col] = pd.to_numeric(work_df[col], errors="coerce") * scale
        except Exception:
            pass

    merged = pd.concat([local_df, work_df], ignore_index=True)
    merged[time_col] = pd.to_datetime(merged[time_col], errors="coerce", utc=True, format="mixed")
    merged = merged.dropna(subset=[time_col]).drop_duplicates(subset=[time_col], keep="last")
    merged = merged.sort_values(time_col).reset_index(drop=True)
    return merged.tail(min_scan_bars).reset_index(drop=True)


def load_scan_universe_candidates() -> list[dict]:
    snapshot = load_download_universe_snapshot()
    candidates: list[dict] = []
    seen: set[str] = set()
    for item in snapshot:
        code = str(item.get("code", "")).zfill(6)
        if not code or code in seen:
            continue
        seen.add(code)
        candidates.append(
            {
                "code": code,
                "name": str(item.get("name", "") or code),
                "market": int(item.get("market", 1)),
            }
        )
    if candidates:
        return candidates

    for item in db.list_stock_pool(scan_eligible_only=True):
        code = str(item.get("code", "")).zfill(6)
        if not code or code in seen:
            continue
        seen.add(code)
        candidates.append(
            {
                "code": code,
                "name": str(item.get("name", "") or code),
                "market": int(item.get("market", 1)),
            }
        )
    return candidates


def normalize_selected_codes(codes: Optional[list[str] | tuple[str, ...]]) -> list[str]:
    if not codes:
        return []
    seen: set[str] = set()
    normalized: list[str] = []
    for code in codes:
        normalized_code = str(code).strip().zfill(6)
        if not normalized_code or normalized_code in seen:
            continue
        seen.add(normalized_code)
        normalized.append(normalized_code)
    return normalized
