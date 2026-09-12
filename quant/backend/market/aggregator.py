import calendar
from datetime import datetime
from typing import List

import numpy as np
import pandas as pd


def _to_chart_timestamp(value: pd.Timestamp) -> int:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("Asia/Shanghai")
        naive_bj = ts.replace(tzinfo=None)
    else:
        naive_bj = ts
    return calendar.timegm(naive_bj.timetuple())

def kline_to_chart_data(df: pd.DataFrame, period: str) -> List[dict]:
    if df is None or df.empty:
        return []

    results = []
    time_col = "datetime" if "datetime" in df.columns else "date"

    price_digits = 5 if period not in ["daily", "weekly", "monthly"] else 3

    for _, row in df.iterrows():
        t = row[time_col]
        if isinstance(t, str):
            t = pd.to_datetime(t)

        if period in ["daily", "weekly", "monthly"]:
            time_str = t.strftime("%Y-%m-%d")
            chart_timestamp = calendar.timegm(datetime.strptime(time_str, "%Y-%m-%d").timetuple())
        else:
            if hasattr(t, 'tz_convert') and t.tzinfo is not None:
                t_bj = t.tz_convert("Asia/Shanghai")
                time_str = t_bj.strftime("%Y-%m-%d %H:%M")
            else:
                time_str = t.strftime("%Y-%m-%d %H:%M")
            chart_timestamp = _to_chart_timestamp(t)

        results.append({
            "time": time_str,
            "timestamp": chart_timestamp,
            "open": round(float(row["open"]), price_digits),
            "high": round(float(row["high"]), price_digits),
            "low": round(float(row["low"]), price_digits),
            "close": round(float(row["close"]), price_digits),
            "volume": int(float(row.get("volume", 0))) if pd.notna(row.get("volume", 0)) else 0,
            "amount": round(float(row["amount"]), 2) if "amount" in row and pd.notna(row["amount"]) else 0,
        })

    return results


def _sanitize_list(lst) -> list:
    return [None if (isinstance(x, float) and (np.isnan(x) or np.isinf(x))) else x for x in lst]


def calculate_ma(df: pd.DataFrame, periods: List[int] = [5, 10, 20, 60, 144]) -> dict:
    if df is None or df.empty or "close" not in df.columns:
        return {}

    result = {}
    for p in periods:
        ma_series = df["close"].rolling(window=p).mean()
        result[f"MA{p}"] = _sanitize_list(ma_series.round(5).tolist())
    return result


def calculate_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    if df is None or df.empty or "close" not in df.columns:
        return {}

    close = df["close"]
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    macd = (dif - dea) * 2

    return {
        "DIF": _sanitize_list(dif.round(5).tolist()),
        "DEA": _sanitize_list(dea.round(5).tolist()),
        "MACD": _sanitize_list(macd.round(5).tolist()),
    }


def calculate_rsi(df: pd.DataFrame, periods: List[int] = [6, 12, 24]) -> dict:
    if df is None or df.empty or "close" not in df.columns:
        return {}

    result = {}
    close = df["close"]
    delta_series = close.diff()

    for p in periods:
        gain = delta_series.where(delta_series > 0, 0).rolling(window=p).mean()
        loss = (-delta_series.where(delta_series < 0, 0)).rolling(window=p).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        result[f"RSI{p}"] = _sanitize_list(rsi.round(2).tolist())

    return result


def calculate_boll(df: pd.DataFrame, period: int = 20, nbdev: int = 2) -> dict:
    if df is None or df.empty or "close" not in df.columns:
        return {}

    close = df["close"]
    mid = close.rolling(window=period).mean()
    # Align with common trading software BOLL calculations.
    std = close.rolling(window=period).std(ddof=0)
    upper = mid + nbdev * std
    lower = mid - nbdev * std

    return {
        "MID": _sanitize_list(mid.round(5).tolist()),
        "UPPER": _sanitize_list(upper.round(5).tolist()),
        "LOWER": _sanitize_list(lower.round(5).tolist()),
    }
