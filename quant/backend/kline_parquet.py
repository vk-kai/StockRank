from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta

from backend.time_utils import now_beijing
from pathlib import Path
from typing import Optional

import pandas as pd

from backend.paths import get_kline_parquet_path, ensure_kline_dir, KLINE_PARQUET_DIR

logger = logging.getLogger(__name__)

_kline_lock = threading.Lock()
_sync_state_cache: dict[str, dict] = {}
KLINE_MAX_HISTORY_YEARS = 3


def _filter_plausible_kline_times(df: pd.DataFrame, time_col: str) -> pd.DataFrame:
    if df.empty or time_col not in df.columns:
        return df
    min_time = pd.Timestamp("1990-01-01", tz="UTC")
    # K线时间轴约定为"北京墙钟、UTC标签",上界要用北京日期(服务器本地日期在 0-8 点窗口会差一天)
    max_time = pd.Timestamp((now_beijing() + timedelta(days=1)).replace(tzinfo=None), tz="UTC")
    mask = df[time_col].between(min_time, max_time)
    if bool(mask.all()):
        return df
    return df[mask].reset_index(drop=True)


def _get_sync_state_path(period: str) -> Path:
    ensure_kline_dir()
    return KLINE_PARQUET_DIR / f"sync_state_{period}.json"


def _load_sync_states(period: str) -> dict[str, dict]:
    state_path = _get_sync_state_path(period)
    if not state_path.exists():
        return {}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        return {}


def _save_sync_states(period: str, states: dict[str, dict]):
    state_path = _get_sync_state_path(period)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(states, f, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        pass


def get_kline_parquet(
    code: str,
    period: str,
    limit: Optional[int] = None,
    before_ts: Optional[str | int | float] = None,
) -> pd.DataFrame:
    parquet_path = get_kline_parquet_path(code, period)
    if not parquet_path.exists():
        return pd.DataFrame()
    
    try:
        df = pd.read_parquet(parquet_path)
        if df.empty:
            return pd.DataFrame()
        
        time_col = "date" if period == "daily" else "datetime"
        if time_col not in df.columns:
            return pd.DataFrame()
        
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce", format="mixed")
        if period != "daily" and not pd.api.types.is_datetime64tz_dtype(df[time_col]):
            try:
                df[time_col] = df[time_col].dt.tz_localize("Asia/Shanghai", ambiguous="infer", nonexistent="shift_forward").dt.tz_convert("UTC")
            except Exception:
                df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
        elif pd.api.types.is_datetime64tz_dtype(df[time_col]):
            df[time_col] = df[time_col].dt.tz_convert("UTC")
        else:
            df[time_col] = pd.to_datetime(df[time_col], errors="coerce", utc=True)
        df = df.dropna(subset=[time_col]).sort_values(time_col).reset_index(drop=True)

        if before_ts not in (None, ""):
            before_dt = pd.to_datetime(before_ts, errors="coerce", utc=True)
            if pd.isna(before_dt):
                return pd.DataFrame()
            df = df[df[time_col] < before_dt].reset_index(drop=True)
        
        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        
        if limit and limit > 0:
            return df.tail(limit).reset_index(drop=True)
        return df.reset_index(drop=True)
    except Exception as exc:
        logger.warning("Failed to read kline parquet %s: %s", parquet_path, exc)
        return pd.DataFrame()


def upsert_kline_parquet(code: str, period: str, records: list[dict], keep_latest: int = 0, replace_existing: bool = False) -> bool:
    if not records:
        return False
    
    parquet_path = get_kline_parquet_path(code, period)
    time_col = "date" if period == "daily" else "datetime"
    
    new_df = pd.DataFrame(records)
    if "bar_time" in new_df.columns:
        parsed = pd.to_datetime(new_df["bar_time"], errors="coerce", format="mixed")
        if period != "daily" and not pd.api.types.is_datetime64tz_dtype(parsed):
            try:
                parsed = parsed.dt.tz_localize("Asia/Shanghai", ambiguous="infer", nonexistent="shift_forward").dt.tz_convert("UTC")
            except Exception:
                parsed = pd.to_datetime(new_df["bar_time"], errors="coerce", utc=True)
        elif pd.api.types.is_datetime64tz_dtype(parsed):
            parsed = parsed.dt.tz_convert("UTC")
        else:
            parsed = pd.to_datetime(new_df["bar_time"], errors="coerce", utc=True)
        new_df[time_col] = parsed
        new_df = new_df.drop(columns=["bar_time"], errors="ignore")
    
    if time_col not in new_df.columns:
        return False
    
    if not pd.api.types.is_datetime64tz_dtype(new_df[time_col]):
        new_df[time_col] = pd.to_datetime(new_df[time_col], errors="coerce", utc=True)
    else:
        new_df[time_col] = new_df[time_col].dt.tz_convert("UTC")
    new_df = new_df.dropna(subset=[time_col])
    new_df = _filter_plausible_kline_times(new_df, time_col)
    if new_df.empty:
        return False
    
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in new_df.columns:
            new_df[col] = pd.to_numeric(new_df[col], errors="coerce")
    
    existing_df = pd.DataFrame()
    if not replace_existing and parquet_path.exists():
        try:
            existing_df = pd.read_parquet(parquet_path)
            if time_col in existing_df.columns:
                existing_df[time_col] = pd.to_datetime(existing_df[time_col], errors="coerce", utc=True)
                existing_df = existing_df.dropna(subset=[time_col])
                existing_df = _filter_plausible_kline_times(existing_df, time_col)
        except Exception as exc:
            logger.warning("Failed to read existing kline parquet %s: %s", parquet_path, exc)
            existing_df = pd.DataFrame()
    
    if not existing_df.empty and time_col in existing_df.columns:
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=[time_col], keep="last")
        combined = combined.sort_values(time_col).reset_index(drop=True)
    else:
        combined = new_df.sort_values(time_col).reset_index(drop=True)

    if not combined.empty:
        latest_time = combined[time_col].max()
        if pd.notna(latest_time):
            cutoff_time = latest_time - pd.DateOffset(years=KLINE_MAX_HISTORY_YEARS)
            combined = combined[combined[time_col] >= cutoff_time].reset_index(drop=True)
    
    if combined.empty:
        return False
    
    try:
        combined.to_parquet(parquet_path, index=False, compression="snappy")
        return True
    except Exception as exc:
        logger.warning("Failed to write kline parquet %s: %s", parquet_path, exc)
        return False


