# -*- coding: utf-8 -*-
"""当日分时分钟序列(从 api/market.py 抽出,供 K线接口与套利背离监控共用)。"""
from __future__ import annotations

from typing import Optional

import pandas as pd

from backend.market import pytdx_data


def get_latest_session_minutes(code: str, count: int, is_index: bool = False) -> pd.DataFrame:
    """取某证券最新一个交易日的 1 分钟K线。

    - 拉取量取 max(count, 320),保证跨午休也能覆盖全天,且与套利引擎的 320 一致
      (否则同代码会形成两份 pytdx 缓存条目,上游拉取翻倍);
    - 过滤只留最新日期(pyt dx 尾巴可能带 forming bar,统一按日期截断);
    - 返回空 DataFrame 表示无数据。
    """
    fetch_count = max(count, 320)
    if is_index:
        df = pytdx_data.get_index_kline(code, "1min", fetch_count)
    else:
        df = pytdx_data.get_kline(code, "1min", fetch_count)

    if df is None or df.empty:
        return pd.DataFrame()
    if "datetime" not in df.columns:
        return df

    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    if "close" in df.columns:
        # 集合竞价/开盘前会混入 close=0 的脏 bar(按昨收归一会算出 -100%),直接丢弃;
        # 全天只剩脏 bar 时,最新有效日期自动顺延回上一个交易日 → 盘前继续展示昨收分时
        df = df[pd.to_numeric(df["close"], errors="coerce") > 0]
    if df.empty:
        return pd.DataFrame()
    latest_date = df["datetime"].dt.date.max()
    return df[df["datetime"].dt.date == latest_date].reset_index(drop=True)


def minutes_to_pct_points(df: pd.DataFrame, pre_close: Optional[float]) -> list[dict]:
    """把分钟 DataFrame 整形为 [{time,timestamp,price,pct}](与基准 trends 同构)。

    pre_close 缺失时 pct 置 None,由调用方决定是否可用。
    """
    if df is None or df.empty or "datetime" not in df.columns:
        return []
    points: list[dict] = []
    for _, row in df.iterrows():
        naive = pd.Timestamp(row["datetime"]).to_pydatetime().replace(tzinfo=None)
        try:
            price = float(row["close"])
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue  # 竞价脏 bar:0 价不写入,保留之前的有效序列
        pct = None
        if pre_close and pre_close > 0:
            pct = round((price / float(pre_close) - 1) * 100, 4)
        points.append({
            "time": naive.strftime("%H:%M"),
            "timestamp": 0,  # 由调用方按需填充,避免重复 import time_utils
            "price": price,
            "pct": pct,
        })
    return points
