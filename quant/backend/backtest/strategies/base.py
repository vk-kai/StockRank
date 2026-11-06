from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class BacktestSignal:
    direction: str
    price: float
    time: str
    reason: str
    # 结构化附加信息(如 MACD 买点的趋势质量报告),回测引擎会透传进 trade_records
    extra: Optional[dict] = None


class BaseBacktestStrategy(ABC):
    name = ""
    description = ""
    min_bars = 35

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> List[BacktestSignal]:
        raise NotImplementedError

    def _create_signal(self, direction: str, price: float, time: str, reason: str) -> BacktestSignal:
        return BacktestSignal(
            direction=direction,
            price=round(float(price), 5),
            time=time,
            reason=reason,
        )


def ema_sma_seeded(values: np.ndarray, span: int) -> np.ndarray:
    """教科书式 EMA:前 span 个样本的 SMA 作种子,其后按标准 alpha 递推。

    pandas 的 ewm(adjust=False) 用第 1 个样本作种子,slow=26 时种子权重要约
    70 根K线后才衰减到 1% 以下——短窗口回测里 MACD 的交叉/面积会整体偏移。
    SMA 种子让 EMA 从第 span 个样本起即无种子偏差;不足 span 个样本返回全 NaN。
    """
    arr = np.asarray(values, dtype=float)
    # 单根脏数据(NaN收盘)会经递推毒化其后全部EMA→信号静默全丢;pandas ewm
    # 遇NaN是跳过该样本继续递推(自愈),这里对齐:缺失处前向填充后再算
    # (纯numpy实现,本模块不依赖pandas)
    nan_mask = np.isnan(arr)
    if nan_mask.any():
        idx = np.where(~nan_mask, np.arange(arr.size), -1)
        np.maximum.accumulate(idx, out=idx)
        if idx[0] == -1:
            # 开头就是NaN:无前值可用,后向填充(首个有效值)
            first_valid = int(np.argmax(~nan_mask))
            arr[:first_valid] = arr[first_valid]
        arr = arr[np.maximum(idx, 0)]
    out = np.full(arr.shape, np.nan)
    if span <= 0 or arr.size < span:
        return out
    alpha = 2.0 / (span + 1.0)
    out[span - 1] = float(arr[:span].mean())
    for i in range(span, arr.size):
        out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
    return out


def macd_sma_seeded(close: np.ndarray, fast: int, slow: int, signal: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """SMA 种子 MACD,返回 (dif, dea, hist);预热区为 NaN。

    有效起点:DIF 自 i>=slow-1,DEA 自 i>=slow+signal-2。调用方主循环的
    isnan 防护会自动跳过预热区,避免用未收敛的值出信号。
    """
    dif = ema_sma_seeded(close, fast) - ema_sma_seeded(close, slow)
    dea = np.full_like(dif, np.nan)
    valid = ~np.isnan(dif)
    if valid.any():
        first = int(np.argmax(valid))
        dea[first:] = ema_sma_seeded(dif[first:], signal)
    hist = (dif - dea) * 2
    return dif, dea, hist