def get_kline_sync_state(code: str, period: str) -> Optional[dict]:
    with _kline_lock:
        states = _sync_state_cache.get(period)
        if states is None:
            states = _load_sync_states(period)
            _sync_state_cache[period] = states
        state = states.get(code)
        return dict(state) if isinstance(state, dict) else state


def update_kline_sync_state(code: str, period: str, bar_count: int, first_bar_time: Optional[str] = None, last_bar_time: Optional[str] = None):
    with _kline_lock:
        states = _sync_state_cache.get(period)
        if states is None:
            states = _load_sync_states(period)
        states[code] = {
            "bar_count": bar_count,
            "first_bar_time": first_bar_time,
            "last_bar_time": last_bar_time,
            "last_synced_at": now_beijing().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _sync_state_cache[period] = states
        _save_sync_states(period, states)


def get_kline_bar_count(code: str, period: str) -> int:
    state = get_kline_sync_state(code, period)
    if state:
        return int(state.get("bar_count", 0) or 0)
    
    df = get_kline_parquet(code, period)
    return len(df)


def delete_kline_parquet(code: str, period: str) -> bool:
    parquet_path = get_kline_parquet_path(code, period)
    if not parquet_path.exists():
        return True
    try:
        parquet_path.unlink()
        with _kline_lock:
            states = _sync_state_cache.get(period)
            if states is None:
                states = _load_sync_states(period)
            if code in states:
                del states[code]
                _sync_state_cache[period] = states
                _save_sync_states(period, states)
        return True
    except Exception:
        return False


def list_kline_codes(period: str) -> list[str]:
    kline_dir = ensure_kline_dir()
    if not kline_dir.exists():
        return []
    
    codes = []
    for code_dir in kline_dir.iterdir():
        if code_dir.is_dir():
            parquet_file = code_dir / f"{period}.parquet"
            if parquet_file.exists():
                codes.append(code_dir.name)
    return sorted(codes)


def get_kline_storage_stats(period: str) -> dict:
    kline_dir = ensure_kline_dir()
    if not kline_dir.exists():
        return {"code_count": 0, "total_size_bytes": 0, "total_size_mb": 0}
    
    total_size = 0
    file_count = 0
    for code_dir in kline_dir.iterdir():
        if code_dir.is_dir():
            parquet_file = code_dir / f"{period}.parquet"
            if parquet_file.exists():
                total_size += parquet_file.stat().st_size
                file_count += 1
    
    return {
        "code_count": file_count,
        "total_size_bytes": total_size,
        "total_size_mb": round(total_size / (1024 * 1024), 2),
    }
